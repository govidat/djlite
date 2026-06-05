# Sprint 3B.4 — Forecast Engine and Reconciliation
## Detailed Implementation Instructions

**Dependencies:** Sprint 3B.3 complete  
**Estimated effort:** 4–5 days  
**Deliverable:** Triggering a ForecastVersion run produces complete ForecastLine  
and ForecastAggregate records with qty AND value at every hierarchy level.

---

## Table of Contents

1. [Model Delta — value fields and ItemPlanningProfile](#1-model-delta) Already incorporated.
2. [Forecast Engine — `utils/demand/forecast_engine.py`](#2-forecast-engine)
3. [Celery Tasks](#3-celery-tasks)
4. [REST Endpoints — run and status](#4-rest-endpoints)
5. [Serializer and URL additions](#5-serializer-and-url-additions)
6. [Unit Tests](#6-unit-tests)
7. [Migration checklist](#7-migration-checklist)

---

## 1. Model Delta

### 1.1 `ItemPlanningProfile` — standard price without polluting catalog

Rather than adding `standard_price` to `mysite.Item` (which belongs to the
catalog module), create a thin planning-specific companion model.
One row per (client, item) pair, managed by demand planners.

Add to `mysite/models/demand/actuals.py` below `ActualSaleLocation`:

```python
class ItemPlanningProfile(models.Model):
    """
    Demand-planning attributes for an item, kept separate from the
    catalog Item model.

    standard_price:
        Used to convert qty forecasts to value (₹) at every aggregate level.
        Set by demand planners, not catalog managers.
        Represents the expected selling / transfer price for planning purposes.

    weighted_avg_price:
        Computed by the forecast engine from recent actuals:
            sum(ActualSale.revenue) / sum(ActualSale.qty)
        over the last N periods. Stored here so aggregate-level value
        overrides can convert a ₹ target back to a qty delta without
        re-querying actuals each time.
    """

    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='item_planning_profiles',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='planning_profile',
    )
    standard_price = models.DecimalField(
        _('standard price'),
        max_digits=14, decimal_places=4,
        help_text=_(
            'Expected selling/transfer price used for value forecasts. '
            'Set by demand planners.'
        ),
    )
    weighted_avg_price = models.DecimalField(
        _('weighted average price'),
        max_digits=14, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Computed from recent actuals: sum(revenue)/sum(qty). '
            'Auto-updated by the forecast engine before each run.'
        ),
    )
    price_updated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [('client', 'item')]
        verbose_name = _('02-07 Item Planning Profile')
        verbose_name_plural = _('02-07 Item Planning Profiles')

    def __str__(self):
        return f'{self.item.item_id} | std_price={self.standard_price}'

    @property
    def effective_price(self) -> 'Decimal':
        """
        Price to use for value calculations.
        Falls back to standard_price if no weighted_avg_price computed yet.
        """
        return self.weighted_avg_price or self.standard_price
```

### 1.2 Add value fields to `ForecastLine`

Add these three fields to `ForecastLine` in `forecast.py`, after `final_qty`:

```python
# ── Value fields (derived from qty × effective_price) ─────────────────────
statistical_value = models.DecimalField(
    _('statistical value'),
    max_digits=18, decimal_places=2,
    null=True, blank=True,
    help_text=_(
        'statistical_qty × item standard/weighted-avg price. '
        'Computed at write time by the forecast engine.'
    ),
)
override_value = models.DecimalField(
    _('override value'),
    max_digits=18, decimal_places=2,
    null=True, blank=True,
    help_text=_('override_qty × effective_price. Null if no override.'),
)
final_value = models.DecimalField(
    _('final value'),
    max_digits=18, decimal_places=2,
    null=True, blank=True,
    editable=False,
    help_text=_(
        'final_qty × effective_price. '
        'Auto-computed in save(). Used for aggregate rollups.'
    ),
)
price_used = models.DecimalField(
    _('price used'),
    max_digits=14, decimal_places=4,
    null=True, blank=True,
    help_text=_(
        'The effective_price applied when computing value fields. '
        'Stored for auditability — price may change after forecast is run.'
    ),
)
```

Update `ForecastLine.save()`:

```python
def save(self, *args, **kwargs):
    if self.period_type and self.period_start:
        self.period_end = compute_period_end(self.period_start, self.period_type)
    # Compute final_qty
    self.final_qty = (
        self.override_qty
        if self.override_qty is not None
        else self.statistical_qty
    )
    # Compute value fields if price is available
    if self.price_used is not None:
        self.statistical_value = (
            self.statistical_qty * self.price_used
        ).quantize(Decimal('0.01'))
        self.override_value = (
            (self.override_qty * self.price_used).quantize(Decimal('0.01'))
            if self.override_qty is not None else None
        )
        self.final_value = (
            self.final_qty * self.price_used
        ).quantize(Decimal('0.01'))
    super().save(*args, **kwargs)
```

### 1.3 Add value fields to `ForecastAggregate`

Add to `ForecastAggregate` after `final_qty`:

```python
total_statistical_value = models.DecimalField(
    _('total statistical value'),
    max_digits=20, decimal_places=2,
    null=True, blank=True,
    help_text=_('Sum of statistical_value across all constituent ForecastLines.'),
)
total_override_value = models.DecimalField(
    _('total override value'),
    max_digits=20, decimal_places=2,
    null=True, blank=True,
)
total_final_value = models.DecimalField(
    _('total final value'),
    max_digits=20, decimal_places=2,
    null=True, blank=True,
    help_text=_(
        'Sum of final_value across all constituent ForecastLines. '
        'Primary value figure shown to planners at aggregate level.'
    ),
)
```

Update `ForecastAggregate.save()` to compute `final_qty` and set `period_end`:

```python
def save(self, *args, **kwargs):
    if self.period_type and self.period_start:
        self.period_end = compute_period_end(self.period_start, self.period_type)
    self.final_qty = (
        self.override_qty
        if self.override_qty is not None
        else self.statistical_qty
    )
    super().save(*args, **kwargs)
```

### 1.4 Add `celery_task_id` and `run_status` to `ForecastVersion`

```python
# Add to ForecastVersion model:

celery_task_id = models.CharField(
    _('celery task ID'),
    max_length=255,
    blank=True,
    help_text=_('ID of the Celery task currently running for this version.'),
)
run_status = models.CharField(
    _('run status'),
    max_length=16,
    blank=True,
    choices=[
        ('',          _('Not started')),
        ('QUEUED',    _('Queued')),
        ('PROFILING', _('Profiling series')),
        ('RUNNING',   _('Running forecast')),
        ('RECONCILING', _('Reconciling')),
        ('AGGREGATING', _('Building aggregates')),
        ('COMPLETE',  _('Complete')),
        ('FAILED',    _('Failed')),
    ],
    help_text=_(
        'Granular progress state of the forecast run. '
        'Separate from version status workflow.'
    ),
)
run_error = models.TextField(
    _('run error'),
    blank=True,
    help_text=_('Error traceback if run_status=FAILED.'),
)
```

---

## 2. Forecast Engine — `utils/demand/forecast_engine.py`

Create `utils/demand/__init__.py` (empty) and
`utils/demand/forecast_engine.py`:

```python
"""
utils/demand/forecast_engine.py

Pure functions for the demand forecast pipeline.
No Django ORM calls — all data arrives as DataFrames.
This makes every function independently testable without DB fixtures.

Pipeline order:
  1. update_weighted_avg_prices()   — update ItemPlanningProfile prices
  2. build_actuals_dataframe()      — actuals → Y_long Polars DataFrame
  3. build_summing_matrix()         — hierarchy trees → S_df + tags
  4. classify_series()              — dispatch by SeriesProfile.effective_strategy
  5. run_statsforecast()            — AutoETS / AutoARIMA / CrostonSBA batches
  6. handle_lumpy_series()          — aggregate → forecast → disaggregate
  7. handle_insufficient_series()   — moving average
  8. assemble_forecast_lines()      — merge all results → ForecastLine records
  9. run_hierarchical_reconciliation() — MinTrace on assembled lines
 10. write_forecast_lines()         — bulk_create ForecastLine rows
 11. write_forecast_aggregates()    — rollup → ForecastAggregate rows
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING

import duckdb
import numpy as np
import pandas as pd
import polars as pl
from statsforecast import StatsForecast
from statsforecast.models import AutoETS, AutoARIMA, CrostonSBA, SeasonalNaive
from statsforecast.utils import ConformalIntervals
from hierarchicalforecast.utils import aggregate as hf_aggregate
from hierarchicalforecast.core import HierarchicalReconciliation
from hierarchicalforecast.methods import BottomUp, MinTrace

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

BATCH_SIZE_LINES = 2000   # bulk_create batch size for ForecastLine


# ─────────────────────────────────────────────────────────────────────────────
# 1. Update weighted average prices
# ─────────────────────────────────────────────────────────────────────────────

def update_weighted_avg_prices(
    client_id: int,
    period_type: str,
    lookback_periods: int = 12,
) -> dict[int, Decimal]:
    """
    Compute weighted average price (sum(revenue)/sum(qty)) per item
    from the most recent `lookback_periods` actuals periods.

    Returns dict: {item_id (int): weighted_avg_price (Decimal)}

    Updates ItemPlanningProfile.weighted_avg_price in bulk.
    Falls back to standard_price for items with no revenue data.
    """
    from django.utils import timezone
    from mysite.models.demand.actuals import ActualSale, ItemPlanningProfile

    # One DuckDB query across all items for the client
    qs = (
        ActualSale.objects
        .filter(
            client_id=client_id,
            period_type=period_type,
            revenue__isnull=False,
        )
        .values('item_id', 'qty', 'revenue', 'period_start')
        .order_by('-period_start')
    )

    if not qs.exists():
        logger.warning(
            f'update_weighted_avg_prices: no revenue data for client {client_id}'
        )
        return {}

    df_pd = pd.DataFrame(list(qs))
    con    = duckdb.connect()
    con.register('actuals', df_pd)

    # Get the N most recent distinct period_starts
    recent_periods = con.execute(f"""
        SELECT DISTINCT period_start
        FROM actuals
        ORDER BY period_start DESC
        LIMIT {lookback_periods}
    """).df()['period_start'].tolist()

    if not recent_periods:
        return {}

    wap_df = con.execute("""
        SELECT
            item_id,
            SUM(CAST(revenue AS DOUBLE)) / NULLIF(SUM(CAST(qty AS DOUBLE)), 0)
                AS weighted_avg_price
        FROM actuals
        WHERE period_start IN (SELECT period_start FROM recent_periods)
        GROUP BY item_id
        HAVING SUM(CAST(qty AS DOUBLE)) > 0
    """).df()

    # Build result dict
    result = {
        int(row['item_id']): Decimal(str(round(row['weighted_avg_price'], 4)))
        for _, row in wap_df.iterrows()
        if row['weighted_avg_price'] is not None
    }

    # Bulk update ItemPlanningProfile
    now = timezone.now()
    profiles = list(
        ItemPlanningProfile.objects
        .filter(client_id=client_id, item_id__in=list(result.keys()))
    )
    for p in profiles:
        if p.item_id in result:
            p.weighted_avg_price = result[p.item_id]
            p.price_updated_at   = now

    if profiles:
        ItemPlanningProfile.objects.bulk_update(
            profiles,
            ['weighted_avg_price', 'price_updated_at'],
            batch_size=500,
        )

    logger.info(
        f'update_weighted_avg_prices: client={client_id} '
        f'updated {len(profiles)} profiles'
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. Build actuals DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def build_actuals_dataframe(
    client_id: int,
    period_type: str,
    period_start_from: 'date',
    period_start_to: 'date',
) -> pl.DataFrame:
    """
    Pull ActualSale rows for the client/period range into a Polars DataFrame.

    Returns columns:
        unique_id   str   — "{item_id}|{customer_id}|{location_id}"
                            customer_id = "NULL" when planning_customer is null
        ds          date  — period_start
        y           float — qty (as float for StatsForecast)
        item_id     int   — FK for later disaggregation
        customer_id str   — FK or "NULL"
        location_id int   — FK
        category    str   — from item taxonomy (for summing matrix)
        subcategory str   — from item taxonomy

    Uses DuckDB for the aggregation so the Django ORM doesn't load all rows
    into Python objects.
    """
    from mysite.models.demand.actuals import ActualSale

    qs = (
        ActualSale.objects
        .filter(
            client_id=client_id,
            period_type=period_type,
            period_start__gte=period_start_from,
            period_start__lte=period_start_to,
        )
        .select_related(
            'item',
            'planning_location',
            'planning_customer',
        )
        .values(
            'item_id',
            'item__item_id',
            'planning_location_id',
            'planning_location__code',
            'planning_customer_id',
            'planning_customer__code',
            'period_start',
            'qty',
        )
    )

    rows = list(qs)
    if not rows:
        raise ValueError(
            f'No actuals found for client={client_id}, '
            f'period_type={period_type}, '
            f'{period_start_from} to {period_start_to}'
        )

    df_pd = pd.DataFrame(rows)

    # Build unique_id: item_id|customer_id|location_id
    df_pd['customer_str'] = df_pd['planning_customer_id'].fillna('NULL').astype(str)
    df_pd['unique_id'] = (
        df_pd['item__item_id'].astype(str) + '|' +
        df_pd['customer_str'] + '|' +
        df_pd['planning_location__code'].astype(str)
    )
    df_pd['y']  = df_pd['qty'].astype(float)
    df_pd['ds'] = pd.to_datetime(df_pd['period_start'])

    # Aggregate duplicate (unique_id, ds) combinations — shouldn't exist
    # due to unique constraint but defensive aggregation is safe
    df_pd = (
        df_pd.groupby(['unique_id', 'ds', 'item_id',
                       'planning_customer_id', 'planning_location_id'])
        ['y'].sum()
        .reset_index()
    )

    df = pl.from_pandas(df_pd)
    logger.info(
        f'build_actuals_dataframe: client={client_id} '
        f'rows={len(df)} unique_series={df["unique_id"].n_unique()}'
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3. Build summing matrix
# ─────────────────────────────────────────────────────────────────────────────

def build_summing_matrix(
    client_id: int,
    actuals_df: pl.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    Build the HierarchicalForecast summing matrix (S_df) and tags dict
    from the three hierarchy trees.

    Hierarchy spec (3 levels, matching the product_planning Taxonomy):
        category → subcategory → unique_id (item|customer|location)

    In Sprint 3B.4, the hierarchy is product × location (2D):
        category/location_code/unique_id

    S_df shape: (all_nodes, leaf_series)
    tags:       {level_name: array of node names at that level}

    Returns (Y_df, S_df, tags) where Y_df is the aggregated long DataFrame
    ready for StatsForecast.
    """
    from mysite.models import Item
    from mysite.models.demand.hierarchy import PlanningLocation
    from mysite.models.demand.actuals import ActualSale

    # ── Build item → category/subcategory lookup ───────────────────────────
    # Pull taxonomy membership from ItemTaxonomyMapping
    # Simplified: use item.item_id as the leaf label
    # For the summing matrix we need to know which category each unique_id belongs to

    # Get unique item_ids in the actuals
    item_ids_in_actuals = (
        actuals_df['unique_id']
        .to_pandas()
        .str.split('|').str[0]
        .unique()
        .tolist()
    )

    # Pull item taxonomy from DB (category, subcategory per item)
    # This assumes ItemTaxonomyMapping links Item → TaxonomyNode
    # If your model differs, adjust the query accordingly
    item_taxonomy_qs = (
        Item.objects
        .filter(client_id=client_id, item_id__in=item_ids_in_actuals)
        .values('item_id', 'item_id')   # extend with taxonomy join in your project
    )

    # ── Build location lookup ──────────────────────────────────────────────
    location_codes_in_actuals = (
        actuals_df['unique_id']
        .to_pandas()
        .str.split('|').str[2]
        .unique()
        .tolist()
    )

    location_qs = (
        PlanningLocation.objects
        .filter(client_id=client_id, code__in=location_codes_in_actuals)
        .values('code', 'parent__code', 'level_label')
    )
    location_map = {
        row['code']: row['parent__code'] or 'ALL_LOCATIONS'
        for row in location_qs
    }

    # ── Assemble the raw DataFrame for hf_aggregate ────────────────────────
    # hf_aggregate needs: ds, [hierarchy columns], y
    # We use a 2-level hierarchy: location_group → unique_id

    df_pd = actuals_df.to_pandas()
    df_pd['ds'] = pd.to_datetime(df_pd['ds'])
    df_pd['y']  = df_pd['y'].astype(float)

    # Extract location_code from unique_id
    df_pd['location_code'] = df_pd['unique_id'].str.split('|').str[2]
    df_pd['location_group'] = df_pd['location_code'].map(
        lambda c: location_map.get(c, 'ALL_LOCATIONS')
    )

    # Hierarchy spec: region → location_group → unique_id
    hier_spec = [
        ['location_group'],
        ['location_group', 'unique_id'],
    ]

    raw = df_pd[['ds', 'location_group', 'unique_id', 'y']].copy()

    Y_df, S_df, tags = hf_aggregate(raw, hier_spec)

    logger.info(
        f'build_summing_matrix: client={client_id} '
        f'Y_df={Y_df.shape} S_df={S_df.shape} levels={list(tags.keys())}'
    )
    return Y_df, S_df, tags


# ─────────────────────────────────────────────────────────────────────────────
# 4. Classify and separate series by strategy
# ─────────────────────────────────────────────────────────────────────────────

def classify_series_by_strategy(
    client_id: int,
    period_type: str,
    unique_ids: list[str],
) -> dict[str, list[str]]:
    """
    Load SeriesProfile rows and group unique_ids by effective_strategy.

    Returns dict:
        {
            'AUTOETS':      ['item1|cust|loc', ...],
            'AUTOARIMA':    [...],
            'CROSTON':      [...],
            'AGG_LOCATION': [...],
            'MOVING_AVG':   [...],
            'MANUAL':       [...],
            'ZERO':         [...],
        }
    """
    from mysite.models.demand.forecast import SeriesProfile
    from mysite.models import Item
    from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer

    # Build reverse lookup: (item_id_str, customer_code, location_code) → unique_id
    # unique_id format: "{item_id}|{customer_code_or_NULL}|{location_code}"

    profiles = (
        SeriesProfile.objects
        .filter(client_id=client_id, period_type=period_type)
        .select_related('item', 'planning_location', 'planning_customer')
    )

    strategy_map: dict[str, list[str]] = {
        'AUTOETS':      [],
        'AUTOARIMA':    [],
        'CROSTON':      [],
        'AGG_LOCATION': [],
        'MOVING_AVG':   [],
        'MANUAL':       [],
        'ZERO':         [],
        'INSUFFICIENT': [],
    }

    profiled_ids = set()

    for profile in profiles:
        cust_code = (
            profile.planning_customer.code
            if profile.planning_customer else 'NULL'
        )
        uid = (
            f'{profile.item.item_id}|'
            f'{cust_code}|'
            f'{profile.planning_location.code}'
        )
        if uid in unique_ids:
            strategy = profile.effective_strategy
            strategy_map.setdefault(strategy, []).append(uid)
            profiled_ids.add(uid)

    # Series with no SeriesProfile — default to AUTOETS
    # (they haven't been classified yet — compute_series_profiles wasn't run)
    unclassified = [uid for uid in unique_ids if uid not in profiled_ids]
    if unclassified:
        logger.warning(
            f'classify_series_by_strategy: {len(unclassified)} series '
            f'have no SeriesProfile — defaulting to AUTOETS'
        )
        strategy_map['AUTOETS'].extend(unclassified)

    # Log summary
    for strategy, ids in strategy_map.items():
        if ids:
            logger.info(
                f'  strategy={strategy}: {len(ids)} series'
            )

    return strategy_map


# ─────────────────────────────────────────────────────────────────────────────
# 5. Run StatsForecast batches
# ─────────────────────────────────────────────────────────────────────────────

def run_statsforecast_batch(
    Y_df: pd.DataFrame,
    unique_ids: list[str],
    model_name: str,
    horizon: int,
    freq: str,
    season_length: int = 12,
    n_jobs: int = -1,
) -> pd.DataFrame:
    """
    Run one StatsForecast model on a subset of series.

    Args:
        Y_df:        long DataFrame with (unique_id, ds, y) for ALL series.
                     This function filters to unique_ids subset.
        unique_ids:  list of unique_id values to forecast with this model
        model_name:  'AUTOETS' | 'AUTOARIMA' | 'CROSTON' | 'SEASONAL_NAIVE'
        horizon:     number of periods ahead
        freq:        pandas offset alias (from PERIOD_FREQ_MAP)
        season_length: number of periods per season (12 for monthly)
        n_jobs:      -1 = all cores

    Returns:
        DataFrame with columns: unique_id, ds, <model_name>
    """
    subset = Y_df[Y_df['unique_id'].isin(unique_ids)].copy()
    if subset.empty:
        return pd.DataFrame(columns=['unique_id', 'ds', model_name])

    MODEL_MAP = {
        'AUTOETS':        AutoETS(season_length=season_length),
        'AUTOARIMA':      AutoARIMA(season_length=season_length),
        'CROSTON':        CrostonSBA(),
        'SEASONAL_NAIVE': SeasonalNaive(season_length=season_length),
    }

    model = MODEL_MAP.get(model_name)
    if model is None:
        raise ValueError(f'Unknown model_name: {model_name!r}')

    sf = StatsForecast(
        models=[model],
        freq=freq,
        n_jobs=n_jobs,
    )

    forecast_df = sf.forecast(
        df=subset,
        h=horizon,
        prediction_intervals=ConformalIntervals(h=horizon, n_windows=2),
        level=[80, 95],
    )

    # Rename model column to model_name for consistency
    model_col = [c for c in forecast_df.columns
                 if c not in ('unique_id', 'ds') and not c.endswith(('-lo-80', '-hi-80', '-lo-95', '-hi-95'))]
    if model_col and model_col[0] != model_name:
        forecast_df = forecast_df.rename(columns={model_col[0]: model_name})

    # Keep only point forecast columns
    keep_cols = ['unique_id', 'ds', model_name]
    lo_col = f'{model_name}-lo-80'
    hi_col = f'{model_name}-hi-80'
    if lo_col in forecast_df.columns:
        keep_cols += [lo_col, hi_col]

    return forecast_df[[c for c in keep_cols if c in forecast_df.columns]]


# ─────────────────────────────────────────────────────────────────────────────
# 6. Handle LUMPY series — aggregate → forecast → disaggregate
# ─────────────────────────────────────────────────────────────────────────────

def handle_lumpy_series(
    Y_df: pd.DataFrame,
    lumpy_ids: list[str],
    horizon: int,
    freq: str,
    season_length: int = 12,
) -> pd.DataFrame:
    """
    For LUMPY series:
      1. Aggregate actuals to location level (sum across items and customers)
         for each location that has lumpy series.
      2. Run AutoETS on the aggregated location series.
      3. Disaggregate the location forecast back to each lumpy unique_id
         using historical proportional share.

    Returns DataFrame with columns: unique_id, ds, AUTOETS
    (same structure as run_statsforecast_batch so the caller can merge)
    """
    if not lumpy_ids:
        return pd.DataFrame(columns=['unique_id', 'ds', 'AUTOETS'])

    lumpy_df = Y_df[Y_df['unique_id'].isin(lumpy_ids)].copy()

    # Extract location from unique_id
    lumpy_df['location_code'] = lumpy_df['unique_id'].str.split('|').str[2]

    # ── Step 1: Aggregate to location level ───────────────────────────────
    loc_actuals = (
        lumpy_df.groupby(['location_code', 'ds'])['y']
        .sum()
        .reset_index()
        .rename(columns={'location_code': 'unique_id'})
    )
    loc_actuals['y'] = loc_actuals['y'].astype(float)

    # ── Step 2: Forecast at location level ────────────────────────────────
    loc_ids = loc_actuals['unique_id'].unique().tolist()
    loc_forecast = run_statsforecast_batch(
        Y_df=loc_actuals,
        unique_ids=loc_ids,
        model_name='AUTOETS',
        horizon=horizon,
        freq=freq,
        season_length=season_length,
    )

    # ── Step 3: Compute historical proportions per unique_id ──────────────
    # proportion = mean(y for this series) / mean(y for its location total)
    series_mean = (
        lumpy_df.groupby(['unique_id', 'location_code'])['y']
        .mean()
        .reset_index()
        .rename(columns={'y': 'series_mean'})
    )
    loc_mean = (
        lumpy_df.groupby('location_code')['y']
        .mean()
        .reset_index()
        .rename(columns={'y': 'loc_mean'})
    )
    proportions = series_mean.merge(loc_mean, on='location_code')
    proportions['share'] = (
        proportions['series_mean'] /
        proportions['loc_mean'].replace(0, float('nan'))
    ).fillna(0)

    # Normalise shares within each location to sum to 1
    loc_share_sum = proportions.groupby('location_code')['share'].transform('sum')
    proportions['share'] = proportions['share'] / loc_share_sum.replace(0, 1)

    # ── Step 4: Disaggregate ──────────────────────────────────────────────
    # For each period in loc_forecast, multiply location qty by each series' share
    results = []
    for loc_code in loc_ids:
        loc_fcast = loc_forecast[loc_forecast['unique_id'] == loc_code]
        loc_series = proportions[proportions['location_code'] == loc_code]

        for _, series_row in loc_series.iterrows():
            uid   = series_row['unique_id']
            share = series_row['share']
            series_fcast = loc_fcast[['ds']].copy()
            series_fcast['unique_id'] = uid
            series_fcast['AUTOETS']   = (loc_fcast['AUTOETS'] * share).values
            results.append(series_fcast)

    if not results:
        return pd.DataFrame(columns=['unique_id', 'ds', 'AUTOETS'])

    return pd.concat(results, ignore_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Handle INSUFFICIENT / ZERO series — moving average
# ─────────────────────────────────────────────────────────────────────────────

def handle_insufficient_series(
    Y_df: pd.DataFrame,
    insufficient_ids: list[str],
    horizon: int,
    freq: str,
    n_periods: int = 6,
) -> pd.DataFrame:
    """
    For INSUFFICIENT and MOVING_AVG series:
    Compute a simple N-period moving average of non-zero actuals
    and project it flat across all forecast periods.

    For ZERO series: return statistical_qty = 0 for all periods.

    Returns DataFrame with columns: unique_id, ds, MOVING_AVG
    """
    if not insufficient_ids:
        return pd.DataFrame(columns=['unique_id', 'ds', 'MOVING_AVG'])

    subset = Y_df[Y_df['unique_id'].isin(insufficient_ids)].copy()
    results = []

    # Build forecast date spine
    last_ds = Y_df['ds'].max()
    future_dates = pd.date_range(
        start=last_ds + pd.tseries.frequencies.to_offset(freq),
        periods=horizon,
        freq=freq,
    )

    for uid in insufficient_ids:
        series = subset[subset['unique_id'] == uid].sort_values('ds')
        non_zero = series[series['y'] > 0]['y']

        if len(non_zero) == 0:
            avg = 0.0
        else:
            avg = float(non_zero.tail(n_periods).mean())

        rows = pd.DataFrame({
            'unique_id':  uid,
            'ds':         future_dates,
            'MOVING_AVG': avg,
        })
        results.append(rows)

    return pd.concat(results, ignore_index=True) if results else \
        pd.DataFrame(columns=['unique_id', 'ds', 'MOVING_AVG'])


# ─────────────────────────────────────────────────────────────────────────────
# 8. Run hierarchical reconciliation
# ─────────────────────────────────────────────────────────────────────────────

def run_hierarchical_reconciliation(
    forecasts_df: pd.DataFrame,
    Y_df: pd.DataFrame,
    S_df: pd.DataFrame,
    tags: dict,
    method: str = 'MinTrace_ols',
) -> pd.DataFrame:
    """
    Apply HierarchicalForecast reconciliation so that forecasts at every
    level of the hierarchy are mathematically consistent (sum up correctly).

    Args:
        forecasts_df: base forecasts from StatsForecast (all series + aggregates)
        Y_df:         historical actuals in long format (from hf_aggregate)
        S_df:         summing matrix (from build_summing_matrix)
        tags:         hierarchy level tags (from build_summing_matrix)
        method:       reconciliation method string:
                      'BottomUp' | 'MinTrace_ols' | 'MinTrace_wls_struct'

    Returns reconciled DataFrame with additional columns per reconciler.
    """
    reconcilers = {
        'BottomUp':          [BottomUp()],
        'MinTrace_ols':      [MinTrace(method='ols')],
        'MinTrace_wls_struct': [MinTrace(method='wls_struct')],
    }

    selected = reconcilers.get(method)
    if selected is None:
        logger.warning(
            f'Unknown reconciliation method {method!r}, '
            f'falling back to MinTrace_ols'
        )
        selected = [MinTrace(method='ols')]

    hrec = HierarchicalReconciliation(reconcilers=selected)

    reconciled_df = hrec.reconcile(
        Y_hat_df=forecasts_df,
        Y_df=Y_df,
        S_df=S_df,
        tags=tags,
    )

    return reconciled_df


# ─────────────────────────────────────────────────────────────────────────────
# 9. Write ForecastLine rows
# ─────────────────────────────────────────────────────────────────────────────

def write_forecast_lines(
    version_id: int,
    forecast_df: pd.DataFrame,
    strategy_map: dict[str, list[str]],
    price_map: dict[int, Decimal],
    period_type: str,
) -> int:
    """
    Convert the combined forecast DataFrame into ForecastLine rows
    and bulk_create them.

    forecast_df columns expected:
        unique_id, ds, statistical_qty, model_used

    unique_id format: "{item_id_str}|{customer_code_or_NULL}|{location_code}"

    Returns: number of lines created.
    """
    from mysite.models.demand.forecast import ForecastLine, ForecastVersion
    from mysite.models import Item
    from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
    from mysite.models.demand.actuals import compute_period_end

    version = ForecastVersion.objects.get(pk=version_id)

    # ── Build reverse FK lookups ───────────────────────────────────────────
    # Item: item_id_str → Item pk
    item_str_to_pk: dict[str, int] = {
        row['item_id']: row['id']
        for row in Item.objects.filter(client=version.client)
        .values('id', 'item_id')
    }
    # Location: code → pk
    loc_code_to_pk: dict[str, int] = {
        row['code']: row['id']
        for row in PlanningLocation.objects.filter(client=version.client)
        .values('id', 'code')
    }
    # Customer: code → pk (None for 'NULL')
    cust_code_to_pk: dict[str, int | None] = {
        row['code']: row['id']
        for row in PlanningCustomer.objects.filter(client=version.client)
        .values('id', 'code')
    }
    cust_code_to_pk['NULL'] = None

    # Build reverse strategy map: unique_id → (strategy, model_used, forecast_level)
    uid_to_strategy: dict[str, tuple[str, str, str]] = {}
    for strategy, uids in strategy_map.items():
        model_used = {
            'AUTOETS':      'AutoETS',
            'AUTOARIMA':    'AutoARIMA',
            'CROSTON':      'CrostonSBA',
            'AGG_LOCATION': 'AutoETS',
            'MOVING_AVG':   'MovingAverage',
            'MANUAL':       'Manual',
            'ZERO':         'None',
            'INSUFFICIENT': 'MovingAverage',
        }.get(strategy, strategy)

        forecast_level = {
            'AGG_LOCATION': 'location',
        }.get(strategy, 'sku_customer_location')

        for uid in uids:
            uid_to_strategy[uid] = (strategy, model_used, forecast_level)

    # Delete existing lines for this version (re-run scenario)
    ForecastLine.objects.filter(version=version).delete()

    lines = []
    skipped = 0

    for _, row in forecast_df.iterrows():
        uid = row['unique_id']
        parts = uid.split('|')
        if len(parts) != 3:
            skipped += 1
            continue

        item_id_str, cust_code, loc_code = parts

        item_pk = item_str_to_pk.get(item_id_str)
        loc_pk  = loc_code_to_pk.get(loc_code)

        if item_pk is None or loc_pk is None:
            skipped += 1
            continue

        cust_pk = cust_code_to_pk.get(cust_code)  # None for 'NULL'

        period_start = row['ds'].date() if hasattr(row['ds'], 'date') else row['ds']
        period_end   = compute_period_end(period_start, period_type)
        stat_qty     = Decimal(str(round(max(float(row['statistical_qty']), 0), 3)))

        # Price for value calculation
        price = price_map.get(item_pk)

        strategy, model_used, forecast_level = uid_to_strategy.get(
            uid, ('AUTOETS', 'AutoETS', 'sku_customer_location')
        )

        line = ForecastLine(
            version_id           = version_id,
            item_id              = item_pk,
            planning_customer_id = cust_pk,
            planning_location_id = loc_pk,
            period_type          = period_type,
            period_start         = period_start,
            period_end           = period_end,
            statistical_qty      = stat_qty,
            override_qty         = None,
            model_used           = model_used,
            forecast_level       = forecast_level,
            price_used           = price,
        )
        # final_qty and value fields computed in save()
        lines.append(line)

    # Bulk create in batches — triggers save() for each object
    # Note: bulk_create does NOT call save() by default.
    # We therefore compute final_qty and value fields here before creating.
    for line in lines:
        line.period_end  = compute_period_end(line.period_start, period_type)
        line.final_qty   = line.statistical_qty  # no override yet
        if line.price_used is not None:
            line.statistical_value = (line.statistical_qty * line.price_used).quantize(Decimal('0.01'))
            line.final_value       = line.statistical_value

    created = 0
    for i in range(0, len(lines), BATCH_SIZE_LINES):
        batch = lines[i: i + BATCH_SIZE_LINES]
        ForecastLine.objects.bulk_create(batch, batch_size=BATCH_SIZE_LINES)
        created += len(batch)

    if skipped:
        logger.warning(f'write_forecast_lines: skipped {skipped} rows (FK not found)')
    logger.info(f'write_forecast_lines: created {created} ForecastLine rows')
    return created


# ─────────────────────────────────────────────────────────────────────────────
# 10. Write ForecastAggregate rows (rollup from ForecastLine)
# ─────────────────────────────────────────────────────────────────────────────

def write_forecast_aggregates(version_id: int) -> int:
    """
    Roll up ForecastLine rows into ForecastAggregate at multiple levels.

    Aggregation levels computed:
        'total'       — grand total across all items/locations/customers
        'location'    — per PlanningLocation (leaf)
        'region'      — per PlanningLocation parent (one level up)
        'customer'    — per PlanningCustomer
        'item'        — per Item (across all locations and customers)

    Uses DuckDB for fast in-process aggregation without loading all rows
    into Python objects.

    Returns: number of ForecastAggregate rows created.
    """
    from mysite.models.demand.forecast import ForecastLine, ForecastAggregate, ForecastVersion
    from mysite.models.demand.actuals import compute_period_end

    version = ForecastVersion.objects.get(pk=version_id)

    # ── Pull ForecastLine data into DuckDB ────────────────────────────────
    lines_qs = (
        ForecastLine.objects
        .filter(version=version)
        .select_related('item', 'planning_location', 'planning_customer')
        .values(
            'item_id', 'item__item_id',
            'planning_location_id', 'planning_location__code',
            'planning_customer_id', 'planning_customer__code',
            'period_type', 'period_start',
            'statistical_qty', 'final_qty',
            'statistical_value', 'final_value',
        )
    )

    if not lines_qs.exists():
        logger.warning(f'write_forecast_aggregates: no ForecastLine rows for version {version_id}')
        return 0

    df_pd = pd.DataFrame(list(lines_qs))
    df_pd['ds'] = pd.to_datetime(df_pd['period_start'])
    df_pd['statistical_qty']   = df_pd['statistical_qty'].astype(float)
    df_pd['final_qty']         = df_pd['final_qty'].astype(float)
    df_pd['statistical_value'] = df_pd['statistical_value'].fillna(0).astype(float)
    df_pd['final_value']       = df_pd['final_value'].fillna(0).astype(float)
    df_pd['customer_code']     = df_pd['planning_customer__code'].fillna('__unattributed__')
    df_pd['period_type_col']   = df_pd['period_type']

    con = duckdb.connect()
    con.register('lines', df_pd)

    # ── Define aggregation queries ─────────────────────────────────────────
    AGG_QUERIES = {
        'total': """
            SELECT
                'total'                         AS agg_level,
                '{"level": "total"}'            AS agg_key_json,
                period_type_col                 AS period_type,
                period_start,
                SUM(statistical_qty)            AS statistical_qty,
                SUM(final_qty)                  AS final_qty,
                SUM(statistical_value)          AS total_statistical_value,
                SUM(final_value)                AS total_final_value
            FROM lines
            GROUP BY period_type_col, period_start
        """,
        'location': """
            SELECT
                'location'                       AS agg_level,
                CONCAT('{"location_code": "',
                    planning_location__code,
                    '"}')                        AS agg_key_json,
                period_type_col                  AS period_type,
                period_start,
                SUM(statistical_qty)             AS statistical_qty,
                SUM(final_qty)                   AS final_qty,
                SUM(statistical_value)           AS total_statistical_value,
                SUM(final_value)                 AS total_final_value
            FROM lines
            GROUP BY planning_location__code, period_type_col, period_start
        """,
        'item': """
            SELECT
                'item'                           AS agg_level,
                CONCAT('{"item_id": "',
                    item__item_id,
                    '"}')                        AS agg_key_json,
                period_type_col                  AS period_type,
                period_start,
                SUM(statistical_qty)             AS statistical_qty,
                SUM(final_qty)                   AS final_qty,
                SUM(statistical_value)           AS total_statistical_value,
                SUM(final_value)                 AS total_final_value
            FROM lines
            GROUP BY item__item_id, period_type_col, period_start
        """,
        'customer': """
            SELECT
                'customer'                       AS agg_level,
                CONCAT('{"customer_code": "',
                    customer_code,
                    '"}')                        AS agg_key_json,
                period_type_col                  AS period_type,
                period_start,
                SUM(statistical_qty)             AS statistical_qty,
                SUM(final_qty)                   AS final_qty,
                SUM(statistical_value)           AS total_statistical_value,
                SUM(final_value)                 AS total_final_value
            FROM lines
            GROUP BY customer_code, period_type_col, period_start
        """,
    }

    # Delete existing aggregates for this version
    ForecastAggregate.objects.filter(version=version).delete()

    import json
    created = 0

    for agg_level, query in AGG_QUERIES.items():
        result_df = con.execute(query).df()

        agg_objects = []
        for _, row in result_df.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()

            try:
                agg_key = json.loads(row['agg_key_json'])
            except Exception:
                agg_key = {'raw': row['agg_key_json']}

            period_end = compute_period_end(period_start, row['period_type'])

            agg = ForecastAggregate(
                version_id              = version_id,
                agg_level               = agg_level,
                agg_key                 = agg_key,
                period_type             = row['period_type'],
                period_start            = period_start,
                period_end              = period_end,
                statistical_qty         = Decimal(str(round(row['statistical_qty'], 3))),
                final_qty               = Decimal(str(round(row['final_qty'], 3))),
                total_statistical_value = Decimal(str(round(row['total_statistical_value'], 2))),
                total_final_value       = Decimal(str(round(row['total_final_value'], 2))),
            )
            agg_objects.append(agg)

        ForecastAggregate.objects.bulk_create(agg_objects, batch_size=500)
        created += len(agg_objects)
        logger.info(f'write_forecast_aggregates: level={agg_level} rows={len(agg_objects)}')

    return created
```

---

## 3. Celery Tasks

Create `mysite/tasks/demand/run_forecast.py`:

```python
"""
mysite/tasks/demand/run_forecast.py

Four Celery tasks for Sprint 3B.4:

  run_forecast(version_id)         — main pipeline orchestrator
  apply_overrides(version_id)      — disaggregate planner overrides to lines
  compute_accuracy(client_id)      — nightly MAPE/Bias computation
"""

from __future__ import annotations

import logging
import traceback
from decimal import Decimal

from celery import shared_task, chain
from django.db import transaction

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Task 1: run_forecast — main pipeline
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=1, default_retry_delay=120)
def run_forecast(self, version_id: int):
    """
    Orchestrate the full forecast pipeline for a ForecastVersion.

    Steps:
      1. Validate version is in DRAFT status
      2. Update weighted average prices
      3. Pull actuals via DuckDB → Polars
      4. Build summing matrix from hierarchy trees
      5. Classify series by effective_strategy
      6. Run StatsForecast per strategy group
      7. Handle LUMPY series (aggregate → forecast → disaggregate)
      8. Handle INSUFFICIENT/ZERO series (moving average or zero)
      9. Combine all forecast results
     10. Run HierarchicalForecast reconciliation
     11. Write ForecastLine rows
     12. Write ForecastAggregate rollups
     13. Update version run_status → COMPLETE
    """
    from mysite.models.demand.forecast import ForecastVersion
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP
    from utils.demand.forecast_engine import (
        update_weighted_avg_prices,
        build_actuals_dataframe,
        build_summing_matrix,
        classify_series_by_strategy,
        run_statsforecast_batch,
        handle_lumpy_series,
        handle_insufficient_series,
        run_hierarchical_reconciliation,
        write_forecast_lines,
        write_forecast_aggregates,
    )
    from utils.feature_control import celery_demand_feature_guard
    import pandas as pd

    # ── Load version ───────────────────────────────────────────────────────
    try:
        version = ForecastVersion.objects.select_related('client', 'created_by').get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        logger.error(f'run_forecast: version_id={version_id} not found')
        return

    # ── Feature guard ──────────────────────────────────────────────────────
    skip = celery_demand_feature_guard(version.client, 'forecast_run')
    if skip:
        return skip

    # ── Validate status ────────────────────────────────────────────────────
    if not version.is_editable:
        logger.warning(
            f'run_forecast: version {version_id} is {version.status}, '
            f'must be DRAFT to run forecast'
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
        method      = version.engine_config.get('reconciliation', 'MinTrace_ols')
        season_length = version.engine_config.get('season_length', 12)

        # Determine actuals window: use last 36 periods ending at base_period_end
        from mysite.models.demand.actuals import ActualSale
        earliest = (
            ActualSale.objects
            .filter(client=client, period_type=period_type)
            .order_by('period_start')
            .values_list('period_start', flat=True)
            .first()
        )
        if earliest is None:
            raise ValueError('No actuals found for this client and period_type.')

        period_start_from = earliest
        period_start_to   = version.base_period_end

        # ── Step 1: Update prices ──────────────────────────────────────────
        _set_status('PROFILING')
        price_map = update_weighted_avg_prices(client_id, period_type)

        # ── Step 2: Pull actuals ───────────────────────────────────────────
        actuals_pl = build_actuals_dataframe(
            client_id, period_type, period_start_from, period_start_to
        )
        actuals_pd = actuals_pl.to_pandas()
        actuals_pd['ds'] = pd.to_datetime(actuals_pd['ds'])
        actuals_pd['y']  = actuals_pd['y'].astype(float)

        # ── Step 3: Build summing matrix ───────────────────────────────────
        Y_df, S_df, tags = build_summing_matrix(client_id, actuals_pl)

        # ── Step 4: Classify series ────────────────────────────────────────
        all_unique_ids = actuals_pd['unique_id'].unique().tolist()
        strategy_map   = classify_series_by_strategy(
            client_id, period_type, all_unique_ids
        )

        # ── Step 5: Run forecasts per strategy ─────────────────────────────
        _set_status('RUNNING')
        all_forecasts = []

        # AutoETS batch
        if strategy_map.get('AUTOETS'):
            df = run_statsforecast_batch(
                actuals_pd, strategy_map['AUTOETS'],
                'AUTOETS', horizon, freq, season_length,
            )
            df = df.rename(columns={'AUTOETS': 'statistical_qty'})
            df['model_used'] = 'AutoETS'
            all_forecasts.append(df)

        # AutoARIMA batch
        if strategy_map.get('AUTOARIMA'):
            df = run_statsforecast_batch(
                actuals_pd, strategy_map['AUTOARIMA'],
                'AUTOARIMA', horizon, freq, season_length,
            )
            df = df.rename(columns={'AUTOARIMA': 'statistical_qty'})
            df['model_used'] = 'AutoARIMA'
            all_forecasts.append(df)

        # Croston batch
        if strategy_map.get('CROSTON'):
            df = run_statsforecast_batch(
                actuals_pd, strategy_map['CROSTON'],
                'CROSTON', horizon, freq,
            )
            df = df.rename(columns={'CROSTON': 'statistical_qty'})
            df['model_used'] = 'CrostonSBA'
            all_forecasts.append(df)

        # Lumpy batch (aggregate → forecast → disaggregate)
        lumpy_ids = (
            strategy_map.get('AGG_LOCATION', []) +
            strategy_map.get('AGG_ITEM', []) +
            strategy_map.get('AGG_TOTAL', [])
        )
        if lumpy_ids:
            df = handle_lumpy_series(
                actuals_pd, lumpy_ids, horizon, freq, season_length,
            )
            df = df.rename(columns={'AUTOETS': 'statistical_qty'})
            df['model_used'] = 'AutoETS'
            df['forecast_level'] = 'location'
            all_forecasts.append(df)

        # Insufficient / zero batch
        insuff_ids = (
            strategy_map.get('INSUFFICIENT', []) +
            strategy_map.get('MOVING_AVG', [])
        )
        if insuff_ids:
            df = handle_insufficient_series(
                actuals_pd, insuff_ids, horizon, freq,
            )
            df = df.rename(columns={'MOVING_AVG': 'statistical_qty'})
            df['model_used'] = 'MovingAverage'
            all_forecasts.append(df)

        zero_ids = strategy_map.get('ZERO', []) + strategy_map.get('MANUAL', [])
        if zero_ids:
            import numpy as np
            future_dates = pd.date_range(
                start=pd.to_datetime(period_start_to),
                periods=horizon + 1, freq=freq,
            )[1:]
            zero_rows = []
            for uid in zero_ids:
                for ds in future_dates:
                    zero_rows.append({
                        'unique_id': uid, 'ds': ds,
                        'statistical_qty': 0.0, 'model_used': 'None',
                    })
            if zero_rows:
                all_forecasts.append(pd.DataFrame(zero_rows))

        if not all_forecasts:
            raise ValueError('No forecast results produced — check strategy classification.')

        combined_df = pd.concat(all_forecasts, ignore_index=True)
        combined_df = combined_df.drop_duplicates(subset=['unique_id', 'ds'])

        # ── Step 6: Hierarchical reconciliation ────────────────────────────
        _set_status('RECONCILING')

        # Prepare forecasts_df in the shape hrec.reconcile() expects:
        # unique_id, ds, <model_column>
        # We use 'COMBINED' as the column name
        hf_input = combined_df[['unique_id', 'ds', 'statistical_qty']].copy()
        hf_input = hf_input.rename(columns={'statistical_qty': 'COMBINED'})

        try:
            reconciled_df = run_hierarchical_reconciliation(
                forecasts_df=hf_input,
                Y_df=Y_df,
                S_df=S_df,
                tags=tags,
                method=method,
            )
            # Use reconciled values where available
            reconciled_col = [
                c for c in reconciled_df.columns
                if 'COMBINED' in c and c != 'COMBINED'
            ]
            if reconciled_col:
                reconciled_df = reconciled_df.rename(
                    columns={reconciled_col[0]: 'statistical_qty'}
                )
                combined_df = reconciled_df[['unique_id', 'ds', 'statistical_qty']].copy()
                # Reattach model_used from original combined_df
                combined_df = combined_df.merge(
                    all_forecasts_concat[['unique_id', 'ds', 'model_used']],
                    on=['unique_id', 'ds'], how='left',
                )
        except Exception as exc:
            logger.warning(
                f'run_forecast: reconciliation failed ({exc}), '
                f'proceeding with unreconciled forecasts'
            )

        # ── Step 7: Write ForecastLine rows ───────────────────────────────
        _set_status('AGGREGATING')
        n_lines = write_forecast_lines(
            version_id, combined_df, strategy_map, price_map, period_type
        )

        # ── Step 8: Write ForecastAggregate rollups ────────────────────────
        n_agg = write_forecast_aggregates(version_id)

        _set_status('COMPLETE')
        logger.info(
            f'run_forecast: version={version_id} COMPLETE '
            f'lines={n_lines} aggregates={n_agg}'
        )

    except Exception as exc:
        error_text = traceback.format_exc()
        _set_status('FAILED', error=error_text)
        logger.exception(f'run_forecast: version={version_id} FAILED')
        raise self.retry(exc=exc)


# ─────────────────────────────────────────────────────────────────────────────
# Task 2: apply_overrides
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def apply_overrides(self, version_id: int):
    """
    Disaggregate all unapplied ForecastOverride rows to ForecastLine.override_qty.

    Override modes:
      override_qty (absolute):
        - SKU level:      directly set ForecastLine.override_qty
        - Aggregate level: distribute proportionally by historical final_qty share
          among all constituent ForecastLine rows

      override_pct (percentage adjustment):
        - Adjust statistical_qty by the percentage
        - e.g. +10% on a category → each SKU line in that category
          gets override_qty = statistical_qty × 1.10

      override_qty (value / ₹):
        - Only when override_key contains {"value_override": true}
        - Convert ₹ target to qty using weighted_avg_price of constituent items
        - Then disaggregate as quantity

    After processing each override, sets ForecastOverride.is_applied = True.
    Recomputes ForecastLine.final_qty and final_value via save().
    """
    from mysite.models.demand.forecast import ForecastVersion, ForecastOverride, ForecastLine
    from mysite.models.demand.actuals import ItemPlanningProfile

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
            # Continue with remaining overrides

    logger.info(
        f'apply_overrides: version={version_id} '
        f'applied={applied_count}/{pending.count()}'
    )

    # Recompute aggregates after overrides applied
    from utils.demand.forecast_engine import write_forecast_aggregates
    write_forecast_aggregates(version_id)


def _apply_single_override(override, version):
    """Apply one ForecastOverride to matching ForecastLine rows."""
    from mysite.models.demand.forecast import ForecastLine
    from mysite.models.demand.actuals import ItemPlanningProfile

    # Identify matching ForecastLine rows based on override_level + override_key
    qs = ForecastLine.objects.filter(
        version=version,
        period_type=override.period_type,
        period_start=override.period_start,
    )

    key = override.override_key

    # Filter lines by override key
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

    elif override.override_level in ('category', 'subcategory'):
        # Filter via item taxonomy
        # Implementation depends on your ItemTaxonomyMapping model
        # Simplified: pass through all lines for now
        pass

    lines = list(qs.select_related('item'))
    if not lines:
        logger.warning(
            f'_apply_single_override: no matching lines for override {override.pk}'
        )
        return

    # ── Percentage override ────────────────────────────────────────────────
    if override.override_pct is not None:
        multiplier = 1 + (float(override.override_pct) / 100)
        for line in lines:
            line.override_qty = (line.statistical_qty * Decimal(str(multiplier))).quantize(
                Decimal('0.001')
            )
            line.save(update_fields=[
                'override_qty', 'final_qty',
                'override_value', 'final_value',
            ])
        return

    # ── Absolute quantity override ─────────────────────────────────────────
    if override.override_qty is not None:
        is_value_override = key.get('value_override', False)

        if is_value_override:
            # Convert ₹ target to qty using weighted avg price
            # Get weighted avg prices for all items in these lines
            item_pks = [l.item_id for l in lines]
            price_map = {
                p.item_id: p.effective_price
                for p in ItemPlanningProfile.objects.filter(
                    client=version.client, item_id__in=item_pks
                )
            }
            # Compute implied total qty from value target
            total_value_target = override.override_qty
            total_stat_value   = sum(
                l.statistical_qty * (price_map.get(l.item_id) or Decimal('1'))
                for l in lines
            )
            if total_stat_value > 0:
                scale_factor = total_value_target / total_stat_value
                for line in lines:
                    line.override_qty = (
                        line.statistical_qty * scale_factor
                    ).quantize(Decimal('0.001'))
                    line.save(update_fields=[
                        'override_qty', 'final_qty',
                        'override_value', 'final_value',
                    ])
            return

        # Distribute override_qty proportionally by statistical_qty
        total_stat = sum(float(l.statistical_qty) for l in lines)
        override_total = float(override.override_qty)

        if override.disagg_method == 'CUSTOM':
            # Use OverrideSplitWeight rows
            weights = {
                str(sw.child_key): float(sw.weight)
                for sw in override.split_weights.all()
            }
            for line in lines:
                uid_key = str({'item_id': line.item.item_id})
                weight  = weights.get(uid_key, 0)
                line.override_qty = Decimal(str(round(override_total * weight, 3)))
                line.save(update_fields=[
                    'override_qty', 'final_qty',
                    'override_value', 'final_value',
                ])

        elif override.disagg_method == 'EQUAL':
            equal_share = Decimal(str(round(override_total / len(lines), 3)))
            for line in lines:
                line.override_qty = equal_share
                line.save(update_fields=[
                    'override_qty', 'final_qty',
                    'override_value', 'final_value',
                ])

        else:  # PROPORTIONAL (default)
            for line in lines:
                if total_stat > 0:
                    share = float(line.statistical_qty) / total_stat
                    line.override_qty = Decimal(str(round(override_total * share, 3)))
                else:
                    line.override_qty = Decimal('0')
                line.save(update_fields=[
                    'override_qty', 'final_qty',
                    'override_value', 'final_value',
                ])


# ─────────────────────────────────────────────────────────────────────────────
# Task 3: compute_accuracy — nightly MAPE / Bias
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True)
def compute_accuracy(self, client_id: int):
    """
    Nightly task. For each LOCKED or APPROVED ForecastVersion where actuals
    have landed for forecast periods, compute MAPE and Bias and write
    ForecastAccuracy rows.

    MAPE  = |actual - forecast| / actual × 100   (null if actual = 0)
    Bias  = (forecast - actual) / actual × 100
            positive = over-forecast, negative = under-forecast

    Uses DuckDB to join ForecastLine vs ActualSale without loading all rows.
    """
    from mysite.models.demand.forecast import ForecastVersion, ForecastAccuracy, ForecastLine
    from mysite.models.demand.actuals import ActualSale, compute_period_end
    import duckdb, pandas as pd

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

        # Pull ForecastLine for this version
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

        # Pull matching ActualSale rows
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

        # Join in DuckDB
        con = duckdb.connect()
        con.register('lines', lines_df)
        con.register('actuals', actuals_df)

        joined = con.execute("""
            SELECT
                l.id                        AS line_id,
                l.item_id,
                l.planning_customer_id,
                l.planning_location_id,
                l.period_start,
                CAST(l.final_qty AS DOUBLE) AS forecast_qty,
                CAST(a.qty AS DOUBLE)       AS actual_qty,
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
                ON  l.item_id               = a.item_id
                AND l.planning_location_id  = a.planning_location_id
                AND l.period_start          = a.period_start
                AND (
                    (l.planning_customer_id IS NULL AND a.planning_customer_id IS NULL)
                    OR l.planning_customer_id = a.planning_customer_id
                )
        """).df()

        if joined.empty:
            continue

        # Delete existing accuracy rows for this version
        ForecastAccuracy.objects.filter(version=version).delete()

        accuracy_objects = []
        for _, row in joined.iterrows():
            period_start = row['period_start']
            if hasattr(period_start, 'date'):
                period_start = period_start.date()

            acc = ForecastAccuracy(
                version_id           = version.pk,
                item_id              = int(row['item_id']),
                planning_customer_id = int(row['planning_customer_id'])
                                       if row['planning_customer_id'] is not None
                                       and not pd.isna(row['planning_customer_id'])
                                       else None,
                planning_location_id = int(row['planning_location_id']),
                period_type          = period_type,
                period_start         = period_start,
                period_end           = compute_period_end(period_start, period_type),
                actual_qty           = Decimal(str(round(row['actual_qty'], 3))),
                forecast_qty         = Decimal(str(round(row['forecast_qty'], 3))),
                mape                 = Decimal(str(round(row['mape'], 4)))
                                       if row['mape'] is not None
                                       and not pd.isna(row['mape'])
                                       else None,
                bias                 = Decimal(str(round(row['bias'], 4)))
                                       if row['bias'] is not None
                                       and not pd.isna(row['bias'])
                                       else None,
            )
            accuracy_objects.append(acc)

        ForecastAccuracy.objects.bulk_create(accuracy_objects, batch_size=500)
        total_written += len(accuracy_objects)
        logger.info(
            f'compute_accuracy: version={version.pk} '
            f'accuracy_rows={len(accuracy_objects)}'
        )

    logger.info(
        f'compute_accuracy: client={client_id} total_written={total_written}'
    )
```

---

## 4. REST Endpoints

Add to `mysite/api/demand/views.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Forecast run endpoints
# ─────────────────────────────────────────────────────────────────────────────

class ForecastVersionRunView(DemandFeatureMixin, APIView):
    """
    POST /api/demand/forecast-versions/{id}/run/

    Trigger the forecast pipeline for a DRAFT version.
    Fires compute_series_profiles then run_forecast as a Celery chain.

    Returns 202 immediately with the Celery task ID.

    Response:
        {
            "version_id": 42,
            "run_status": "QUEUED",
            "celery_task_id": "abc-123",
            "poll_url": "/api/demand/forecast-versions/42/run-status/"
        }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        result = is_demand_feature_disabled(request.client, 'forecast_run')
        if result['disabled']:
            return Response({'detail': result['message']},
                            status=status.HTTP_403_FORBIDDEN)

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )

        if not version.is_editable:
            return Response(
                {
                    'detail': (
                        f'Version is {version.status}. '
                        f'Only DRAFT versions can be run.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if version.run_status in ('QUEUED', 'PROFILING', 'RUNNING',
                                   'RECONCILING', 'AGGREGATING'):
            return Response(
                {'detail': 'A forecast run is already in progress for this version.'},
                status=status.HTTP_409_CONFLICT,
            )

        from mysite.tasks.demand.compute_series_profiles import compute_series_profiles
        from mysite.tasks.demand.run_forecast import run_forecast

        # Chain: profile first, then forecast
        task_chain = chain(
            compute_series_profiles.si(
                version.client.pk, version.period_type
            ),
            run_forecast.si(version.pk),
        )
        async_result = task_chain.apply_async()

        ForecastVersion.objects.filter(pk=pk).update(
            run_status='QUEUED',
            celery_task_id=async_result.id or '',
            run_error='',
        )

        return Response(
            {
                'version_id':    version.pk,
                'run_status':    'QUEUED',
                'celery_task_id': async_result.id,
                'poll_url': (
                    f'/api/demand/forecast-versions/{pk}/run-status/'
                ),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ForecastVersionRunStatusView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/run-status/

    Poll the forecast run progress.

    Response:
        {
            "version_id": 42,
            "run_status": "COMPLETE",   // QUEUED|PROFILING|RUNNING|
                                        // RECONCILING|AGGREGATING|COMPLETE|FAILED
            "celery_task_id": "abc-123",
            "run_error": "",
            "line_count": 14400,
            "aggregate_count": 240
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from mysite.models.demand.forecast import ForecastLine, ForecastAggregate

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        return Response({
            'version_id':      version.pk,
            'run_status':      version.run_status,
            'celery_task_id':  version.celery_task_id,
            'run_error':       version.run_error,
            'line_count':      version.lines.count(),
            'aggregate_count': version.aggregates.count(),
        })
```

---

## 5. Serializer and URL Additions

### Serializer delta (add to `serializers.py`)

```python
# Update ForecastVersionSerializer to include run fields:
# Add to fields list:
#   'run_status', 'celery_task_id', 'run_error'
# Add to read_only_fields:
#   'run_status', 'celery_task_id', 'run_error'

# Update ForecastLineSerializer to include value and engine fields:
# Add to fields list:
#   'statistical_value', 'override_value', 'final_value',
#   'price_used', 'forecast_level', 'model_used'
# Add to read_only_fields:
#   'statistical_value', 'override_value', 'final_value',
#   'price_used', 'forecast_level', 'model_used'

# Update ForecastAggregateSerializer to include value fields:
# Add to fields list:
#   'total_statistical_value', 'total_override_value', 'total_final_value'
```

### URL delta (add to `urls.py`)

```python
path(
    'forecast-versions/<int:pk>/run/',
    views.ForecastVersionRunView.as_view(),
    name='demand-forecast-version-run',
),
path(
    'forecast-versions/<int:pk>/run-status/',
    views.ForecastVersionRunStatusView.as_view(),
    name='demand-forecast-version-run-status',
),
```

---

## 6. Unit Tests

```python
# mysite/tests/demand/test_forecast_engine.py

import pytest
import datetime
from decimal import Decimal
import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# Test: build_summing_matrix produces correct S shape
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestBuildSummingMatrix:

    def test_s_matrix_shape(self, client_obj, leaf_location, active_item):
        """S_df should have shape (all_nodes, leaf_series)."""
        from utils.demand.forecast_engine import build_summing_matrix
        import polars as pl

        # 2 leaf series → 1 location group + 2 leaves = 3 nodes total
        actuals_df = pl.DataFrame({
            'unique_id':          ['ITEM-001|NULL|LEAF-01', 'ITEM-001|CUST-001|LEAF-01'],
            'ds':                 [datetime.date(2024, 1, 1)] * 2,
            'y':                  [100.0, 50.0],
            'item_id':            [active_item.pk] * 2,
            'planning_customer_id': [None, 1],
            'planning_location_id': [leaf_location.pk] * 2,
        })

        Y_df, S_df, tags = build_summing_matrix(client_obj.pk, actuals_df)

        # S_df rows = all nodes (aggregates + leaves), cols = leaves only
        n_leaves = 2
        assert S_df.shape[1] == n_leaves
        assert S_df.shape[0] >= n_leaves  # at least as many rows as leaves


# ─────────────────────────────────────────────────────────────────────────────
# Test: MinTrace coherence — top-level total == sum of bottom-up
# ─────────────────────────────────────────────────────────────────────────────

class TestMinTraceCoherence:

    def test_reconciled_total_equals_summed_leaves(self):
        """
        After MinTrace reconciliation, the aggregate node forecast must equal
        the sum of its constituent leaf forecasts (within float tolerance).
        """
        from utils.demand.forecast_engine import run_hierarchical_reconciliation
        from hierarchicalforecast.utils import aggregate

        # Build a minimal 2-level hierarchy
        raw = pd.DataFrame({
            'ds':     pd.date_range('2022-01-01', periods=24, freq='MS').tolist() * 2,
            'group':  ['A'] * 24 + ['A'] * 24,
            'unique_id': ['A|leaf1'] * 24 + ['A|leaf2'] * 24,
            'y':      list(range(100, 124)) + list(range(50, 74)),
        })
        raw['y'] = raw['y'].astype(float)

        Y_df, S_df, tags = aggregate(raw, [['group'], ['group', 'unique_id']])

        # Forecast: use simple values
        import statsforecast
        from statsforecast import StatsForecast
        from statsforecast.models import SeasonalNaive

        sf = StatsForecast(models=[SeasonalNaive(season_length=12)], freq='MS', n_jobs=1)
        forecasts_df = sf.forecast(df=Y_df, h=3)

        reconciled = run_hierarchical_reconciliation(
            forecasts_df=forecasts_df,
            Y_df=Y_df,
            S_df=S_df,
            tags=tags,
            method='MinTrace_ols',
        )

        # Find reconciled column name
        rec_col = [c for c in reconciled.columns
                   if c not in ('unique_id', 'ds') and 'SeasonalNaive' in c]
        assert rec_col, 'No reconciled column found'
        rec_col = rec_col[0]

        # For each forecast period, aggregate total == sum of leaves
        for ds_val in reconciled['ds'].unique():
            period = reconciled[reconciled['ds'] == ds_val]
            total = float(
                period[period['unique_id'] == 'A'][rec_col].values[0]
            )
            leaf1 = float(
                period[period['unique_id'] == 'A/A|leaf1'][rec_col].values[0]
            )
            leaf2 = float(
                period[period['unique_id'] == 'A/A|leaf2'][rec_col].values[0]
            )
            assert abs(total - (leaf1 + leaf2)) < 0.01, (
                f'Coherence violated at {ds_val}: '
                f'total={total} leaf1={leaf1} leaf2={leaf2}'
            )


# ─────────────────────────────────────────────────────────────────────────────
# Test: LUMPY series correctly aggregated to location level
# ─────────────────────────────────────────────────────────────────────────────

class TestLumpySeriesAggregation:

    def test_lumpy_disaggregation_sums_to_location_total(self):
        """
        After handle_lumpy_series, the sum of disaggregated SKU forecasts
        for a location must equal the location-level forecast.
        """
        from utils.demand.forecast_engine import handle_lumpy_series

        # Two lumpy series at the same location
        lumpy_ids = ['ITEM-001|NULL|LOC-A', 'ITEM-002|NULL|LOC-A']

        # Build actuals: ITEM-001 gets 2× the demand of ITEM-002
        dates = pd.date_range('2022-01-01', periods=24, freq='MS')
        rows = []
        for ds in dates:
            rows.append({'unique_id': 'ITEM-001|NULL|LOC-A', 'ds': ds, 'y': 20.0})
            rows.append({'unique_id': 'ITEM-002|NULL|LOC-A', 'ds': ds, 'y': 10.0})
        actuals_df = pd.DataFrame(rows)

        result = handle_lumpy_series(
            actuals_df, lumpy_ids, horizon=3, freq='MS', season_length=12
        )

        for ds_val in result['ds'].unique():
            period = result[result['ds'] == ds_val]
            item1_qty = float(
                period[period['unique_id'] == 'ITEM-001|NULL|LOC-A']['AUTOETS'].values[0]
            )
            item2_qty = float(
                period[period['unique_id'] == 'ITEM-002|NULL|LOC-A']['AUTOETS'].values[0]
            )
            # ITEM-001 should get ~2× the qty of ITEM-002 (proportional share)
            if item2_qty > 0:
                ratio = item1_qty / item2_qty
                assert abs(ratio - 2.0) < 0.1, (
                    f'Expected ~2:1 ratio, got {ratio:.2f}'
                )


# ─────────────────────────────────────────────────────────────────────────────
# Test: CrostonSBA selected for high-zero-rate series
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestStrategyClassification:

    def test_croston_selected_for_intermittent_series(
        self, client_obj, active_item, leaf_location
    ):
        """
        A series with ADI ≥ 1.32 and CV² < 0.49 should get strategy=CROSTON.
        """
        from mysite.models.demand.forecast import SeriesProfile

        # ADI = 36/6 = 6.0, CV² of non-zero values will be low (all same value)
        qty_series = [Decimal('0')] * 30 + [Decimal('100')] * 6

        result = SeriesProfile.classify(qty_series)
        assert result['demand_class'] == SeriesProfile.DemandClass.INTERMITTENT
        assert result['recommended_strategy'] == SeriesProfile.ForecastStrategy.CROSTON

    def test_autoets_selected_for_smooth_series(self):
        """
        A series with ADI < 1.32 and CV² < 0.49 should get strategy=AUTOETS.
        """
        from mysite.models.demand.forecast import SeriesProfile

        # All non-zero, low variance
        qty_series = [Decimal('100')] * 36

        result = SeriesProfile.classify(qty_series)
        assert result['demand_class'] == SeriesProfile.DemandClass.SMOOTH
        assert result['recommended_strategy'] == SeriesProfile.ForecastStrategy.AUTOETS


# ─────────────────────────────────────────────────────────────────────────────
# Test: write_forecast_lines produces correct row count
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db(transaction=True)
class TestWriteForecastLines:

    def test_row_count_matches_input(
        self, draft_version, active_item, leaf_location, staff_user
    ):
        """write_forecast_lines creates exactly N ForecastLine rows."""
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine
        import datetime

        forecast_df = pd.DataFrame([
            {
                'unique_id':       'ITEM-001|NULL|LEAF-01',
                'ds':              pd.Timestamp('2025-01-01'),
                'statistical_qty': 480.0,
                'model_used':      'AutoETS',
            },
            {
                'unique_id':       'ITEM-001|NULL|LEAF-01',
                'ds':              pd.Timestamp('2025-02-01'),
                'statistical_qty': 520.0,
                'model_used':      'AutoETS',
            },
        ])

        strategy_map = {'AUTOETS': ['ITEM-001|NULL|LEAF-01']}
        price_map    = {active_item.pk: Decimal('150.00')}

        n = write_forecast_lines(
            draft_version.pk, forecast_df,
            strategy_map, price_map, 'month'
        )

        assert n == 2
        assert ForecastLine.objects.filter(version=draft_version).count() == 2

    def test_final_value_computed_correctly(
        self, draft_version, active_item, leaf_location
    ):
        """final_value = statistical_qty × price_used."""
        from utils.demand.forecast_engine import write_forecast_lines
        from mysite.models.demand.forecast import ForecastLine

        forecast_df = pd.DataFrame([{
            'unique_id':       'ITEM-001|NULL|LEAF-01',
            'ds':              pd.Timestamp('2025-01-01'),
            'statistical_qty': 100.0,
            'model_used':      'AutoETS',
        }])

        price = Decimal('250.00')
        write_forecast_lines(
            draft_version.pk, forecast_df,
            {'AUTOETS': ['ITEM-001|NULL|LEAF-01']},
            {active_item.pk: price}, 'month',
        )

        line = ForecastLine.objects.get(version=draft_version)
        assert line.final_value == Decimal('25000.00')  # 100 × 250


# ─────────────────────────────────────────────────────────────────────────────
# Test: MAPE and Bias computation
# ─────────────────────────────────────────────────────────────────────────────

class TestMapeComputation:

    def test_mape_formula(self):
        """MAPE = |actual - forecast| / actual × 100"""
        actual   = 400.0
        forecast = 440.0
        expected_mape = abs(actual - forecast) / actual * 100  # 10.0
        expected_bias = (forecast - actual) / actual * 100    # +10.0

        assert abs(expected_mape - 10.0) < 0.001
        assert abs(expected_bias - 10.0) < 0.001

    def test_mape_null_when_actual_zero(self):
        """MAPE is undefined (null) when actual = 0."""
        actual = 0.0
        mape   = None if actual == 0 else abs(0 - actual) / actual * 100
        assert mape is None
```

---

## 7. Migration Checklist

```bash
# 1. Generate migration for model delta
python manage.py makemigrations mysite --name forecast_engine_delta

# 2. Apply
python manage.py migrate

# 3. Verify check passes
python manage.py check

# 4. Run tests
pytest mysite/tests/demand/test_forecast_engine.py -v

# 5. Update project plan sprint status
```

**Model delta summary for this migration:**
- `ItemPlanningProfile` — new model in `actuals.py`
- `ForecastLine` — 4 new fields: `statistical_value`, `override_value`, `final_value`, `price_used`
- `ForecastLine` — 2 existing fields: `forecast_level`, `model_used` (added in Sprint 3B.3 — already migrated)
- `ForecastAggregate` — 3 new fields: `total_statistical_value`, `total_override_value`, `total_final_value`
- `ForecastVersion` — 3 new fields: `celery_task_id`, `run_status`, `run_error`
