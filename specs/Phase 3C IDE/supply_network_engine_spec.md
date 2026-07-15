# Supply Network & Replenishment Demand Propagation — Engine Spec

## Context

The platform maintains material stocking points in a multi-tier structure: **HO → DC → Location**.
Two hierarchies coexist over the same node set and must be kept structurally separate:

1. **Sales/Forecast Hierarchy** — Total → Region → Branch → Location. Used for statistical
   forecasting and revenue-share disaggregation. Relatively static, geography/org-driven.
2. **Supply Network** — Vendor → HO → DC → Location. Used for replenishment/sourcing. This is
   **item-specific, time-dependent, and may diverge in shape from the sales hierarchy** at any node
   (e.g. an item sold HO→Customer directly, HO→DC for some DCs, Vendor→DC directly for others).

Do not conflate these two structures or let them share a parent-link field. The replenishment
engine must resolve demand by walking the **Supply Network**, using FCST values that live on the
**Sales Hierarchy**.

---

## Two-Stage Forecasting

- **Stage 1 — `SALES_CONSENSUS`**: consensus forecast owned by the sales team, generated/reviewed
  independently at each node. May be optimistic and is not guaranteed additive
  (`FCST(parent) ≠ Σ FCST(children)` is expected and acceptable here).
- **Stage 2 — `OPERATING_PLAN`**: derived from Stage 1 by applying a planner-set
  `ForecastNormalizationFactor` at an anchor node (commonly HO, but any node), then **cascading
  down using the existing revenue-share disaggregation logic** already used for
  Total→Region→Branch→Item. Because child-node numbers are *derived* from the parent via fixed
  shares, additivity holds by construction unless a planner manually overrides a specific node
  (flag such overrides with `is_manual_override` for audit).

**The Supply Network resolution and replenishment engine must consume `OPERATING_PLAN` exclusively.**
`SALES_CONSENSUS` is never a direct input to supply planning — it feeds Stage 2 and separately
serves sales target-setting.

Residual non-additivity (from manual overrides) is NOT silently clamped to zero. It is written to
a `ForecastReconciliationException` record and surfaced to planners.

---

## Master Data: Supply Network Rules (generic → specific, with split sourcing)

Full item × location assignment (20K+ items) is not maintainable as flat rows. Use a
condition-technique / access-sequence approach, reusing the existing `Taxonomy`/`TaxonomyNode`
materialized-path pattern (same mechanism as Phase 2's dynamic taxonomy filter injection).

**Resolution priority (most specific wins, evaluated per item + location + date):**
1. `scope_type = ITEM` — exact item + location match
2. `scope_type = TAXONOMY` — walk the item's taxonomy path from its own node to root; deepest
   ancestor with a matching rule for that location wins
3. `scope_type = ALL` — location-wide default (e.g. "all items at Location A ← DC1")
4. No match at any level → hard validation error, never a silent fallback

**Split sourcing**: a scope key + location may resolve to multiple rows (e.g. 60% from HO, 40%
directly from Vendor), each carrying an `allocation_pct`. All legs for a given resolution must come
from the **same scope level** (never mix an ITEM-level leg with a TAXONOMY-level leg for the same
resolution — keeps audit and maintenance tractable). `Σ allocation_pct` across legs must equal
100%; validate on save AND via a periodic integrity job (since a rule's `valid_to` lapsing can
silently break a previously-valid split without any row being edited).

**Performance**: never resolve rules at run time. Materialize resolution nightly (or on rule
change) into a `ResolvedSupplySource` cache table — one row per allocation leg — carrying an FK
back to the originating rule for audit ("why is Item X at Location A 40% Vendor-sourced?"). The
replenishment engine reads only from this cache table.

---

## Replenishment Demand Propagation

For each node N in the sales hierarchy, using `OPERATING_PLAN` FCST and `ResolvedSupplySource`
allocations:

```
NetOwnDemand(N) = FCST(N) − Σ [ FCST(C) × alloc_pct(C → X)
                                  for C in sales_children(N)
                                  for X in resolved_sources(C)
                                  where X != N ]          # every leg of every child NOT sourced from N

For each resolved source X of N (with its own allocation_pct share of N's total requirement):
    RR(N, via X) = ( NetOwnDemand(N)
                    + Σ [ RR(C, via N) for C in sales_children(N) where N ∈ resolved_sources(C) ] )
                    × allocation_pct(N → X)
```

This generalizes to arbitrary depth and arbitrary bypass patterns — it does not assume single-level
bypass, and it does not assume the sales hierarchy and supply network are congruent below the point
of divergence.

**Conservation invariant** (run as a regression test after every engine change):
```
Σ RR at every vendor-facing leg across the network  ==  Σ FCST (OPERATING_PLAN) at every end node
```
A violation indicates either a resolution bug (item/location falling through all three scope
levels) or a bypass-detection bug — not a data anomaly to be tolerated.

### Worked example
- HO `OPERATING_PLAN` FCST = 300
- DC1 FCST = 200, sourced 60% HO / 40% Vendor
- DC2 FCST = 100, sourced 100% Vendor

```
bypass(DC1) = 200 × 0.40 = 80
bypass(DC2) = 100 × 1.00 = 100
NetOwnDemand(HO) = 300 − 80 − 100 = 120

RR(DC1, via HO)     = 200 × 0.60 = 120   → HO supplies DC1: 120
RR(DC1, via Vendor) = 200 × 0.40 = 80    → DC1 orders Vendor: 80
RR(DC2, via Vendor) = 100                → DC2 orders Vendor: 100
RR(HO, via Vendor)  = (120 + 120) = 240  → HO orders Vendor: 240

Check: 240 + 80 + 100 = 420  ==  120 + 200 + 100 = 420 ✓
```

---

## Rounding

`allocation_pct` is stored and computed as an exact decimal. Rounding to integer/pack quantities
happens only at the final conversion of `RR × allocation_pct` into an actual order/transfer
quantity, using largest-remainder allocation, with the rule's `priority` field as tie-breaker for
where any remainder unit goes.

---

## Engine Interfaces (data the Inventory Decision Engine consumes)

- `ResolvedSupplySource(item, location, effective_date, source_type, source_node/vendor, allocation_pct, resolved_rule)`
- `NodeReplenishmentRequirement(item, node, date, source_leg, quantity)` — output of the propagation
  step above; one row per (node, source leg) pair; this is the actual input to buffer sizing / net
  flow equation / PO-vs-transfer-order determination.
- `ForecastReconciliationException(item, node, forecast_version, computed_net_demand, status)` —
  surfaced to planners, not auto-resolved.

Do not let the Inventory Decision Engine read `SALES_CONSENSUS` forecasts or raw
`SupplyNetworkRule` rows directly — it should only ever touch `OPERATING_PLAN` forecasts and the
materialized `ResolvedSupplySource` / `NodeReplenishmentRequirement` tables.

---

## MRP-Style Netting (Gross Requirement → Net Requirement)

Propagation (above) produces gross requirement at each node. This must be netted against live
transactional supply position — data the application does not own, since it is a standalone
service. The client must supply this via a versioned snapshot before every run.

```
Net Requirement(item, node, date) = Gross Requirement(item, node, date)
                                   − On Hand Available (unrestricted)
                                   − Scheduled Receipts (Open PO + Open STO due before/at date)
                                   + Committed Demand not yet reflected in Gross Requirement (open SO)
```

### Ingestion data structures

**Snapshot envelope** — every ingestion is versioned, never silently overwritten:
- `SupplyPositionSnapshot`: `client`, `snapshot_id` (UUID), `as_of_datetime` (client's clock, not
  upload time), `received_at`, `source_system`, `status` (RECEIVED → VALIDATED → APPLIED /
  REJECTED), `is_full_snapshot`, `supersedes` (self-FK for deltas).

**Stock on hand** — flat, no lot/batch detail unless quality-hold materially affects availability:
- `StockOnHand`: `snapshot`, `item`, `node`, `qty_unrestricted`, `qty_blocked`,
  `qty_in_transit_to_node`. Only `qty_unrestricted` feeds netting; `qty_blocked` explains apparent
  shortages to planners. Unique on `(snapshot, item, node)`.

**Open supply** — unified table for PO/STO/WO, discriminated by type (both are "receipts expected
at this node by this date"):
- `OpenSupply`: `snapshot`, `supply_type` (PO/STO/WO), `external_doc_number`,
  `external_line_number`, `item`, `receiving_node`, `source_node` (STO only), `vendor` (PO only),
  `order_qty`, `received_qty`, `open_qty`, `expected_receipt_date`, `order_status`. Unique on
  `(snapshot, supply_type, external_doc_number, external_line_number)`.

**Open demand commitment** — optional per client; only needed at nodes with direct customer
commitments not yet reflected in `OPERATING_PLAN` FCST:
- `OpenDemandCommitment`: `snapshot`, `item`, `node`, `committed_qty`, `required_date`,
  `external_doc_number`. If a client cannot cleanly separate "committed but not yet in forecast"
  from "already in forecast," exclude this table rather than forcing a bad feed.

### Ingestion contract
- Bulk-ingest via DRF endpoints per entity type (or one composite payload). Validate structurally
  at ingestion (item/node codes resolve, quantities non-negative, dates parseable) and **reject the
  whole snapshot on failure** — never partially apply a snapshot.
- A Celery task materializes a `VALIDATED` snapshot into a denormalized item×node netting-ready
  structure; the netting run never queries raw ingestion tables directly.
- Snapshot `status` transitions let the client poll/confirm acceptance before assuming a run
  reflects their data.

### Reducing data load
1. **Time fencing (highest impact, apply first)** — full open-supply/on-hand detail is only needed
   within a netting horizon = lead time + review period + safety margin. Beyond the fence, an
   aggregated "total qty due after fence date" per item-node suffices; no netting decision in this
   run depends on receipts that far out.
2. **Delta/CDC feed** — persist last-applied position per item-node; client sends only changes
   since the last successful snapshot, with a periodic (nightly/weekly) full reconciliation
   snapshot to catch drift. Treat as a v2 optimization, not a day-one build.
3. **Sparse transmission** — omit item-node rows with zero on-hand and no open supply; most of a
   20K-item catalogue is sparse at any given node.
4. **Frequency tiering by ABC/demand-pattern class** — A-class/fast-movers feed daily; C-class/slow
   movers can run on a 3–7 day cycle without materially affecting decision quality.
5. **Filter the expected-feed manifest** by active `ItemPlanningProfile` — don't ask for position
   data on inactive/discontinued/non-stocked item-node combinations at all.

---

## Vendor Discount Schemes & Carrying/Dead-Stock Cost

Order quantity is not simply the net requirement — vendor discount slabs may justify ordering
above it, but only if the carrying/dead-stock cost of the resulting excess doesn't outweigh the
saving. This requires a cost master, a vendor scheme master (SAP-style access sequence), and a
breakpoint evaluation that trades the two off.

### Carrying / dead-stock cost master

Reuse existing ABC classification and Syntetos-Boylan demand-pattern classification as the grid
axes — do not invent a new classification.

- `InventoryCarryingCostRate`: `client`, `abc_class`, `demand_pattern_class`
  (STABLE/INTERMITTENT/ERRATIC/LUMPY), `annual_carrying_cost_pct` (cost of capital + storage +
  insurance + baseline obsolescence, % of item value/year), `valid_from`/`valid_to`. Unique on
  `(client, abc_class, demand_pattern_class, valid_from)`.
- `ExcessInventoryPenaltyTier`: additional dead-stock surcharge layered on top of the base rate
  once stock ages past normal cycle expectations — `client`, `abc_class`, `demand_pattern_class`,
  `age_bucket_from_days`, `age_bucket_to_days` (null = unbounded), `additional_annual_pct`,
  `valid_from`/`valid_to`.

Effective daily holding cost per unit = `item_value × (annual_carrying_cost_pct + applicable
ExcessInventoryPenaltyTier) / 365`. C-class/Lumpy items must carry a materially higher rate than
A-class/Stable — this differential is what discourages bulk-ordering slow, erratic items even when
a vendor slab looks attractive.

### Vendor scheme master — access sequence

Two structurally different categories; do not conflate them:
- **Transactional** — applies at order time, directly changes unit cost for *this* PO (qty/value
  slabs, brand-specific, sub-brand-specific, item-specific). Resolved via generic→specific access
  sequence, **exclusive** — most specific scope wins.
- **Rebate** — cumulative, long-term (quarterly/annual), settled after the fact. Cannot be resolved
  to an exact discount at transaction time. Always **additive** on top of the transactional
  scheme — never competes with it in the same resolution.

```python
class VendorScheme(models.Model):
    CATEGORY_CHOICES = [('TRANSACTIONAL', 'Transactional'), ('REBATE', 'Rebate')]
    SCHEME_TYPE_CHOICES = [
        ('QTY_SLAB', 'Quantity Slab'), ('VALUE_SLAB', 'Value Slab'),
        ('FLAT_PCT', 'Flat Percent Off'), ('CUMULATIVE_REBATE', 'Cumulative Rebate'),
    ]
    BASIS_CHOICES = [('PER_ORDER', 'Per Order'), ('MTD', 'Month to Date'),
                      ('QTD', 'Quarter to Date'), ('YTD', 'Year to Date'), ('CUSTOM', 'Custom Period')]
    client = models.ForeignKey(ClientProfile, on_delete=models.CASCADE)
    vendor = models.ForeignKey('Vendor', on_delete=models.CASCADE)
    scheme_code = models.CharField(max_length=30)
    category = models.CharField(max_length=15, choices=CATEGORY_CHOICES)
    scheme_type = models.CharField(max_length=20, choices=SCHEME_TYPE_CHOICES)
    computation_basis = models.CharField(max_length=10, choices=BASIS_CHOICES, default='PER_ORDER')
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=15, default='ACTIVE')  # DRAFT, ACTIVE, EXPIRED

class VendorSchemeScope(models.Model):
    """Access-sequence condition table: generic -> specific, same pattern as SupplyNetworkRule."""
    SCOPE_CHOICES = [('OVERALL', 'Overall'), ('TAXONOMY', 'Brand/Sub-brand'), ('ITEM', 'Item')]
    scheme = models.ForeignKey(VendorScheme, on_delete=models.CASCADE, related_name='scopes')
    scope_type = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    taxonomy_node = models.ForeignKey(TaxonomyNode, null=True, blank=True, on_delete=models.CASCADE)
    item = models.ForeignKey(GlobalItem, null=True, blank=True, on_delete=models.CASCADE)
    # brand vs sub-brand is just depth in the taxonomy path — no separate field needed

class VendorSchemeSlab(models.Model):
    scope = models.ForeignKey(VendorSchemeScope, on_delete=models.CASCADE, related_name='slabs')
    slab_from = models.DecimalField(max_digits=14, decimal_places=2)
    slab_to = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    discount_amount_per_unit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
```

**Resolution**: item-specific scope first, then taxonomy path from the item's own node to root
(covers sub-brand before brand), then `OVERALL` — same deepest-match-wins walk as
`SupplyNetworkRule`/taxonomy filter injection. Materialize into `ResolvedVendorScheme`, refreshed
on scheme change, never resolved per order at run time.

### Rebate accrual and the "median" estimate

A rebate's true value is only known at period close; track accrual progress and derive an
estimated effective rate rather than guessing fresh each time:

- `VendorRebateAccrual`: `scheme`, `vendor`, `period_start`, `period_end`,
  `cumulative_value_to_date`, `cumulative_qty_to_date` (client-fed periodically, or accumulated
  from `OpenSupply`/GRN data), `estimated_effective_discount_pct`, `actual_settled_discount_pct`
  (null until period close), `settled_at`.

Compute `estimated_effective_discount_pct` as the **median** (not mean — robust to one unusually
good/bad quarter) of `actual_settled_discount_pct` across the last 3–4 settled periods for that
vendor+scheme, via a scheduled job. Use this as a flat reduction to landed cost in order-qty
evaluation — it should influence vendor selection and cost comparisons, not by itself trigger
bulk-ordering to chase a rebate threshold (treat rebate-threshold-chasing as a separate, longer-
horizon decision if supported at all; do not fold it into the netting run).

### Order-quantity breakpoint evaluation

Evaluated after MRP netting produces `base_qty` (net requirement), at each vendor slab breakpoint
above it:

```
base_qty = Net Requirement (from netting step)
base_unit_cost = resolved transactional scheme discount applied at base_qty

For each slab breakpoint B > base_qty (from resolved VendorSchemeSlab, ascending):
    excess_qty = B − base_qty
    expected_holding_days = excess_qty / periodic_consumption_rate(item, node)   # from OPERATING_PLAN FCST
    daily_carrying_cost = item_value × (carrying_pct + excess_penalty_pct) / 365
    incremental_carrying_cost = excess_qty × daily_carrying_cost × expected_holding_days / 2
        # /2 because excess draws down toward zero over the holding period, not held at peak throughout
    discount_saving = (base_unit_cost − unit_cost_at(B)) × B
    net_benefit(B) = discount_saving − incremental_carrying_cost

Choose qty = argmax over {base_qty, all breakpoints} of net_benefit; default to base_qty if all net_benefit(B) <= 0
```

Apply `estimated_effective_discount_pct` (rebate) as a further flat reduction to `unit_cost_at(B)`
uniformly across all candidate breakpoints — it doesn't change the shape of the trade-off but does
lower effective landed cost for downstream vendor-comparison/margin calculations.

**Guardrails:**
- Cap `expected_holding_days` at the item's max shelf-life or a configurable ceiling — unbounded
  holding horizons will produce absurd order quantities for very slow movers.
- Treat MOQ, warehouse capacity at the node, and cash/budget ceiling as **filters on the candidate
  breakpoint set**, never as inputs to the cost formula itself.
- Log the chosen breakpoint's `discount_saving`, `incremental_carrying_cost`, and `net_benefit` per
  order line — planners need this reasoning visible before trusting an engine-driven quantity bump.

