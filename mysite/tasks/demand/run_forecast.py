# mysite/tasks/demand/run_forecast.py

from __future__ import annotations
import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction
from django.utils import timezone

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
        build_scheme_forecast_factors,
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

        # Build scheme forecast factors for the horizon
        scheme_factors = {}
        if config and config.scheme_net_actuals:
            from mysite.models.demand.forecast import ForecastingConfig
            cfg_fc = ForecastingConfig.get_for_client(version.client)
            if cfg_fc.scheme_apply_forecast_uplift:
                # Determine the period range from the forecast DataFrame
                if not atomic_df.empty and 'ds' in atomic_df.columns:
                    period_starts = pd.to_datetime(atomic_df['ds'])
                    period_start_from = period_starts.min().date() if hasattr(period_starts.min(), 'date') else period_starts.min()
                    period_start_to = period_starts.max().date() if hasattr(period_starts.max(), 'date') else period_starts.max()
                    scheme_factors = build_scheme_forecast_factors(
                        client_id=version.client_id,
                        period_type=period_type,
                        period_start_from=period_start_from,
                        period_start_to=period_start_to,
                    )

        n_lines = write_forecast_lines(
            version_id=version_id,
            forecast_df=atomic_df,
            decisions=decisions,
            period_type=period_type,
            store_all_level_forecasts=store_all_levels,
            scheme_factors=scheme_factors or None,
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
 
 

@shared_task(bind=True)
def compute_accuracy(self, client_id: int, version_id: int = None):
    """
    Manual/nightly accuracy task.

    Grades APPROVED/LOCKED versions (optionally narrowed to one via
    version_id) by joining ForecastLine.final_qty / final_value against
    ActualSale actuals for the version's forecast periods, then writes
    ForecastAccuracy rows (replacing any previous rows for that version).

    ── Net actuals ──────────────────────────────────────────────────────────
    Governed by ForecastingConfig.reporting_uses_net_actuals: when the flag
    is on, actuals are netted of CONFIRMED outlier adjustments before
    grading (net_qty = qty - qty_adjustment, net_revenue = revenue -
    revenue_adjustment). When off, raw qty / revenue are used. A FAILED run
    never advances last_accuracy_run_at, so it can be retried.

    ── Value roll-up basis ──────────────────────────────────────────────────
      actual_value   = net_revenue when maintained, else net_qty × price
      forecast_value = final_value when priced,     else final_qty × price
    where price = ForecastLine.price_used, falling back to
    ItemPlanningProfile.standard_price (planner-maintained planned price).
    Rows drop out of value metrics only when neither revenue nor any price
    is available.

    ── Roll-up stats (stored on the version for reporting) ─────────────────
      wmape      = Σ|forecast − actual|   / Σactual × 100
      wbias      = Σ(forecast − actual)   / Σactual × 100
      value_mape = Σ|forecast_v − actual_v| / Σactual_v × 100
    """
    import duckdb
    import pandas as pd
    from mysite.models import Client
    from mysite.models.demand.forecast import (
        ForecastVersion, ForecastAccuracy, ForecastLine, ForecastingConfig,
    )
    from mysite.models.demand.actuals import (
        compute_period_end, ItemPlanningProfile,
    )
    from utils.demand.actuals_net import actuals_queryset_with_net

    client = Client.objects.get(pk=client_id)

    versions = ForecastVersion.objects.filter(
        client_id=client_id,
        status__in=[
            ForecastVersion.Status.APPROVED,
            ForecastVersion.Status.LOCKED,
        ],
    )
    if version_id:
        versions = versions.filter(pk=version_id)

    cfg = ForecastingConfig.get_for_client(client)
    use_net = bool(cfg.reporting_uses_net_actuals)
    use_scheme_net = bool(cfg.scheme_net_actuals)
    use_sub = bool(cfg.use_item_lifecycle)

    # Planner-maintained planned price fallback, per item.
    fallback_prices = {
        p['item_id']: p['standard_price']
        for p in (
            ItemPlanningProfile.objects
            .filter(client_id=client_id)
            .values('item_id', 'standard_price')
        )
        if p['standard_price'] is not None
    }

    total_written = 0

    for version in versions:
        version.accuracy_run_status = ForecastVersion.AccuracyRunStatus.RUNNING
        version.accuracy_run_error = ''
        version.save(update_fields=['accuracy_run_status', 'accuracy_run_error', 'updated_at'])

        period_type = version.period_type

        try:
            lines_qs = (
                ForecastLine.objects
                .filter(version=version)
                .values(
                    'id', 'item_id', 'planning_customer_id',
                    'planning_location_id', 'distribution_channel_id',
                    'period_start', 'final_qty', 'final_value', 'price_used',
                )
            )
            if not lines_qs.exists():
                raise ValueError('No forecast lines for this version.')

            lines_df = pd.DataFrame(list(lines_qs))

            actuals_qs = (
                actuals_queryset_with_net(client, use_net, use_scheme_net=use_scheme_net,
                                          use_substitution=use_sub)
                .filter(
                    period_type=period_type,
                    period_start__in=lines_df['period_start'].unique().tolist(),
                )
                .values(
                    'item_id', 'planning_customer_id',
                    'planning_location_id', 'distribution_channel_id',
                    'period_start', 'net_qty', 'net_revenue',
                )
            )
            if not actuals_qs.exists():
                raise ValueError('No actuals found for the forecast periods.')

            actuals_df = pd.DataFrame(list(actuals_qs))
            actuals_df = actuals_df.rename(
                columns={'net_qty': 'qty', 'net_revenue': 'revenue'}
            )

            con = duckdb.connect()
            con.register('lines',   lines_df)
            con.register('actuals', actuals_df)

            joined = con.execute("""
                SELECT
                    l.item_id,
                    l.planning_customer_id,
                    l.planning_location_id,
                    l.distribution_channel_id,
                    l.period_start,
                    CAST(l.final_qty   AS DOUBLE) AS forecast_qty,
                    CAST(l.final_value AS DOUBLE) AS forecast_value,
                    CAST(l.price_used  AS DOUBLE) AS price_used,
                    CAST(a.qty         AS DOUBLE) AS actual_qty,
                    CAST(a.revenue     AS DOUBLE) AS actual_revenue,
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
            con.close()

            if joined.empty:
                raise ValueError('No forecast lines matched actuals.')

            def _resolve_value(source_value, qty, price_used, item_id):
                if source_value is not None and not pd.isna(source_value):
                    return Decimal(str(round(float(source_value), 2)))
                price = price_used
                if price is None or pd.isna(price):
                    price = fallback_prices.get(int(item_id))
                if price is None or pd.isna(price):
                    return None
                return (
                    Decimal(str(round(float(qty), 3)))
                    * Decimal(str(round(float(price), 4)))
                ).quantize(Decimal('0.01'))

            ForecastAccuracy.objects.filter(version=version).delete()

            accuracy_objects = []
            for _, row in joined.iterrows():
                period_start = row['period_start']
                if hasattr(period_start, 'date'):
                    period_start = period_start.date()

                cust_id = row['planning_customer_id']
                cust_id = None if pd.isna(cust_id) else int(cust_id)

                actual_qty = Decimal(str(round(float(row['actual_qty']), 3)))
                forecast_qty = Decimal(str(round(float(row['forecast_qty']), 3)))
                actual_value = _resolve_value(
                    row['actual_revenue'], row['actual_qty'],
                    row['price_used'], row['item_id'],
                )
                forecast_value = _resolve_value(
                    row['forecast_value'], row['forecast_qty'],
                    row['price_used'], row['item_id'],
                )

                accuracy_objects.append(
                    ForecastAccuracy(
                        version_id           = version.pk,
                        item_id              = int(row['item_id']),
                        planning_customer_id = cust_id,
                        planning_location_id = int(row['planning_location_id']),
                        distribution_channel_id = str(row['distribution_channel_id']),
                        period_type          = period_type,
                        period_start         = period_start,
                        period_end           = compute_period_end(period_start, period_type),
                        actual_qty           = actual_qty,
                        forecast_qty         = forecast_qty,
                        actual_value         = actual_value,
                        forecast_value       = forecast_value,
                        mape  = Decimal(str(round(float(row['mape']), 4)))
                                if row['mape'] is not None and not pd.isna(row['mape'])
                                else None,
                        bias  = Decimal(str(round(float(row['bias']), 4)))
                                if row['bias'] is not None and not pd.isna(row['bias'])
                                else None,
                    )
                )

            ForecastAccuracy.objects.bulk_create(accuracy_objects, batch_size=500)
            total_written += len(accuracy_objects)

            # ── Weighted roll-up stats ─────────────────────────────────────────
            graded = [r for r in accuracy_objects if r.actual_qty > 0]
            sum_abs  = sum(abs(r.forecast_qty - r.actual_qty) for r in graded)
            sum_act  = sum(r.actual_qty for r in graded)
            sum_diff = sum(r.forecast_qty - r.actual_qty for r in graded)
            wmape = (sum_abs / sum_act * Decimal('100')).quantize(Decimal('0.01')) if sum_act else None
            wbias = (sum_diff / sum_act * Decimal('100')).quantize(Decimal('0.01')) if sum_act else None

            valued = [
                r for r in accuracy_objects
                if r.actual_value is not None and r.actual_value > 0
            ]
            v_abs = sum(abs(r.forecast_value - r.actual_value) for r in valued)
            v_act = sum(r.actual_value for r in valued)
            value_mape = (v_abs / v_act * Decimal('100')).quantize(Decimal('0.01')) if v_act else None

            version.last_accuracy_rows     = len(accuracy_objects)
            version.last_accuracy_wmape    = wmape
            version.last_accuracy_wbias    = wbias
            version.last_accuracy_value_mape = value_mape
            version.last_accuracy_run_at   = timezone.now()
            version.accuracy_run_status    = ForecastVersion.AccuracyRunStatus.COMPLETE
            version.accuracy_run_error     = ''
            version.save(update_fields=[
                'accuracy_run_status', 'accuracy_run_error',
                'last_accuracy_run_at', 'last_accuracy_rows',
                'last_accuracy_wmape', 'last_accuracy_wbias',
                'last_accuracy_value_mape', 'updated_at',
            ])

            logger.info(
                f'compute_accuracy: version={version.pk} '
                f'accuracy_rows={len(accuracy_objects)} wmape={wmape} value_mape={value_mape}'
            )

        except Exception as exc:
            version.accuracy_run_status = ForecastVersion.AccuracyRunStatus.FAILED
            version.accuracy_run_error  = traceback.format_exc()
            version.save(update_fields=['accuracy_run_status', 'accuracy_run_error', 'updated_at'])
            logger.exception(
                f'compute_accuracy: version={version.pk} failed: {exc}'
            )

    logger.info(
        f'compute_accuracy: client={client_id} total_written={total_written}'
    )

