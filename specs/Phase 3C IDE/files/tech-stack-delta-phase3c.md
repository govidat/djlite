# Tech Stack — Delta Updates (Phase 3C)

Apply these changes to `tech-stack.md`, after the "Phase 3B — Demand Planning Stack" section.

---

## Phase 3C — Inventory Decision Engine Stack

### New Python Packages

| Package | Version | Purpose |
|---------|---------|---------|
| `darts` | latest stable | Additional forecasting backend for TSB (Teunter-Syntetos-Babai) intermittent-demand models not in `statsforecast`; used alongside existing Croston/SBA from Phase 3B |
| `statsforecast` | already in 3B | Reused — Croston/SBA already wired for intermittent series |
| `numpy` | already present (transitive) | Explicit dependency — summing-matrix and netting arithmetic in `utils/ide/` |
| `pandas` | already in 3B | Reused for netting-matrix construction and vendor-slab evaluation |
| `polars` | already in 3B | Reused — DuckDB → Polars pull pattern for large item×node matrices |
| `duckdb` | already in 3B | Reused — in-process OLAP for propagation/netting joins over PostgreSQL tables |
| `celery` / `redis` | already present | Reused — netting runs, recommendation generation, materialization jobs |

**No new frontend framework.** Unlike Phase 3B's React SPA, the IDE frontend is **Django Templates +
Tailwind + DaisyUI + HTMX** — same stack as Phase 1/2/3A. This is a deliberate divergence from 3B:
planner workbenches are exception-review UIs (filtered tables, drill-down, approve/reject actions),
which fit the server-rendered + HTMX pattern better than a data-grid SPA. If a future workbench needs
AG-Grid-style bulk editing at scale, revisit per-workbench rather than defaulting the whole module to
SPA.

---

### Inventory Decision Engine Model Package Layout

```
mysite/models/
    ide/
        __init__.py
        classification.py    # (re-exports AbcClassDefinition / SEIL classifier from demand/)
        policy.py             # PolicyMatrix, ReviewPolicy, ReplenishmentPolicy, CoveragePolicy,
                              #   StockingPolicy, TransferPolicy, ServiceLevelPolicy
        supply_network.py     # SupplyNetworkRule, ResolvedSupplySource
        forecast_stage.py     # ForecastNormalizationFactor, ForecastReconciliationException
                              #   (extends demand/forecast.py's ForecastVersion with stage field)
        propagation.py        # NodeReplenishmentRequirement
        ingestion.py           # SupplyPositionSnapshot, StockOnHand, OpenSupply, OpenDemandCommitment
        inventory_position.py # InventoryPosition, DDMRP buffer zone fields
        vendor_scheme.py      # InventoryCarryingCostRate, ExcessInventoryPenaltyTier,
                              #   VendorScheme, VendorSchemeScope, VendorSchemeSlab,
                              #   ResolvedVendorScheme, VendorRebateAccrual
        recommendation.py     # ReplenishmentRecommendation, PlannerDecision
```

---

### Key Model Relationships (Phase 3C)

```
Client
  ├── ItemPlanningProfile (item, is_active_for_ide, ...)   ← filters the expected-feed manifest
  ├── PolicyMatrix (client, abc_class, demand_pattern_class)   ← 12 cells (reuses 3B's AbcClassDefinition
  │     ├── review_policy → ReviewPolicy                          + SEIL classifier as axes)
  │     ├── replenishment_policy → ReplenishmentPolicy
  │     ├── coverage_policy → CoveragePolicy
  │     ├── stocking_policy → StockingPolicy
  │     ├── transfer_policy → TransferPolicy
  │     ├── service_level_policy → ServiceLevelPolicy
  │     ├── forecast_trust_pct
  │     └── planner_approval_rule
  │
  ├── ForecastVersion (existing, Phase 3B)
  │     └── stage field added: SALES_CONSENSUS | OPERATING_PLAN
  ├── ForecastNormalizationFactor (version, anchor_node, factor, set_by, is_manual_override)
  ├── ForecastReconciliationException (item, node, forecast_version, computed_net_demand, status)
  │
  ├── SupplyNetworkRule (client, scope_type ITEM/TAXONOMY/ALL, taxonomy_node/item, location,
  │     valid_from, valid_to, source_type VENDOR/DC/LOCATION/HO, source_ref, allocation_pct)
  │     └── ResolvedSupplySource (item, location, effective_date, source_type, source_node/vendor,
  │           allocation_pct, resolved_rule FK)   ← materialized cache, never resolved at run time
  │
  ├── NodeReplenishmentRequirement (item, node, date, source_leg, quantity)
  │     ← output of demand propagation; sole input to buffer sizing / netting / PO-vs-transfer decision
  │
  ├── SupplyPositionSnapshot (client, snapshot_id UUID, as_of_datetime, received_at, source_system,
  │     status RECEIVED/VALIDATED/APPLIED/REJECTED, is_full_snapshot, supersedes self-FK)
  │     ├── StockOnHand (snapshot, item, node, qty_unrestricted, qty_blocked, qty_in_transit_to_node)
  │     ├── OpenSupply (snapshot, supply_type PO/STO/WO, external_doc_number, external_line_number,
  │     │     item, receiving_node, source_node, vendor, order_qty, received_qty, open_qty,
  │     │     expected_receipt_date, order_status)
  │     └── OpenDemandCommitment (snapshot, item, node, committed_qty, required_date, external_doc_number)
  │
  ├── InventoryPosition (item, node, date, on_hand, in_transit, net_requirement, min, max, rop,
  │     ddmrp_red, ddmrp_yellow, ddmrp_green, projected_inventory)
  │
  ├── InventoryCarryingCostRate (client, abc_class, demand_pattern_class, annual_carrying_cost_pct,
  │     valid_from, valid_to)
  │     └── ExcessInventoryPenaltyTier (client, abc_class, demand_pattern_class, age_bucket_from_days,
  │           age_bucket_to_days, additional_annual_pct, valid_from, valid_to)
  │
  ├── VendorScheme (client, vendor, scheme_code, category TRANSACTIONAL/REBATE,
  │     scheme_type QTY_SLAB/VALUE_SLAB/FLAT_PCT/CUMULATIVE_REBATE, computation_basis, valid_from,
  │     valid_to, status)
  │     ├── VendorSchemeScope (scheme, scope_type OVERALL/TAXONOMY/ITEM, taxonomy_node, item)
  │     │     └── VendorSchemeSlab (scope, slab_from, slab_to, discount_pct, discount_amount_per_unit)
  │     └── VendorRebateAccrual (scheme, vendor, period_start, period_end, cumulative_value_to_date,
  │           cumulative_qty_to_date, estimated_effective_discount_pct, actual_settled_discount_pct,
  │           settled_at)
  ├── ResolvedVendorScheme (materialized, same generic→specific pattern as ResolvedSupplySource)
  │
  └── ReplenishmentRecommendation (item, node, rec_type PURCHASE/TRANSFER/STOCKING/CENTRALIZATION/
        EMERGENCY/ALTERNATIVE_SUPPLY, recommended_qty, policy_cell FK, inputs JSONField,
        formula_used, trigger_reason, alternatives JSONField, expected_outcome JSONField, status)
        └── PlannerDecision (recommendation, decided_by, decision APPROVE/REJECT/MODIFY,
              modified_qty, decided_at, note)
```

---

### Forecast Consumption Rule (hard constraint)

The IDE **never reads `SALES_CONSENSUS` forecasts or raw `SupplyNetworkRule` rows directly**. It only
ever touches:
- `OPERATING_PLAN` forecast lines, and
- the materialized `ResolvedSupplySource` / `NodeReplenishmentRequirement` tables.

Enforce this at the query-layer boundary (`utils/ide/` functions accept a version already filtered to
`stage='OPERATING_PLAN'`; there is no code path that accepts a raw `SupplyNetworkRule` queryset).

---

### Supply Network Rule Resolution

Reuses the Phase 2 taxonomy materialized-path pattern (same mechanism as the dynamic taxonomy filter
injection built for the catalogue):

1. `scope_type = ITEM` — exact item + location match wins.
2. `scope_type = TAXONOMY` — walk the item's taxonomy path from its own node to root; deepest matching
   ancestor for that location wins.
3. `scope_type = ALL` — location-wide default.
4. No match at any level → **hard validation error**, never a silent fallback.

All legs of a split-sourcing resolution must come from the same scope level (never mix an ITEM-level
leg with a TAXONOMY-level leg in one resolution). `Σ allocation_pct` across legs must equal 100% —
validated on save **and** via a periodic integrity job (a rule's `valid_to` lapsing can silently break
a previously-valid split without any row being edited).

Resolution is **never computed at run time** — materialized nightly (or on rule change) into
`ResolvedSupplySource`, one row per allocation leg, carrying an FK back to the originating
`SupplyNetworkRule` for audit.

---

### Demand Propagation Algorithm

```
NetOwnDemand(N) = FCST(N) − Σ [ FCST(C) × alloc_pct(C → X)
                                  for C in sales_children(N)
                                  for X in resolved_sources(C)
                                  where X != N ]

For each resolved source X of N:
    RR(N, via X) = ( NetOwnDemand(N)
                    + Σ [ RR(C, via N) for C in sales_children(N) where N ∈ resolved_sources(C) ] )
                    × allocation_pct(N → X)
```

Generalizes to arbitrary depth and arbitrary bypass patterns; does not assume the sales hierarchy and
supply network are congruent below the point of divergence.

**Conservation invariant** (regression test run after every engine change):
`Σ RR at every vendor-facing leg == Σ FCST (OPERATING_PLAN) at every end node`. A violation indicates a
resolution bug, not a data anomaly — never silently tolerated.

---

### MRP-Style Netting

```
Net Requirement(item, node, date) = Gross Requirement(item, node, date)   ← from NodeReplenishmentRequirement
                                   − On Hand Available (qty_unrestricted)
                                   − Scheduled Receipts (Open PO + Open STO due before/at date)
                                   + Committed Demand not yet reflected in Gross Requirement (open SO)
```

**Ingestion contract:** bulk-ingest per entity type (or one composite payload) via DRF endpoints.
Validate structurally at ingestion (item/node codes resolve, quantities non-negative, dates
parseable) and **reject the whole snapshot on failure** — never partially apply. A Celery task
materializes a `VALIDATED` snapshot into a denormalized item×node netting-ready structure; the
netting run never queries raw ingestion tables directly.

**Reducing data load** (apply in this priority order):
1. **Time fencing** — full on-hand/open-supply detail only needed within `lead_time + review_period +
   safety_margin`; beyond that, an aggregated "total qty due after fence date" per item-node suffices.
2. **Delta/CDC feed** — v2 optimization; persist last-applied position, client sends only changes since
   last successful snapshot plus a periodic full reconciliation snapshot.
3. **Sparse transmission** — omit item-node rows with zero on-hand and no open supply.
4. **Frequency tiering by ABC/demand-pattern class** — A-class feeds daily; C-class can run 3–7 day
   cycles.
5. **Filter the expected-feed manifest** by active `ItemPlanningProfile` — never request position data
   for inactive/discontinued/non-stocked item-node combinations.

---

### Vendor Scheme & Order-Quantity Breakpoint Evaluation

Order quantity is evaluated **after** MRP netting produces `base_qty`, at each vendor slab breakpoint
above it:

```
For each slab breakpoint B > base_qty (ascending):
    excess_qty = B − base_qty
    expected_holding_days = excess_qty / periodic_consumption_rate(item, node)   # from OPERATING_PLAN FCST
    daily_carrying_cost = item_value × (carrying_pct + excess_penalty_pct) / 365
    incremental_carrying_cost = excess_qty × daily_carrying_cost × expected_holding_days / 2
    discount_saving = (base_unit_cost − unit_cost_at(B)) × B
    net_benefit(B) = discount_saving − incremental_carrying_cost

Choose qty = argmax over {base_qty, all breakpoints} of net_benefit; default to base_qty if all <= 0
```

`estimated_effective_discount_pct` (rebate, computed as the **median** — not mean — of the last 3–4
settled periods' `actual_settled_discount_pct`) is applied as a further flat reduction to
`unit_cost_at(B)` uniformly across candidates; it changes landed cost, not the shape of the trade-off,
and never by itself triggers bulk-ordering to chase a threshold.

**Guardrails:** cap `expected_holding_days` at item max shelf-life or a configurable ceiling. Treat
MOQ, warehouse capacity, and cash/budget ceiling as **filters on the candidate breakpoint set**, never
as inputs to the cost formula. Log `discount_saving`, `incremental_carrying_cost`, and `net_benefit`
per order line on the `ReplenishmentRecommendation` — planners need this visible before trusting an
engine-driven quantity bump.

---

### Explainability Contract

Every `ReplenishmentRecommendation` row persists, at write time (not reconstructed later):
`inputs` (JSONField — the actual values consumed), `policy_cell` (FK to the `PolicyMatrix` cell that
fired), `formula_used` (identifies which formula path executed — e.g. `ROP`, `DDMRP`,
`ORDER_UP_TO_COVERAGE`), `trigger_reason`, `alternatives` (JSONField — other candidate options
considered and why they lost), `expected_outcome` (JSONField).

---

### Database Indexes (Phase 3C)

```sql
-- Supply network resolution cache lookups
CREATE INDEX ix_resolvedsupplysource_item_location
    ON mysite_resolvedsupplysource (item_id, location_id, effective_date);

-- Replenishment requirement lookups by node/date
CREATE INDEX ix_nodereplenishmentrequirement_node_date
    ON mysite_nodereplenishmentrequirement (node_id, item_id, date);

-- Snapshot-scoped netting inputs
CREATE INDEX ix_stockonhand_snapshot_item_node
    ON mysite_stockonhand (snapshot_id, item_id, node_id);

CREATE INDEX ix_opensupply_snapshot_item_node
    ON mysite_opensupply (snapshot_id, item_id, receiving_node_id, expected_receipt_date);

-- Recommendation queue for planner workbenches
CREATE INDEX ix_replenishmentrecommendation_status_client
    ON mysite_replenishmentrecommendation (client_id, status, rec_type);

-- Vendor scheme resolution
CREATE INDEX ix_resolvedvendorscheme_item_vendor
    ON mysite_resolvedvendorscheme (item_id, vendor_id, effective_date);
```

---

### REST API Endpoints (Phase 3C, under `mysite/api/ide/`)

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/supply-network-rules/` | GET, POST | CRUD on `SupplyNetworkRule`; triggers re-resolution on save |
| `/resolved-supply-source/` | GET | Read-only materialized cache, filterable by item/location |
| `/forecast-versions/{id}/operating-plan/` | GET, POST | Apply `ForecastNormalizationFactor`; cascade |
| `/reconciliation-exceptions/` | GET | `ForecastReconciliationException` queue |
| `/policy-matrix/` | GET, POST | CRUD on 12-cell `PolicyMatrix` per client |
| `/snapshots/` | POST | Bulk ingest `SupplyPositionSnapshot` + child entities (composite payload) |
| `/snapshots/{id}/` | GET | Poll snapshot status (RECEIVED → VALIDATED → APPLIED/REJECTED) |
| `/inventory-position/` | GET | Filtered `InventoryPosition` query (item, node, date range) |
| `/vendor-schemes/` | GET, POST | CRUD on `VendorScheme` + nested scopes/slabs |
| `/recommendations/` | GET | Filtered `ReplenishmentRecommendation` queue for a workbench |
| `/recommendations/{id}/decide/` | POST | Records `PlannerDecision` (approve/reject/modify) |

Authentication: DRF Session Auth, consistent with server-rendered HTMX frontend (no separate SPA auth
concern here, unlike Phase 3B's React SPA).

---

### Caching (Phase 3C additions)

| Cache key | Content | TTL | Invalidated by |
|-----------|---------|-----|----------------|
| `resolved_supply_source:{client_id}` | Materialized supply-source cache | Until nightly job / rule change | Celery beat job; post_save on `SupplyNetworkRule` |
| `resolved_vendor_scheme:{client_id}` | Materialized vendor-scheme resolution | Until scheme change | post_save on `VendorScheme`/`VendorSchemeSlab` |
| `policy_matrix:{client_id}` | 12-cell policy matrix | 1 hour | post_save on `PolicyMatrix` |
| `carrying_cost_rate:{client_id}` | `InventoryCarryingCostRate` + penalty tiers | 1 hour | post_save on either model |

---

### Background Tasks (Celery)

| Task | Trigger | Notes |
|------|---------|-------|
| `resolve_supply_network(client_id)` | Nightly beat + `SupplyNetworkRule` post_save | Materializes `ResolvedSupplySource`; runs the `Σ allocation_pct == 100%` integrity check |
| `resolve_vendor_schemes(client_id)` | Nightly beat + `VendorScheme` post_save | Materializes `ResolvedVendorScheme` |
| `cascade_operating_plan(version_id)` | Planner sets `ForecastNormalizationFactor` | Applies factor at anchor node, cascades via revenue-share disaggregation, writes `ForecastReconciliationException` for non-additive manual overrides |
| `propagate_replenishment_demand(client_id, version_id)` | Scheduled per client review cadence (`MAX(policy_frequency, data_refresh_frequency)`) | Runs the NetOwnDemand/RR algorithm; writes `NodeReplenishmentRequirement`; runs conservation-invariant check |
| `ingest_supply_position_snapshot(snapshot_id)` | Snapshot POST | Validates structurally; rejects whole snapshot on any row failure; materializes denormalized netting-ready structure on success |
| `run_netting(client_id, snapshot_id)` | Snapshot `APPLIED` + propagation complete | Computes `Net Requirement` per item×node; writes `InventoryPosition` |
| `evaluate_vendor_breakpoints(recommendation_id)` | Netting produces `base_qty` > 0 for a PURCHASE candidate | Runs the breakpoint trade-off; attaches chosen qty + reasoning to the recommendation |
| `generate_recommendations(client_id)` | After netting + breakpoint evaluation | Applies `PolicyMatrix` cell logic per SKU-location; writes `ReplenishmentRecommendation` with full explainability payload |
| `compute_rebate_accrual_estimate(scheme_id)` | Scheduled (period close cadence) | Recomputes `estimated_effective_discount_pct` as median of last 3–4 settled periods |

---

### `ClientFeatureControl` Keys Added (Phase 3C)

`inventory_decision_engine`, `supply_network_rules`, `ddmrp`, `vendor_schemes`, `planner_workbenches`.

---

### Folder structure additions

```
mysite/
├── models/
│   └── ide/                       # per model package layout above
├── api/
│   └── ide/
│       ├── urls.py
│       └── views.py
├── ide_ui/                        # Django-template + HTMX planner workbenches (NOT a React SPA)
│   ├── urls.py
│   ├── views.py
│   └── views_htmx.py
├── tasks/
│   └── ide/
│       ├── resolve_supply_network.py
│       ├── propagate_demand.py
│       ├── ingest_snapshot.py
│       ├── run_netting.py
│       ├── evaluate_vendor_breakpoints.py
│       └── generate_recommendations.py
├── templates/
│   └── ide/
│       ├── dashboard.html
│       ├── workbenches/
│       │   ├── service_risk.html
│       │   ├── replenishment.html
│       │   ├── transfer.html
│       │   ├── inventory_balancing.html
│       │   ├── vendor_scheme.html
│       │   ├── exception_management.html
│       │   └── policy_governance.html
│       └── partials/
├── static/
│   └── ide/
└── utils/
    └── ide/
        ├── supply_network_resolver.py
        ├── propagation_engine.py
        ├── netting_engine.py
        ├── vendor_breakpoint_evaluator.py
        └── recommendation_engine.py
```
