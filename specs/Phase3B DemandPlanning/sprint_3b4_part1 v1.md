# Sprint 3B.4 — Forecast Engine and Reconciliation
## Detailed Implementation Instructions

**Dependencies:** Sprint 3B.3 complete  
**Estimated effort:** 4–5 days  
**Deliverable:** Triggering a `ForecastVersion` run produces auditable `ForecastLine`
records with hierarchically reconciled quantities. `ForecastAggregate` rows cover all
hierarchy levels. Accuracy metrics computed nightly once actuals land.

--- Theory
Q1: Forecastable series → forecast quantity, aggregate/disaggregate on quantity
Yes, this is correct and is the standard approach. For any series classified as SMOOTH, ERRATIC, or INTERMITTENT, the statistical engine forecasts qty at the grain where the series is statistically reliable. MinTrace reconciliation then ensures all levels are coherent — SKU quantities sum to subcategory quantities sum to category quantities. Aggregation and disaggregation operate entirely on qty.

Q2: Non-forecastable series (LUMPY, ZERO, INSUFFICIENT) — do we still forecast?
Yes, but not from the bottom up. The correct approach is:

LUMPY: aggregate all LUMPY items at a location to the location total, forecast that aggregate (which is now smooth because lumpy items aggregate into regular demand), then disaggregate back to SKUs using historical proportions.
INSUFFICIENT / ZERO: use a simple moving average of whatever non-zero observations exist, or carry the last known non-zero period forward. Do not attempt a statistical model.
The forecast engine never produces a zero forecast for an item that had any historical demand — it always produces something, just from a higher level.

So the answer to "do we forecast at the highest aggregation level and disaggregate?" is: yes, for non-forecastable series specifically. For forecastable series the bottom-up statistical forecast is preferred.

Q3: Should there be a value forecast at aggregate levels, with consensus on value, disaggregated back to quantity?
This is the most important question and the answer is: yes, you need both.
Here is the standard industry practice for this exact situation:
Two-layer forecast:
Layer 1 — Statistical quantity forecast (bottom-up, per item)
           StatsForecast → ForecastLine.statistical_qty
           
Layer 2 — Value consensus forecast (top-down, per aggregate level)
           Planner sets a revenue/value target at Region / Channel / Category level
           This is disaggregated back to item quantities using:
             item_qty = (item_historical_value_share × aggregate_value_target) / item_unit_price

The planner never touches 20,000 SKU rows. They work at the value aggregate level — "North Region should do ₹50 Cr in Q1" — and the engine translates that into per-SKU quantities.
Q4: If forecast is only on quantity, aggregate levels still need to see value
Correct. Value is always computed and displayed, even when the forecast engine operates on quantity. The formula is simple:
ForecastLine.statistical_value = statistical_qty × item.unit_price
ForecastLine.final_value       = final_qty × item.unit_price

These are computed fields, not stored — they are derived at query time from qty × price. ForecastAggregate stores the sum of these computed values at each level. Planners see value at every level; the engine only forecasts quantity.

Q5: 20K items is incomprehensible — a single value total per level is what planners use
Exactly right. This is the standard "consensus planning" pattern:
Planner works at:     Category × Region × Period    (value)
Engine works at:      SKU × Customer × Location     (quantity)
The bridge is:        historical value share weights

Unified Design Resulting from These Answers

STATISTICAL ENGINE          CONSENSUS LAYER             OUTPUT
(quantity, bottom-up)       (value, top-down)           (quantity + value)

StatsForecast               Planner sets                ForecastLine
→ statistical_qty           value targets at:             .statistical_qty
  per SKU×Cust×Loc          - Category level              .statistical_value
                            - Region level                .override_qty (from consensus)
                            - Channel level               .final_qty
                                                          .final_value

HierarchicalForecast        Value disaggregated         ForecastAggregate
MinTrace reconciliation     to SKU qty via:               .statistical_qty
→ coherent qty totals         qty = value_target /         .statistical_value
  at all levels               unit_price × share           .override_qty
                                                           .final_qty
                                                           .final_value

This means two additions to the model before the engine code:

ForecastLine needs unit_price (snapshot of price at forecast time) and statistical_value / final_value as stored computed fields
ForecastAggregate needs statistical_value and final_value
ForecastOverride needs to accept override_value (in addition to override_qty and override_pct) as a new override type
---

## Table of Contents

1. [Architecture and Data Flow](#1-architecture-and-data-flow)
2. [Model Changes](#2-model-changes)
3. [Forecast Engine Utility — `forecast_engine.py`](#3-forecast-engine-utility)
4. [Celery Task — `run_forecast`](#4-celery-task-run_forecast)
5. [Celery Task — `run_reconciliation`](#5-celery-task-run_reconciliation)
6. [Celery Task — `apply_overrides`](#6-celery-task-apply_overrides)
7. [Celery Task — `compute_accuracy`](#7-celery-task-compute_accuracy)
8. [REST Endpoints — run and status](#8-rest-endpoints)
9. [Serializers and Views](#9-serializers-and-views)
10. [URL Registration](#10-url-registration)
11. [Caching](#11-caching)
12. [Unit Tests](#12-unit-tests)
13. [Final Checklist](#13-final-checklist)

---

## 1. Architecture and Data Flow

### Pipeline overview

```
Planner clicks "Run Forecast"
         │
         ▼
POST /api/demand/forecast-versions/{id}/run/
  │  Creates ForecastRun record (status=QUEUED)
  │  Fires Celery task chain
  └──► run_forecast.delay(version_id, run_id)
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 1: build_actuals_dataframe()          │
    │  DuckDB query over ActualSale               │
    │  → Polars DataFrame (unique_id, ds, y)      │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 2: classify series via SeriesProfile  │
    │  Group series by effective_strategy         │
    │  LUMPY series → aggregate to location grain │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 3: run_statsforecast()                │
    │  AutoETS batch  → smooth/erratic series     │
    │  CrostonSBA batch → intermittent series     │
    │  MovingAvg batch  → insufficient series     │
    │  (LUMPY series forecasted at location grain)│
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 4: write_forecast_lines()             │
    │  bulk_create ForecastLine rows              │
    │  model_used and forecast_level recorded     │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    run_reconciliation.delay(version_id, run_id)
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 5: build_summing_matrix()             │
    │  Walks Item taxonomy + PlanningLocation     │
    │  + SalesNode trees                          │
    │  → S_df (summing matrix) + tags dict        │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 6: run_hierarchical_reconciliation()  │
    │  HierarchicalForecast MinTrace / BottomUp   │
    │  → reconciled_df                            │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ┌─────────────────────────────────────────────┐
    │  STEP 7: write_forecast_aggregates()        │
    │  Rolls up ForecastLine into ForecastAggregate│
    │  for all agg_levels                         │
    └──────────────────┬──────────────────────────┘
                       │
                       ▼
    ForecastVersion.status → DRAFT (ready for planner review)
    ForecastRun.status     → COMPLETE
```

### Key design principles

**DuckDB for data extraction** — ActualSale has potentially millions of rows.
DuckDB queries PostgreSQL-exported data in-process without loading the entire
table into Python memory. It runs inside the Celery worker process.

**Polars for transformation** — Building the `Y_long` DataFrame (unique_id × ds × y)
and the disaggregation weight matrix uses Polars for speed. At 10K SKUs × 200
customers × 36 months = 72M potential combinations, pandas is too slow.

**StatsForecast batches by model type** — All SMOOTH series are forecast in one
vectorised call, all INTERMITTENT in another. This is faster than per-series
model selection inside a loop.

**Two-phase write** — `run_forecast` writes statistical lines. `run_reconciliation`
reads those lines, reconciles, and overwrites `statistical_qty`. The two tasks
are chained in Celery so they run sequentially but can be retried independently.

---

## 2. Model Changes

Two additions needed before writing the engine code.

### 2.1 Add `ForecastRun` model to `forecast.py`

`ForecastRun` tracks the progress of one forecast engine execution for a version.
A version can have multiple runs (e.g. re-run after new actuals arrive).

```python
# Add to mysite/models/demand/forecast.py

class ForecastRun(models.Model):
    """
    Tracks one execution of the forecast engine for a ForecastVersion.

    A ForecastVersion can have multiple ForecastRun records — e.g. the
    planner re-runs after uploading corrected actuals.

    celery_task_id is stored so the client can poll Celery directly
    for real-time progress if needed.
    """

    class RunStatus(models.TextChoices):
        QUEUED      = 'QUEUED',      _('Queued')
        RUNNING     = 'RUNNING',     _('Running')
        RECONCILING = 'RECONCILING', _('Reconciling')
        COMPLETE    = 'COMPLETE',    _('Complete')
        FAILED      = 'FAILED',      _('Failed')

    version = models.ForeignKey(
        ForecastVersion,
        on_delete=models.CASCADE,
        related_name='runs',
        verbose_name=_('forecast version'),
    )
    status = models.CharField(
        _('status'),
        max_length=16,
        choices=RunStatus.choices,
        default=RunStatus.QUEUED,
        db_index=True,
    )
    celery_task_id = models.CharField(
        _('celery task ID'),
        max_length=255,
        blank=True,
        help_text=_('Celery AsyncResult ID for progress polling.'),
    )
    started_at  = models.DateTimeField(_('started at'),  null=True, blank=True)
    finished_at = models.DateTimeField(_('finished at'), null=True, blank=True)
    triggered_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='forecast_runs_triggered',
        verbose_name=_('triggered by'),
    )
    # Progress counters for UI polling
    series_total     = models.PositiveIntegerField(default=0)
    series_done      = models.PositiveIntegerField(default=0)
    lines_written    = models.PositiveIntegerField(default=0)
    error_log        = models.TextField(blank=True)

    class Meta:
        app_label           = 'mysite'
        ordering            = ['-started_at']
        verbose_name        = _('03-08 Forecast Run')
        verbose_name_plural = _('03-08 Forecast Runs')
        indexes = [
            models.Index(
                fields=['version', 'status'],
                name='ix_fcstrun_ver_status',
            ),
        ]

    def __str__(self):
        return (
            f'{self.version.version_label} | '
            f'run #{self.pk} | {self.status}'
        )

    @property
    def progress_pct(self) -> int:
        if self.series_total == 0:
            return 0
        return min(100, int(self.series_done / self.series_total * 100))
```

### 2.2 Migration

```bash
python manage.py makemigrations mysite --name forecast_run_model
python manage.py migrate
```

---

## 3. Forecast Engine Utility

Create `mysite/utils/demand/forecast_engine.py`.
This is a pure utility module — no Django ORM calls, no Celery.
Every function takes plain Python/Polars/pandas objects and returns them.
This makes unit testing trivial.

```python
# mysite/utils/demand/forecast_engine.py
"""
Forecast engine utility functions.

All functions are pure (no Django ORM, no Celery).
Celery tasks in mysite/tasks/demand/run_forecast.py call these functions
and handle all DB reads/writes around them.

Pipeline:
  build_actuals_dataframe()       → polars DataFrame
  classify_series()               → dict grouping unique_ids by strategy
  run_statsforecast()             → pandas DataFrame (StatsForecast output)
  build_summing_matrix()          → (S_df, tags)
  run_hierarchical_reconciliation() → pandas DataFrame (reconciled)
  disaggregate_location_forecasts() → pandas DataFrame (expanded back to grain)
  compute_moving_average()        → pandas DataFrame
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import duckdb
import polars as pl
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ── StatsForecast freq map (imported from actuals to avoid duplication) ───────
# Import at call time to avoid circular imports at module level


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Build actuals DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def build_actuals_dataframe(
    actuals_records: list[dict],
    period_type: str,
    min_date: str | None = None,
    max_date: str | None = None,
) -> pl.DataFrame:
    """
    Build the Y_long DataFrame consumed by StatsForecast.

    Args:
        actuals_records: list of dicts with keys:
            item_id, planning_customer_id (nullable), planning_location_id,
            period_start (date), qty (Decimal)
        period_type: e.g. 'month'
        min_date: ISO date string — exclude periods before this date
        max_date: ISO date string — exclude periods after this date

    Returns:
        Polars DataFrame with columns:
            unique_id  str   — "{item_id}|{customer_id}|{location_id}"
                               customer_id is 'NONE' when null
            ds         date  — period_start
            y          float — qty
            item_id    str
            customer_id str  — 'NONE' when unattributed
            location_id str
    """
    if not actuals_records:
        return pl.DataFrame(
            schema={
                'unique_id': pl.Utf8, 'ds': pl.Date,
                'y': pl.Float64, 'item_id': pl.Utf8,
                'customer_id': pl.Utf8, 'location_id': pl.Utf8,
            }
        )

    con = duckdb.connect()
    con.register('actuals', pd.DataFrame(actuals_records))

    where_clauses = []
    if min_date:
        where_clauses.append(f"period_start >= DATE '{min_date}'")
    if max_date:
        where_clauses.append(f"period_start <= DATE '{max_date}'")
    where_sql = ('WHERE ' + ' AND '.join(where_clauses)) if where_clauses else ''

    sql = f"""
        SELECT
            CONCAT(
                item_id, '|',
                COALESCE(CAST(planning_customer_id AS VARCHAR), 'NONE'), '|',
                CAST(planning_location_id AS VARCHAR)
            )                                     AS unique_id,
            period_start                          AS ds,
            SUM(CAST(qty AS DOUBLE))              AS y,
            item_id,
            COALESCE(
                CAST(planning_customer_id AS VARCHAR), 'NONE'
            )                                     AS customer_id,
            CAST(planning_location_id AS VARCHAR) AS location_id
        FROM actuals
        {where_sql}
        GROUP BY item_id, planning_customer_id, planning_location_id, period_start
        ORDER BY unique_id, period_start
    """
    result_pd = con.execute(sql).df()
    con.close()

    df = pl.from_pandas(result_pd).with_columns([
        pl.col('ds').cast(pl.Date),
        pl.col('y').cast(pl.Float64),
    ])
    return df


def build_full_time_spine(
    df: pl.DataFrame,
    period_type: str,
) -> pl.DataFrame:
    """
    Ensure every unique_id has a row for every period in the date range,
    filling missing periods with y=0.0.

    StatsForecast requires a complete, gapless time series.
    Missing periods (no sales) must be represented as zeros, not absent rows.
    """
    all_dates = df.select('ds').unique().sort('ds')['ds'].to_list()
    all_ids   = df.select('unique_id').unique()['unique_id'].to_list()

    # Cross join: every id × every date
    spine = pl.DataFrame({
        'unique_id': all_ids * len(all_dates),
        'ds': sorted(all_dates * len(all_ids)),
    }).sort(['unique_id', 'ds'])

    # Left join spine onto actuals — missing y becomes null → fill with 0
    result = spine.join(
        df.select(['unique_id', 'ds', 'y']),
        on=['unique_id', 'ds'],
        how='left',
    ).with_columns(
        pl.col('y').fill_null(0.0)
    )

    # Re-attach dimension columns (item_id, customer_id, location_id)
    dim_df = df.select(
        ['unique_id', 'item_id', 'customer_id', 'location_id']
    ).unique('unique_id')
    result = result.join(dim_df, on='unique_id', how='left')

    return result


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Classify series by strategy
# ─────────────────────────────────────────────────────────────────────────────

def classify_series(
    df: pl.DataFrame,
    profiles: dict[str, str],
) -> dict[str, list[str]]:
    """
    Group unique_ids by their effective forecast strategy.

    Args:
        df:       actuals DataFrame with 'unique_id' column
        profiles: dict mapping unique_id → effective_strategy string
                  Built by the Celery task from SeriesProfile.objects.

    Returns:
        dict mapping strategy → list of unique_ids
        e.g. {
            'AUTOETS':      ['ITEM-001|CUST-A|LOC-1', ...],
            'CROSTON':      ['ITEM-005|NONE|LOC-2', ...],
            'AGG_LOCATION': ['ITEM-009|CUST-B|LOC-1', ...],
            'MOVING_AVG':   ['ITEM-012|NONE|LOC-3', ...],
            'MANUAL':       ['ITEM-015|CUST-C|LOC-2', ...],
        }
    """
    all_ids = df['unique_id'].unique().to_list()
    groups: dict[str, list[str]] = {}

    for uid in all_ids:
        strategy = profiles.get(uid, 'AUTOETS')  # default to AutoETS if no profile
        groups.setdefault(strategy, []).append(uid)

    # Log distribution
    for strategy, ids in sorted(groups.items()):
        logger.info(f'classify_series: {strategy} → {len(ids)} series')

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Run StatsForecast
# ─────────────────────────────────────────────────────────────────────────────

def run_statsforecast(
    df: pl.DataFrame,
    unique_ids: list[str],
    horizon: int,
    freq: str,
    model_name: str,
    season_length: int = 12,
    n_windows: int = 2,
) -> pd.DataFrame:
    """
    Run StatsForecast for a specific group of series with one model type.

    Args:
        df:           full actuals DataFrame (all series)
        unique_ids:   subset of unique_ids to forecast with this model
        horizon:      number of periods ahead to forecast
        freq:         pandas/StatsForecast offset alias (e.g. 'MS')
        model_name:   'AUTOETS' | 'AUTOARIMA' | 'CROSTON' | 'MOVING_AVG'
        season_length: seasonal period length (12 for monthly, 4 for quarterly)
        n_windows:    ConformalIntervals windows for prediction intervals

    Returns:
        pandas DataFrame with columns:
            unique_id, ds, {ModelName}, {ModelName}-lo-80, {ModelName}-hi-80
    """
    from statsforecast import StatsForecast
    from statsforecast.models import (
        AutoETS, AutoARIMA, CrostonSBA, SeasonalNaive,
    )
    from statsforecast.utils import ConformalIntervals

    # Filter to this group
    subset = df.filter(pl.col('unique_id').is_in(unique_ids))
    subset_pd = subset.select(['unique_id', 'ds', 'y']).to_pandas()
    subset_pd['ds'] = pd.to_datetime(subset_pd['ds'])
    subset_pd['y']  = subset_pd['y'].astype(float)

    if subset_pd.empty:
        return pd.DataFrame(columns=['unique_id', 'ds', model_name])

    # Select model
    if model_name == 'AUTOETS':
        models = [AutoETS(season_length=season_length)]
    elif model_name == 'AUTOARIMA':
        models = [AutoARIMA(season_length=season_length)]
    elif model_name == 'CROSTON':
        models = [CrostonSBA()]
    elif model_name == 'MOVING_AVG':
        # SeasonalNaive as proxy for moving average — uses last season
        models = [SeasonalNaive(season_length=season_length)]
    else:
        raise ValueError(f'Unknown model_name: {model_name!r}')

    sf = StatsForecast(models=models, freq=freq, n_jobs=-1)

    forecast_pd = sf.forecast(
        df=subset_pd,
        h=horizon,
        fitted=True,
        prediction_intervals=ConformalIntervals(h=horizon, n_windows=n_windows),
        level=[80, 95],
    )

    # Standardise column name: model produces e.g. 'AutoETS' → rename to model_name
    model_col = [c for c in forecast_pd.columns
                 if c not in ('unique_id', 'ds')
                 and not c.endswith(('-lo-80', '-hi-80', '-lo-95', '-hi-95'))][0]

    forecast_pd = forecast_pd.rename(columns={
        model_col: model_name,
        f'{model_col}-lo-80': f'{model_name}-lo-80',
        f'{model_col}-hi-80': f'{model_name}-hi-80',
        f'{model_col}-lo-95': f'{model_name}-lo-95',
        f'{model_col}-hi-95': f'{model_name}-hi-95',
    })

    return forecast_pd


def compute_moving_average(
    df: pl.DataFrame,
    unique_ids: list[str],
    horizon: int,
    freq: str,
    window: int = 6,
) -> pd.DataFrame:
    """
    Simple trailing moving average for INSUFFICIENT / MOVING_AVG series.

    Uses the mean of the last `window` non-zero observations.
    Flat forecast (same value for all horizon periods).
    """
    from statsforecast.models import SeasonalNaive
    from statsforecast import StatsForecast

    subset = df.filter(pl.col('unique_id').is_in(unique_ids))

    rows = []
    for uid in unique_ids:
        series = subset.filter(pl.col('unique_id') == uid).sort('ds')
        non_zero = series.filter(pl.col('y') > 0)['y'].to_list()
        if non_zero:
            avg = float(np.mean(non_zero[-window:]))
        else:
            avg = 0.0

        # Generate horizon periods
        last_date = series['ds'].max()
        future_dates = _generate_future_dates(last_date, horizon, freq)
        for d in future_dates:
            rows.append({'unique_id': uid, 'ds': d, 'MOVING_AVG': avg})

    return pd.DataFrame(rows)


def _generate_future_dates(last_date, horizon: int, freq: str) -> list:
    """Generate `horizon` future dates starting after `last_date`."""
    import datetime
    from dateutil.relativedelta import relativedelta

    freq_map = {
        'D': lambda d, i: d + datetime.timedelta(days=i),
        'W-MON': lambda d, i: d + datetime.timedelta(weeks=i),
        'MS':    lambda d, i: (d.replace(day=1) + relativedelta(months=i+1)),
        '2MS':   lambda d, i: (d.replace(day=1) + relativedelta(months=(i+1)*2)),
        'QS':    lambda d, i: (d.replace(day=1) + relativedelta(months=(i+1)*3)),
        '2QS':   lambda d, i: (d.replace(day=1) + relativedelta(months=(i+1)*6)),
        'YS':    lambda d, i: (d.replace(day=1) + relativedelta(years=i+1)),
    }
    fn = freq_map.get(freq)
    if fn is None:
        raise ValueError(f'Unsupported freq: {freq!r}')
    return [fn(last_date, i) for i in range(horizon)]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3b — Aggregate LUMPY series to location grain, then disaggregate back
# ─────────────────────────────────────────────────────────────────────────────

def aggregate_to_location_grain(
    df: pl.DataFrame,
    lumpy_ids: list[str],
) -> tuple[pl.DataFrame, dict[str, dict]]:
    """
    For LUMPY series, aggregate actuals to (item, location) grain — dropping
    the customer dimension — so the time series becomes smoother.

    Returns:
        agg_df:    Polars DataFrame at (item, location) grain with unique_id
                   = "{item_id}|NONE|{location_id}"
        weights:   dict mapping agg_uid → {original_uid: share}
                   Used by disaggregate_location_forecasts() to split
                   the location-level forecast back to customer level.
    """
    subset = df.filter(pl.col('unique_id').is_in(lumpy_ids))

    # Aggregate to item × location
    agg = (
        subset
        .group_by(['item_id', 'location_id', 'ds'])
        .agg(pl.sum('y').alias('y'))
        .with_columns(
            pl.concat_str([
                pl.col('item_id'),
                pl.lit('|NONE|'),
                pl.col('location_id'),
            ]).alias('unique_id')
        )
        .select(['unique_id', 'ds', 'y', 'item_id', 'location_id'])
        .with_columns(pl.lit('NONE').alias('customer_id'))
    )

    # Compute historical share weights for disaggregation
    # Weight = customer's share of total location-level demand (trailing history)
    total_by_loc_item = (
        subset
        .group_by(['item_id', 'location_id'])
        .agg(pl.sum('y').alias('total_y'))
    )
    share_by_uid = (
        subset
        .group_by(['unique_id', 'item_id', 'location_id'])
        .agg(pl.sum('y').alias('uid_y'))
        .join(total_by_loc_item, on=['item_id', 'location_id'])
        .with_columns(
            pl.concat_str([
                pl.col('item_id'),
                pl.lit('|NONE|'),
                pl.col('location_id'),
            ]).alias('agg_uid')
        )
        .with_columns(
            (pl.col('uid_y') / pl.col('total_y').clip(lower_bound=0.0001))
            .alias('share')
        )
    )

    weights: dict[str, dict] = {}
    for row in share_by_uid.iter_rows(named=True):
        agg_uid = row['agg_uid']
        weights.setdefault(agg_uid, {})[row['unique_id']] = float(row['share'])

    return agg, weights


def disaggregate_location_forecasts(
    location_forecast_df: pd.DataFrame,
    weights: dict[str, dict],
    model_name: str,
) -> pd.DataFrame:
    """
    Disaggregate a location-level forecast back to customer × item grain
    using historical share weights.

    Args:
        location_forecast_df: output of run_statsforecast() at location grain
        weights: dict from aggregate_to_location_grain()
        model_name: column name in location_forecast_df

    Returns:
        pandas DataFrame at original grain with same columns
    """
    rows = []
    for _, row in location_forecast_df.iterrows():
        agg_uid = row['unique_id']
        agg_qty = float(row.get(model_name, 0) or 0)
        uid_weights = weights.get(agg_uid, {})

        if not uid_weights:
            # No weight info — keep at location grain (customer=NONE)
            rows.append({
                'unique_id': agg_uid,
                'ds': row['ds'],
                model_name: agg_qty,
            })
            continue

        for original_uid, share in uid_weights.items():
            rows.append({
                'unique_id': original_uid,
                'ds': row['ds'],
                model_name: round(agg_qty * share, 3),
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Build summing matrix for hierarchical reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def build_summing_matrix(
    bottom_level_ids: list[str],
    item_hierarchy: list[dict],
    location_hierarchy: list[dict],
    sales_hierarchy: list[dict],
) -> tuple[pd.DataFrame, dict]:
    """
    Build the summing matrix S and tags dict for HierarchicalForecast.

    The summing matrix S maps every hierarchy node to the bottom-level
    series (unique_ids) that contribute to it.

    Args:
        bottom_level_ids: list of unique_id strings at leaf grain
            e.g. ['ITEM-001|CUST-A|LOC-1', ...]

        item_hierarchy: list of dicts — one per item leaf — with keys:
            item_id, subcategory, category
            e.g. [{'item_id': 'ITEM-001', 'subcategory': 'Brake Pads',
                   'category': 'Braking Systems'}, ...]

        location_hierarchy: list of dicts — one per location — with keys:
            location_id (str of PK), code, parent_code (nullable), region
            e.g. [{'location_id': '3', 'code': 'DEL',
                   'parent_code': 'NORTH', 'region': 'North'}, ...]

        sales_hierarchy: list of dicts — one per sales node — with keys:
            node_id (str), name, parent_id (nullable), level_label
            (Used for SalesNode-level aggregates in ForecastAggregate)

    Returns:
        (S_df, tags) in HierarchicalForecast format:
            S_df: pandas DataFrame, index=all node names,
                  columns=bottom_level_ids, values=0/1
            tags: dict mapping level_name → array of node names at that level
    """
    from hierarchicalforecast.utils import aggregate

    # Build a flat table linking each bottom-level unique_id to its
    # hierarchy attributes — this is what aggregate() needs.
    item_map     = {d['item_id']:     d for d in item_hierarchy}
    location_map = {d['location_id']: d for d in location_hierarchy}

    rows = []
    for uid in bottom_level_ids:
        parts = uid.split('|')
        if len(parts) != 3:
            logger.warning(f'build_summing_matrix: skipping malformed uid {uid!r}')
            continue

        item_id, customer_id, location_id = parts
        item_info = item_map.get(item_id, {})
        loc_info  = location_map.get(location_id, {})

        rows.append({
            'unique_id':   uid,
            'ds':          pd.Timestamp('2020-01-01'),  # placeholder — not used
            'y':           0.0,                          # placeholder
            # Item hierarchy
            'category':    item_info.get('category',    'Unknown'),
            'subcategory': item_info.get('subcategory', 'Unknown'),
            'item_id':     item_id,
            # Location hierarchy
            'region':      loc_info.get('region',       'Unknown'),
            'location':    loc_info.get('code',         location_id),
        })

    if not rows:
        raise ValueError('build_summing_matrix: no valid rows — check unique_ids')

    df_flat = pd.DataFrame(rows)

    # Define hierarchy spec — which column combinations form each level
    # Product hierarchy: category → subcategory → item
    # Location hierarchy: region → location
    # Combined: category × region → ... → item × location (bottom)
    hier_spec = [
        ['category'],
        ['region'],
        ['category', 'region'],
        ['category', 'subcategory'],
        ['category', 'subcategory', 'region'],
        ['category', 'subcategory', 'item_id'],
        ['category', 'subcategory', 'item_id', 'region'],
        ['category', 'subcategory', 'item_id', 'region', 'location'],
    ]

    # aggregate() builds S_df and tags from the spec
    # It uses the 'unique_id' column as the bottom-level identifier
    # We pass 'unique_id' as id_col to tell it the leaf is already defined
    Y_df, S_df, tags = aggregate(
        df_flat.rename(columns={'unique_id': 'series_id'}),
        spec=[
            ['category'],
            ['region'],
            ['category', 'subcategory'],
            ['category', 'region'],
            ['category', 'subcategory', 'item_id'],
            ['category', 'subcategory', 'item_id', 'region'],
            ['category', 'subcategory', 'item_id', 'region', 'location'],
        ],
        id_col='series_id',
    )

    return S_df, tags


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Hierarchical reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def run_hierarchical_reconciliation(
    forecasts_df: pd.DataFrame,
    actuals_df: pd.DataFrame,
    S_df: pd.DataFrame,
    tags: dict,
    method: str = 'MinTrace_ols',
) -> pd.DataFrame:
    """
    Reconcile base forecasts so they are hierarchically coherent
    (bottom-level series sum exactly to higher-level aggregates).

    Args:
        forecasts_df:  output of StatsForecast in long format
                       (unique_id, ds, model_col)
        actuals_df:    actuals in long format (unique_id, ds, y)
                       — pandas, for HierarchicalForecast compatibility
        S_df:          summing matrix from build_summing_matrix()
        tags:          tags dict from build_summing_matrix()
        method:        reconciliation method:
                       'BottomUp'          — aggregate from bottom
                       'TopDown_AHP'       — top-down average historical proportion
                       'MinTrace_ols'      — minimum trace OLS (default)
                       'MinTrace_wls_struct' — minimum trace WLS structural

    Returns:
        Reconciled pandas DataFrame with columns:
            unique_id, ds, {method}_reconciled_qty
    """
    from hierarchicalforecast.core import HierarchicalReconciliation
    from hierarchicalforecast.methods import BottomUp, MinTrace, TopDown

    method_map = {
        'BottomUp':            [BottomUp()],
        'TopDown_AHP':         [TopDown(method='average_proportions')],
        'MinTrace_ols':        [MinTrace(method='ols')],
        'MinTrace_wls_struct': [MinTrace(method='wls_struct')],
    }

    if method not in method_map:
        raise ValueError(
            f'Unknown reconciliation method: {method!r}. '
            f'Choose from: {list(method_map.keys())}'
        )

    reconcilers = method_map[method]
    hrec = HierarchicalReconciliation(reconcilers=reconcilers)

    reconciled = hrec.reconcile(
        Y_hat_df = forecasts_df,
        Y_df     = actuals_df,
        S_df     = S_df,
        tags     = tags,
    )

    # Identify the reconciled column — HierarchicalForecast appends method suffix
    # e.g. 'AUTOETS/MinTrace(ols)'
    reconciled_cols = [
        c for c in reconciled.columns
        if c not in ('unique_id', 'ds')
        and 'lo' not in c and 'hi' not in c
        and '/' in c
    ]
    if not reconciled_cols:
        raise ValueError(
            'run_hierarchical_reconciliation: no reconciled column found. '
            f'Available columns: {reconciled.columns.tolist()}'
        )

    # Rename the reconciled column to a standard name
    rec_col = reconciled_cols[0]
    reconciled = reconciled.rename(columns={rec_col: 'reconciled_qty'})

    return reconciled[['unique_id', 'ds', 'reconciled_qty']]


# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Write forecast lines (pure data transformation)
# ─────────────────────────────────────────────────────────────────────────────

def prepare_forecast_line_records(
    reconciled_df: pd.DataFrame,
    unreconciled_by_uid: dict[str, pd.DataFrame],
    version_id: int,
    item_pk_map: dict[str, int],
    customer_pk_map: dict[str, int],
    location_pk_map: dict[str, int],
    period_type: str,
    model_by_uid: dict[str, str],
    forecast_level_by_uid: dict[str, str],
) -> list[dict]:
    """
    Transform reconciled_df into a list of dicts ready for ForecastLine bulk_create.

    Args:
        reconciled_df:       reconciled forecasts (unique_id, ds, reconciled_qty)
        unreconciled_by_uid: dict uid → pre-reconciliation forecast DataFrame
                             (used to store statistical_qty before reconciliation)
        version_id:          ForecastVersion PK
        item_pk_map:         item_id string → Item PK integer
        customer_pk_map:     customer_id string → PlanningCustomer PK (or None for 'NONE')
        location_pk_map:     location_id string → PlanningLocation PK integer
        period_type:         e.g. 'month'
        model_by_uid:        unique_id → model name string
        forecast_level_by_uid: unique_id → forecast level string

    Returns:
        list of dicts, one per ForecastLine to create
    """
    from mysite.models.demand.actuals import compute_period_end
    import datetime

    records = []

    # Build pre-reconciliation lookup: uid + ds → statistical_qty
    stat_lookup: dict[tuple, float] = {}
    for uid, df in unreconciled_by_uid.items():
        model_col = model_by_uid.get(uid, '')
        if model_col and model_col in df.columns:
            for _, row in df[df['unique_id'] == uid].iterrows():
                stat_lookup[(uid, row['ds'])] = float(row.get(model_col, 0) or 0)

    for _, row in reconciled_df.iterrows():
        uid      = row['unique_id']
        parts    = uid.split('|')
        if len(parts) != 3:
            continue

        item_id_str, customer_id_str, location_id_str = parts

        item_pk     = item_pk_map.get(item_id_str)
        location_pk = location_pk_map.get(location_id_str)

        if item_pk is None or location_pk is None:
            logger.warning(
                f'prepare_forecast_line_records: '
                f'missing PK for uid={uid!r} — skipping'
            )
            continue

        customer_pk = (
            None if customer_id_str == 'NONE'
            else customer_pk_map.get(customer_id_str)
        )

        ds = row['ds']
        if isinstance(ds, str):
            ds = datetime.date.fromisoformat(ds)
        elif hasattr(ds, 'date'):
            ds = ds.date()

        reconciled_qty = float(row.get('reconciled_qty', 0) or 0)
        reconciled_qty = max(0.0, reconciled_qty)  # floor at zero

        statistical_qty = stat_lookup.get(
            (uid, row['ds']),
            reconciled_qty,   # fall back to reconciled if pre-rec not available
        )

        period_end = compute_period_end(ds, period_type)

        records.append({
            'version_id':           version_id,
            'item_id':              item_pk,
            'planning_customer_id': customer_pk,
            'planning_location_id': location_pk,
            'period_type':          period_type,
            'period_start':         ds,
            'period_end':           period_end,
            'statistical_qty':      statistical_qty,
            'override_qty':         None,
            'final_qty':            statistical_qty,
            'model_used':           model_by_uid.get(uid, ''),
            'forecast_level':       forecast_level_by_uid.get(
                uid, 'sku_customer_location'
            ),
        })

    return records


def compute_aggregates_from_lines(
    line_records: list[dict],
    item_hierarchy: list[dict],
    location_hierarchy: list[dict],
    version_id: int,
    period_type: str,
) -> list[dict]:
    """
    Roll up ForecastLine records into ForecastAggregate records at multiple levels.

    Aggregation levels computed:
      'total'       — grand total across all items and locations
      'category'    — by product category
      'subcategory' — by product subcategory
      'region'      — by location region
      'location'    — by individual PlanningLocation

    Returns:
        list of dicts ready for ForecastAggregate bulk_create
    """
    import duckdb
    from mysite.models.demand.actuals import compute_period_end

    if not line_records:
        return []

    item_map = {d['item_id']: d for d in item_hierarchy}
    loc_map  = {str(d['location_id']): d for d in location_hierarchy}

    # Enrich line records with hierarchy attributes
    enriched = []
    for rec in line_records:
        item_info = item_map.get(str(rec.get('item_id', '')), {})
        loc_info  = loc_map.get(str(rec.get('planning_location_id', '')), {})
        enriched.append({
            **rec,
            'category':    item_info.get('category',    'Unknown'),
            'subcategory': item_info.get('subcategory', 'Unknown'),
            'region':      loc_info.get('region',       'Unknown'),
            'loc_code':    loc_info.get('code',         str(rec.get('planning_location_id', ''))),
        })

    con = duckdb.connect()
    con.register('lines', pd.DataFrame(enriched))

    agg_queries = {
        'total': """
            SELECT 'total' AS agg_level,
                   '{}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty,
                   NULL AS override_qty,
                   SUM(final_qty) AS final_qty
            FROM lines
            GROUP BY period_type, period_start
        """,
        'category': """
            SELECT 'category' AS agg_level,
                   '{"category": "' || category || '"}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty,
                   NULL AS override_qty,
                   SUM(final_qty) AS final_qty
            FROM lines
            GROUP BY category, period_type, period_start
        """,
        'subcategory': """
            SELECT 'subcategory' AS agg_level,
                   '{"category": "' || category || '", "subcategory": "' || subcategory || '"}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty,
                   NULL AS override_qty,
                   SUM(final_qty) AS final_qty
            FROM lines
            GROUP BY category, subcategory, period_type, period_start
        """,
        'region': """
            SELECT 'region' AS agg_level,
                   '{"region": "' || region || '"}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty,
                   NULL AS override_qty,
                   SUM(final_qty) AS final_qty
            FROM lines
            GROUP BY region, period_type, period_start
        """,
        'location': """
            SELECT 'location' AS agg_level,
                   '{"location": "' || loc_code || '"}' AS agg_key_json,
                   period_type, period_start,
                   SUM(statistical_qty) AS statistical_qty,
                   NULL AS override_qty,
                   SUM(final_qty) AS final_qty
            FROM lines
            GROUP BY loc_code, period_type, period_start
        """,
    }

    import json
    import datetime
    agg_records = []

    for level, sql in agg_queries.items():
        result = con.execute(sql).df()
        for _, row in result.iterrows():
            ds = row['period_start']
            if hasattr(ds, 'date'):
                ds = ds.date()
            elif isinstance(ds, str):
                ds = datetime.date.fromisoformat(ds)

            try:
                agg_key = json.loads(row['agg_key_json'])
            except Exception:
                agg_key = {}

            period_end = compute_period_end(ds, period_type)

            agg_records.append({
                'version_id':     version_id,
                'agg_level':      row['agg_level'],
                'agg_key':        agg_key,
                'period_type':    row['period_type'],
                'period_start':   ds,
                'period_end':     period_end,
                'statistical_qty': float(row['statistical_qty'] or 0),
                'override_qty':   None,
                'final_qty':      float(row['final_qty'] or 0),
            })

    con.close()
    return agg_records
```
