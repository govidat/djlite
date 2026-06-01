## 11. Additional point - forecast level selection or intermittency classification.
The Core Problem
When you try to forecast a C-class item with sporadic demand at SKU × Customer × Location level, you get a time series that looks like this:
Jan  Feb  Mar  Apr  May  Jun  Jul  Aug  Sep  Oct  Nov  Dec
 0    0    12   0    0    0    8    0    0    0    0    15

 Statistical models like AutoETS and AutoARIMA are designed for smooth, regular series. They will produce poor forecasts on this — often worse than a simple average. The right response is either to use a specialist intermittency model (Croston, TSB) or to aggregate the series up to a level where demand becomes smoother.

Established Measures for This Decision
There are three standard metrics used in the literature (Syntetos, Boylan, Croston):
### 1. ADI — Average Demand Interval
Average number of periods between non-zero demand observations.
ADI = total periods / number of non-zero periods

ADI = 1.0  → demand every period (smooth)
ADI = 4.0  → demand every 4 periods on average (intermittent)

### 2. CV² — Squared Coefficient of Variation of Non-Zero Demand
Measures how lumpy the non-zero demand quantities are.

CV² = (std of non-zero qty / mean of non-zero qty)²

CV² = 0.0  → non-zero quantities are always the same (regular)
CV² = 1.5  → non-zero quantities vary wildly (lumpy)

### 3. The Syntetos-Boylan Classification Matrix
These two measures together classify every series into four quadrants:
CV² < 0.49          CV² ≥ 0.49
                ┌───────────────────┬───────────────────┐
  ADI < 1.32   │    SMOOTH         │    ERRATIC        │
               │  → AutoETS        │  → AutoETS/ARIMA  │
               │  → AutoARIMA      │  (volatile but     │
               │  (regular demand) │   frequent)        │
               ├───────────────────┼───────────────────┤
  ADI ≥ 1.32   │    INTERMITTENT   │    LUMPY          │
               │  → Croston / TSB  │  → CrostonSBA     │
               │  (sparse but      │  → Aggregate up   │
               │   stable qty)     │  (worst case)     │
               └───────────────────┴───────────────────┘

The thresholds ADI=1.32 and CV²=0.49 come from Syntetos & Boylan (2005) and are widely used in industry. They are not sacred — some practitioners use ADI=1.5 or CV²=0.5.

### 4. Additional Measures Worth Computing
Metric              Formula                 Threshold               Meaning
Zero rate           zero periods / 
                    total periods            > 0.7               More than 70% zeros — strongly consider aggregating

Min observations    count of non-zero periods< 12                Too few data points for any model to learn from

Total volume        sum of all qty          < client-defined     C-class by volume — candidate for aggregation

How to Handle This in the Model
There are three things to add:

A SeriesProfile model that stores computed metrics per series
A classification result that maps to a recommended forecast strategy
A forecast_level field on ForecastLine / ForecastVersion that records what level was actually used

## Addition 1 — SeriesProfile model

```python
class SeriesProfile(models.Model):
    """
    Computed demand characteristics for one (item, customer, location) series.

    Populated by a Celery task that runs before forecast generation.
    The forecasting engine reads this to decide:
      a) which model to use (AutoETS vs Croston vs aggregate)
      b) at what level to forecast (SKU×Customer×Location vs SKU×Location vs Location)

    Metrics follow the Syntetos-Boylan (2005) classification framework.
    """

    class DemandClass(models.TextChoices):
        SMOOTH       = 'SMOOTH',       _('Smooth — regular frequent demand')
        ERRATIC      = 'ERRATIC',      _('Erratic — frequent but variable quantity')
        INTERMITTENT = 'INTERMITTENT', _('Intermittent — sparse but stable quantity')
        LUMPY        = 'LUMPY',        _('Lumpy — sparse and variable quantity')
        INSUFFICIENT = 'INSUFFICIENT', _('Insufficient data — fewer than min_obs non-zero periods')
        ZERO         = 'ZERO',         _('Zero demand — no non-zero observations')

    class ForecastStrategy(models.TextChoices):
        # Forecast at this exact granularity using the named model
        AUTOETS      = 'AUTOETS',      _('AutoETS (smooth/erratic series)')
        AUTOARIMA    = 'AUTOARIMA',    _('AutoARIMA (erratic series)')
        CROSTON      = 'CROSTON',      _('Croston SBA (intermittent series)')
        # Aggregate before forecasting, then disaggregate back
        AGG_LOCATION = 'AGG_LOCATION', _('Aggregate to Location level, then disaggregate')
        AGG_ITEM     = 'AGG_ITEM',     _('Aggregate to Item level (across locations)')
        AGG_TOTAL    = 'AGG_TOTAL',    _('Aggregate to client total')
        # No statistical forecast — use historical average or manual
        MOVING_AVG   = 'MOVING_AVG',  _('Simple moving average (lumpy / low volume)')
        MANUAL       = 'MANUAL',      _('Manual — no statistical forecast recommended')

    client            = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_profiles',
    )
    item              = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
        help_text=_('Null = location-level series (no customer breakdown).'),
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    period_type       = models.CharField(
        max_length=16, choices=PERIOD_TYPE_CHOICES,
    )
    # ── Window of analysis ────────────────────────────────────────────────────
    analysis_from  = models.DateField(
        help_text=_('Start of the actuals window used for classification.'),
    )
    analysis_to    = models.DateField(
        help_text=_('End of the actuals window used for classification.'),
    )
    computed_at    = models.DateTimeField(auto_now=True)

    # ── Raw counts ────────────────────────────────────────────────────────────
    total_periods  = models.PositiveSmallIntegerField(
        help_text=_('Total number of periods in the analysis window.'),
    )
    nonzero_periods = models.PositiveSmallIntegerField(
        help_text=_('Number of periods with qty > 0.'),
    )
    total_qty      = models.DecimalField(
        max_digits=16, decimal_places=3,
        help_text=_('Sum of all qty over the analysis window.'),
    )

    # ── Syntetos-Boylan metrics ───────────────────────────────────────────────
    adi = models.DecimalField(
        _('ADI'),
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Average Demand Interval. '
            'total_periods / nonzero_periods. '
            'Null if nonzero_periods = 0.'
        ),
    )
    cv2 = models.DecimalField(
        _('CV²'),
        max_digits=8, decimal_places=4,
        null=True, blank=True,
        help_text=_(
            'Squared Coefficient of Variation of non-zero demand quantities. '
            '(std / mean)² of non-zero qty. '
            'Null if fewer than 2 non-zero periods.'
        ),
    )
    zero_rate = models.DecimalField(
        _('zero rate'),
        max_digits=5, decimal_places=4,
        help_text=_('Fraction of periods with zero demand. 0.0–1.0.'),
    )

    # ── Classification result ─────────────────────────────────────────────────
    demand_class = models.CharField(
        _('demand class'),
        max_length=16,
        choices=DemandClass.choices,
    )
    recommended_strategy = models.CharField(
        _('recommended strategy'),
        max_length=16,
        choices=ForecastStrategy.choices,
    )

    # ── Planner override of the recommendation ────────────────────────────────
    # Planners can disagree with the auto-classification and pin a strategy
    override_strategy = models.CharField(
        _('override strategy'),
        max_length=16,
        choices=ForecastStrategy.choices,
        blank=True,
        help_text=_(
            'If set, the forecast engine uses this strategy instead of '
            'recommended_strategy. Set by a planner or superadmin.'
        ),
    )
    override_note = models.TextField(blank=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [
            ('client', 'item', 'planning_customer',
             'planning_location', 'period_type'),
        ]
        ordering = ['item__item_id', 'planning_location__code']
        verbose_name        = _('03-07 Series Profile')
        verbose_name_plural = _('03-07 Series Profiles')
        indexes = [
            models.Index(
                fields=['client', 'demand_class'],
                name='ix_seriesprofile_client_class',
            ),
            models.Index(
                fields=['client', 'recommended_strategy'],
                name='ix_seriesprofile_client_strategy',
            ),
        ]

    def __str__(self):
        cust = self.planning_customer or 'all'
        return (
            f'{self.item.item_id} | {self.planning_location.code} | '
            f'{cust} | {self.demand_class}'
        )

    @property
    def effective_strategy(self) -> str:
        """The strategy the forecast engine should actually use."""
        return self.override_strategy or self.recommended_strategy

    @classmethod
    def classify(
        cls,
        qty_series: list,          # list of Decimal, one per period, zeros included
        adi_threshold: float = 1.32,
        cv2_threshold: float = 0.49,
        min_nonzero: int = 6,      # minimum non-zero periods for any statistical model
    ) -> dict:
        """
        Compute metrics and classify a demand series.

        Args:
            qty_series:     list of qty values (including zeros), ordered by period
            adi_threshold:  Syntetos-Boylan ADI cutoff (default 1.32)
            cv2_threshold:  Syntetos-Boylan CV² cutoff (default 0.49)
            min_nonzero:    minimum non-zero observations required for
                            statistical modelling (default 6)

        Returns dict with keys:
            total_periods, nonzero_periods, total_qty,
            adi, cv2, zero_rate,
            demand_class, recommended_strategy
        """
        import statistics
        from decimal import Decimal

        total_periods   = len(qty_series)
        nonzero_vals    = [q for q in qty_series if q > 0]
        nonzero_periods = len(nonzero_vals)
        total_qty       = sum(qty_series)
        zero_rate       = Decimal(
            1 - nonzero_periods / total_periods
        ) if total_periods > 0 else Decimal('1')

        # ── Edge cases ────────────────────────────────────────────────────────
        if nonzero_periods == 0:
            return {
                'total_periods':   total_periods,
                'nonzero_periods': 0,
                'total_qty':       Decimal('0'),
                'adi':             None,
                'cv2':             None,
                'zero_rate':       Decimal('1'),
                'demand_class':    cls.DemandClass.ZERO,
                'recommended_strategy': cls.ForecastStrategy.MANUAL,
            }

        if nonzero_periods < min_nonzero:
            adi = Decimal(str(round(total_periods / nonzero_periods, 4)))
            return {
                'total_periods':   total_periods,
                'nonzero_periods': nonzero_periods,
                'total_qty':       total_qty,
                'adi':             adi,
                'cv2':             None,
                'zero_rate':       zero_rate,
                'demand_class':    cls.DemandClass.INSUFFICIENT,
                'recommended_strategy': cls.ForecastStrategy.MOVING_AVG,
            }

        # ── Compute ADI and CV² ───────────────────────────────────────────────
        adi  = Decimal(str(round(total_periods / nonzero_periods, 4)))
        mean = statistics.mean(float(v) for v in nonzero_vals)
        std  = statistics.stdev(float(v) for v in nonzero_vals) if len(nonzero_vals) > 1 else 0.0
        cv2  = Decimal(str(round((std / mean) ** 2, 4))) if mean > 0 else Decimal('0')

        adi_f = float(adi)
        cv2_f = float(cv2)

        # ── Syntetos-Boylan classification ────────────────────────────────────
        if adi_f < adi_threshold and cv2_f < cv2_threshold:
            demand_class = cls.DemandClass.SMOOTH
            strategy     = cls.ForecastStrategy.AUTOETS

        elif adi_f < adi_threshold and cv2_f >= cv2_threshold:
            demand_class = cls.DemandClass.ERRATIC
            strategy     = cls.ForecastStrategy.AUTOARIMA

        elif adi_f >= adi_threshold and cv2_f < cv2_threshold:
            demand_class = cls.DemandClass.INTERMITTENT
            strategy     = cls.ForecastStrategy.CROSTON

        else:  # adi_f >= adi_threshold and cv2_f >= cv2_threshold
            demand_class = cls.DemandClass.LUMPY
            # Lumpy: try aggregating to location level first
            strategy     = cls.ForecastStrategy.AGG_LOCATION

        return {
            'total_periods':        total_periods,
            'nonzero_periods':      nonzero_periods,
            'total_qty':            total_qty,
            'adi':                  adi,
            'cv2':                  cv2,
            'zero_rate':            zero_rate,
            'demand_class':         demand_class,
            'recommended_strategy': strategy,
        }
```

## Addition 2 — forecast_level on ForecastLine
Add two fields to ForecastLine to record what actually happened during forecasting:

```python
# Add to ForecastLine, after override_qty:

forecast_level = models.CharField(
    _('forecast level'),
    max_length=32,
    blank=True,
    default='sku_customer_location',
    help_text=_(
        'The aggregation level at which the statistical forecast was actually '
        'computed before disaggregation. '
        'e.g. "sku_customer_location" (atomic), "sku_location" (no customer), '
        '"location" (all items aggregated to location).'
    ),
)
model_used = models.CharField(
    _('model used'),
    max_length=32,
    blank=True,
    help_text=_(
        'The StatsForecast model that produced statistical_qty. '
        'e.g. "AutoETS", "CrostonSBA", "MovingAverage".'
    ),
)
```

## Addition 3 — Celery task: compute_series_profiles
This task runs before the forecast task. It reads actuals, classifies every series, writes SeriesProfile rows, and the forecast task reads them to decide strategy.

```python
# mysite/tasks/demand/compute_series_profiles.py

import logging
from decimal import Decimal
from celery import shared_task
from django.db import transaction

from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.forecast import SeriesProfile

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Classify every (item, customer, location) series for a client.

    Run this BEFORE the forecast task. The forecast task reads
    SeriesProfile.effective_strategy to decide model and level.

    Steps:
      1. Pull all ActualSale rows for the client (last N periods)
         into memory via DuckDB for fast groupby.
      2. For each unique (item, customer, location) combination,
         compute ADI, CV², zero_rate.
      3. Classify using Syntetos-Boylan matrix.
      4. Upsert SeriesProfile rows.
    """
    import duckdb
    import polars as pl
    from mysite.models import Client

    client = Client.objects.get(pk=client_id)

    # ── 1. Pull actuals into a Polars DataFrame via DuckDB ────────────────────
    # Use the last 36 periods for classification (configurable)
    actuals_qs = (
        ActualSale.objects
        .filter(client=client, period_type=period_type)
        .values(
            'item_id', 'planning_customer_id',
            'planning_location_id', 'period_start', 'qty',
        )
        .order_by('period_start')
    )

    if not actuals_qs.exists():
        logger.info(f'compute_series_profiles: no actuals for client {client_id}')
        return

    import pandas as pd
    df_pd = pd.DataFrame(list(actuals_qs))
    df    = pl.from_pandas(df_pd)

    # ── 2. Get all period dates for this client (the full time spine) ─────────
    all_periods = sorted(df['period_start'].unique().to_list())
    total_periods = len(all_periods)
    analysis_from = all_periods[0]
    analysis_to   = all_periods[-1]

    # ── 3. Classify each series ───────────────────────────────────────────────
    # Group by (item, customer, location) and build the qty time series
    group_keys = ['item_id', 'planning_customer_id', 'planning_location_id']

    # Pivot to wide: rows = series, columns = periods
    # Fill missing periods with 0 (these are the zero-demand periods)
    profiles_to_upsert = []

    grouped = df.group_by(group_keys)

    for keys, group in grouped:
        # Build full time spine with zeros for missing periods
        period_qty = {row['period_start']: row['qty'] for row in group.iter_rows(named=True)}
        qty_series = [
            Decimal(str(period_qty.get(p, 0)))
            for p in all_periods
        ]

        metrics = SeriesProfile.classify(qty_series)

        item_id       = keys[0]
        customer_id   = keys[1]
        location_id   = keys[2]

        profiles_to_upsert.append({
            'client_id':              client_id,
            'item_id':                item_id,
            'planning_customer_id':   customer_id,
            'planning_location_id':   location_id,
            'period_type':            period_type,
            'analysis_from':          analysis_from,
            'analysis_to':            analysis_to,
            'total_periods':          metrics['total_periods'],
            'nonzero_periods':        metrics['nonzero_periods'],
            'total_qty':              metrics['total_qty'],
            'adi':                    metrics['adi'],
            'cv2':                    metrics['cv2'],
            'zero_rate':              metrics['zero_rate'],
            'demand_class':           metrics['demand_class'],
            'recommended_strategy':   metrics['recommended_strategy'],
        })

    # ── 4. Upsert SeriesProfile rows ──────────────────────────────────────────
    with transaction.atomic():
        for p in profiles_to_upsert:
            SeriesProfile.objects.update_or_create(
                client_id            = p['client_id'],
                item_id              = p['item_id'],
                planning_customer_id = p['planning_customer_id'],
                planning_location_id = p['planning_location_id'],
                period_type          = p['period_type'],
                defaults={k: v for k, v in p.items()
                          if k not in ('client_id', 'item_id',
                                       'planning_customer_id',
                                       'planning_location_id', 'period_type')},
            )

    # Summary log
    from collections import Counter
    class_counts = Counter(p['demand_class'] for p in profiles_to_upsert)
    logger.info(
        f'compute_series_profiles: client={client_id} '
        f'total_series={len(profiles_to_upsert)} '
        f'classes={dict(class_counts)}'
    )
```

## Addition 4 — How the forecast task uses SeriesProfile
In your Sprint 3B.4 forecast Celery task, the dispatch logic will look like this (pseudocode showing the decision tree):

```python
# Inside the forecast Celery task — pseudocode

profiles = SeriesProfile.objects.filter(
    client=client, period_type=period_type
).select_related('item', 'planning_location', 'planning_customer')

# Separate series by effective_strategy
smooth_series       = []   # → AutoETS
erratic_series      = []   # → AutoARIMA
intermittent_series = []   # → CrostonSBA
agg_location_series = []   # → aggregate to location, forecast, disaggregate back
moving_avg_series   = []   # → simple moving average
manual_series       = []   # → skip statistical forecast entirely

for profile in profiles:
    strategy = profile.effective_strategy
    if strategy == 'AUTOETS':
        smooth_series.append(profile)
    elif strategy == 'AUTOARIMA':
        erratic_series.append(profile)
    elif strategy == 'CROSTON':
        intermittent_series.append(profile)
    elif strategy == 'AGG_LOCATION':
        agg_location_series.append(profile)
    elif strategy == 'MOVING_AVG':
        moving_avg_series.append(profile)
    else:  # MANUAL, ZERO, INSUFFICIENT
        manual_series.append(profile)

# Run StatsForecast in batches per model type
# AutoETS batch
if smooth_series:
    sf = StatsForecast(models=[AutoETS(season_length=12)], freq=freq, n_jobs=-1)
    sf.forecast(df=build_df(smooth_series), h=horizon)
    # Write ForecastLine with model_used='AutoETS', forecast_level='sku_customer_location'

# Croston batch
if intermittent_series:
    sf = StatsForecast(models=[CrostonSBA()], freq=freq, n_jobs=-1)
    sf.forecast(df=build_df(intermittent_series), h=horizon)
    # Write ForecastLine with model_used='CrostonSBA', forecast_level='sku_customer_location'

# Aggregated series: group by location, forecast at location level,
# then disaggregate back to SKU × Customer using historical share weights
if agg_location_series:
    # aggregate actuals to location grain
    # forecast with AutoETS at location level
    # disaggregate back using historical proportions
    # Write ForecastLine with model_used='AutoETS', forecast_level='location'

```

## Summary of What Gets Added to the Model
Addition                        Where               Purpose     
SeriesProfile model             forecast.py         Stores ADI, CV², zero_rate, demand_class, 
                                                    recommended_strategy per series

SeriesProfile.classify()        classmethod         Pure function — computes metrics from a qty list, 
                                                    returns classification dict
ForecastLine.forecast_level     forecast.py         Records what aggregation level was used when forecasting this line
ForecastLine.model_used         forecast.py         Records which StatsForecast model produced statistical_qty  

compute_series_profiles         Celery task         Runs before forecast task; classifies all series and
                                                    writes SeriesProfile

The key design principle is that classification is separated from forecasting. SeriesProfile is computed once per planning cycle and can be reviewed by planners (via admin or a future UI screen) before the forecast runs. A planner who disagrees with the auto-classification can set override_strategy on a specific series. The forecast task always reads effective_strategy (which honours the planner override), never recommended_strategy directly.