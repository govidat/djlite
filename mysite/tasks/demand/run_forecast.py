# mysite/tasks/demand/run_forecast.py

from __future__ import annotations
import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction

logger = logging.getLogger(__name__)
import pandas as pd

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
        reconciliation       = cfg.get('reconciliation', 'MinTrace_ols')
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
        combined_df = run_statsforecast_by_grain(
            aggregated_actuals=agg_actuals,
            decisions=decisions,
            horizon=horizon,
            freq=freq,
            season_length=season_length,
        )

        # ── Step 8: Disaggregate to atomic ─────────────────────────────────
        atomic_df = disaggregate_to_atomic(
            forecast_df     = combined_df,
            actuals_df      = actuals_pl,
            decisions       = decisions,
            period_type     = version.period_type,
            base_freq       = PERIOD_FREQ_MAP[version.period_type],
            disagg_conflict = disagg_conflict,
        )
        """
        atomic_df = disaggregate_to_atomic(
            forecast_df=combined_df,
            actuals_df=actuals_pl,
            decisions=decisions,
            disagg_conflict=disagg_conflict,
        )
        """

        # ── Step 9: Reconciliation (on atomic forecasts only) ──────────────
        _set_status('RECONCILING')
        try:
            # Build summing matrix from atomic forecasts
            from hierarchicalforecast.utils import aggregate as hf_agg
            actuals_for_rec = actuals_pl.to_pandas()[
                ['unique_id', 'ds', 'y']
            ].copy()
            actuals_for_rec['y']  = actuals_for_rec['y'].astype(float)
            actuals_for_rec['ds'] = pd.to_datetime(actuals_for_rec['ds'])

            # Build location_group for the summing matrix
            actuals_pd = actuals_pl.to_pandas()
            actuals_pd['location_group'] = actuals_pd['region_code']
            hier_raw = actuals_pd[['ds', 'location_group', 'unique_id', 'y']].copy()
            hier_raw['y']  = hier_raw['y'].astype(float)
            hier_raw['ds'] = pd.to_datetime(hier_raw['ds'])

            Y_df, S_df, tags = hf_agg(
                hier_raw,
                [['location_group'], ['location_group', 'unique_id']],
            )

            hf_input = atomic_df[['unique_id', 'ds', 'statistical_qty']].copy()
            hf_input = hf_input.rename(columns={'statistical_qty': 'COMBINED'})

            reconciled = run_hierarchical_reconciliation(
                forecasts_df=hf_input,
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
                # Merge reconciled values back
                rec_lookup = reconciled.set_index(['unique_id', 'ds'])['statistical_qty'].to_dict()
                atomic_df['statistical_qty'] = atomic_df.apply(
                    lambda row: rec_lookup.get(
                        (row['unique_id'], row['ds']),
                        row['statistical_qty']
                    ),
                    axis=1,
                )
        except Exception as exc:
            logger.warning(
                f'run_forecast: reconciliation failed ({exc}) — '
                f'using unreconciled forecasts'
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


def _apply_single_override(override, version):
    """Apply one ForecastOverride to matching ForecastLine rows."""
    from mysite.models.demand.forecast import ForecastLine, ForecastAggregate
    from mysite.models.demand.actuals import ItemPlanningProfile

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

    lines = list(qs.select_related('item'))
    if not lines:
        logger.warning(
            f'_apply_single_override: no matching lines for override {override.pk}'
        )
        return

    update_fields = ['override_qty', 'final_qty', 'override_value', 'final_value']

    # ── Percentage override ────────────────────────────────────────────────
    if override.override_pct is not None:
        multiplier = 1 + float(override.override_pct) / 100
        for line in lines:
            line.override_qty = (
                line.statistical_qty * Decimal(str(multiplier))
            ).quantize(Decimal('0.001'))
            line.save(update_fields=update_fields)
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
                weight  = weights.get(uid_key, 0)
                line.override_qty = Decimal(str(round(override_total * weight, 3)))
                line.save(update_fields=update_fields)

        elif override.disagg_method == 'EQUAL':
            equal_share = Decimal(str(round(override_total / len(lines), 3)))
            for line in lines:
                line.override_qty = equal_share
                line.save(update_fields=update_fields)

        else:  # PROPORTIONAL
            for line in lines:
                share = float(line.statistical_qty) / total_stat
                line.override_qty = Decimal(str(round(override_total * share, 3)))
                line.save(update_fields=update_fields)
        return

    # ── Value override (₹) ────────────────────────────────────────────────
    if override.override_value is not None:
        # Find the ForecastAggregate for this level to get weighted_avg_price
        from mysite.models.demand.forecast import ForecastAggregate
        agg = (
            ForecastAggregate.objects
            .filter(
                version=version,
                agg_level=override.override_level,
                period_start=override.period_start,
            )
            .first()
        )

        if agg and agg.weighted_avg_price and float(agg.weighted_avg_price) > 0:
            # Convert ₹ target to total qty, then disaggregate by VALUE share
            implied_total_qty = (
                override.override_value / agg.weighted_avg_price
            ).quantize(Decimal('0.001'))

            # Disaggregate by value share (each item's final_value / total_final_value)
            total_final_value = sum(
                float(l.final_value or 0) for l in lines
            ) or 1.0

            for line in lines:
                line_value_share = float(line.final_value or 0) / total_final_value
                line.override_qty = (
                    implied_total_qty * Decimal(str(line_value_share))
                ).quantize(Decimal('0.001'))
                line.save(update_fields=update_fields)

        else:
            # Fallback: no weighted_avg_price available
            # Use each line's own price_used to convert value target
            total_stat_value = sum(
                float(l.statistical_value or 0) for l in lines
            ) or 1.0
            for line in lines:
                line_val_share = float(line.statistical_value or 0) / total_stat_value
                line_value_target = override.override_value * Decimal(str(line_val_share))
                if line.price_used and float(line.price_used) > 0:
                    line.override_qty = (
                        line_value_target / line.price_used
                    ).quantize(Decimal('0.001'))
                else:
                    # No price at all — fall back to equal split
                    line.override_qty = (
                        override.override_value / Decimal(str(len(lines)))
                    ).quantize(Decimal('0.001'))
                line.save(update_fields=update_fields)


@shared_task(bind=True)
def compute_accuracy(self, client_id: int):
    """
    Nightly task. For LOCKED/APPROVED versions where actuals have landed,
    compute MAPE and Bias and write ForecastAccuracy rows.
    """
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

        joined = con.execute("""
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
        """).df()

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