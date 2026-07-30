# mysite/tasks/demand/run_forecast.py

from __future__ import annotations
import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction

logger = logging.getLogger(__name__)
import pandas as pd
import warnings


@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_forecast(self, version_id: int):
    """
    Orchestrate the full forecast pipeline.
 
    Assumes compute_series_profiles has already run (either directly
    before this task, or via the Celery chain in ForecastVersionRunView).
 
    Steps:
      1  Validate version is DRAFT
      2  Read engine_config settings
      3  Update weighted avg prices (ItemPlanningProfile)
      4  Pull actuals via DuckDB → Polars
      5  Load SeriesProfile decisions (grain, strategy, price per series)
      6  Build aggregated actuals per grain
      7  Run StatsForecast batched by (grain, strategy, eval_period)
      8  Disaggregate non-atomic forecasts back to atomic level
           - Location grains: qty-share disaggregation
           - Product grains: VALUE-share disaggregation → qty via price
      9  Hierarchical reconciliation (MinTrace)
     10  Write ForecastLine rows
     11  Write ForecastAggregate rollups (with value fields and weighted_avg_price)
     12  Update version run_status → COMPLETE
    """
    from mysite.models.demand.forecast import ForecastVersion
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP, ActualSale
    from utils.demand.forecast_engine import (
        update_weighted_avg_prices,
        build_actuals_dataframe,
        load_series_decisions,
        build_aggregated_actuals,
        run_statsforecast_by_grain,
        disaggregate_to_atomic,
        run_hierarchical_reconciliation,
        write_forecast_lines,
        write_forecast_aggregates,
    )
    from utils.feature_control import celery_demand_feature_guard
 
    try:
        version = ForecastVersion.objects.select_related(
            'client', 'created_by'
        ).get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        logger.error(f'run_forecast: version_id={version_id} not found')
        return
 
    skip = celery_demand_feature_guard(version.client, 'forecast_run')
    if skip:
        return skip
 
    if not version.is_editable:
        logger.warning(
            f'run_forecast: version {version_id} is {version.status} — must be DRAFT'
        )
        return
 
    def _set_status(run_status: str, error: str = ''):
        ForecastVersion.objects.filter(pk=version_id).update(
            run_status=run_status,
            run_error=error,
            celery_task_id=self.request.id or '',
        )
 
    try:
        client      = version.client
        client_id   = client.pk
        period_type = version.period_type
        horizon     = version.horizon_periods
        freq        = PERIOD_FREQ_MAP[period_type]
 
        # ── Read engine_config ─────────────────────────────────────────────
        cfg = version.engine_config
        #reconciliation       = cfg.get('reconciliation', 'MinTrace_ols')
        reconciliation       = cfg.get('reconciliation', None)  # disabled until hierarchy fix
        disagg_conflict      = cfg.get('disagg_conflict_resolution', 'retain_lower')
        store_all_levels     = cfg.get('store_all_level_forecasts', True)
        force_grain          = cfg.get('force_grain')
        season_length        = cfg.get('season_length', 12)
 
        # ── Determine actuals window ───────────────────────────────────────
        earliest = (
            ActualSale.objects
            .filter(client=client, period_type=period_type)
            .order_by('period_start')
            .values_list('period_start', flat=True)
            .first()
        )
        if earliest is None:
            raise ValueError('No actuals found for this client and period_type.')
 
        # ── Step 3: Update prices ──────────────────────────────────────────
        _set_status('PROFILING')
        price_map = update_weighted_avg_prices(client_id, period_type)
 
        # ── Step 4: Pull actuals ───────────────────────────────────────────
        actuals_pl = build_actuals_dataframe(
            client_id, period_type, earliest, version.base_period_end
        )
 
        # ── Step 5: Load SeriesProfile decisions ───────────────────────────
        all_uids  = actuals_pl['unique_id'].unique().to_list()
        decisions = load_series_decisions(
            client_id, period_type, all_uids, price_map, force_grain
        )
 
        # -- Step 6: Build aggregated actuals per grain -------------------------
        _set_status('RUNNING')
        all_periods   = sorted(actuals_pl['period_start'].unique().to_list())
        # `as_of` is the same value used by compute_series_profiles for Sales
        # Hierarchy resolution -- keeping classification and forecasting on
        # the SAME org-chart snapshot. compute_series_profiles resolves
        # against the client's latest actual period, not this version's own
        # base_period_end -- these can differ if this version was created
        # with an earlier cutoff than the most recent actuals. Using
        # base_period_end here (what's naturally in scope) rather than
        # re-querying "latest across all history" a second time; flag if you
        # want these forced identical instead.
        as_of = version.base_period_end
        agg_actuals, code_lookup = build_aggregated_actuals(
            actuals_pl, decisions, period_type, all_periods,
            client_id=client_id, as_of=as_of,
        )
 
        # -- Step 7: Run StatsForecast --------------------------------------
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning, module='statsforecast')
            combined_df = run_statsforecast_by_grain(
                aggregated_actuals=agg_actuals,
                decisions=decisions,
                horizon=horizon,
                freq=freq,
                code_lookup=code_lookup,
                season_length=season_length,
            )
 
        # -- Step 8: Disaggregate to atomic ---------------------------------
        atomic_df = disaggregate_to_atomic(
            forecast_df     = combined_df,
            actuals_df      = actuals_pl,
            decisions       = decisions,
            period_type     = version.period_type,
            base_freq       = PERIOD_FREQ_MAP[version.period_type],
            client_id       = client_id,
            as_of           = as_of,
            disagg_conflict = disagg_conflict,
        )
 
        # ── Step 9: Reconciliation ─────────────────────────────────────────
        _set_status('RECONCILING')
        if reconciliation:
            try:
                from hierarchicalforecast.utils import aggregate as hf_agg
                from utils.demand.hierarchy_utils import (
                    resolve_sales_forecast_link, get_sales_hierarchy_ancestor_map,
                )
                from mysite.models.demand.hierarchy import SalesNode
 
                actuals_pd = actuals_pl.to_pandas()
 
                # NEW: reconciliation grouping is Sales Hierarchy ONLY —
                # PlanningLocation's parent chain (the old region_code) plays
                # no role at all, per product decision. Each leaf location
                # maps to its ROOT SalesNode's code; locations with no
                # resolvable link (no SalesForecastLink as_of this date, or
                # no Sales Hierarchy configured for the client at all) group
                # under a single '__NO_SALES_HIERARCHY__' bucket rather than
                # being silently dropped from reconciliation.
                sales_ancestor_map = get_sales_hierarchy_ancestor_map(client_id)
                sales_node_codes = {
                    n.pk: n.code for n in SalesNode.objects.filter(client_id=client_id)
                }
                loc_to_group: dict[int, str] = {}
                for loc_id in actuals_pd['planning_location_id'].unique().tolist():
                    link = resolve_sales_forecast_link(client_id, loc_id, None, None, as_of=as_of)
                    if not link:
                        loc_to_group[loc_id] = '__NO_SALES_HIERARCHY__'
                        continue
                    ancestors = sales_ancestor_map.get(link['sales_node_id'], [])
                    root_id = ancestors[0] if ancestors else link['sales_node_id']
                    loc_to_group[loc_id] = sales_node_codes.get(root_id, f'NODE_{root_id}')
 
                actuals_pd['location_group'] = actuals_pd['planning_location_id'].map(loc_to_group)
 
                hier_raw = actuals_pd[['ds', 'location_group', 'unique_id', 'y']].copy()
                hier_raw = hier_raw.rename(columns={'unique_id': 'series'})
                hier_raw['y']  = hier_raw['y'].astype(float)
                hier_raw['ds'] = pd.to_datetime(hier_raw['ds'])
 
                Y_df, S_df, tags = hf_agg(
                    hier_raw,
                    [['location_group'], ['location_group', 'series']],
                )
 
                # Build uid → sales-hierarchy-root lookup for prefixing
                uid_to_group = (
                    actuals_pd[['unique_id', 'location_group']]
                    .drop_duplicates('unique_id')
                    .set_index('unique_id')['location_group']
                    .to_dict()
                )
 
                # Bottom-level forecast rows with prefixed unique_id
                hf_bottom = atomic_df[['unique_id', 'ds', 'statistical_qty']].copy()
                hf_bottom['ds'] = pd.to_datetime(hf_bottom['ds'])
                hf_bottom = (
                    hf_bottom.groupby(['unique_id', 'ds'])['statistical_qty']
                    .sum().reset_index()
                )
                hf_bottom['unique_id'] = hf_bottom['unique_id'].map(
                    lambda uid: f"{uid_to_group.get(uid, '__NO_SALES_HIERARCHY__')}/{uid}"
                )
                hf_bottom = hf_bottom.rename(columns={'statistical_qty': 'COMBINED'})
 
                # Top-level aggregate per sales-hierarchy root (one row per
                # root per ds). NOTE, carried over from earlier design review
                # and still true here: this top level is computed as the SUM
                # OF THE BOTTOM rows, not an independent statistical forecast
                # at the root level -- meaning reconciliation has nothing
                # genuinely independent to reconcile against and is
                # structurally close to a no-op. Left as-is since fixing that
                # is a separate, larger piece of work than today's ask
                # (region_code elimination); flagging again since it's
                # directly adjacent to what changed here.
                region_totals = hf_bottom.copy()
                region_totals['region'] = region_totals['unique_id'].map(
                    lambda uid: uid.split('/', 1)[0]
                )
                top_level = (
                    region_totals.groupby(['region', 'ds'])['COMBINED']
                    .sum()
                    .reset_index()
                    .rename(columns={'region': 'unique_id'})
                )[['unique_id', 'ds', 'COMBINED']]
 
                hf_input_full = pd.concat([top_level, hf_bottom], ignore_index=True)
 
                reconciled = run_hierarchical_reconciliation(
                    forecasts_df=hf_input_full,
                    Y_df=Y_df, S_df=S_df, tags=tags,
                    method=reconciliation,
                )
 
                rec_col = [
                    c for c in reconciled.columns
                    if 'COMBINED' in c and c != 'COMBINED'
                ]
                if rec_col:
                    reconciled = reconciled.rename(
                        columns={rec_col[0]: 'statistical_qty'}
                    )
                    # Strip sales-hierarchy-root prefix from unique_id for lookup
                    rec_lookup = {
                        (
                            row['unique_id'].split('/', 1)[1]
                            if '/' in str(row['unique_id']) else row['unique_id'],
                            pd.Timestamp(row['ds'])
                        ): row['statistical_qty']
                        for _, row in reconciled.iterrows()
                    }
                    atomic_df['statistical_qty'] = atomic_df.apply(
                        lambda row: rec_lookup.get(
                            (row['unique_id'], pd.Timestamp(row['ds'])),
                            row['statistical_qty']
                        ),
                        axis=1,
                    )
 
            except Exception as exc:
                import traceback
                logger.warning(
                    f'run_forecast: reconciliation failed ({exc}) — '
                    f'using unreconciled forecasts\n{traceback.format_exc()}'
                )
 
        # ── Step 10: Write ForecastLine rows ──────────────────────────────
        _set_status('AGGREGATING')
        n_lines = write_forecast_lines(
            version_id=version_id,
            forecast_df=atomic_df,
            decisions=decisions,
            period_type=period_type,
            store_all_level_forecasts=store_all_levels,
        )
 
        # ── Step 11: Write ForecastAggregate rollups ──────────────────────
        n_agg = write_forecast_aggregates(version_id)
 
        _set_status('COMPLETE')
        logger.info(
            f'run_forecast: version={version_id} COMPLETE '
            f'lines={n_lines} aggregates={n_agg}'
        )
 
    except Exception as exc:
        _set_status('FAILED', error=traceback.format_exc())
        logger.exception(f'run_forecast: version={version_id} FAILED')
        raise self.retry(exc=exc)
 
 
@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def apply_overrides(self, version_id: int):
    """
    Disaggregate all unapplied ForecastOverride rows to ForecastLine.override_qty.
 
    Three override modes:
        override_qty:   absolute qty → disaggregate by historical qty share
        override_pct:   percentage → multiply statistical_qty
        override_value: ₹ target → convert to qty via weighted_avg_price
                        → disaggregate by VALUE share
 
    After applying: recompute ForecastAggregate rollups.
    """
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastOverride, ForecastLine, ForecastAggregate
    )
    from utils.demand.forecast_engine import write_forecast_aggregates
 
    try:
        version = ForecastVersion.objects.get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        return
 
    if not version.is_editable:
        logger.warning(f'apply_overrides: version {version_id} is not DRAFT')
        return
 
    pending = ForecastOverride.objects.filter(
        version=version, is_applied=False
    ).select_related('created_by').order_by('created_at')
 
    applied_count = 0
    for override in pending:
        try:
            _apply_single_override(override, version)
            override.is_applied = True
            override.save(update_fields=['is_applied'])
            applied_count += 1
        except Exception as exc:
            logger.exception(
                f'apply_overrides: failed on override {override.pk}: {exc}'
            )
 
    logger.info(
        f'apply_overrides: version={version_id} '
        f'applied={applied_count}'
    )
    write_forecast_aggregates(version_id)
 
def _line_matches_child_key(line, child_key: dict) -> bool:
    """
    Subset match for CUSTOM split weights: only checks fields actually
    present in child_key, treating absent fields as wildcards. Matches
    OverrideSplitWeight's own documented convention (e.g.
    child_key={'item_id': 'SKU-001'} applies uniformly across every
    location/customer/channel of that SKU, unless the weight row ALSO
    specifies one of those fields to narrow it further).
 
    Corrects a prior version of this function that required an exact,
    fully-disambiguated key match -- that would never match a partial key
    like the model docstring's own example, since real lines always have
    non-null location/channel values.
    """
    field_map = {
        'item_id': line.item.item_id,
        'location_code': line.planning_location.code if line.planning_location_id else None,
        'customer_code': line.planning_customer.code if line.planning_customer_id else None,
        'distribution_channel_id': line.distribution_channel_id,
    }
    return all(field_map.get(k) == v for k, v in child_key.items() if k in field_map)
 
 
def _custom_weight_for_line(line, split_weights: list) -> float:
    matches = [sw for sw in split_weights if _line_matches_child_key(line, sw.child_key)]
    if not matches:
        return 0.0
    if len(matches) > 1:
        # Most-specific match wins (most keys specified) -- e.g. a
        # channel-specific weight should override a blanket item-only weight
        # if a planner has entered both.
        matches.sort(key=lambda sw: len(sw.child_key), reverse=True)
        logger.warning(
            f'_custom_weight_for_line: {len(matches)} OverrideSplitWeight rows matched '
            f'line {line.pk} -- using the most specific match ({matches[0].child_key}).'
        )
    return float(matches[0].weight)
 
 
def _resolve_override_queryset(qs, override, client_id: int, as_of):
    """
    Filters `qs` (a ForecastLine queryset already scoped to version/period)
    down to the lines this override targets, per override_level.
 
    'region' resolves via the Sales Hierarchy ONLY (SalesForecastLink /
    SalesNode) -- PlanningLocation's parent chain plays no role, per
    product decision. 'subcategory'/'category' both resolve via item
    hierarchy membership (the depth distinction is a label on the client's
    taxonomy, not something this code needs to treat differently).
 
    override_key conventions used here (confirm these match what the
    frontend actually sends -- flagging since this is a real design point
    that needs frontend/backend alignment):
      sku:                  {'item_id': <Item.item_id str>}
      subcategory/category: {'taxon_node_id': <TaxonomyNode pk, int>}
      location:              {'location_code': <PlanningLocation.code>}
      region:                {'sales_node_code': <SalesNode.code>}
      customer:              {'customer_code': <PlanningCustomer.code>}
      channel:               {'distribution_channel_id': <DistributionChannel.code>}
      total:                 {} (no key needed)
    Any level MAY additionally include 'distribution_channel_id' to further
    scope to one channel (e.g. a 'sku' override for one item in one channel).
    """
    from utils.demand.forecast_engine import sales_node_location_ids, taxon_node_item_ids
    from mysite.models.demand.hierarchy import SalesNode
 
    key = override.override_key or {}
    level = override.override_level
 
    if level == 'sku':
        item_id_str = key.get('item_id')
        if item_id_str:
            qs = qs.filter(item__item_id=item_id_str)
 
    elif level in ('subcategory', 'category'):
        node_id = key.get('taxon_node_id')
        if node_id is not None:
            item_ids = taxon_node_item_ids(client_id, int(node_id))
            qs = qs.filter(item_id__in=item_ids)
        else:
            logger.warning(
                f'_resolve_override_queryset: {level} override {override.pk} '
                f'missing taxon_node_id in override_key'
            )
 
    elif level == 'location':
        loc_code = key.get('location_code')
        if loc_code:
            qs = qs.filter(planning_location__code=loc_code)
 
    elif level == 'region':
        node_code = key.get('sales_node_code')
        if node_code:
            node = SalesNode.objects.filter(client_id=client_id, code=node_code).first()
            if node:
                as_of_iso = as_of.isoformat() if hasattr(as_of, 'isoformat') else str(as_of)
                loc_ids = sales_node_location_ids(client_id, node.pk, as_of_iso)
                qs = qs.filter(planning_location_id__in=loc_ids)
            else:
                logger.warning(
                    f'_resolve_override_queryset: SalesNode {node_code!r} '
                    f'not found for client {client_id}'
                )
        else:
            logger.warning(
                f'_resolve_override_queryset: region override {override.pk} '
                f'missing sales_node_code in override_key'
            )
 
    elif level == 'customer':
        cust_code = key.get('customer_code')
        if cust_code:
            qs = qs.filter(planning_customer__code=cust_code)
 
    elif level == 'channel':
        dc_code = key.get('distribution_channel_id')
        if dc_code:
            qs = qs.filter(distribution_channel_id=dc_code)
    # 'total' -- no additional filter, all lines for this period
 
    # Any level can additionally be scoped to one channel via override_key,
    # unless override_level=='channel' itself (already handled above).
    if level != 'channel':
        dc_code = key.get('distribution_channel_id')
        if dc_code:
            qs = qs.filter(distribution_channel_id=dc_code)
 
    return qs
 
 
def _apply_single_override(override, version):
    from mysite.models.demand.forecast import ForecastLine
    from decimal import Decimal
 
    qs = ForecastLine.objects.filter(
        version=version,
        period_type=override.period_type,
        period_start=override.period_start,
    )
    qs = _resolve_override_queryset(qs, override, version.client_id, version.base_period_end)
 
    lines = list(qs.select_related('item', 'planning_location', 'planning_customer'))
    if not lines:
        logger.warning(
            f'_apply_single_override: no matching lines for override {override.pk}'
        )
        return
 
    # ── Percentage override ────────────────────────────────────────────────
    if override.override_pct is not None:
        multiplier = Decimal(str(1 + float(override.override_pct) / 100))
        for line in lines:
            line.override_qty = (
                line.statistical_qty * multiplier
            ).quantize(Decimal('0.001'))
            line.final_qty   = line.override_qty
            line.final_value = (
                line.final_qty * line.price_used
                if line.price_used else line.statistical_value
            ).quantize(Decimal('0.01'))
            line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
        return
 
    # ── Absolute qty override ──────────────────────────────────────────────
    if override.override_qty is not None:
        total_stat = sum(float(l.statistical_qty) for l in lines) or 1.0
        override_total = float(override.override_qty)
 
        if override.disagg_method == 'CUSTOM':
            split_weights = list(override.split_weights.all())
            for line in lines:
                weight = _custom_weight_for_line(line, split_weights)
                line.override_qty = Decimal(str(round(override_total * weight, 3)))
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
 
        elif override.disagg_method == 'EQUAL':
            equal_share = Decimal(str(round(override_total / len(lines), 3)))
            for line in lines:
                line.override_qty = equal_share
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
 
        else:  # PROPORTIONAL
            for line in lines:
                share = float(line.statistical_qty) / total_stat
                line.override_qty = Decimal(str(round(override_total * share, 3)))
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
        return
 
    # ── Value override (₹) ────────────────────────────────────────────────
    if override.override_value is not None:
        target_total_value = override.override_value
 
        total_stat_value = sum(
            float(l.statistical_value or 0) for l in lines
        ) or 1.0
        scale = float(target_total_value) / total_stat_value
        split_weights = list(override.split_weights.all()) if override.disagg_method == 'CUSTOM' else []
 
        for line in lines:
            if override.disagg_method == 'PROPORTIONAL':
                line.final_value = (
                    Decimal(str(float(line.statistical_value or 0) * scale))
                ).quantize(Decimal('0.01'))
 
            elif override.disagg_method == 'EQUAL':
                line.final_value = (
                    target_total_value / Decimal(str(len(lines)))
                ).quantize(Decimal('0.01'))
 
            elif override.disagg_method == 'CUSTOM':
                weight = _custom_weight_for_line(line, split_weights)
                line.final_value = (
                    target_total_value * Decimal(str(weight))
                ).quantize(Decimal('0.01'))
 
            # Back-calculate final_qty from final_value using this line's price
            if line.price_used and float(line.price_used) > 0:
                line.override_qty = (
                    line.final_value / line.price_used
                ).quantize(Decimal('0.001'))
                line.final_qty = line.override_qty
            else:
                line.override_qty = line.statistical_qty
                line.final_qty    = line.statistical_qty
 
            line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
 
 
def compute_accuracy(self, client_id: int):
    """
    Nightly task. For LOCKED/APPROVED versions where actuals have landed,
    compute MAPE and Bias and write ForecastAccuracy rows.
    """
    import duckdb
    import pandas as pd
    from mysite.models import Client
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastAccuracy, ForecastLine
    )
    from mysite.models.demand.actuals import ActualSale, compute_period_end
 
    client = Client.objects.get(pk=client_id)
 
    versions = ForecastVersion.objects.filter(
        client_id=client_id,
        status__in=[
            ForecastVersion.Status.APPROVED,
            ForecastVersion.Status.LOCKED,
        ],
    )
 
    total_written = 0
 
    for version in versions:
        period_type = version.period_type
 
        lines_qs = (
            ForecastLine.objects
            .filter(version=version)
            .values(
                'id', 'item_id', 'planning_customer_id',
                'planning_location_id', 'distribution_channel_id',
                'period_start', 'final_qty',
            )
        )
        if not lines_qs.exists():
            continue
 
        lines_df = pd.DataFrame(list(lines_qs))
 
        # Governed by reporting_uses_net_actuals -- accuracy measurement is
        # conceptually a reporting concern per the client's own flag
        # taxonomy. Judgment call worth confirming: this compares the
        # forecast against a NET actual, which can differ from what
        # genuinely happened if a fresh outlier landed in the accuracy
        # window itself. If you'd rather always compare against raw
        # ground truth regardless of this flag, or tie this to
        # forecast_uses_net_actuals instead (matching whichever actuals
        # generated the forecast being graded), that's a one-line change
        # right here.
        from mysite.models.demand.forecast import ForecastingConfig
        from utils.demand.actuals_net import actuals_queryset_with_net
 
        cfg = ForecastingConfig.get_for_client_id(client_id)
        use_net = bool(cfg.reporting_uses_net_actuals)
 
        actuals_qs = (
            actuals_queryset_with_net(client, use_net)
            .filter(
                period_type=period_type,
                period_start__in=lines_df['period_start'].unique().tolist(),
            )
            .values(
                'item_id', 'planning_customer_id',
                'planning_location_id', 'distribution_channel_id',
                'period_start', 'net_qty',
            )
        )
        if not actuals_qs.exists():
            continue
 
        actuals_df = pd.DataFrame(list(actuals_qs))
        actuals_df = actuals_df.rename(columns={'net_qty': 'qty'})
 
        con = duckdb.connect()
        con.register('lines',   lines_df)
        con.register('actuals', actuals_df)
 
        # NOTE: distribution_channel_id added to the join key -- without it,
        # any (item, location, customer, period) combination with more than
        # one channel on either side produces a many-to-many cross join
        # (2 channels x 2 channels = 4 matched pairs instead of 2), silently
        # inflating MAPE/bias and pairing e.g. Retail forecast against
        # Institutional actuals in the spurious cross-matches. Both sides
        # default to '00' for clients with channel disabled, so this is a
        # no-op join-key addition for those clients (still 1:1 as before).
        joined = con.execute("""
            SELECT
                l.item_id,
                l.planning_customer_id,
                l.planning_location_id,
                l.distribution_channel_id,
                l.period_start,
                CAST(l.final_qty AS DOUBLE) AS forecast_qty,
                CAST(a.qty       AS DOUBLE) AS actual_qty,
                CASE
                    WHEN a.qty > 0 THEN
                        ABS(CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS mape,
                CASE
                    WHEN a.qty > 0 THEN
                        (CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS bias
            FROM lines l
            INNER JOIN actuals a
                ON  l.item_id                 = a.item_id
                AND l.planning_location_id    = a.planning_location_id
                AND l.distribution_channel_id = a.distribution_channel_id
                AND l.period_start            = a.period_start
                AND (
                    (l.planning_customer_id IS NULL AND a.planning_customer_id IS NULL)
                    OR l.planning_customer_id = a.planning_customer_id
                )
        """).df()
 
        if joined.empty:
            continue
 
        # NOTE: this assumes ForecastAccuracy has a distribution_channel FK,
        # matching the pattern every other atomic-grain model in this system
        # picked up (ActualSale, SeriesProfile, ForecastLine). If it doesn't
        # yet, this needs a migration (add the field, default '00', backfill)
        # before this will run -- same pattern as those earlier additions.
        ForecastAccuracy.objects.filter(version=version).delete()
 
        accuracy_objects = []
        for _, row in joined.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()
 
            cust_id = row['planning_customer_id']
            cust_id = None if pd.isna(cust_id) else int(cust_id)
 
            accuracy_objects.append(
                ForecastAccuracy(
                    version_id           = version.pk,
                    item_id              = int(row['item_id']),
                    planning_customer_id = cust_id,
                    planning_location_id = int(row['planning_location_id']),
                    distribution_channel_id = row['distribution_channel_id'],
                    period_type          = period_type,
                    period_start         = period_start,
                    period_end           = compute_period_end(period_start, period_type),
                    actual_qty           = Decimal(str(round(row['actual_qty'],   3))),
                    forecast_qty         = Decimal(str(round(row['forecast_qty'], 3))),
                    mape  = Decimal(str(round(row['mape'], 4)))
                            if row['mape'] is not None and not pd.isna(row['mape'])
                            else None,
                    bias  = Decimal(str(round(row['bias'], 4)))
                            if row['bias'] is not None and not pd.isna(row['bias'])
                            else None,
                )
            )
 
        ForecastAccuracy.objects.bulk_create(accuracy_objects, batch_size=500)
        total_written += len(accuracy_objects)
        logger.info(
            f'compute_accuracy: version={version.pk} '
            f'accuracy_rows={len(accuracy_objects)}'
        )
 
    logger.info(
        f'compute_accuracy: client={client_id} total_written={total_written}'
    )

"""

from __future__ import annotations
import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction

logger = logging.getLogger(__name__)
import pandas as pd
import warnings

@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_forecast(self, version_id: int):

    from mysite.models.demand.forecast import ForecastVersion
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP, ActualSale
    from utils.demand.forecast_engine import (
        update_weighted_avg_prices,
        build_actuals_dataframe,
        load_series_decisions,
        build_aggregated_actuals,
        run_statsforecast_by_grain,
        disaggregate_to_atomic,
        run_hierarchical_reconciliation,
        write_forecast_lines,
        write_forecast_aggregates,
    )
    from utils.feature_control import celery_demand_feature_guard

    try:
        version = ForecastVersion.objects.select_related(
            'client', 'created_by'
        ).get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        logger.error(f'run_forecast: version_id={version_id} not found')
        return

    skip = celery_demand_feature_guard(version.client, 'forecast_run')
    if skip:
        return skip

    if not version.is_editable:
        logger.warning(
            f'run_forecast: version {version_id} is {version.status} — must be DRAFT'
        )
        return

    def _set_status(run_status: str, error: str = ''):
        ForecastVersion.objects.filter(pk=version_id).update(
            run_status=run_status,
            run_error=error,
            celery_task_id=self.request.id or '',
        )

    try:
        client      = version.client
        client_id   = client.pk
        period_type = version.period_type
        horizon     = version.horizon_periods
        freq        = PERIOD_FREQ_MAP[period_type]

        # ── Read engine_config ─────────────────────────────────────────────
        cfg = version.engine_config
        #reconciliation       = cfg.get('reconciliation', 'MinTrace_ols')
        reconciliation       = cfg.get('reconciliation', None)  # disabled until hierarchy fix
        disagg_conflict      = cfg.get('disagg_conflict_resolution', 'retain_lower')
        store_all_levels     = cfg.get('store_all_level_forecasts', True)
        force_grain          = cfg.get('force_grain')
        season_length        = cfg.get('season_length', 12)

        # ── Determine actuals window ───────────────────────────────────────
        earliest = (
            ActualSale.objects
            .filter(client=client, period_type=period_type)
            .order_by('period_start')
            .values_list('period_start', flat=True)
            .first()
        )
        if earliest is None:
            raise ValueError('No actuals found for this client and period_type.')

        # ── Step 3: Update prices ──────────────────────────────────────────
        _set_status('PROFILING')
        price_map = update_weighted_avg_prices(client_id, period_type)

        # ── Step 4: Pull actuals ───────────────────────────────────────────
        actuals_pl = build_actuals_dataframe(
            client_id, period_type, earliest, version.base_period_end
        )

        # ── Step 5: Load SeriesProfile decisions ───────────────────────────
        all_uids  = actuals_pl['unique_id'].unique().to_list()
        decisions = load_series_decisions(
            client_id, period_type, all_uids, price_map, force_grain
        )

        # ── Step 6: Build aggregated actuals per grain ─────────────────────
        _set_status('RUNNING')
        all_periods   = sorted(actuals_pl['period_start'].unique().to_list())
        agg_actuals   = build_aggregated_actuals(
            actuals_pl, decisions, period_type, all_periods
        )

        # ── Step 7: Run StatsForecast ──────────────────────────────────────
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore', category=RuntimeWarning, module='statsforecast')
            combined_df = run_statsforecast_by_grain(aggregated_actuals=agg_actuals,
            decisions=decisions,
            horizon=horizon,
            freq=freq,
            season_length=season_length,)


        # ── Step 8: Disaggregate to atomic ─────────────────────────────────
        atomic_df = disaggregate_to_atomic(
            forecast_df     = combined_df,
            actuals_df      = actuals_pl,
            decisions       = decisions,
            period_type     = version.period_type,
            base_freq       = PERIOD_FREQ_MAP[version.period_type],
            disagg_conflict = disagg_conflict,
        )


        # ── Step 9: Reconciliation ─────────────────────────────────────────
        _set_status('RECONCILING')
        if reconciliation:
            try:
                from hierarchicalforecast.utils import aggregate as hf_agg

                actuals_pd = actuals_pl.to_pandas()
                actuals_pd['location_group'] = actuals_pd['region_code']
                hier_raw = actuals_pd[['ds', 'location_group', 'unique_id', 'y']].copy()
                hier_raw = hier_raw.rename(columns={'unique_id': 'series'})
                hier_raw['y']  = hier_raw['y'].astype(float)
                hier_raw['ds'] = pd.to_datetime(hier_raw['ds'])

                Y_df, S_df, tags = hf_agg(
                    hier_raw,
                    [['location_group'], ['location_group', 'series']],
                )

                # Build uid → region lookup for prefixing
                uid_to_region = (
                    actuals_pd[['unique_id', 'region_code']]
                    .drop_duplicates('unique_id')
                    .set_index('unique_id')['region_code']
                    .to_dict()
                )

                # Bottom-level forecast rows with prefixed unique_id
                hf_bottom = atomic_df[['unique_id', 'ds', 'statistical_qty']].copy()
                hf_bottom['ds'] = pd.to_datetime(hf_bottom['ds'])
                hf_bottom = (
                    hf_bottom.groupby(['unique_id', 'ds'])['statistical_qty']
                    .sum().reset_index()
                )
                hf_bottom['unique_id'] = hf_bottom['unique_id'].map(
                    lambda uid: f"{uid_to_region.get(uid, '__NO_REGION__')}/{uid}"
                )
                hf_bottom = hf_bottom.rename(columns={'statistical_qty': 'COMBINED'})

                # Top-level aggregate per region (one row per region per ds)
                # Handles multi-region clients correctly
                region_totals = (
                    hf_bottom.copy()
                )
                # Extract region from prefixed unique_id ("region/uid" → "region")
                region_totals['region'] = region_totals['unique_id'].map(
                    lambda uid: uid.split('/', 1)[0]
                )
                top_level = (
                    region_totals.groupby(['region', 'ds'])['COMBINED']
                    .sum()
                    .reset_index()
                    .rename(columns={'region': 'unique_id'})
                )[['unique_id', 'ds', 'COMBINED']]

                hf_input_full = pd.concat([top_level, hf_bottom], ignore_index=True)
 
                reconciled = run_hierarchical_reconciliation(
                    forecasts_df=hf_input_full,
                    Y_df=Y_df, S_df=S_df, tags=tags,
                    method=reconciliation,
                )

                rec_col = [
                    c for c in reconciled.columns
                    if 'COMBINED' in c and c != 'COMBINED'
                ]
                if rec_col:
                    reconciled = reconciled.rename(
                        columns={rec_col[0]: 'statistical_qty'}
                    )
                    # Strip region prefix from unique_id for lookup
                    rec_lookup = {
                        (
                            row['unique_id'].split('/', 1)[1]
                            if '/' in str(row['unique_id']) else row['unique_id'],
                            pd.Timestamp(row['ds'])
                        ): row['statistical_qty']
                        for _, row in reconciled.iterrows()
                    }
                    atomic_df['statistical_qty'] = atomic_df.apply(
                        lambda row: rec_lookup.get(
                            (row['unique_id'], pd.Timestamp(row['ds'])),
                            row['statistical_qty']
                        ),
                        axis=1,
                    )

            except Exception as exc:
                import traceback
                logger.warning(
                    f'run_forecast: reconciliation failed ({exc}) — '
                    f'using unreconciled forecasts\n{traceback.format_exc()}'
                )

        # ── Step 10: Write ForecastLine rows ──────────────────────────────
        _set_status('AGGREGATING')
        n_lines = write_forecast_lines(
            version_id=version_id,
            forecast_df=atomic_df,
            decisions=decisions,
            period_type=period_type,
            store_all_level_forecasts=store_all_levels,
        )

        # ── Step 11: Write ForecastAggregate rollups ──────────────────────
        n_agg = write_forecast_aggregates(version_id)

        _set_status('COMPLETE')
        logger.info(
            f'run_forecast: version={version_id} COMPLETE '
            f'lines={n_lines} aggregates={n_agg}'
        )

    except Exception as exc:
        _set_status('FAILED', error=traceback.format_exc())
        logger.exception(f'run_forecast: version={version_id} FAILED')
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def apply_overrides(self, version_id: int):

    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastOverride, ForecastLine, ForecastAggregate
    )
    from utils.demand.forecast_engine import write_forecast_aggregates

    try:
        version = ForecastVersion.objects.get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        return

    if not version.is_editable:
        logger.warning(f'apply_overrides: version {version_id} is not DRAFT')
        return

    pending = ForecastOverride.objects.filter(
        version=version, is_applied=False
    ).select_related('created_by').order_by('created_at')

    applied_count = 0
    for override in pending:
        try:
            _apply_single_override(override, version)
            override.is_applied = True
            override.save(update_fields=['is_applied'])
            applied_count += 1
        except Exception as exc:
            logger.exception(
                f'apply_overrides: failed on override {override.pk}: {exc}'
            )

    logger.info(
        f'apply_overrides: version={version_id} '
        f'applied={applied_count}'
    )
    write_forecast_aggregates(version_id)

def _apply_single_override(override, version):
    from mysite.models.demand.forecast import ForecastLine
    from decimal import Decimal

    qs = ForecastLine.objects.filter(
        version=version,
        period_type=override.period_type,
        period_start=override.period_start,
    )

    key = override.override_key
    if override.override_level == 'sku':
        item_id_str = key.get('item_id')
        if item_id_str:
            qs = qs.filter(item__item_id=item_id_str)
    elif override.override_level == 'location':
        loc_code = key.get('location_code')
        if loc_code:
            qs = qs.filter(planning_location__code=loc_code)
    elif override.override_level == 'customer':
        cust_code = key.get('customer_code')
        if cust_code:
            qs = qs.filter(planning_customer__code=cust_code)
    # 'total' — no additional filter, all lines for this period

    lines = list(qs.select_related('item'))
    if not lines:
        logger.warning(
            f'_apply_single_override: no matching lines for override {override.pk}'
        )
        return

    # ── Percentage override ────────────────────────────────────────────────
    if override.override_pct is not None:
        multiplier = Decimal(str(1 + float(override.override_pct) / 100))
        for line in lines:
            line.override_qty = (
                line.statistical_qty * multiplier
            ).quantize(Decimal('0.001'))
            line.final_qty   = line.override_qty
            line.final_value = (
                line.final_qty * line.price_used
                if line.price_used else line.statistical_value
            ).quantize(Decimal('0.01'))
            line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
        return

    # ── Absolute qty override ──────────────────────────────────────────────
    if override.override_qty is not None:
        total_stat = sum(float(l.statistical_qty) for l in lines) or 1.0
        override_total = float(override.override_qty)

        if override.disagg_method == 'CUSTOM':
            weights = {
                str(sw.child_key): float(sw.weight)
                for sw in override.split_weights.all()
            }
            for line in lines:
                uid_key = str({'item_id': line.item.item_id})
                weight  = weights.get(uid_key, 0.0)
                line.override_qty = Decimal(str(round(override_total * weight, 3)))
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])

        elif override.disagg_method == 'EQUAL':
            equal_share = Decimal(str(round(override_total / len(lines), 3)))
            for line in lines:
                line.override_qty = equal_share
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])

        else:  # PROPORTIONAL
            for line in lines:
                share = float(line.statistical_qty) / total_stat
                line.override_qty = Decimal(str(round(override_total * share, 3)))
                line.final_qty    = line.override_qty
                line.final_value  = (
                    line.final_qty * line.price_used
                    if line.price_used else Decimal('0')
                ).quantize(Decimal('0.01'))
                line.save(update_fields=['override_qty', 'final_qty', 'final_value'])
        return

    # ── Value override (₹) ────────────────────────────────────────────────
    if override.override_value is not None:
        target_total_value = override.override_value

        # Total statistical value across all affected lines
        total_stat_value = sum(
            float(l.statistical_value or 0) for l in lines
        ) or 1.0

        # The scaling factor — same for all lines in PROPORTIONAL
        scale = float(target_total_value) / total_stat_value

        for line in lines:
            if override.disagg_method == 'PROPORTIONAL':
                # Each line scales by the same factor — preserves mix
                line.final_value = (
                    Decimal(str(float(line.statistical_value or 0) * scale))
                ).quantize(Decimal('0.01'))

            elif override.disagg_method == 'EQUAL':
                # Each line gets an equal share of the target value
                line.final_value = (
                    target_total_value / Decimal(str(len(lines)))
                ).quantize(Decimal('0.01'))

            elif override.disagg_method == 'CUSTOM':
                weights = {
                    str(sw.child_key): float(sw.weight)
                    for sw in override.split_weights.all()
                }
                uid_key = str({'item_id': line.item.item_id})
                weight  = weights.get(uid_key, 0.0)
                line.final_value = (
                    target_total_value * Decimal(str(weight))
                ).quantize(Decimal('0.01'))

            # Back-calculate final_qty from final_value using this line's price
            # This is for reference only — value is the source of truth at total level
            if line.price_used and float(line.price_used) > 0:
                line.override_qty = (
                    line.final_value / line.price_used
                ).quantize(Decimal('0.001'))
                line.final_qty = line.override_qty
            else:
                # No price — preserve statistical qty, just record value override
                line.override_qty = line.statistical_qty
                line.final_qty    = line.statistical_qty

            line.save(update_fields=['override_qty', 'final_qty', 'final_value'])


@shared_task(bind=True)
def compute_accuracy(self, client_id: int):

    import duckdb
    import pandas as pd
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastAccuracy, ForecastLine
    )
    from mysite.models.demand.actuals import ActualSale, compute_period_end

    versions = ForecastVersion.objects.filter(
        client_id=client_id,
        status__in=[
            ForecastVersion.Status.APPROVED,
            ForecastVersion.Status.LOCKED,
        ],
    )

    total_written = 0

    for version in versions:
        period_type = version.period_type

        lines_qs = (
            ForecastLine.objects
            .filter(version=version)
            .values(
                'id', 'item_id', 'planning_customer_id',
                'planning_location_id', 'period_start', 'final_qty',
            )
        )
        if not lines_qs.exists():
            continue

        lines_df = pd.DataFrame(list(lines_qs))

        actuals_qs = (
            ActualSale.objects
            .filter(
                client_id=client_id,
                period_type=period_type,
                period_start__in=lines_df['period_start'].unique().tolist(),
            )
            .values(
                'item_id', 'planning_customer_id',
                'planning_location_id', 'period_start', 'qty',
            )
        )
        if not actuals_qs.exists():
            continue

        actuals_df = pd.DataFrame(list(actuals_qs))

        con = duckdb.connect()
        con.register('lines',   lines_df)
        con.register('actuals', actuals_df)

        joined = con.execute("3
            SELECT
                l.item_id,
                l.planning_customer_id,
                l.planning_location_id,
                l.period_start,
                CAST(l.final_qty AS DOUBLE) AS forecast_qty,
                CAST(a.qty       AS DOUBLE) AS actual_qty,
                CASE
                    WHEN a.qty > 0 THEN
                        ABS(CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS mape,
                CASE
                    WHEN a.qty > 0 THEN
                        (CAST(l.final_qty AS DOUBLE) - CAST(a.qty AS DOUBLE))
                        / CAST(a.qty AS DOUBLE) * 100
                    ELSE NULL
                END AS bias
            FROM lines l
            INNER JOIN actuals a
                ON  l.item_id              = a.item_id
                AND l.planning_location_id = a.planning_location_id
                AND l.period_start         = a.period_start
                AND (
                    (l.planning_customer_id IS NULL AND a.planning_customer_id IS NULL)
                    OR l.planning_customer_id = a.planning_customer_id
                )
        "3).df()

        if joined.empty:
            continue

        ForecastAccuracy.objects.filter(version=version).delete()

        accuracy_objects = []
        for _, row in joined.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()

            cust_id = row['planning_customer_id']
            cust_id = None if pd.isna(cust_id) else int(cust_id)

            accuracy_objects.append(
                ForecastAccuracy(
                    version_id           = version.pk,
                    item_id              = int(row['item_id']),
                    planning_customer_id = cust_id,
                    planning_location_id = int(row['planning_location_id']),
                    period_type          = period_type,
                    period_start         = period_start,
                    period_end           = compute_period_end(period_start, period_type),
                    actual_qty           = Decimal(str(round(row['actual_qty'],   3))),
                    forecast_qty         = Decimal(str(round(row['forecast_qty'], 3))),
                    mape  = Decimal(str(round(row['mape'], 4)))
                            if row['mape'] is not None and not pd.isna(row['mape'])
                            else None,
                    bias  = Decimal(str(round(row['bias'], 4)))
                            if row['bias'] is not None and not pd.isna(row['bias'])
                            else None,
                )
            )

        ForecastAccuracy.objects.bulk_create(accuracy_objects, batch_size=500)
        total_written += len(accuracy_objects)
        logger.info(
            f'compute_accuracy: version={version.pk} '
            f'accuracy_rows={len(accuracy_objects)}'
        )

    logger.info(
        f'compute_accuracy: client={client_id} total_written={total_written}'
    )

"""