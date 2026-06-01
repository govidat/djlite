# Sprint 3B.3 — SeriesProfile Section (Final Revised)
## Dynamic Hierarchy, Flexible ABC Classes, Configurable Time Horizons

**Replaces:** `sprint_3b3_seriesprofile_revised.md` in full  
**Scope:** Models, Celery task, Admin, Serializer, API  

---

## 0. Business Flow Summary (Plain Language)

### The Planning Matrix

Every item gets **two independent scores at every level evaluated**:

**ABC — How important is this item?**
Based on its share of total demand *value* among all items at the level
being evaluated. The number of classes and their thresholds are
configurable per client via `AbcClassDefinition`. Client A might use
A/B/C (3 classes), Client B might use A/B/C/D (4 classes).
An item can be **C** client-wide but **A** at a specific location.

**Syntetos-Boylan Class — How forecastable is this item at this level?**
Based on ADI (how often demand occurs) and CV² (how variable non-zero
quantities are). Thresholds are configurable per client via
`ForecastingConfig`. Results: SMOOTH / ERRATIC / INTERMITTENT / LUMPY.

### The Classification Search — Dynamic, Not Hardcoded

The search path is derived at runtime from the client's actual data:

- **Location hierarchy depth** — read from `PlanningLocation` tree
  (how many levels exist for this client)
- **Product hierarchy levels** — read from the client's `TaxonomyNode`
  tree for the `product_planning` taxonomy
- **Time horizon steps** — configured in `ForecastingConfig.time_horizon_steps`
  (how many levels up to try). The actual periods are derived automatically
  from the base `period_type`:
  - Monthly base → [quarter, half-year, year]
  - Daily base   → [week, fortnight, month]
  - Weekly base  → [month, quarter]
  - etc.

### The Search Flow

```
For every item:

Step 0: Item × Client Total
  → SMOOTH / ERRATIC / INTERMITTENT?
       → These are PART A items. Continue drilling DOWN location hierarchy.
  → LUMPY / INSUFFICIENT / ZERO?
       → These are PART B items. Skip PART A. Go directly to PART B.

─────────────────────────────────────────────────────────────────────
PART A — Item is forecastable at Client level.
Drill DOWN through location hierarchy levels (derived from PlanningLocation tree).
Goal: find the FINEST level at which the item stays forecastable.
─────────────────────────────────────────────────────────────────────

Step A1: Item × Level-1 of location tree (e.g. Region)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step A2
  → LUMPY?
       → STOP. USE Step 0 level (Item × Client Total) for this location group.
              Mark: chosen_grain = item_client

Step A2: Item × Level-2 of location tree (e.g. Zone)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step A3
  → LUMPY?
       → STOP. USE Step A1 level (Item × Region).
              Mark: chosen_grain = item_location_level_1

... repeat for each level in the location tree ...

Step An: Item × Leaf Location (finest location grain, all customers)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → Keep going to Step An+1 (customer level)
  → LUMPY?
       → STOP. USE previous level (Item × Level n-1).

Step An+1: Item × Leaf Location × Planning Customer (atomic grain)
  → SMOOTH / ERRATIC / INTERMITTENT?
       → USE THIS LEVEL. Mark: chosen_grain = item_cust_location
  → LUMPY?
       → USE previous level (Item × Leaf Location).
              Mark: chosen_grain = item_location_leaf

─────────────────────────────────────────────────────────────────────
PART B — Item is LUMPY at Client level.
Roll UP through product hierarchy (from ForecastingConfig taxonomy levels).
─────────────────────────────────────────────────────────────────────

Step B1: Level-1 product group × Client
         (first level above Item in product_planning taxonomy)
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Step B2

Step B2: Level-2 product group × Client
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Step B3

... repeat for each level in product taxonomy ...

Step Bn: Highest product group × Client (root of taxonomy)
  → Not LUMPY?  ✓ USE THIS LEVEL
  → LUMPY?  → Go to PART C

─────────────────────────────────────────────────────────────────────
PART C — LUMPY at all product levels.
Try TIME AGGREGATION in combination with product levels.
Time horizons are derived from period_type + time_horizon_steps config.
─────────────────────────────────────────────────────────────────────

  For each time horizon H (from finest to coarsest):
    Step C-H-0: Item × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → next product level

    Step C-H-1: Product Level 1 × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → next product level

    ... repeat through product levels for this time horizon ...

    Step C-H-n: Highest Product Level × Client × Time Horizon H
      → Not LUMPY?  ✓ USE THIS LEVEL
      → LUMPY?  → try next coarser time horizon

  Step Z: MANUAL — no level found anywhere.
    statistical_qty = 0. ForecastLine written with model_used='None'.
    Planner enters override.

At EVERY step: ABC class, ADI, CV², demand_class are stored in
SeriesLevelEvaluation so planners can see the full audit trail.
```

### Disaggregation Conflict Resolution

When an item has its own forecast at a fine grain (Part A) AND its product
group also has a forecast (Part B, because some sibling items were LUMPY):

- **Both forecasts are always stored** in `SeriesLevelEvaluation`
- `ForecastVersion.engine_config["disagg_conflict_resolution"]` controls
  which one becomes `ForecastLine.final_qty`:
  - `"retain_lower"` (default) — finer-grain wins, product-group
    disaggregation does not overwrite it
  - `"use_upper"` — product-group disaggregation overwrites everything
- `ForecastVersion.engine_config["store_all_level_forecasts"]` (default `true`)
  — when true, a `ForecastLine` is written for every evaluated level,
  tagged with `forecast_level`. Enables post-run comparison without re-running.

---

## 1. Helper: Time Horizon Derivation 

Add to `mysite/models/demand/actuals.py` alongside `PERIOD_FREQ_MAP`:

```python
# Time horizons above each base period type.
# Ordered from immediate-next to coarsest.
PERIOD_HIGHER_HORIZONS: dict[str, list[str]] = {
    'second':   ['minute', 'hour', 'day'],
    'minute':   ['hour', 'day', 'week'],
    'hour':     ['day', 'week', 'month'],
    'day':      ['week', 'fortnight', 'month'],
    'week':     ['month', 'quarter'],
    'month':    ['quarter', 'halfyear', 'year'],
    'bimonth':  ['quarter', 'halfyear', 'year'],
    'quarter':  ['halfyear', 'year'],
    'halfyear': ['year'],
    'year':     [],
}

# Add 'fortnight' to PERIOD_FREQ_MAP
PERIOD_FREQ_MAP['fortnight'] = '2W-MON'

# Add 'fortnight' to PERIOD_TYPE_CHOICES
# (append to existing list)
# ('fortnight', _('Fortnight (2 weeks)')),
```

Add a pure helper function — no DB access:

```python
def get_higher_period_types(base_period_type: str, steps: int) -> list[str]:
    """
    Return the list of higher period types to try, up to `steps` levels.

    Examples:
        get_higher_period_types('month', 2)  → ['quarter', 'halfyear']
        get_higher_period_types('day', 3)    → ['week', 'fortnight', 'month']
        get_higher_period_types('year', 2)   → []
    """
    horizons = PERIOD_HIGHER_HORIZONS.get(base_period_type, [])
    return horizons[:steps]
```

---

## 2. Helper: Location Hierarchy Introspection

Add to `utils/demand/hierarchy_utils.py` (new file):

```python
# utils/demand/hierarchy_utils.py
"""
Runtime introspection of PlanningLocation and TaxonomyNode trees.
Pure DB queries — no business logic.
"""
from __future__ import annotations
from collections import defaultdict


def get_location_levels(client_id: int) -> list[dict]:
    """
    Return the location hierarchy levels for a client, ordered from
    root (level 0 = client total) to leaves.

    Returns list of dicts:
        [
            {'depth': 0, 'level_label': 'Client Total',
             'location_ids': None},         # virtual — all locations
            {'depth': 1, 'level_label': 'Region',
             'location_ids': [1, 2, 3]},
            {'depth': 2, 'level_label': 'Zone',
             'location_ids': [4, 5, 6, 7]},
            {'depth': 3, 'level_label': 'Branch',
             'location_ids': [8, 9, ...], 'is_leaf': True},
        ]

    Depth 0 is the virtual "Client Total" (no model row — just the aggregate).
    Actual PlanningLocation nodes start at depth 1.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    locations = list(
        PlanningLocation.objects
        .filter(client_id=client_id, is_active=True)
        .values('id', 'code', 'name', 'level_label', 'parent_id', 'is_leaf', 'path')
        .order_by('path')
    )

    if not locations:
        return [{'depth': 0, 'level_label': 'Client Total',
                 'location_ids': None, 'is_leaf': False}]

    # Compute depth from path (path = "1/4/12/" → depth = 2)
    def _depth(loc: dict) -> int:
        return loc['path'].count('/') - 1

    by_depth: dict[int, list] = defaultdict(list)
    for loc in locations:
        d = _depth(loc)
        by_depth[d].append(loc)

    max_depth = max(by_depth.keys())

    # Level 0 is always the virtual Client Total
    levels = [{'depth': 0, 'level_label': 'Client Total',
                'location_ids': None, 'is_leaf': False}]

    for depth in range(0, max_depth + 1):
        locs = by_depth.get(depth, [])
        if not locs:
            continue
        label = locs[0]['level_label'] or f'Level {depth}'
        levels.append({
            'depth': depth + 1,   # +1 because 0 is Client Total
            'level_label': label,
            'location_ids': [l['id'] for l in locs],
            'location_codes': [l['code'] for l in locs],
            'is_leaf': all(l['is_leaf'] for l in locs),
        })

    return levels


def get_location_children_map(client_id: int) -> dict[int | None, list[int]]:
    """
    Returns dict: {parent_id → [child_ids]}.
    parent_id=None means root nodes (direct children of client total).
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result: dict[int | None, list[int]] = defaultdict(list)
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'parent_id'):
        result[loc['parent_id']].append(loc['id'])
    return dict(result)


def get_location_ancestor_map(client_id: int) -> dict[int, list[int]]:
    """
    Returns dict: {location_id → [ancestor_ids from root to parent]}.
    Used to find the region/zone a leaf belongs to.
    """
    from mysite.models.demand.hierarchy import PlanningLocation

    result = {}
    for loc in PlanningLocation.objects.filter(
        client_id=client_id, is_active=True
    ).values('id', 'path'):
        parts = [p for p in loc['path'].split('/') if p]
        ancestor_ids = [int(p) for p in parts[:-1]]
        result[loc['id']] = ancestor_ids
    return result


def get_product_hierarchy_levels(client_id: int) -> list[dict]:
    """
    Return the product taxonomy levels for the 'product_planning' taxonomy,
    ordered from leaf (SKU) to root (highest category).

    Returns list of dicts ordered from FINEST to COARSEST:
        [
            {'depth': 3, 'level_label': 'SKU',       'node_ids': [...]},
            {'depth': 2, 'level_label': 'Brand',      'node_ids': [...]},
            {'depth': 1, 'level_label': 'Sub-cat',    'node_ids': [...]},
            {'depth': 0, 'level_label': 'Category',   'node_ids': [...]},
        ]

    The leaf level (SKUs) is excluded from Part B evaluation — Part B starts
    one level above the leaf.
    """
    from mysite.models import TaxonomyNode, Taxonomy

    try:
        taxonomy = Taxonomy.objects.get(
            client_id=client_id, slug='product_planning'
        )
    except Taxonomy.DoesNotExist:
        return []

    nodes = list(
        TaxonomyNode.objects
        .filter(taxonomy=taxonomy)
        .values('id', 'name', 'parent_id', 'depth')
        .order_by('depth')
    )

    if not nodes:
        return []

    max_depth = max(n['depth'] for n in nodes)
    by_depth: dict[int, list] = defaultdict(list)
    for n in nodes:
        by_depth[n['depth']].append(n)

    # Return from leaf-1 up to root (skip leaf level — those are the items)
    levels = []
    for depth in range(max_depth - 1, -1, -1):
        group = by_depth.get(depth, [])
        if not group:
            continue
        label = group[0].get('level_label') or f'Level {depth}'
        levels.append({
            'depth':      depth,
            'level_label': label,
            'node_ids':   [n['id'] for n in group],
            'node_names': [n['name'] for n in group],
        })

    return levels
```

---

## 3. Model: `AbcClassDefinition` (flexible ABC subtable)

Replaces the two hardcoded threshold fields on `ForecastingConfig`.
Add to `mysite/models/demand/forecast.py` **before** `ForecastingConfig`:

```python
class AbcClassDefinition(models.Model):
    """
    One row per ABC class tier for a client.

    Supports any number of classes: A/B/C (3 tiers), A/B/C/D (4 tiers), etc.
    Each row defines one class tier with a cumulative value share upper bound.

    Example for 3-tier client (standard):
        rank=1  label='A'  cumulative_upper_pct=70.0   → top 70% of value
        rank=2  label='B'  cumulative_upper_pct=90.0   → next 20%
        rank=3  label='C'  cumulative_upper_pct=100.0  → bottom 10%

    Example for 4-tier client:
        rank=1  label='A'  cumulative_upper_pct=60.0
        rank=2  label='B'  cumulative_upper_pct=80.0
        rank=3  label='C'  cumulative_upper_pct=95.0
        rank=4  label='D'  cumulative_upper_pct=100.0

    Rules enforced in clean():
      - Ranks must be contiguous starting at 1.
      - cumulative_upper_pct must be strictly increasing.
      - The highest rank must have cumulative_upper_pct = 100.0.
    """

    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='abc_class_definitions',
        verbose_name=_('client'),
    )
    rank = models.PositiveSmallIntegerField(
        _('rank'),
        help_text=_(
            'Display and evaluation order. 1 = most important class (e.g. A).'
        ),
    )
    label = models.CharField(
        _('label'),
        max_length=8,
        help_text=_('Class label shown to planners. e.g. "A", "B", "Gold", "Tier1".'),
    )
    cumulative_upper_pct = models.DecimalField(
        _('cumulative upper % (inclusive)'),
        max_digits=6,
        decimal_places=3,
        help_text=_(
            'Items whose cumulative demand value share (at the level being '
            'evaluated) falls at or below this % receive this class. '
            'Must be 100.0 for the last rank. Must be strictly increasing.'
        ),
    )
    description = models.CharField(
        _('description'),
        max_length=255,
        blank=True,
        help_text=_('Optional description shown in reports.'),
    )

    class Meta:
        app_label   = 'mysite'
        unique_together = [('client', 'rank'), ('client', 'label')]
        ordering    = ['client', 'rank']
        verbose_name        = _('03-00A ABC Class Definition')
        verbose_name_plural = _('03-00A ABC Class Definitions')

    def __str__(self):
        return f'{self.client} | rank={self.rank} label={self.label} ≤{self.cumulative_upper_pct}%'

    def clean(self):
        if self.cumulative_upper_pct is not None:
            if self.cumulative_upper_pct <= 0 or self.cumulative_upper_pct > 100:
                raise ValidationError(
                    _('cumulative_upper_pct must be between 0.001 and 100.')
                )

    @classmethod
    def get_or_create_defaults(cls, client) -> list['AbcClassDefinition']:
        """
        Return existing definitions or create standard A/B/C defaults.
        Safe to call from Celery tasks.
        """
        existing = list(
            cls.objects.filter(client=client).order_by('rank')
        )
        if existing:
            return existing

        defaults = [
            cls(client=client, rank=1, label='A',
                cumulative_upper_pct=Decimal('70.000'),
                description='High value — top 70% of demand value'),
            cls(client=client, rank=2, label='B',
                cumulative_upper_pct=Decimal('90.000'),
                description='Medium value — next 20%'),
            cls(client=client, rank=3, label='C',
                cumulative_upper_pct=Decimal('100.000'),
                description='Low value — remaining 10%'),
        ]
        cls.objects.bulk_create(defaults)
        return defaults

    @classmethod
    def compute_class(
        cls,
        item_value: float,
        all_values_sorted_desc: list[float],
        definitions: list['AbcClassDefinition'],
    ) -> dict:
        """
        Classify one item given sorted values for all items at the same level
        and the client's class definitions.

        Returns:
            {'abc_class': str, 'value_share_pct': Decimal, 'rank': int}

        This is a pure function — no DB access after definitions are loaded.
        """
        total = sum(all_values_sorted_desc) or 1.0
        share_pct = item_value / total * 100

        # Compute cumulative % up to and including this item's value
        cumulative = 0.0
        for v in all_values_sorted_desc:
            cumulative += v / total * 100
            if v <= item_value + 1e-9:
                break

        # Find which class this cumulative % falls into
        for defn in definitions:
            if cumulative <= float(defn.cumulative_upper_pct):
                return {
                    'abc_class':       defn.label,
                    'rank':            defn.rank,
                    'value_share_pct': Decimal(str(round(share_pct, 4))),
                    'cumulative_pct':  Decimal(str(round(cumulative, 4))),
                }

        # Fallback to lowest rank (should not happen if 100% is defined)
        last = definitions[-1]
        return {
            'abc_class':       last.label,
            'rank':            last.rank,
            'value_share_pct': Decimal(str(round(share_pct, 4))),
            'cumulative_pct':  Decimal('100'),
        }
```

---

## 4. Model: `ForecastingConfig` (revised — no hardcoded hierarchy)

```python
class ForecastingConfig(models.Model):
    """
    Client-level configuration for the forecasting classification engine.

    One row per client. Created with defaults on first forecast run.

    What is NOT here (derived at runtime instead):
      - Location hierarchy depth → read from PlanningLocation tree
      - Product hierarchy levels → read from product_planning TaxonomyNode tree
      - ABC thresholds           → stored in AbcClassDefinition subtable
    """

    client = models.OneToOneField(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='forecasting_config',
        verbose_name=_('client'),
    )

    # ── Syntetos-Boylan thresholds ────────────────────────────────────────────
    adi_threshold = models.DecimalField(
        _('ADI threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('1.3200'),
        help_text=_(
            'Average Demand Interval cutoff. Series with ADI ≥ this value '
            'are INTERMITTENT or LUMPY. Syntetos-Boylan (2005) default: 1.32.'
        ),
    )
    cv2_threshold = models.DecimalField(
        _('CV² threshold'),
        max_digits=6, decimal_places=4,
        default=Decimal('0.4900'),
        help_text=_(
            'Squared Coefficient of Variation cutoff for non-zero demand. '
            'Series with CV² ≥ this value are ERRATIC or LUMPY. '
            'Syntetos-Boylan (2005) default: 0.49.'
        ),
    )
    min_nonzero_periods = models.PositiveSmallIntegerField(
        _('minimum non-zero periods'),
        default=6,
        help_text=_(
            'Minimum non-zero demand periods required before any statistical '
            'model is attempted. Series below this are INSUFFICIENT.'
        ),
    )

    # ── Time horizon aggregation ──────────────────────────────────────────────
    time_horizon_steps = models.PositiveSmallIntegerField(
        _('time horizon steps'),
        default=2,
        help_text=_(
            'How many coarser time periods to try in Part C when an item is '
            'LUMPY at all location and product levels.\n'
            'The actual period types are derived automatically from the '
            'ForecastVersion.period_type:\n'
            '  period_type=month, steps=2 → tries [quarter, halfyear]\n'
            '  period_type=day,   steps=3 → tries [week, fortnight, month]\n'
            '  period_type=week,  steps=1 → tries [month]\n'
            '0 = do not try time aggregation at all.'
        ),
    )

    # ── Include customer dimension ─────────────────────────────────────────────
    evaluate_customer_grain = models.BooleanField(
        _('evaluate customer grain'),
        default=True,
        help_text=_(
            'If True, Part A evaluation drills down to '
            'Item × Leaf Location × Planning Customer '
            'as the finest possible grain. '
            'If False, the finest grain is Item × Leaf Location.'
        ),
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label           = 'mysite'
        verbose_name        = _('03-00 Forecasting Config')
        verbose_name_plural = _('03-00 Forecasting Configs')

    def __str__(self):
        return (
            f'{self.client} | ADI≥{self.adi_threshold} '
            f'CV²≥{self.cv2_threshold} | time_steps={self.time_horizon_steps}'
        )

    @classmethod
    def get_for_client(cls, client) -> 'ForecastingConfig':
        config, _ = cls.objects.get_or_create(client=client)
        return config
```

---

## 5. Model: `SeriesLevelEvaluation` (revised — dynamic grain)

The `grain` field now uses a flexible string rather than a fixed enum
so it can represent any depth in any hierarchy without code changes.

```python
class SeriesLevelEvaluation(models.Model):
    """
    One row per (item, evaluated level). The full audit trail.

    grain encodes WHAT was aggregated and HOW:
        'item_client'               — item across all locations
        'item_loc_depth_{n}'        — item at location hierarchy depth n
                                      (n=1 is root children, n=max is leaves)
        'item_cust_location'        — item × customer × leaf location (atomic)
        'taxon_{node_id}_client'    — TaxonomyNode {node_id} × client
        'item_client_{period}'      — item × client at a coarser period type
        'taxon_{node_id}_{period}'  — TaxonomyNode × client at coarser period

    evaluation_key is a JSONField with the specific node values:
        item_client:
            {'grain': 'item_client'}
        item_loc_depth_1:
            {'grain': 'item_loc_depth_1', 'location_id': 4,
             'location_code': 'NORTH', 'level_label': 'Region'}
        item_cust_location:
            {'grain': 'item_cust_location', 'location_id': 12,
             'location_code': 'DEL-01', 'customer_id': 7,
             'customer_code': 'CUST-001'}
        taxon_5_client:
            {'grain': 'taxon_5_client', 'node_id': 5,
             'node_name': 'Brake Pads', 'level_label': 'Sub-category'}
        item_client_quarter:
            {'grain': 'item_client_quarter', 'period_type': 'quarter'}
        taxon_3_quarter:
            {'grain': 'taxon_3_quarter', 'node_id': 3,
             'node_name': 'Braking Systems', 'period_type': 'quarter'}
    """

    client = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='series_level_evaluations',
    )
    item = models.ForeignKey(
        'mysite.Item', on_delete=models.PROTECT,
        related_name='series_level_evaluations',
    )
    # planning_customer only set for item_cust_location grain
    planning_customer = models.ForeignKey(
        PlanningCustomer, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_level_evaluations',
    )
    period_type = models.CharField(
        _('base period type'),
        max_length=16, choices=PERIOD_TYPE_CHOICES,
        help_text=_('The ForecastVersion base period type, not the evaluation period.'),
    )

    # ── Which level ───────────────────────────────────────────────────────────
    grain = models.CharField(
        _('evaluation grain'),
        max_length=64,
        db_index=True,
        help_text=_(
            'String encoding the aggregation dimension. '
            'e.g. "item_client", "item_loc_depth_2", '
            '"taxon_5_client", "item_client_quarter".'
        ),
    )
    evaluation_key = models.JSONField(
        _('evaluation key'),
        help_text=_('Identifies the specific node at this grain.'),
    )
    # The evaluation period type (may differ from period_type in Part C)
    eval_period_type = models.CharField(
        _('evaluation period type'),
        max_length=16, choices=PERIOD_TYPE_CHOICES,
        help_text=_(
            'The period type used for THIS evaluation. '
            'Equals period_type for Parts A and B. '
            'Coarser (e.g. quarter) for Part C.'
        ),
    )

    # ── Analysis window ───────────────────────────────────────────────────────
    analysis_from = models.DateField()
    analysis_to   = models.DateField()

    # ── Raw metrics ───────────────────────────────────────────────────────────
    total_periods   = models.PositiveSmallIntegerField()
    nonzero_periods = models.PositiveSmallIntegerField()
    total_qty       = models.DecimalField(max_digits=18, decimal_places=3)
    total_value     = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
    )

    # ── Syntetos-Boylan ───────────────────────────────────────────────────────
    adi       = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    cv2       = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    zero_rate = models.DecimalField(max_digits=5, decimal_places=4)

    # ── ABC at this level ─────────────────────────────────────────────────────
    abc_class = models.CharField(
        _('ABC class at this level'),
        max_length=8,          # supports longer labels like 'Gold', 'Tier1'
        blank=True,
    )
    value_share_pct_at_level = models.DecimalField(
        max_digits=7, decimal_places=4, null=True, blank=True,
    )
    value_rank_at_level = models.PositiveIntegerField(null=True, blank=True)

    # ── Syntetos-Boylan classification ────────────────────────────────────────
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

    # ── Decision ──────────────────────────────────────────────────────────────
    is_accepted = models.BooleanField(
        _('accepted'),
        default=False,
        db_index=True,
    )
    rejection_reason = models.CharField(
        max_length=255, blank=True,
    )
    recommended_strategy = models.CharField(
        max_length=16, blank=True,
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
        ordering  = ['item__item_id', 'grain']
        verbose_name        = _('03-06 Series Level Evaluation')
        verbose_name_plural = _('03-06 Series Level Evaluations')
        indexes = [
            models.Index(
                fields=['client', 'grain', 'demand_class'],
                name='ix_sleveval_grain_cls',
            ),
            models.Index(
                fields=['client', 'is_accepted'],
                name='ix_sleveval_accepted',
            ),
            models.Index(
                fields=['client', 'item', 'is_accepted'],
                name='ix_sleveval_item_accepted',
            ),
        ]

    def __str__(self):
        status = 'ACCEPTED' if self.is_accepted else 'rejected'
        return (
            f'{self.item.item_id} | {self.grain} | '
            f'{self.demand_class} | {status}'
        )
```

---

## 6. Model: `SeriesProfile` (revised — references dynamic grain)

```python
class SeriesProfile(models.Model):
    """
    Forecast level selection summary for one atomic series
    (item, customer, location). One row per unique atomic combination.

    chosen_evaluation FK points to the accepted SeriesLevelEvaluation row.
    chosen_grain is denormalised for fast filter/display without a join.
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

    # ── Metrics at atomic grain ───────────────────────────────────────────────
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
    demand_class_atomic = models.CharField(max_length=16, blank=True)
    abc_class_atomic    = models.CharField(max_length=8, blank=True)

    # ── Chosen evaluation ─────────────────────────────────────────────────────
    chosen_evaluation = models.ForeignKey(
        SeriesLevelEvaluation,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='series_profiles',
        verbose_name=_('chosen evaluation'),
    )
    # Denormalised fields from chosen_evaluation for fast access
    chosen_grain         = models.CharField(max_length=64, blank=True, db_index=True)
    chosen_demand_class  = models.CharField(max_length=16, blank=True)
    chosen_strategy      = models.CharField(max_length=16, blank=True)
    chosen_eval_period   = models.CharField(
        _('chosen evaluation period type'),
        max_length=16, blank=True,
        help_text=_(
            'The period type used at the chosen level. '
            'May differ from period_type when time aggregation was applied.'
        ),
    )

    # ── Planner overrides ─────────────────────────────────────────────────────
    override_grain = models.CharField(
        _('override grain'),
        max_length=64, blank=True,
        help_text=_(
            'Planner-specified grain string. Must match a valid grain from '
            'SeriesLevelEvaluation for this item. '
            'The forecast engine reads effective_grain.'
        ),
    )
    override_strategy = models.CharField(max_length=16, blank=True)
    override_note     = models.TextField(blank=True)
    override_set_by   = models.ForeignKey(
        'auth.User', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    override_set_at   = models.DateTimeField(null=True, blank=True)

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
            models.Index(fields=['client', 'chosen_grain'],      name='ix_seriespro_grain'),
            models.Index(fields=['client', 'demand_class_atomic'], name='ix_seriespro_cls'),
            models.Index(fields=['client', 'abc_class_atomic'],   name='ix_seriespro_abc'),
        ]

    def __str__(self):
        cust = self.planning_customer or 'all'
        return (
            f'{self.item.item_id} | {self.planning_location.code} | {cust} | '
            f'atomic={self.demand_class_atomic} | chosen={self.chosen_grain}'
        )

    @property
    def effective_grain(self) -> str:
        return self.override_grain or self.chosen_grain or 'item_client'

    @property
    def effective_strategy(self) -> str:
        return self.override_strategy or self.chosen_strategy or 'AUTOETS'

    @property
    def effective_eval_period(self) -> str:
        return self.chosen_eval_period or self.period_type

    @property
    def is_overridden(self) -> bool:
        return bool(self.override_grain or self.override_strategy)

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
        Compute ADI, CV², zero_rate and Syntetos-Boylan demand class.
        Pure function — no DB access.
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

        if   adi_f < adi_threshold and cv2_f < cv2_threshold:
            demand_class = 'SMOOTH';       strategy = 'AUTOETS'
        elif adi_f < adi_threshold:
            demand_class = 'ERRATIC';      strategy = 'AUTOARIMA'
        elif cv2_f < cv2_threshold:
            demand_class = 'INTERMITTENT'; strategy = 'CROSTON'
        else:
            demand_class = 'LUMPY';        strategy = ''

        return {
            'total_periods': total_periods, 'nonzero_periods': nonzero_periods,
            'total_qty': total_qty, 'adi': adi, 'cv2': cv2,
            'zero_rate': zero_rate, 'demand_class': demand_class,
            'recommended_strategy': strategy,
        }
```

---

## 7. Revised Celery Task: `compute_series_profiles`

```python
# mysite/tasks/demand/compute_series_profiles.py

import logging
from collections import defaultdict
from decimal import Decimal

import duckdb
import pandas as pd
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from mysite.models.demand.actuals import ActualSale, get_higher_period_types
from mysite.models.demand.forecast import (
    AbcClassDefinition, ForecastingConfig,
    SeriesLevelEvaluation, SeriesProfile,
)

logger = logging.getLogger(__name__)

LUMPY_CLASSES = {'LUMPY', 'INSUFFICIENT', 'ZERO'}


@shared_task(bind=True)
def compute_series_profiles(self, client_id: int, period_type: str):
    """
    Full multi-level classification: dynamic location depth,
    dynamic product hierarchy, dynamic time horizons.
    """
    from mysite.models import Client
    from utils.demand.hierarchy_utils import (
        get_location_levels,
        get_product_hierarchy_levels,
    )

    client = Client.objects.get(pk=client_id)
    config = ForecastingConfig.get_for_client(client)
    abc_defs = AbcClassDefinition.get_or_create_defaults(client)

    adi_thr = float(config.adi_threshold)
    cv2_thr = float(config.cv2_threshold)
    min_nz  = config.min_nonzero_periods

    # ── Derive search space from client's actual hierarchies ──────────────────

    # Location levels: [{depth, level_label, location_ids, is_leaf}]
    loc_levels = get_location_levels(client_id)
    # loc_levels[0] is always Client Total (virtual).
    # loc_levels[1..n] are actual PlanningLocation levels from the DB.

    # Product levels: [{depth, level_label, node_ids}] — finest to coarsest
    prod_levels = get_product_hierarchy_levels(client_id)
    # prod_levels[0] is the level just above SKU (e.g. Brand or SubCategory).
    # prod_levels[-1] is the root (Category or similar).

    # Time horizons: list of period_type strings coarser than base
    time_horizons = get_higher_period_types(period_type, config.time_horizon_steps)

    logger.info(
        f'compute_series_profiles: client={client_id} period={period_type}\n'
        f'  location levels: {[l["level_label"] for l in loc_levels]}\n'
        f'  product levels: {[l["level_label"] for l in prod_levels]}\n'
        f'  time horizons: {time_horizons}\n'
        f'  ADI≥{adi_thr} CV²≥{cv2_thr} min_nz={min_nz}'
    )

    # ── Pull actuals ──────────────────────────────────────────────────────────
    qs = (
        ActualSale.objects
        .filter(client=client, period_type=period_type)
        .select_related(
            'item',
            'planning_location',
            'planning_customer',
        )
        .values(
            'item_id', 'item__item_id',
            'planning_customer_id', 'planning_customer__code',
            'planning_location_id', 'planning_location__code',
            'planning_location__path',    # materialized path for ancestor lookup
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
    df['cust_code'] = df['planning_customer__code'].fillna('__NULL__')

    # Build ancestor lookup from materialized path
    # path = "1/4/12/" → ancestors at depth 1 = node 1, depth 2 = node 4
    def _ancestor_at_depth(path: str, target_depth: int) -> int | None:
        """Return the location_id at target_depth in the path, or None."""
        parts = [p for p in path.split('/') if p]
        # parts[0] is depth-1 node, parts[1] is depth-2, etc.
        idx = target_depth - 1
        return int(parts[idx]) if idx < len(parts) else None

    # Build location_id → location_id-at-depth-n lookup
    # Used to group locations by their ancestor at each level
    loc_id_to_path = df.groupby('planning_location_id')['planning_location__path'].first().to_dict()

    def _loc_ancestor(loc_id: int, depth: int) -> int | None:
        path = loc_id_to_path.get(loc_id, '')
        return _ancestor_at_depth(path, depth)

    # For each location_id, build its ancestor at each location level depth
    all_loc_ids = df['planning_location_id'].unique()
    loc_ancestor: dict[int, dict[int, int | None]] = {}
    for loc_id in all_loc_ids:
        loc_ancestor[loc_id] = {
            level['depth']: _loc_ancestor(loc_id, level['depth'])
            for level in loc_levels[1:]  # skip virtual level 0
        }

    # Add ancestor columns to df
    for level in loc_levels[1:]:
        d = level['depth']
        col = f'anc_depth_{d}'
        df[col] = df['planning_location_id'].map(
            lambda lid, d=d: loc_ancestor.get(int(lid), {}).get(d)
        )

    # ── Build time spine ──────────────────────────────────────────────────────
    all_periods   = sorted(df['period_start'].unique().tolist())
    analysis_from = all_periods[0]
    analysis_to   = all_periods[-1]

    # ── DuckDB aggregations ───────────────────────────────────────────────────
    con = duckdb.connect()
    con.register('actuals', df)

    def _agg_sql(group_cols: list[str], extra_cols: str = '') -> str:
        """Build a GROUP BY aggregation SQL."""
        gc = ', '.join(group_cols)
        return f"""
            SELECT {gc},
                   period_start,
                   SUM(qty) AS qty,
                   SUM(revenue) AS revenue
                   {', ' + extra_cols if extra_cols else ''}
            FROM actuals
            GROUP BY {gc}, period_start
        """

    # Level 0: Item × Client (virtual — all locations)
    df_item_client = con.execute(_agg_sql(['item_id'])).df()

    # Levels 1..n: Item × Location ancestor at each depth
    df_by_depth: dict[int, pd.DataFrame] = {}
    for level in loc_levels[1:]:
        d = level['depth']
        anc_col = f'anc_depth_{d}'
        if anc_col in df.columns:
            df_by_depth[d] = con.execute(
                _agg_sql(['item_id', anc_col])
            ).df().rename(columns={anc_col: 'loc_ancestor_id'})

    # Item × Leaf Location (all customers)
    df_item_loc = con.execute(
        _agg_sql(['item_id', 'planning_location_id',
                  'planning_location__code'])
    ).df()

    # Atomic: Item × Customer × Leaf Location
    df_atomic = con.execute(
        _agg_sql(['item_id', 'cust_code', 'planning_customer_id',
                  'planning_location_id', 'planning_location__code'])
    ).df()

    # Quarterly aggregations for Part C time horizons
    df_time_agg: dict[str, pd.DataFrame] = {}
    for h_period in time_horizons:
        from mysite.models.demand.actuals import PERIOD_FREQ_MAP
        freq = PERIOD_FREQ_MAP.get(h_period)
        if not freq:
            continue
        try:
            tmp = df[['item_id', 'period_start', 'qty', 'revenue']].copy()
            tmp['period_start'] = pd.to_datetime(tmp['period_start'])
            agg = (
                tmp.groupby(['item_id', pd.Grouper(key='period_start', freq=freq)])
                .agg({'qty': 'sum', 'revenue': 'sum'})
                .reset_index()
            )
            agg['period_start'] = agg['period_start'].dt.date
            df_time_agg[h_period] = agg
        except Exception as exc:
            logger.warning(f'Time agg failed for {h_period}: {exc}')

    # ── Helper: build qty series from filtered DataFrame ──────────────────────
    def _qty_series(filtered: pd.DataFrame, periods: list) -> list[float]:
        pq = dict(zip(filtered['period_start'], filtered['qty']))
        return [pq.get(p, 0.0) for p in periods]

    def _value_series(filtered: pd.DataFrame) -> float:
        return float(filtered['revenue'].sum())

    # ── Helper: classify ──────────────────────────────────────────────────────
    def _classify(qty_list: list) -> dict:
        series = [Decimal(str(q)) for q in qty_list]
        return SeriesProfile.compute_syntetos_boylan(
            series, adi_thr, cv2_thr, min_nz
        )

    # ── Helper: ABC at a level ────────────────────────────────────────────────
    def _compute_abc_at_level(
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        """
        Compute ABC for item_value given all items' values in level_df.
        level_df must contain a 'revenue' column grouped by item_id.
        """
        all_values = level_df.groupby('item_id')['revenue'].sum().sort_values(ascending=False).tolist()
        return AbcClassDefinition.compute_class(
            item_value, all_values, abc_defs
        )

    # ── Helper: build SeriesLevelEvaluation dict ──────────────────────────────
    def _eval_dict(
        grain: str,
        key: dict,
        eval_period: str,
        qty_list: list,
        item_value: float,
        level_df: pd.DataFrame,
    ) -> dict:
        m   = _classify(qty_list)
        abc = _compute_abc_at_level(item_value, level_df)
        return {
            'grain':           grain,
            'evaluation_key':  key,
            'eval_period':     eval_period,
            'metrics':         m,
            'abc':             abc,
            'total_value':     item_value,
            'is_forecastable': m['demand_class'] not in LUMPY_CLASSES,
        }

    # ── Main per-series loop ──────────────────────────────────────────────────
    evaluations_to_create: list[SeriesLevelEvaluation] = []
    profiles_to_upsert: list[dict] = []

    # Get unique atomic series
    atomic_groups = df_atomic.groupby(
        ['item_id', 'cust_code', 'planning_customer_id',
         'planning_location_id', 'planning_location__code']
    )

    for keys, _ in atomic_groups:
        item_id   = keys[0]
        cust_code = keys[1]
        cust_id   = keys[2]
        loc_id    = keys[3]
        loc_code  = keys[4]
        cust_id_int = None if pd.isna(cust_id) else int(cust_id)

        evals: list[dict] = []
        chosen: dict | None = None

        # ── Step 0: Item × Client ─────────────────────────────────────────────
        ic_rows = df_item_client[df_item_client['item_id'] == item_id]
        ic_qty  = _qty_series(ic_rows, all_periods)
        ic_val  = _value_series(ic_rows)
        e0 = _eval_dict(
            grain='item_client',
            key={'grain': 'item_client'},
            eval_period=period_type,
            qty_list=ic_qty,
            item_value=ic_val,
            level_df=df_item_client,
        )
        evals.append(e0)

        if e0['is_forecastable']:
            # ── PART A: drill DOWN location hierarchy ─────────────────────────
            prev_accepted = e0  # last forecastable level

            for level in loc_levels[1:]:
                d       = level['depth']
                anc_id  = loc_ancestor.get(int(loc_id), {}).get(d)
                if anc_id is None:
                    continue  # this location has no ancestor at this depth

                level_df_d = df_by_depth.get(d)
                if level_df_d is None:
                    continue

                rows_d = level_df_d[
                    (level_df_d['item_id'] == item_id) &
                    (level_df_d['loc_ancestor_id'] == anc_id)
                ]
                if rows_d.empty:
                    continue

                val_d = _value_series(rows_d)
                e_d = _eval_dict(
                    grain=f'item_loc_depth_{d}',
                    key={'grain': f'item_loc_depth_{d}',
                         'location_id': int(anc_id),
                         'level_label': level['level_label']},
                    eval_period=period_type,
                    qty_list=_qty_series(rows_d, all_periods),
                    item_value=val_d,
                    level_df=level_df_d,
                )
                evals.append(e_d)

                if e_d['is_forecastable']:
                    prev_accepted = e_d   # keep drilling
                else:
                    # Hit LUMPY — step back
                    chosen = prev_accepted
                    break

            else:
                # Finished all location levels without going LUMPY
                # Now try customer grain if config says so
                if config.evaluate_customer_grain:
                    leaf_rows = df_item_loc[
                        (df_item_loc['item_id'] == item_id) &
                        (df_item_loc['planning_location_id'] == loc_id)
                    ]
                    at_rows = df_atomic[
                        (df_atomic['item_id'] == item_id) &
                        (df_atomic['planning_location_id'] == loc_id) &
                        (df_atomic['cust_code'] == cust_code)
                    ]
                    if not at_rows.empty:
                        at_val = _value_series(at_rows)
                        e_at = _eval_dict(
                            grain='item_cust_location',
                            key={'grain': 'item_cust_location',
                                 'location_id': int(loc_id),
                                 'location_code': loc_code,
                                 'customer_code': cust_code},
                            eval_period=period_type,
                            qty_list=_qty_series(at_rows, all_periods),
                            item_value=at_val,
                            level_df=df_atomic[
                                df_atomic['planning_location_id'] == loc_id
                            ],
                        )
                        evals.append(e_at)
                        if e_at['is_forecastable']:
                            prev_accepted = e_at

                if chosen is None:
                    chosen = prev_accepted

        else:
            # ── PART B: Item is LUMPY at client level ─────────────────────────
            # Roll UP through product hierarchy

            for prod_level in prod_levels:
                # Build series: sum all items in the same product group
                # at this level that belong to this item
                # (requires ItemTaxonomyMapping join — simplified here)
                node_ids = prod_level.get('node_ids', [])
                if not node_ids:
                    continue

                # Placeholder: extend with actual taxonomy lookup
                # For each node in prod_level that contains item_id:
                # sum actuals of all items in that node
                node_id = None  # resolve item → node at this level
                if node_id is None:
                    continue

                # Build aggregated series for this product group
                # (requires a pre-built item → node_id mapping per level)
                # Omitted here — wire in your ItemTaxonomyMapping query
                pass  # replace with actual implementation

            # ── PART C: time aggregation ──────────────────────────────────────
            for h_period in time_horizons:
                if chosen:
                    break
                h_df = df_time_agg.get(h_period)
                if h_df is None:
                    continue
                h_periods = sorted(h_df['period_start'].unique().tolist())
                if len(h_periods) < min_nz:
                    continue

                # Step C-H-0: Item × Client × Time Horizon
                ic_h_rows = h_df[h_df['item_id'] == item_id]
                if not ic_h_rows.empty:
                    ic_h_qty = _qty_series(ic_h_rows, h_periods)
                    ic_h_val = _value_series(ic_h_rows)
                    e_ch = _eval_dict(
                        grain=f'item_client_{h_period}',
                        key={'grain': f'item_client_{h_period}',
                             'period_type': h_period},
                        eval_period=h_period,
                        qty_list=ic_h_qty,
                        item_value=ic_h_val,
                        level_df=h_df,
                    )
                    evals.append(e_ch)
                    if e_ch['is_forecastable']:
                        chosen = e_ch
                        break

                # Step C-H-n: product hierarchy × time horizon
                # (extend with actual taxonomy loop — same pattern as Part B)

            # Final fallback: MANUAL
            if not chosen:
                e_manual = {
                    'grain':          'item_client',
                    'evaluation_key': {'grain': 'item_client', 'note': 'MANUAL'},
                    'eval_period':    period_type,
                    'metrics': {
                        'demand_class': 'LUMPY', 'recommended_strategy': 'MANUAL',
                        'total_periods': len(all_periods), 'nonzero_periods': 0,
                        'total_qty': Decimal('0'), 'adi': None, 'cv2': None,
                        'zero_rate': Decimal('1'),
                    },
                    'abc':         e0['abc'],
                    'total_value': ic_val,
                    'is_forecastable': False,
                }
                evals.append(e_manual)
                chosen = e_manual

        # Mark chosen and build rejection reasons
        for ev in evals:
            ev['is_accepted'] = (ev is chosen)
            if not ev['is_accepted']:
                m = ev['metrics']
                ev['rejection_reason'] = (
                    f"{m['demand_class']} (ADI={m.get('adi','—')}, "
                    f"CV²={m.get('cv2','—')})"
                    if m['demand_class'] in LUMPY_CLASSES else ''
                )
            else:
                ev['rejection_reason'] = ''

        # Build SeriesLevelEvaluation objects
        for ev in evals:
            m = ev['metrics']
            evaluations_to_create.append(
                SeriesLevelEvaluation(
                    client_id=client_id,
                    item_id=item_id,
                    planning_customer_id=(
                        cust_id_int
                        if ev['grain'] == 'item_cust_location'
                        else None
                    ),
                    period_type=period_type,
                    grain=ev['grain'],
                    evaluation_key=ev['evaluation_key'],
                    eval_period_type=ev.get('eval_period', period_type),
                    analysis_from=analysis_from,
                    analysis_to=analysis_to,
                    total_periods=m['total_periods'],
                    nonzero_periods=m['nonzero_periods'],
                    total_qty=m['total_qty'],
                    total_value=Decimal(str(round(ev.get('total_value', 0), 2))),
                    adi=m.get('adi'),
                    cv2=m.get('cv2'),
                    zero_rate=m['zero_rate'],
                    abc_class=ev['abc'].get('abc_class', ''),
                    value_share_pct_at_level=ev['abc'].get('value_share_pct'),
                    demand_class=m['demand_class'],
                    is_accepted=ev.get('is_accepted', False),
                    rejection_reason=ev.get('rejection_reason', ''),
                    recommended_strategy=m.get('recommended_strategy', ''),
                )
            )

        # Build SeriesProfile summary
        chosen_m = chosen['metrics'] if chosen else {}
        atom_rows = df_atomic[
            (df_atomic['item_id'] == item_id) &
            (df_atomic['planning_location_id'] == loc_id) &
            (df_atomic['cust_code'] == cust_code)
        ]
        atom_qty = _qty_series(atom_rows, all_periods)
        atom_m   = _classify(atom_qty)
        atom_val = _value_series(atom_rows)
        atom_abc = _compute_abc_at_level(atom_val, df_atomic)

        profiles_to_upsert.append({
            'client_id':             client_id,
            'item_id':               item_id,
            'planning_customer_id':  cust_id_int,
            'planning_location_id':  int(loc_id),
            'period_type':           period_type,
            'analysis_from':         analysis_from,
            'analysis_to':           analysis_to,
            'total_periods':         atom_m['total_periods'],
            'nonzero_periods':       atom_m['nonzero_periods'],
            'total_qty':             atom_m['total_qty'],
            'total_value':           Decimal(str(round(atom_val, 2))),
            'adi':                   atom_m.get('adi'),
            'cv2':                   atom_m.get('cv2'),
            'zero_rate':             atom_m['zero_rate'],
            'demand_class_atomic':   atom_m['demand_class'],
            'abc_class_atomic':      atom_abc.get('abc_class', ''),
            'chosen_grain':          chosen['grain'] if chosen else '',
            'chosen_demand_class':   chosen_m.get('demand_class', ''),
            'chosen_strategy':       chosen_m.get('recommended_strategy', 'MANUAL'),
            'chosen_eval_period':    chosen.get('eval_period', period_type) if chosen else period_type,
        })

    # ── Persist ────────────────────────────────────────────────────────────────
    with transaction.atomic():
        SeriesLevelEvaluation.objects.filter(
            client_id=client_id, period_type=period_type
        ).delete()

        SeriesLevelEvaluation.objects.bulk_create(
            evaluations_to_create, batch_size=500, ignore_conflicts=True
        )

        # Re-query to get PKs (bulk_create doesn't return PKs on all DB backends)
        eval_pk_map = {
            (e.item_id, e.grain, str(e.evaluation_key)): e.pk
            for e in SeriesLevelEvaluation.objects.filter(
                client_id=client_id, period_type=period_type, is_accepted=True
            )
        }

        for p in profiles_to_upsert:
            update_fields = {k: v for k, v in p.items()
                             if k not in ('client_id', 'item_id',
                                          'planning_customer_id',
                                          'planning_location_id', 'period_type')}
            # Find chosen_evaluation FK
            # (match by item_id + chosen_grain from accepted evaluations)
            chosen_eval_pk = eval_pk_map.get(
                (p['item_id'], p['chosen_grain'],
                 str({'grain': p['chosen_grain']}))
            )
            if chosen_eval_pk:
                update_fields['chosen_evaluation_id'] = chosen_eval_pk

            SeriesProfile.objects.update_or_create(
                client_id=p['client_id'],
                item_id=p['item_id'],
                planning_customer_id=p['planning_customer_id'],
                planning_location_id=p['planning_location_id'],
                period_type=p['period_type'],
                defaults=update_fields,
            )

    from collections import Counter
    grain_counts = Counter(p['chosen_grain'] for p in profiles_to_upsert)
    class_counts = Counter(p['demand_class_atomic'] for p in profiles_to_upsert)
    logger.info(
        f'compute_series_profiles: client={client_id} '
        f'total={len(profiles_to_upsert)} '
        f'chosen_grain={dict(grain_counts)} '
        f'atomic_class={dict(class_counts)}'
    )
```

---

## 8. Migration

```bash
python manage.py makemigrations mysite \
    --name forecasting_config_abc_defs_series_level_eval
python manage.py migrate
python manage.py check
```

**New tables:**
- `mysite_forecastingconfig` — one row per client, ADI/CV²/time thresholds
- `mysite_abcclassdefinition` — subtable, N rows per client defining ABC tiers
- `mysite_seriesleveleval` — one row per (item, grain evaluated), full audit

**Modified table:**
- `mysite_seriesprofile` — new fields: `chosen_evaluation_id`,
  `chosen_grain`, `chosen_demand_class`, `chosen_strategy`,
  `chosen_eval_period`, `demand_class_atomic`, `abc_class_atomic`,
  `total_value`, `override_grain`, `override_set_by_id`, `override_set_at`

**Notes for Sprint 3B.4:**
The task receives `SeriesProfile.effective_grain` and
`SeriesProfile.effective_eval_period`. The grain string is sufficient
to know WHAT to aggregate and at WHAT time bucket. No hardcoded level
names exist in the forecast engine — it reads grain strings produced
here and acts accordingly.
