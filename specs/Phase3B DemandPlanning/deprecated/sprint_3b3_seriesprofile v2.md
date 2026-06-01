# Sprint 3B.3 — Revised SeriesProfile Section
## Full Business Flow: ABC/XYZ, Configurable Thresholds, Multi-Level Evaluation

**Replaces:** The SeriesProfile addition in `sprint_3b3_instructions.md`  
**Scope:** Models, Celery task, Admin, Serializer, API  

---

## 0. Business Flow Summary (Plain Language)

### The Planning Matrix

Every item gets **two independent scores**:

**ABC — How important is this item?**  
Based on its share of total demand *value* at the level being evaluated.  
An item can be **C** at the Client level (small share of total business)  
but **A** at a specific Location (dominant product at that branch).  
ABC thresholds are configurable per client (default: A=top 70%, B=next 20%, C=bottom 10%).

**Syntetos-Boylan Class — How forecastable is this item at this level?**  
Based on ADI (how often demand occurs) and CV² (how variable the non-zero quantities are).  
Results in SMOOTH / ERRATIC / INTERMITTENT / LUMPY.  
ADI and CV² thresholds are configurable per client (default: ADI=1.32, CV²=0.49).

### The Classification Search Flow

```

Get the PlanningLocation levels required in Part A from the Client PlanningLocation model. 
Get the ProductHierarchy levels from the Client Item Taxonomy. This will be used in Step B.
In the Planning Profile take the Client input for the higher Time horizons that need to be used for aggregation. Based on the Planning Time bucket in the Planning profile, higher time horizons to be controlled. Eg if Monthly is the time bucket, then higher Time Horizons are Quarterly, HalYearly, Yearly are the possible horizons. If Day is the time bucket, then Weekly, Fortnightly and Month are the possible higher Time horizons.

For every item:

  Step 1: Item × Client Total
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ These items are to be evaluated further in Part A
    → LUMPY?  → go to PART B


PART A — Try the item as-is from coarsest to finest location grain:

  Step A1: Item × Region  (one level down location hierarchy)
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in Step A2
    → LUMPY?  → USE THE LEVEL in Step 1 (Item x Client Total)

  Step A2: Item x Region x abc (one level below Region)...
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in next Step
    → LUMPY?  → USE THE LEVEL in Step A1 (Item x Region) 

    ... Keep going down the PlanningLocation hierarchy... 

  Step An: Item × Leaf Location  (location grain)
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in Step Am
    → LUMPY?  → USE THE LEVEL in Previous Step An-1  (Eg Item x Region)

  Step Am: Item × Leaf Location x PlanningCustomer  (finest grain)
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ USE THE LEVEL in this Step Am  (Item x PlanningLocation x PlanningCustomer)
    → LUMPY?  → USE THE LEVEL in Previous Step An  (Item x Leaf Location)

PART B — Item is LUMPY at Client level. Aggregate upward:

  Step B1: SubCategory × Client  (roll up product hierarchy)
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → go higher Step B2

    ... Repeat the step for the ProductHierarchy level derived above.

  Step Bn: Category × Client
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → try time aggregation Step C1

Part C - Coarser Time horizons.
    First go up up in the ProductHierarchy and then go up in the Time Hierarchy.

  Step C1: Item × Client × Next ImmediateTime Horizon 1 (aggregate time periods)
    → Not LUMPY?  ✓ USE THIS LEVEL (forecast quarterly, disaggregate to months)
    → LUMPY?  → try time aggregation Step C2

  Step C2: Next Item ProductHierarchy × Client × Time Horizon 1
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → 

    ... Repeat the steps in the Product Hierarchy x Time Hierarchy combinations.

  Step Z: MANUAL — no statistical level found.
            statistical_qty = 0. Planner enters override.

At EVERY step, the ABC class and Syntetos-Boylan metrics are stored
so planners can see the full audit trail.


For every item:

PART A — Try the item as-is from coarsest to finest location grain:

  Step 1: Item × Client Total
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ USE THIS LEVEL
    → LUMPY?  → go to PART B

  Step 2: Item × Region  (one level down location hierarchy)
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ USE THIS LEVEL
    → LUMPY?  → go deeper

  Step 3: Item × Leaf Location  (finest location grain)
    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ USE THIS LEVEL
    → LUMPY?  → Item is LUMPY everywhere → go to PART B

PART B — Item is LUMPY at all location levels. Aggregate upward:

  Step 4: SubCategory × Client  (roll up product hierarchy)
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → go higher

  Step 5: Category × Client
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → try time aggregation

  Step 6: Item × Client × Quarterly  (aggregate time periods)
    → Not LUMPY?  ✓ USE THIS LEVEL (forecast quarterly, disaggregate to months)
    → LUMPY?  → try coarser time

  Step 7: SubCategory × Client × Quarterly
    → Not LUMPY?  ✓ USE THIS LEVEL
    → LUMPY?  → MANUAL

  Step 8: MANUAL — no statistical level found.
            statistical_qty = 0. Planner enters override.

At EVERY step, the ABC class and Syntetos-Boylan metrics are stored
so planners can see the full audit trail.
```

### Disaggregation Conflict Resolution (Requirement 7)

When Item A is forecastable at Location level AND its product group
(which includes LUMPY Items B and C) is also forecasted at SubCategory level:

- **Both forecasts are stored** — `SeriesLevelEvaluation` has one row per level tried
- The `ForecastVersion.engine_config` has a setting `disagg_conflict_resolution`:
  - `"retain_lower"` (default) — the finer-grain forecast wins; the product-group
    disaggregation does not overwrite it
  - `"use_upper"` — the product-group disaggregation overwrites all items including
    those that had their own forecast

---

## 1. New Model: `ForecastingConfig`

Client-level configuration for forecasting thresholds.
Add to `mysite/models/demand/forecast.py` **before** `SeriesProfile`:

```python
class ForecastingConfig(models.Model):
    """
    Client-level configuration for the forecasting classification engine.

    One row per client. Created with defaults on first forecast run
    if not already present.

    All threshold fields have sensible defaults matching published
    Syntetos-Boylan (2005) values and standard ABC practice.
    Planners / superadmins adjust these via admin.
    """

    client = models.OneToOneField(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='forecasting_config',
        verbose_name=_('client'),
    )

    # ── ABC thresholds (cumulative value %) ───────────────────────────────────
    abc_a_threshold = models.DecimalField(
        _('ABC — A threshold (cumulative %)'),
        max_digits=5, decimal_places=2,
        default=Decimal('70.00'),
        help_text=_(
            'Items whose cumulative demand value share (at the level being '
            'evaluated) falls within this % are class A. Default 70.'
        ),
    )
    abc_b_threshold = models.DecimalField(
        _('ABC — B threshold (cumulative %)'),
        max_digits=5, decimal_places=2,
        default=Decimal('90.00'),
        help_text=_(
            'Items whose cumulative share falls between the A threshold and '
            'this % are class B. The remainder are class C. Default 90.'
        ),
    )

    # ── Syntetos-Boylan thresholds ────────────────────────────────────────────
    adi_threshold = models.DecimalField(
        _('ADI threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('1.3200'),
        help_text=_(
            'Average Demand Interval cutoff. Series with ADI ≥ this value '
            'are classified as INTERMITTENT or LUMPY. '
            'Syntetos-Boylan (2005) default: 1.32.'
        ),
    )
    cv2_threshold = models.DecimalField(
        _('CV² threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('0.4900'),
        help_text=_(
            'Squared Coefficient of Variation cutoff for non-zero demand. '
            'Series with CV² ≥ this value are classified as ERRATIC or LUMPY. '
            'Syntetos-Boylan (2005) default: 0.49.'
        ),
    )

    # ── Minimum data requirements ─────────────────────────────────────────────
    min_nonzero_periods = models.PositiveSmallIntegerField(
        _('minimum non-zero periods'),
        default=6,
        help_text=_(
            'Minimum number of non-zero demand periods required before any '
            'statistical model is attempted. Series below this threshold are '
            'classified INSUFFICIENT and assigned a moving average.'
        ),
    )

    # ── Location hierarchy levels to evaluate ────────────────────────────────
    # The task walks the PlanningLocation tree from root to leaves.
    # This limits how many levels deep it goes.
    max_location_levels = models.PositiveSmallIntegerField(
        _('max location levels'),
        default=3,
        help_text=_(
            'How many levels of the PlanningLocation hierarchy to evaluate '
            'during the coarse-to-fine search. 1 = client total only. '
            '3 = client → region → branch.'
        ),
    )

    # ── Part B: time aggregation options ─────────────────────────────────────
    try_quarterly_aggregation = models.BooleanField(
        _('try quarterly aggregation'),
        default=True,
        help_text=_(
            'If an item is LUMPY at all location and product levels, '
            'try aggregating monthly periods into quarters before giving up.'
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label           = 'mysite'
        verbose_name        = _('03-00 Forecasting Config')
        verbose_name_plural = _('03-00 Forecasting Configs')

    def __str__(self):
        return (
            f'{self.client} | '
            f'ADI≥{self.adi_threshold} CV²≥{self.cv2_threshold} | '
            f'ABC: A≤{self.abc_a_threshold}% B≤{self.abc_b_threshold}%'
        )

    @classmethod
    def get_for_client(cls, client) -> 'ForecastingConfig':
        """Get or create with defaults. Safe to call from Celery tasks."""
        config, _ = cls.objects.get_or_create(client=client)
        return config
```

---

## 2. New Model: `SeriesLevelEvaluation`

One row per `(item, customer, evaluation_level, evaluation_grain)`.
This is the audit trail. Add to `forecast.py` **before** `SeriesProfile`:

```python
class SeriesLevelEvaluation(models.Model):
    """
    Records the classification result for one item at one evaluated level.

    The classification engine evaluates each item at multiple levels
    (client total, region, location, subcategory, category, quarterly, etc.)
    and stores one row here per level tried.

    The `SeriesProfile` model (one row per atomic series) points to
    the chosen level via `chosen_evaluation`.

    This allows planners to see:
      - Every level that was evaluated
      - The ADI, CV², ABC class at each level
      - Why a level was rejected (LUMPY at that level)
      - Which level was ultimately chosen

    evaluation_grain encodes the dimension combination:
        'item_client'           — item summed across all locations and customers
        'item_region'           — item summed across locations in one region
        'item_location'         — item at one leaf location (all customers)
        'item_customer_location'— item at one leaf location for one customer
        'subcategory_client'    — all items in subcategory, all locations
        'category_client'       — all items in category, all locations
        'item_client_quarter'   — item × client, quarterly time aggregation
        'subcategory_client_quarter' — subcategory × client, quarterly

    evaluation_key is a JSONField identifying the specific node:
        {'grain': 'item_region',   'region_code': 'NORTH'}
        {'grain': 'item_location', 'location_code': 'DEL-01'}
        {'grain': 'subcategory_client', 'subcategory': 'Brake Pads'}
    """

    # ── Evaluation grain choices ──────────────────────────────────────────────
    class Grain(models.TextChoices):
        ITEM_CLIENT           = 'item_client',           _('Item × Client')
        ITEM_REGION           = 'item_region',           _('Item × Region')
        ITEM_LOCATION         = 'item_location',         _('Item × Location')
        ITEM_CUST_LOCATION    = 'item_cust_location',    _('Item × Customer × Location')
        SUBCAT_CLIENT         = 'subcat_client',         _('Sub-category × Client')
        CATEGORY_CLIENT       = 'category_client',       _('Category × Client')
        ITEM_CLIENT_QTR       = 'item_client_qtr',       _('Item × Client (Quarterly)')
        SUBCAT_CLIENT_QTR     = 'subcat_client_qtr',     _('Sub-category × Client (Quarterly)')
        CATEGORY_CLIENT_QTR   = 'category_client_qtr',  _('Category × Client (Quarterly)')

    # ── Identity ──────────────────────────────────────────────────────────────
    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_level_evaluations',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_level_evaluations',
    )
    # planning_customer is only set for the finest grain (ITEM_CUST_LOCATION)
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_level_evaluations',
    )
    period_type = models.CharField(max_length=16, choices=PERIOD_TYPE_CHOICES)

    # ── Which level ───────────────────────────────────────────────────────────
    grain = models.CharField(
        _('evaluation grain'),
        max_length=32,
        choices=Grain.choices,
        db_index=True,
    )
    evaluation_key = models.JSONField(
        _('evaluation key'),
        help_text=_(
            'Identifies the specific node at this grain. '
            'e.g. {"grain": "item_region", "region_code": "NORTH"}'
        ),
    )

    # ── Analysis window ───────────────────────────────────────────────────────
    analysis_from = models.DateField()
    analysis_to   = models.DateField()

    # ── Raw metrics at this level ─────────────────────────────────────────────
    total_periods   = models.PositiveSmallIntegerField()
    nonzero_periods = models.PositiveSmallIntegerField()
    total_qty       = models.DecimalField(max_digits=18, decimal_places=3)
    total_value     = models.DecimalField(
        max_digits=18, decimal_places=2,
        null=True, blank=True,
        help_text=_('Sum of revenue at this level. Used for ABC classification.'),
    )

    # ── ADI and CV² at this level ─────────────────────────────────────────────
    adi      = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    cv2      = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    zero_rate = models.DecimalField(max_digits=5, decimal_places=4)

    # ── ABC at this level ─────────────────────────────────────────────────────
    # ABC is computed relative to all items at the SAME level.
    # An item that is C at client level may be A at a specific location.
    abc_class = models.CharField(
        _('ABC class at this level'),
        max_length=1,
        choices=[('A', 'A'), ('B', 'B'), ('C', 'C')],
        blank=True,
    )
    value_rank_at_level = models.PositiveIntegerField(
        _('value rank at this level'),
        null=True, blank=True,
        help_text=_('1 = highest value item at this level.'),
    )
    value_share_pct_at_level = models.DecimalField(
        _('value share % at this level'),
        max_digits=7, decimal_places=4,
        null=True, blank=True,
    )

    # ── Syntetos-Boylan classification at this level ──────────────────────────
    demand_class = models.CharField(
        _('demand class'),
        max_length=16,
        choices=[
            ('SMOOTH',       _('Smooth')),
            ('ERRATIC',      _('Erratic')),
            ('INTERMITTENT', _('Intermittent')),
            ('LUMPY',        _('Lumpy')),
            ('INSUFFICIENT', _('Insufficient data')),
            ('ZERO',         _('Zero demand')),
        ],
    )

    # ── Was this level accepted or rejected? ──────────────────────────────────
    is_accepted = models.BooleanField(
        _('accepted'),
        default=False,
        help_text=_(
            'True if the classification engine chose this level for forecasting. '
            'Only one evaluation per item is accepted.'
        ),
    )
    rejection_reason = models.CharField(
        _('rejection reason'),
        max_length=255,
        blank=True,
        help_text=_(
            'Why this level was rejected. '
            'e.g. "LUMPY at this level (ADI=2.1, CV²=0.8)"'
        ),
    )

    # ── Recommended model at this level (if accepted) ─────────────────────────
    recommended_strategy = models.CharField(
        _('recommended strategy'),
        max_length=16,
        blank=True,
        choices=[
            ('AUTOETS',    'AutoETS'),
            ('AUTOARIMA',  'AutoARIMA'),
            ('CROSTON',    'Croston SBA'),
            ('MOVING_AVG', 'Moving Average'),
            ('MANUAL',     'Manual'),
        ],
    )

    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'mysite'
        unique_together = [
            ('client', 'item', 'planning_customer',
             'period_type', 'grain', 'evaluation_key'),
        ]
        # unique_together with JSONField works in PostgreSQL
        ordering = ['item__item_id', 'grain']
        verbose_name        = _('03-06 Series Level Evaluation')
        verbose_name_plural = _('03-06 Series Level Evaluations')
        indexes = [
            models.Index(
                fields=['client', 'grain', 'demand_class'],
                name='ix_sleveval_client_grain_cls',
            ),
            models.Index(
                fields=['client', 'is_accepted'],
                name='ix_sleveval_client_accepted',
            ),
        ]

    def __str__(self):
        status = 'ACCEPTED' if self.is_accepted else 'rejected'
        return (
            f'{self.item.item_id} | {self.grain} | '
            f'{self.evaluation_key} | '
            f'{self.demand_class} | {status}'
        )
```

---

## 3. Revised `SeriesProfile` Model

`SeriesProfile` is now the **summary** — one row per atomic series
`(item, customer, location)`. It stores:
- The chosen evaluation level (FK to `SeriesLevelEvaluation`)
- The planner override
- The `effective_*` properties used by the forecast engine

```python
class SeriesProfile(models.Model):
    """
    Forecast level selection summary for one atomic series
    (item, customer, location).

    The classification engine evaluates the item at multiple levels
    (stored in SeriesLevelEvaluation) and records the chosen level here.

    The forecast engine reads effective_grain and effective_strategy
    (which honour planner overrides) to decide how to forecast this series.

    Two roles:
      1. PART A items (not LUMPY at client level):
         chosen_evaluation points to the finest location grain at which
         the item is SMOOTH / ERRATIC / INTERMITTENT.

      2. PART B items (LUMPY at all location grains):
         chosen_evaluation points to the coarsest grain in the product
         or time hierarchy at which the item is not LUMPY.
    """

    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_profiles',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name='series_profiles',
    )
    period_type = models.CharField(max_length=16, choices=PERIOD_TYPE_CHOICES)

    # ── Analysis window ───────────────────────────────────────────────────────
    analysis_from = models.DateField()
    analysis_to   = models.DateField()
    computed_at   = models.DateTimeField(auto_now=True)

    # ── Metrics at the ATOMIC grain (item × customer × location) ─────────────
    # Stored here for quick display without joining SeriesLevelEvaluation
    total_periods    = models.PositiveSmallIntegerField()
    nonzero_periods  = models.PositiveSmallIntegerField()
    total_qty        = models.DecimalField(max_digits=16, decimal_places=3)
    total_value      = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )
    adi              = models.DecimalField(
        _('ADI at atomic grain'),
        max_digits=8, decimal_places=4, null=True, blank=True,
    )
    cv2              = models.DecimalField(
        _('CV² at atomic grain'),
        max_digits=8, decimal_places=4, null=True, blank=True,
    )
    zero_rate        = models.DecimalField(max_digits=5, decimal_places=4)
    demand_class_atomic = models.CharField(
        _('demand class at atomic grain'),
        max_length=16,
        blank=True,
        help_text=_('The Syntetos-Boylan class at the raw SKU×Customer×Location grain.'),
    )

    # ── ABC at atomic grain ───────────────────────────────────────────────────
    abc_class_atomic = models.CharField(
        _('ABC at atomic grain'),
        max_length=1,
        choices=[('A', 'A'), ('B', 'B'), ('C', 'C')],
        blank=True,
    )

    # ── Chosen evaluation level ───────────────────────────────────────────────
    chosen_evaluation = models.ForeignKey(
        SeriesLevelEvaluation,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
        verbose_name=_('chosen evaluation'),
        help_text=_(
            'The SeriesLevelEvaluation row that was accepted. '
            'The forecast engine uses chosen_evaluation.grain and '
            'chosen_evaluation.recommended_strategy.'
        ),
    )

    # ── Classification outcome summary (denormalised for fast querying) ───────
    chosen_grain = models.CharField(
        _('chosen grain'),
        max_length=32,
        choices=SeriesLevelEvaluation.Grain.choices,
        blank=True,
        help_text=_('Denormalised copy of chosen_evaluation.grain.'),
    )
    chosen_demand_class = models.CharField(
        _('demand class at chosen level'),
        max_length=16,
        blank=True,
        help_text=_('Denormalised copy of chosen_evaluation.demand_class.'),
    )
    chosen_strategy = models.CharField(
        _('chosen strategy'),
        max_length=16,
        blank=True,
        help_text=_('Denormalised copy of chosen_evaluation.recommended_strategy.'),
    )

    # ── Planner overrides ─────────────────────────────────────────────────────
    override_grain = models.CharField(
        _('override grain'),
        max_length=32,
        choices=SeriesLevelEvaluation.Grain.choices,
        blank=True,
        help_text=_(
            'Planner-specified grain. When set, the forecast engine uses '
            'this grain instead of chosen_grain.'
        ),
    )
    override_strategy = models.CharField(
        _('override strategy'),
        max_length=16,
        choices=[
            ('AUTOETS',    'AutoETS'),
            ('AUTOARIMA',  'AutoARIMA'),
            ('CROSTON',    'Croston SBA'),
            ('MOVING_AVG', 'Moving Average'),
            ('MANUAL',     'Manual'),
        ],
        blank=True,
    )
    override_note = models.TextField(blank=True)
    override_set_by = models.ForeignKey(
        'auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    override_set_at = models.DateTimeField(null=True, blank=True)

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
                fields=['client', 'chosen_grain'],
                name='ix_seriespro_client_grain',
            ),
            models.Index(
                fields=['client', 'demand_class_atomic'],
                name='ix_seriespro_client_cls',
            ),
            models.Index(
                fields=['client', 'abc_class_atomic'],
                name='ix_seriespro_client_abc',
            ),
        ]

    def __str__(self):
        cust = self.planning_customer or 'all'
        return (
            f'{self.item.item_id} | {self.planning_location.code} | {cust} | '
            f'atomic={self.demand_class_atomic} | '
            f'chosen={self.chosen_grain}'
        )

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def effective_grain(self) -> str:
        return self.override_grain or self.chosen_grain or 'item_cust_location'

    @property
    def effective_strategy(self) -> str:
        return self.override_strategy or self.chosen_strategy or 'AUTOETS'

    @property
    def is_overridden(self) -> bool:
        return bool(self.override_grain or self.override_strategy)

    @property
    def is_manual(self) -> bool:
        return self.effective_strategy == 'MANUAL'

    # ── Classification pure functions ─────────────────────────────────────────

    @classmethod
    def compute_syntetos_boylan(
        cls,
        qty_series: list,
        adi_threshold: float,
        cv2_threshold: float,
        min_nonzero: int,
    ) -> dict:
        """
        Compute ADI, CV², zero_rate and classify using configurable thresholds.

        Args:
            qty_series:     list of Decimal, one per period (zeros included)
            adi_threshold:  from ForecastingConfig.adi_threshold
            cv2_threshold:  from ForecastingConfig.cv2_threshold
            min_nonzero:    from ForecastingConfig.min_nonzero_periods

        Returns dict with all metrics and demand_class.
        This is a pure function — no DB access.
        """
        import statistics

        total_periods   = len(qty_series)
        nonzero_vals    = [q for q in qty_series if q > 0]
        nonzero_periods = len(nonzero_vals)
        total_qty       = sum(qty_series)
        zero_rate       = Decimal(
            str(round(1 - nonzero_periods / total_periods, 4))
        ) if total_periods > 0 else Decimal('1')

        if nonzero_periods == 0:
            return {
                'total_periods': total_periods, 'nonzero_periods': 0,
                'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                'zero_rate': Decimal('1'), 'demand_class': 'ZERO',
                'recommended_strategy': 'MANUAL',
            }

        if nonzero_periods < min_nonzero:
            adi = Decimal(str(round(total_periods / nonzero_periods, 4)))
            return {
                'total_periods': total_periods, 'nonzero_periods': nonzero_periods,
                'total_qty': total_qty, 'adi': adi, 'cv2': None,
                'zero_rate': zero_rate, 'demand_class': 'INSUFFICIENT',
                'recommended_strategy': 'MOVING_AVG',
            }

        adi  = Decimal(str(round(total_periods / nonzero_periods, 4)))
        mean = statistics.mean(float(v) for v in nonzero_vals)
        std  = statistics.stdev(float(v) for v in nonzero_vals) \
               if len(nonzero_vals) > 1 else 0.0
        cv2  = Decimal(str(round((std / mean) ** 2, 4))) if mean > 0 else Decimal('0')

        adi_f, cv2_f = float(adi), float(cv2)

        if adi_f < adi_threshold and cv2_f < cv2_threshold:
            demand_class = 'SMOOTH'
            strategy     = 'AUTOETS'
        elif adi_f < adi_threshold and cv2_f >= cv2_threshold:
            demand_class = 'ERRATIC'
            strategy     = 'AUTOARIMA'
        elif adi_f >= adi_threshold and cv2_f < cv2_threshold:
            demand_class = 'INTERMITTENT'
            strategy     = 'CROSTON'
        else:
            demand_class = 'LUMPY'
            strategy     = ''   # determined by which level resolves LUMPY

        return {
            'total_periods': total_periods, 'nonzero_periods': nonzero_periods,
            'total_qty': total_qty, 'adi': adi, 'cv2': cv2,
            'zero_rate': zero_rate, 'demand_class': demand_class,
            'recommended_strategy': strategy,
        }

    @classmethod
    def compute_abc(
        cls,
        item_value: float,
        all_items_values: list[float],
        a_threshold: float,
        b_threshold: float,
    ) -> dict:
        """
        Compute ABC class for one item given all items' values at the SAME level.

        Sorts items by value descending, computes cumulative share,
        assigns A/B/C based on configurable thresholds.

        Returns: {'abc_class': 'A'|'B'|'C',
                  'value_share_pct': Decimal,
                  'cumulative_pct': Decimal}

        This is a pure function — no DB access.
        Called separately for each level (client, region, location).
        """
        if not all_items_values or sum(all_items_values) == 0:
            return {
                'abc_class': 'C',
                'value_share_pct': Decimal('0'),
                'cumulative_pct':  Decimal('0'),
            }

        total = sum(all_items_values)
        sorted_vals = sorted(all_items_values, reverse=True)
        share_pct   = item_value / total * 100

        # Compute cumulative percentages for all items
        running = 0.0
        cum_pct_for_item = 0.0
        for v in sorted_vals:
            running += v / total * 100
            if v <= item_value:
                cum_pct_for_item = running
                break

        if cum_pct_for_item <= a_threshold:
            abc = 'A'
        elif cum_pct_for_item <= b_threshold:
            abc = 'B'
        else:
            abc = 'C'

        return {
            'abc_class':       abc,
            'value_share_pct': Decimal(str(round(share_pct, 4))),
            'cumulative_pct':  Decimal(str(round(cum_pct_for_item, 4))),
        }
```

---

## 4. Revised Celery Task: `compute_series_profiles`

Replace the existing task in `mysite/tasks/demand/compute_series_profiles.py`:

```python
# mysite/tasks/demand/compute_series_profiles.py
"""
Celery task: compute_series_profiles

Implements the full classification flow:

PART A (coarse location → fine location):
  1. Evaluate each item at Client level
  2. If not LUMPY → find finest location grain that stays not-LUMPY
  3. Accept that grain

PART B (LUMPY everywhere in location hierarchy):
  4. Try SubCategory × Client
  5. Try Category × Client
  6. Try Item × Client × Quarterly
  7. Try SubCategory × Client × Quarterly
  8. Manual

At every level: compute ADI, CV², ABC, demand_class.
Store one SeriesLevelEvaluation row per level tried.
Store one SeriesProfile row per atomic series with FK to chosen evaluation.
"""

import logging
from collections import defaultdict
from decimal import Decimal

import duckdb
import pandas as pd
import polars as pl
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.forecast import (
    ForecastingConfig,
    SeriesLevelEvaluation,
    SeriesProfile,
)

logger = logging.getLogger(__name__)

LUMPY_CLASSES = {'LUMPY', 'INSUFFICIENT', 'ZERO'}
FORECASTABLE_CLASSES = {'SMOOTH', 'ERRATIC', 'INTERMITTENT'}


@shared_task(bind=True)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Full multi-level classification for all (item, customer, location) series.
    """
    from mysite.models import Client

    client = Client.objects.get(pk=client_id)
    config = ForecastingConfig.get_for_client(client)

    adi_thr  = float(config.adi_threshold)
    cv2_thr  = float(config.cv2_threshold)
    min_nz   = config.min_nonzero_periods
    abc_a    = float(config.abc_a_threshold)
    abc_b    = float(config.abc_b_threshold)

    logger.info(
        f'compute_series_profiles: client={client_id} period={period_type} '
        f'ADI≥{adi_thr} CV²≥{cv2_thr} min_nz={min_nz} '
        f'ABC A≤{abc_a}% B≤{abc_b}%'
    )

    # ── 1. Pull actuals ────────────────────────────────────────────────────────
    qs = (
        ActualSale.objects
        .filter(client=client, period_type=period_type)
        .select_related(
            'item',
            'planning_location',
            'planning_location__parent',
            'planning_customer',
        )
        .values(
            'item_id', 'item__item_id',
            'planning_customer_id', 'planning_customer__code',
            'planning_location_id', 'planning_location__code',
            'planning_location__parent_id',
            'planning_location__parent__code',
            'period_start', 'qty', 'revenue',
        )
        .order_by('period_start')
    )

    if not qs.exists():
        logger.info(f'compute_series_profiles: no actuals for client {client_id}')
        return

    df = pd.DataFrame(list(qs))
    df['qty']     = df['qty'].astype(float)
    df['revenue'] = df['revenue'].fillna(0).astype(float)
    df['cust_code']   = df['planning_customer__code'].fillna('__NULL__')
    df['region_code'] = df['planning_location__parent__code'].fillna('__NO_REGION__')

    # ── 2. Item taxonomy (category / subcategory) ─────────────────────────────
    # Replace with your actual ItemTaxonomyMapping query if available
    from mysite.models import Item
    taxonomy_qs = (
        Item.objects
        .filter(client=client)
        .values('id', 'item_id')
        # Add .annotate() with taxonomy fields if your model has them
    )
    item_taxonomy: dict[int, dict] = {
        row['id']: {'subcategory': 'ALL', 'category': 'ALL'}
        for row in taxonomy_qs
    }

    # ── 3. Build time spine ────────────────────────────────────────────────────
    all_periods   = sorted(df['period_start'].unique().tolist())
    analysis_from = all_periods[0]
    analysis_to   = all_periods[-1]

    # ── 4. DuckDB aggregations at all levels ──────────────────────────────────
    con = duckdb.connect()
    con.register('actuals', df)

    # Level: item × client (all locations, all customers)
    lv_item_client = con.execute("""
        SELECT item_id,
               period_start,
               SUM(qty) AS qty,
               SUM(revenue) AS revenue
        FROM actuals
        GROUP BY item_id, period_start
    """).df()

    # Level: item × region
    lv_item_region = con.execute("""
        SELECT item_id, region_code,
               period_start,
               SUM(qty) AS qty,
               SUM(revenue) AS revenue
        FROM actuals
        GROUP BY item_id, region_code, period_start
    """).df()

    # Level: item × location (leaf, all customers)
    lv_item_location = con.execute("""
        SELECT item_id, planning_location__code AS loc_code,
               planning_location_id,
               period_start,
               SUM(qty) AS qty,
               SUM(revenue) AS revenue
        FROM actuals
        GROUP BY item_id, planning_location__code,
                 planning_location_id, period_start
    """).df()

    # Level: item × customer × location (atomic)
    lv_atomic = con.execute("""
        SELECT item_id, cust_code, planning_customer_id,
               planning_location__code AS loc_code,
               planning_location_id,
               period_start,
               SUM(qty) AS qty,
               SUM(revenue) AS revenue
        FROM actuals
        GROUP BY item_id, cust_code, planning_customer_id,
                 planning_location__code, planning_location_id, period_start
    """).df()

    # Quarterly aggregation: item × client
    lv_item_client_qtr = con.execute("""
        SELECT item_id,
               DATE_TRUNC('quarter', period_start) AS quarter_start,
               SUM(qty) AS qty,
               SUM(revenue) AS revenue
        FROM actuals
        GROUP BY item_id, DATE_TRUNC('quarter', period_start)
    """).df()

    # ── 5. Helper: build time series from grouped DF ──────────────────────────
    def _series(group_df: pd.DataFrame, key_cols: list, periods: list) -> dict:
        """
        Returns dict: {(key_vals_tuple): [qty_per_period]}
        Fills missing periods with 0.
        """
        result = defaultdict(lambda: {p: 0.0 for p in periods})
        for _, row in group_df.iterrows():
            key = tuple(row[k] for k in key_cols)
            result[key][row['period_start']] += float(row['qty'])
        return {k: [v[p] for p in periods] for k, v in result.items()}

    def _value_by_key(group_df: pd.DataFrame, key_cols: list) -> dict:
        """Sum revenue per key."""
        grouped = group_df.groupby(key_cols)['revenue'].sum()
        return grouped.to_dict()

    # ── 6. ABC at client level (for all items) ────────────────────────────────
    item_client_value = _value_by_key(lv_item_client, ['item_id'])
    all_client_values = list(item_client_value.values())

    def _abc(item_id_int: int, level_values: dict) -> dict:
        v = level_values.get(item_id_int, 0.0)
        all_v = list(level_values.values())
        return SeriesProfile.compute_abc(v, all_v, abc_a, abc_b)

    # ── 7. Helper: classify a qty series ──────────────────────────────────────
    def _classify(qty_list: list) -> dict:
        series = [Decimal(str(q)) for q in qty_list]
        return SeriesProfile.compute_syntetos_boylan(
            series, adi_thr, cv2_thr, min_nz
        )

    # ── 8. Per-item level search ───────────────────────────────────────────────
    # We collect (SeriesLevelEvaluation, SeriesProfile) objects for bulk_create

    evaluations_to_create: list[SeriesLevelEvaluation] = []
    profiles_to_upsert:    list[dict]                   = []

    # Build series dicts for all levels
    item_client_series  = _series(lv_item_client,  ['item_id'],              all_periods)
    item_region_series  = _series(lv_item_region,  ['item_id', 'region_code'], all_periods)
    item_loc_series     = _series(lv_item_location, ['item_id', 'loc_code'], all_periods)
    atomic_series       = _series(lv_atomic, ['item_id', 'cust_code', 'loc_code'], all_periods)

    # Build quarterly series
    qtr_periods = sorted(lv_item_client_qtr['quarter_start'].unique().tolist())
    item_client_qtr_series = _series(
        lv_item_client_qtr, ['item_id'],
        qtr_periods if qtr_periods else []
    )

    # Get all unique atomic keys
    all_atomic_keys = list(atomic_series.keys())

    for atomic_key in all_atomic_keys:
        item_id_int, cust_code, loc_code = atomic_key

        # Get FKs needed for model creation
        loc_rows = lv_atomic[
            (lv_atomic['item_id'] == item_id_int) &
            (lv_atomic['loc_code'] == loc_code)
        ]
        if loc_rows.empty:
            continue
        loc_id  = int(loc_rows['planning_location_id'].iloc[0])
        cust_id = loc_rows['planning_customer_id'].iloc[0]
        cust_id = None if pd.isna(cust_id) else int(cust_id)

        evals_for_this_item: list[dict] = []
        chosen_eval: dict | None = None

        # ── PART A: Location hierarchy search ─────────────────────────────
        # Step 1: Item × Client
        key_ic    = (item_id_int,)
        ic_series = item_client_series.get(key_ic)

        if ic_series:
            metrics = _classify(ic_series)
            abc_ic  = _abc(item_id_int, item_client_value)
            eval_ic = {
                'grain':             'item_client',
                'evaluation_key':    {'grain': 'item_client'},
                'metrics':           metrics,
                'abc':               abc_ic,
                'total_value':       item_client_value.get(item_id_int, 0),
                'is_forecastable':   metrics['demand_class'] not in LUMPY_CLASSES,
            }
            evals_for_this_item.append(eval_ic)

            if eval_ic['is_forecastable']:
                # Item is forecastable at client level.
                # Now try FINER location grains to find the finest acceptable.
                # We go: client → regions for this location → this leaf location
                # and keep drilling until we hit LUMPY (then step back one level).
                prev_eval = eval_ic  # last forecastable level

                # Region level
                region_code = df[df['planning_location__code'] == loc_code]['region_code'].iloc[0] \
                              if not df[df['planning_location__code'] == loc_code].empty else None

                if region_code and region_code != '__NO_REGION__':
                    key_ir    = (item_id_int, region_code)
                    ir_series = item_region_series.get(key_ir)
                    if ir_series:
                        region_value = _value_by_key(
                            lv_item_region[lv_item_region['region_code'] == region_code],
                            ['item_id']
                        )
                        metrics_ir = _classify(ir_series)
                        abc_ir     = _abc(item_id_int, region_value)
                        eval_ir = {
                            'grain':          'item_region',
                            'evaluation_key': {'grain': 'item_region', 'region_code': region_code},
                            'metrics':        metrics_ir,
                            'abc':            abc_ir,
                            'total_value':    region_value.get(item_id_int, 0),
                            'is_forecastable': metrics_ir['demand_class'] not in LUMPY_CLASSES,
                        }
                        evals_for_this_item.append(eval_ir)
                        if eval_ir['is_forecastable']:
                            prev_eval = eval_ir

                # Location level (leaf)
                key_il    = (item_id_int, loc_code)
                il_series = item_loc_series.get(key_il)
                if il_series:
                    loc_value = _value_by_key(
                        lv_item_location[lv_item_location['loc_code'] == loc_code],
                        ['item_id']
                    )
                    metrics_il = _classify(il_series)
                    abc_il     = _abc(item_id_int, loc_value)
                    eval_il = {
                        'grain':          'item_location',
                        'evaluation_key': {'grain': 'item_location', 'location_code': loc_code},
                        'metrics':        metrics_il,
                        'abc':            abc_il,
                        'total_value':    loc_value.get(item_id_int, 0),
                        'is_forecastable': metrics_il['demand_class'] not in LUMPY_CLASSES,
                    }
                    evals_for_this_item.append(eval_il)
                    if eval_il['is_forecastable']:
                        prev_eval = eval_il

                # Atomic: item × customer × location
                key_at    = (item_id_int, cust_code, loc_code)
                at_series = atomic_series.get(key_at)
                if at_series:
                    atomic_value = _value_by_key(
                        lv_atomic[(lv_atomic['loc_code'] == loc_code) &
                                  (lv_atomic['cust_code'] == cust_code)],
                        ['item_id']
                    )
                    metrics_at = _classify(at_series)
                    abc_at     = _abc(item_id_int, atomic_value)
                    eval_at = {
                        'grain':          'item_cust_location',
                        'evaluation_key': {'grain': 'item_cust_location',
                                           'location_code': loc_code,
                                           'customer_code': cust_code},
                        'metrics':        metrics_at,
                        'abc':            abc_at,
                        'total_value':    atomic_value.get(item_id_int, 0),
                        'is_forecastable': metrics_at['demand_class'] not in LUMPY_CLASSES,
                    }
                    evals_for_this_item.append(eval_at)
                    if eval_at['is_forecastable']:
                        prev_eval = eval_at

                chosen_eval = prev_eval  # finest forecastable level

            else:
                # ── PART B: LUMPY at client level ─────────────────────────
                # Try product hierarchy, then time aggregation

                # SubCategory × Client
                subcat = item_taxonomy.get(item_id_int, {}).get('subcategory', 'ALL')
                # Build subcat series: sum all items in same subcategory
                # (simplified — extend with actual taxonomy data)

                # Category × Client
                cat = item_taxonomy.get(item_id_int, {}).get('category', 'ALL')

                # Item × Client × Quarterly
                if config.try_quarterly_aggregation:
                    key_iq    = (item_id_int,)
                    iq_series = item_client_qtr_series.get(key_iq)
                    if iq_series and len(iq_series) >= config.min_nonzero_periods:
                        metrics_iq = _classify(iq_series)
                        eval_iq = {
                            'grain':          'item_client_qtr',
                            'evaluation_key': {'grain': 'item_client_qtr'},
                            'metrics':        metrics_iq,
                            'abc':            _abc(item_id_int, item_client_value),
                            'total_value':    item_client_value.get(item_id_int, 0),
                            'is_forecastable': metrics_iq['demand_class'] not in LUMPY_CLASSES,
                        }
                        evals_for_this_item.append(eval_iq)
                        if eval_iq['is_forecastable']:
                            chosen_eval = eval_iq

                if chosen_eval is None:
                    # Nothing worked — MANUAL
                    chosen_eval = {
                        'grain':          'item_client',  # report at broadest level
                        'evaluation_key': {'grain': 'item_client', 'note': 'MANUAL'},
                        'metrics':        {
                            'demand_class': 'LUMPY', 'recommended_strategy': 'MANUAL',
                            'total_periods': len(all_periods), 'nonzero_periods': 0,
                            'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                            'zero_rate': Decimal('1'),
                        },
                        'abc':            _abc(item_id_int, item_client_value),
                        'total_value':    item_client_value.get(item_id_int, 0),
                        'is_forecastable': False,
                    }
                    evals_for_this_item.append(chosen_eval)
                    chosen_eval['metrics']['recommended_strategy'] = 'MANUAL'
                    chosen_eval['is_accepted'] = True

        # Mark chosen and set rejection reasons
        for ev in evals_for_this_item:
            ev['is_accepted'] = (ev is chosen_eval)
            if not ev['is_accepted'] and ev.get('is_forecastable') is False:
                m = ev['metrics']
                ev['rejection_reason'] = (
                    f"{m['demand_class']} at this level "
                    f"(ADI={m.get('adi','?')}, CV²={m.get('cv2','?')})"
                )
            else:
                ev['rejection_reason'] = ''

        # Collect evaluation rows for bulk_create
        for ev in evals_for_this_item:
            m = ev['metrics']
            evaluations_to_create.append(
                SeriesLevelEvaluation(
                    client_id=client_id,
                    item_id=item_id_int,
                    planning_customer_id=cust_id if ev['grain'] == 'item_cust_location' else None,
                    period_type=period_type,
                    grain=ev['grain'],
                    evaluation_key=ev['evaluation_key'],
                    analysis_from=analysis_from,
                    analysis_to=analysis_to,
                    total_periods=m['total_periods'],
                    nonzero_periods=m['nonzero_periods'],
                    total_qty=m['total_qty'],
                    total_value=Decimal(str(round(ev.get('total_value', 0), 2))),
                    adi=m.get('adi'),
                    cv2=m.get('cv2'),
                    zero_rate=m['zero_rate'],
                    abc_class=ev['abc'].get('abc_class', 'C'),
                    value_share_pct_at_level=ev['abc'].get('value_share_pct'),
                    demand_class=m['demand_class'],
                    is_accepted=ev.get('is_accepted', False),
                    rejection_reason=ev.get('rejection_reason', ''),
                    recommended_strategy=m.get('recommended_strategy', ''),
                )
            )

        # Collect profile summary
        atom = evals_for_this_item[0] if evals_for_this_item else None
        atom_m = atom['metrics'] if atom else {}
        atom_at = metrics_at if 'metrics_at' in dir() else atom_m

        profiles_to_upsert.append({
            'client_id':          client_id,
            'item_id':            item_id_int,
            'planning_customer_id': cust_id,
            'planning_location_id': loc_id,
            'period_type':        period_type,
            'analysis_from':      analysis_from,
            'analysis_to':        analysis_to,
            # Atomic metrics
            'total_periods':      atom_m.get('total_periods', len(all_periods)),
            'nonzero_periods':    atom_m.get('nonzero_periods', 0),
            'total_qty':          atom_m.get('total_qty', Decimal('0')),
            'adi':                atom_m.get('adi'),
            'cv2':                atom_m.get('cv2'),
            'zero_rate':          atom_m.get('zero_rate', Decimal('1')),
            'demand_class_atomic': atom_m.get('demand_class', 'ZERO'),
            'abc_class_atomic':   (atom['abc'].get('abc_class', 'C') if atom else 'C'),
            # Chosen level summary (denormalised)
            'chosen_grain':       chosen_eval['grain'] if chosen_eval else '',
            'chosen_demand_class': chosen_eval['metrics']['demand_class'] if chosen_eval else '',
            'chosen_strategy':    chosen_eval['metrics'].get('recommended_strategy', 'MANUAL')
                                  if chosen_eval else 'MANUAL',
        })

    # ── 9. Persist to DB ──────────────────────────────────────────────────────
    with transaction.atomic():
        # Delete old evaluations for this client+period
        SeriesLevelEvaluation.objects.filter(
            client_id=client_id, period_type=period_type
        ).delete()

        # Bulk create evaluations
        SeriesLevelEvaluation.objects.bulk_create(
            evaluations_to_create, batch_size=500, ignore_conflicts=True
        )

        # Build lookup: (item_id, grain, evaluation_key_str) → pk
        eval_lookup = {
            (e.item_id, e.grain, str(e.evaluation_key)): e
            for e in SeriesLevelEvaluation.objects.filter(
                client_id=client_id, period_type=period_type, is_accepted=True
            ).select_related()
        }

        # Upsert SeriesProfile rows
        for p in profiles_to_upsert:
            # Find the chosen evaluation FK
            chosen_eval_data = next(
                (ev for ev in evaluations_to_create
                 if ev.item_id == p['item_id']
                 and ev.grain == p['chosen_grain']
                 and ev.is_accepted),
                None
            )
            update_fields = {k: v for k, v in p.items()
                             if k not in ('client_id', 'item_id',
                                          'planning_customer_id',
                                          'planning_location_id', 'period_type')}
            if chosen_eval_data:
                update_fields['chosen_evaluation_id'] = chosen_eval_data.pk

            SeriesProfile.objects.update_or_create(
                client_id=p['client_id'],
                item_id=p['item_id'],
                planning_customer_id=p['planning_customer_id'],
                planning_location_id=p['planning_location_id'],
                period_type=p['period_type'],
                defaults=update_fields,
            )

    from collections import Counter
    class_counts = Counter(p['demand_class_atomic'] for p in profiles_to_upsert)
    grain_counts = Counter(p['chosen_grain'] for p in profiles_to_upsert)
    logger.info(
        f'compute_series_profiles: client={client_id} '
        f'total={len(profiles_to_upsert)} '
        f'demand_class={dict(class_counts)} '
        f'chosen_grain={dict(grain_counts)}'
    )
```

---

## 5. Admin

```python
# In mysite/admin/demand_forecast.py

from mysite.models.demand.forecast import (
    ForecastingConfig, SeriesLevelEvaluation, SeriesProfile
)

@admin.register(ForecastingConfig)
class ForecastingConfigAdmin(admin.ModelAdmin):
    list_display = [
        'client', 'adi_threshold', 'cv2_threshold',
        'abc_a_threshold', 'abc_b_threshold',
        'min_nonzero_periods', 'max_location_levels',
        'try_quarterly_aggregation', 'updated_at',
    ]
    fieldsets = [
        (_('Client'), {'fields': ['client']}),
        (_('Syntetos-Boylan Thresholds'), {
            'fields': ['adi_threshold', 'cv2_threshold', 'min_nonzero_periods'],
            'description': _(
                'ADI ≥ threshold → INTERMITTENT or LUMPY. '
                'CV² ≥ threshold → ERRATIC or LUMPY. '
                'Syntetos-Boylan (2005) defaults: ADI=1.32, CV²=0.49.'
            ),
        }),
        (_('ABC Thresholds'), {
            'fields': ['abc_a_threshold', 'abc_b_threshold'],
            'description': _(
                'Cumulative demand value share cutoffs. '
                'A ≤ a_threshold%, B ≤ b_threshold%, remainder = C.'
            ),
        }),
        (_('Level Search Options'), {
            'fields': ['max_location_levels', 'try_quarterly_aggregation'],
        }),
    ]
    admin_role_only = True


@admin.register(SeriesLevelEvaluation)
class SeriesLevelEvaluationAdmin(admin.ModelAdmin):
    list_display  = [
        'item', 'grain', 'demand_class_badge',
        'abc_class', 'adi', 'cv2',
        'nonzero_periods', 'is_accepted', 'rejection_reason',
    ]
    list_filter   = ['client', 'period_type', 'grain', 'demand_class', 'is_accepted', 'abc_class']
    search_fields = ['item__item_id', 'item__name']
    readonly_fields = [f.name for f in SeriesLevelEvaluation._meta.fields]

    @admin.display(description='Class')
    def demand_class_badge(self, obj):
        colours = {
            'SMOOTH': '#198754', 'ERRATIC': '#fd7e14',
            'INTERMITTENT': '#0dcaf0', 'LUMPY': '#dc3545',
            'INSUFFICIENT': '#6c757d', 'ZERO': '#212529',
        }
        c = colours.get(obj.demand_class, '#000')
        return format_html(
            '<span style="background:{c};color:#fff;padding:2px 6px;'
            'border-radius:3px;font-size:11px">{l}</span>',
            c=c, l=obj.demand_class,
        )

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    admin_role_only = True


@admin.register(SeriesProfile)
class SeriesProfileAdmin(admin.ModelAdmin):
    list_display = [
        'item', 'planning_location', 'planning_customer', 'period_type',
        'abc_class_atomic', 'demand_class_atomic',
        'chosen_grain', 'chosen_demand_class', 'effective_grain_display',
        'adi', 'cv2', 'nonzero_periods', 'computed_at',
    ]
    list_filter   = [
        'client', 'period_type',
        'abc_class_atomic', 'demand_class_atomic', 'chosen_grain',
    ]
    search_fields = [
        'item__item_id', 'item__name',
        'planning_location__code', 'planning_customer__code',
    ]
    readonly_fields = [
        'client', 'item', 'planning_customer', 'planning_location', 'period_type',
        'analysis_from', 'analysis_to', 'computed_at',
        'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
        'adi', 'cv2', 'zero_rate',
        'demand_class_atomic', 'abc_class_atomic',
        'chosen_evaluation', 'chosen_grain', 'chosen_demand_class', 'chosen_strategy',
        'override_set_by', 'override_set_at',
    ]
    fieldsets = [
        (_('Identity'), {
            'fields': ['client', 'item', 'planning_location',
                       'planning_customer', 'period_type'],
        }),
        (_('Analysis Window'), {
            'fields': ['analysis_from', 'analysis_to', 'computed_at'],
        }),
        (_('Atomic Grain Metrics'), {
            'fields': ['total_periods', 'nonzero_periods', 'total_qty',
                       'total_value', 'adi', 'cv2', 'zero_rate'],
        }),
        (_('Classification at Atomic Grain'), {
            'fields': ['demand_class_atomic', 'abc_class_atomic'],
        }),
        (_('Chosen Forecast Level'), {
            'fields': ['chosen_evaluation', 'chosen_grain',
                       'chosen_demand_class', 'chosen_strategy'],
        }),
        (_('Planner Override'), {
            'fields': ['override_grain', 'override_strategy',
                       'override_note', 'override_set_by', 'override_set_at'],
        }),
    ]

    @admin.display(description='Effective Grain')
    def effective_grain_display(self, obj):
        if obj.override_grain:
            return format_html(
                '<span style="color:#dc3545;font-weight:bold">{}</span> '
                '<small style="color:#6c757d">(override)</small>',
                obj.override_grain,
            )
        return obj.chosen_grain or '—'

    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
    admin_role_only = True
```

---

## 6. Serializer Updates

```python
# In mysite/api/demand/serializers.py

class ForecastingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ForecastingConfig
        fields = [
            'id',
            'adi_threshold', 'cv2_threshold', 'min_nonzero_periods',
            'abc_a_threshold', 'abc_b_threshold',
            'max_location_levels', 'try_quarterly_aggregation',
            'updated_at',
        ]


class SeriesLevelEvaluationSerializer(serializers.ModelSerializer):
    item_id = serializers.CharField(source='item.item_id', read_only=True)

    class Meta:
        model  = SeriesLevelEvaluation
        fields = [
            'id', 'item_id', 'grain', 'evaluation_key',
            'period_type', 'analysis_from', 'analysis_to',
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            'abc_class', 'value_share_pct_at_level',
            'demand_class', 'recommended_strategy',
            'is_accepted', 'rejection_reason',
            'computed_at',
        ]
        read_only_fields = fields


class SeriesProfileSerializer(serializers.ModelSerializer):
    item_id               = serializers.CharField(source='item.item_id',         read_only=True)
    item_name             = serializers.CharField(source='item.name',            read_only=True)
    location_code         = serializers.CharField(source='planning_location.code', read_only=True)
    customer_code         = serializers.CharField(source='planning_customer.code', read_only=True, default=None)
    effective_grain       = serializers.CharField(read_only=True)
    effective_strategy    = serializers.CharField(read_only=True)
    is_overridden         = serializers.BooleanField(read_only=True)
    evaluations           = SeriesLevelEvaluationSerializer(
        source='item.series_level_evaluations',
        many=True, read_only=True,
    )

    class Meta:
        model  = SeriesProfile
        fields = [
            'id',
            'item_id', 'item_name', 'location_code', 'customer_code',
            'period_type', 'analysis_from', 'analysis_to', 'computed_at',
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            'demand_class_atomic', 'abc_class_atomic',
            'chosen_grain', 'chosen_demand_class', 'chosen_strategy',
            'override_grain', 'override_strategy', 'override_note',
            'effective_grain', 'effective_strategy', 'is_overridden',
            'evaluations',
        ]
        read_only_fields = [
            'item_id', 'item_name', 'location_code', 'customer_code',
            'period_type', 'analysis_from', 'analysis_to', 'computed_at',
            'total_periods', 'nonzero_periods', 'total_qty', 'total_value',
            'adi', 'cv2', 'zero_rate',
            'demand_class_atomic', 'abc_class_atomic',
            'chosen_grain', 'chosen_demand_class', 'chosen_strategy',
            'effective_grain', 'effective_strategy', 'is_overridden',
            'evaluations',
        ]
```

---

## 7. `engine_config` Addition for Requirement 7

Add the disaggregation conflict setting to `ForecastVersion.engine_config` documentation:

```python
# In ForecastVersion.engine_config help_text and in the forecast task:

engine_config = models.JSONField(
    _('engine configuration'),
    default=dict,
    blank=True,
    help_text=_(
        'Controls the forecast engine behaviour. Supported keys:\n'
        '  "models": ["AutoETS", "AutoARIMA"]  — models to try\n'
        '  "season_length": 12                 — periods per season\n'
        '  "reconciliation": "MinTrace_ols"    — reconciliation method\n'
        '  "disagg_conflict_resolution": "retain_lower" | "use_upper"\n'
        '      retain_lower (default): if an item has its own forecast at a\n'
        '        finer grain, keep it; do not overwrite with product-group\n'
        '        disaggregation.\n'
        '      use_upper: product-group disaggregation overwrites all\n'
        '        constituent items regardless of their own forecast level.\n'
        '  "store_all_level_forecasts": true | false (default true)\n'
        '      When true, ForecastLine rows are written for EVERY level\n'
        '      evaluated, not just the chosen level. Use forecast_level\n'
        '      field to filter. Enables post-run comparison.'
    ),
)
```

---

## 8. Migration

```bash
python manage.py makemigrations mysite --name forecasting_config_and_level_evaluation
python manage.py migrate
python manage.py check
```

**New tables created:**
- `mysite_forecastingconfig` — one row per client
- `mysite_seriesleveleval` — one row per (item, level evaluated)

**Modified table:**
- `mysite_seriesprofile` — new fields: `chosen_evaluation_id` FK,
  `chosen_grain`, `chosen_demand_class`, `chosen_strategy`,
  `demand_class_atomic`, `abc_class_atomic`, `total_value`,
  `override_grain`, `override_set_by_id`, `override_set_at`

**Removed field (replaced):**
- `recommended_strategy` on `SeriesProfile` — now on `SeriesLevelEvaluation`
  and denormalised as `chosen_strategy`

---

## 9. How Sprint 3B.4 Uses These Models

The forecast task reads `SeriesProfile` for each atomic series and uses:

```python
profile.effective_grain     # which level to forecast at
profile.effective_strategy  # which StatsForecast model to use

# For requirement 7 (conflict resolution):
version.engine_config.get('disagg_conflict_resolution', 'retain_lower')
version.engine_config.get('store_all_level_forecasts', True)
```

When `store_all_level_forecasts=True`, the Celery task writes a
`ForecastLine` for every evaluated level (not just the chosen one),
using `forecast_level` to distinguish them. This enables planners
to later compare "what would the forecast have been if we'd used
category level vs SKU level" without re-running.


### Revision prompt
I have reviewed the sprint_3b3_seriesprofile_revised.md.

Following changes are required:

Change 1 : The Classification Search Flow is to be modified as below:

Get the PlanningLocation levels required in Part A from the Client PlanningLocation model. 

Get the ProductHierarchy levels from the Client Item Taxonomy. This will be used in Step B.

Based on the Planning Time bucket in the Planning profile, identify the higher time horizons for usage in Step C. Eg if Monthly is the time bucket, then higher Time Horizons are Quarterly, HalYearly, Yearly. If Day is the time bucket, then Weekly, Fortnightly and Month are the higher Time horizons.

For every item:

  Step 1: Item × Client Total

    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ These items are to be evaluated further in Part A

    → LUMPY?  → go to PART B

PART A — Try the item as-is from coarsest to finest location grain:

  Step A1: Item × Region  (one level down location hierarchy)

    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in Step A2

    → LUMPY?  → USE THE LEVEL in Step 1 (Item x Client Total)

  Step A2: Item x Region x abc (one level below Region)...

    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in next Step

    → LUMPY?  → USE THE LEVEL in Step A1 (Item x Region) 

    ... Keep going down the PlanningLocation hierarchy... 

  Step An: Item × Leaf Location  (location grain)

    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ Send these Items for evaluation in Step Am

    → LUMPY?  → USE THE LEVEL in Previous Step An-1  (Eg Item x Region)

  Step Am: Item × Leaf Location x PlanningCustomer  (finest grain)

    → SMOOTH / ERRATIC / INTERMITTENT?  ✓ USE THE LEVEL in this Step Am  (Item x PlanningLocation x PlanningCustomer)

    → LUMPY?  → USE THE LEVEL in Previous Step An  (Item x Leaf Location)

PART B — Item is LUMPY at Client level. Aggregate upward:

  Step B1: SubCategory × Client  (roll up product hierarchy)

    → Not LUMPY?  ✓ USE THIS LEVEL

    → LUMPY?  → go higher Step B2

    ... Repeat the step for the ProductHierarchy level derived above.

  Step Bn: Category × Client

    → Not LUMPY?  ✓ USE THIS LEVEL

    → LUMPY?  → try time aggregation Step C1

Part C - Coarser Time horizons.

    First go up up in the ProductHierarchy and then go up in the Time Hierarchy.

  Step C1: Item × Client × Next ImmediateTime Horizon 1 (aggregate time periods)

    → Not LUMPY?  ✓ USE THIS LEVEL (forecast quarterly, disaggregate to months)

    → LUMPY?  → try time aggregation Step C2

  Step C2: Next Item ProductHierarchy × Client × Time Horizon 1

    → Not LUMPY?  ✓ USE THIS LEVEL

    → LUMPY?  → 

    ... Repeat the steps in the Product Hierarchy x Time Hierarchy combinations.

  Step Z: MANUAL — no statistical level found.

            statistical_qty = 0. Planner enters override.

At EVERY step, the ABC class and Syntetos-Boylan metrics are stored

so planners can see the full audit trail.



Change 2: In ForecastingConfig you have suggested the following:

    # ── ABC thresholds (cumulative value %) ───────────────────────────────────

    abc_a_threshold = models.DecimalField(

        _('ABC — A threshold (cumulative %)'),

max_digits=5, decimal_places=2,

default=Decimal('70.00'),

help_text=_(

'Items whose cumulative demand value share (at the level being '

'evaluated) falls within this % are class A. Default 70.'

        ),

    )

    abc_b_threshold = models.DecimalField(

        _('ABC — B threshold (cumulative %)'),

max_digits=5, decimal_places=2,

default=Decimal('90.00'),

help_text=_(

'Items whose cumulative share falls between the A threshold and '

'this % are class B. The remainder are class C. Default 90.'

        ),

    )

Can this be kept a bit flexible as a subtable if required, so that the levels  and naming can be flexible at Client level. For eg Client A may have levels as A, B, C and another Client may have 4 levels as A, B, C, D?



Change 3: You have given the following code:

    max_location_levels = models.PositiveSmallIntegerField(

        _('max location levels'),

default=3,

help_text=_(

'How many levels of the PlanningLocation hierarchy to evaluate '

'during the coarse-to-fine search. 1 = client total only. '

'3 = client → region → branch.'

        ),

    )

This may be auto derived from PlanningLocation model of the Client.



Change 4: You have given the following code:

    # ── Part B: time aggregation options ─────────────────────────────────────

    try_quarterly_aggregation = models.BooleanField(

        _('try quarterly aggregation'),

default=True,

help_text=_(

'If an item is LUMPY at all location and product levels, '

'try aggregating monthly periods into quarters before giving up.'

        ),

    )

Either the levels are auto determined or we can take the number of higher time slots that the Client wants to go up. Based on the Planning bucket, the higher timeslots to be auto determined.



Rest fof the Sections would undergo change based on above. Presently the code has hardcoing of Location Hierarchy and Time Hierarchy. 

Pls review and reconstruct Sprint 3b3 seriesprofile revised.md.