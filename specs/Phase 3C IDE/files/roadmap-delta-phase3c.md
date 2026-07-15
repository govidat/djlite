# Roadmap — Delta Update (Phase 3C)

Apply after "Phase 3B — Demand Planning" and before "Phase 3 — eCommerce" (or after Phase 3A,
sequencing note below). This section is the **Project Plan** for Phase 3C — use it as the source to
generate detailed step-by-step sprint instructions.

---

## Phase 3C — Inventory Decision Engine (IDE)

**Goal:** Convert inventory position, demand classification, `OPERATING_PLAN` forecasts, and supply-
network data into ranked, explainable replenishment / transfer / stocking / centralization
recommendations. Planners work exception workbenches instead of reviewing individual SKUs.

Phase 3C consumes `Item`, `ClientLocation`, `Taxonomy`/`TaxonomyNode` (Phase 2) and `ForecastVersion`/
`ForecastLine`/`AbcClassDefinition`/SEIL classification (Phase 3B) as foreign keys and reused logic. It
does **not** depend on Phase 3A (eCommerce) — the two are independent consumers of the same master
data. It adds a new `ide/` model package and a Django-template + HTMX frontend (not a React SPA).

**Recommended sequencing relative to 3A:** Phase 3C can run in parallel with Phase 3A once Phase 3B's
`OPERATING_PLAN`-capable forecast infrastructure exists (3C.2 depends on 3B.3/3B.4, not on any 3A
sprint). A later integration sprint (3C.12, optional) wires an approved `ReplenishmentRecommendation`
into a 3A `Order` — that is the only point of contact between the two phases.

---

### Sprint 3C.0 — Foundation and Prerequisites

- [ ] Add `darts` to `requirements.txt` (TSB model, alongside 3B's Croston/SBA in `statsforecast`)
- [ ] Add `ClientFeatureControl` keys: `inventory_decision_engine`, `supply_network_rules`, `ddmrp`,
      `vendor_schemes`, `planner_workbenches`
- [ ] Create `mysite/models/ide/` package (empty `__init__.py` + module stubs per tech-stack layout)
- [ ] Create `ItemPlanningProfile(client, item, is_active_for_ide, lead_time_days, shelf_life_days)` —
      filters which item×node combinations the engine plans for at all
- [ ] `python manage.py makemigrations && migrate`
- [ ] `python manage.py check` — 0 issues
- [ ] Confirm `AbcClassDefinition` and SEIL classifier from 3B are importable/reusable without
      modification — do **not** create a parallel classification model

---

### Sprint 3C.1 — Policy Framework and Policy Matrix

- [ ] Create `mysite/models/ide/policy.py`:
  - `ReviewPolicy(client, name, review_type CONTINUOUS/TIME_BASED, frequency_minutes)` — frequency
    choices span 15 min through Quarterly per spec
  - `ReplenishmentPolicy(client, name, policy_type ROP/MIN_MAX/DDMRP/ORDER_UP_TO/BUY_TO_ORDER/
    TRANSFER_FIRST/CENTRALIZED/EMERGENCY/MANUAL, hybrid_config JSONField)`
  - `CoveragePolicy(client, name, coverage_days)` — 1–180 configurable
  - `StockingPolicy(client, name, strategy LOCAL/CENTRALIZED/DC/VENDOR_DIRECT/TRANSFER_FIRST/
    EMERGENCY/NON_STOCK/BUY_TO_ORDER)`
  - `TransferPolicy(client, name, transfer_strategy JSONField)`
  - `ServiceLevelPolicy(client, name, target_fill_rate_pct)`
  - `PolicyMatrix(client, abc_class, demand_pattern_class, review_policy FK, replenishment_policy FK,
    coverage_policy FK, safety_stock_logic, stocking_policy FK, transfer_policy FK,
    service_level_policy FK, forecast_trust_pct, planner_approval_rule)` — unique on
    `(client, abc_class, demand_pattern_class)`, 12 rows per client
- [ ] Seed migration / management command: `seed_default_policy_matrix(client_id)` — loads the
      reference matrix from the spec (A×Smooth = Continuous/Min-Max/30d ... C×Lumpy = Buy-to-Order/
      Emergency Stock at HO) as the out-of-box default, editable per client
- [ ] Effective review frequency resolver: `resolve_review_frequency(policy, data_refresh_frequency)`
      → `MAX(policy_frequency, data_refresh_frequency)`
- [ ] Admin: `PolicyMatrixAdmin` (12-cell grid display), inlines for each policy sub-type
- [ ] REST endpoint: `GET/POST /api/ide/policy-matrix/`
- [ ] Unit tests: matrix uniqueness constraint; seed command produces 12 rows; frequency resolver
      picks the max of the two inputs

---

### Sprint 3C.2 — Two-Stage Forecasting (`SALES_CONSENSUS` → `OPERATING_PLAN`)

- [ ] Migration: add `stage` field (`SALES_CONSENSUS` / `OPERATING_PLAN`) to Phase 3B's
      `ForecastVersion`; existing 3B versions default to `SALES_CONSENSUS`
- [ ] Create `mysite/models/ide/forecast_stage.py`:
  - `ForecastNormalizationFactor(version, anchor_node, factor, set_by, created_at)`
  - `ForecastReconciliationException(item, node, forecast_version, computed_net_demand, status)`
- [ ] Create `utils/ide/operating_plan.py`:
  - `apply_normalization_factor(version_id, anchor_node, factor)` — creates a new `OPERATING_PLAN`
    version from the source `SALES_CONSENSUS` version
  - `cascade_operating_plan(version_id)` — reuses 3B's revenue-share disaggregation to push the
    anchor-node number down the sales hierarchy; additive by construction
  - `apply_manual_override(version_id, node, qty)` — flags `is_manual_override=True`; writes a
    `ForecastReconciliationException` for the resulting non-additivity rather than clamping it
- [ ] Celery task `cascade_operating_plan(version_id)` wraps the above for large trees
- [ ] REST endpoints: `POST /api/ide/forecast-versions/{id}/operating-plan/`,
      `GET /api/ide/reconciliation-exceptions/`
- [ ] Unit tests: cascade preserves additivity when no override present; manual override produces
      exactly one `ForecastReconciliationException`; `OPERATING_PLAN` version is immutable once
      consumed by a propagation run (guard, not hard lock — mirrors 3B's `LOCKED` pattern)

---

### Sprint 3C.3 — Supply Network Master Data and Resolution

- [ ] Create `mysite/models/ide/supply_network.py`:
  - `SupplyNetworkRule(client, scope_type ITEM/TAXONOMY/ALL, taxonomy_node nullable, item nullable,
    location, valid_from, valid_to, source_type VENDOR/DC/LOCATION/HO, source_ref, allocation_pct)`
  - `ResolvedSupplySource(item, location, effective_date, source_type, source_node/vendor,
    allocation_pct, resolved_rule FK)` — materialized cache table only, never written to directly
- [ ] Create `utils/ide/supply_network_resolver.py`:
  - `resolve_supply_source(item, location, date)` — generic→specific walk: ITEM exact match →
    TAXONOMY (deepest ancestor with a rule for that location) → ALL → hard `ValidationError` on no
    match (reuses the Phase 2 taxonomy materialized-path walk)
  - `validate_split_sourcing(rules_for_key)` — enforces same-scope-level-only legs and
    `Σ allocation_pct == 100%`
  - `materialize_resolved_supply_source(client_id)` — bulk resolves all item×location combinations,
    writes `ResolvedSupplySource`
- [ ] Celery task `resolve_supply_network(client_id)`: nightly beat + triggered on
      `SupplyNetworkRule` post_save
- [ ] Periodic integrity job: catches rules whose `valid_to` has lapsed and silently broken a
      previously-100%-summing split, without requiring any row edit to surface it
- [ ] Admin: `SupplyNetworkRuleAdmin` with scope-type-aware form (hide irrelevant fields per scope)
- [ ] REST endpoints: `GET/POST /api/ide/supply-network-rules/`, `GET /api/ide/resolved-supply-source/`
- [ ] Unit tests: ITEM beats TAXONOMY beats ALL; no-match raises hard error (never silent fallback);
      mixed-scope-level split rejected; lapsed `valid_to` caught by integrity job; split summing to
      100% passes, 97% fails

---

### Sprint 3C.4 — Demand Propagation Engine

- [ ] Create `mysite/models/ide/propagation.py`:
  - `NodeReplenishmentRequirement(item, node, date, source_leg, quantity)`
- [ ] Create `utils/ide/propagation_engine.py`:
  - `compute_net_own_demand(node, period)` — `FCST(N) − Σ bypass legs of children not sourced from N`
  - `compute_replenishment_requirement(node, source, period)` — recursive `RR(N, via X)` per the spec
    algorithm, generalized to arbitrary depth and bypass patterns
  - `run_propagation(client_id, operating_plan_version_id)` — orchestrates full-network propagation,
    writes `NodeReplenishmentRequirement`
  - `check_conservation_invariant(client_id, version_id)` — `Σ RR at every vendor-facing leg == Σ FCST
    at every end node`; raises (does not warn-and-continue) on violation
- [ ] Celery task `propagate_replenishment_demand(client_id, version_id)`, scheduled per client at
      `resolve_review_frequency()` cadence
- [ ] Regression test suite: encode the worked example from the spec (HO 300 / DC1 200 split 60/40 /
      DC2 100 Vendor-only → RR(DC1,HO)=120, RR(DC1,Vendor)=80, RR(DC2,Vendor)=100,
      RR(HO,Vendor)=240) as a permanent test fixture, re-run on every engine change
- [ ] Unit tests: single-level bypass; multi-level bypass; fully congruent tree (no bypass) reduces to
      simple bottom-up; conservation invariant violation raises with actionable diagnostic (which
      item/location fell through)

---

### Sprint 3C.5 — Supply Position Ingestion and MRP Netting

- [ ] Create `mysite/models/ide/ingestion.py`:
  - `SupplyPositionSnapshot(client, snapshot_id UUID, as_of_datetime, received_at, source_system,
    status RECEIVED/VALIDATED/APPLIED/REJECTED, is_full_snapshot, supersedes self-FK)`
  - `StockOnHand(snapshot, item, node, qty_unrestricted, qty_blocked, qty_in_transit_to_node)` —
    unique on `(snapshot, item, node)`
  - `OpenSupply(snapshot, supply_type PO/STO/WO, external_doc_number, external_line_number, item,
    receiving_node, source_node nullable, vendor nullable, order_qty, received_qty, open_qty,
    expected_receipt_date, order_status)` — unique on
    `(snapshot, supply_type, external_doc_number, external_line_number)`
  - `OpenDemandCommitment(snapshot, item, node, committed_qty, required_date, external_doc_number)`
    — optional per client
- [ ] Create `mysite/models/ide/inventory_position.py`:
  - `InventoryPosition(item, node, date, on_hand, in_transit, net_requirement, min, max, rop,
    ddmrp_red, ddmrp_yellow, ddmrp_green, projected_inventory)`
- [ ] Bulk-ingest DRF endpoints: structural validation (item/node codes resolve, quantities
      non-negative, dates parseable); **reject whole snapshot on any row failure** — no partial apply
- [ ] Celery task `ingest_supply_position_snapshot(snapshot_id)` — materializes `VALIDATED` snapshot
      into a denormalized item×node netting-ready structure
- [ ] Create `utils/ide/netting_engine.py`:
  - `compute_net_requirement(item, node, date)` — `Gross Requirement (from
    NodeReplenishmentRequirement) − on_hand_available − scheduled_receipts + uncommitted_open_demand`
  - Time-fencing: full detail only inside `lead_time + review_period + safety_margin`; aggregated
    total beyond the fence
- [ ] Celery task `run_netting(client_id, snapshot_id)` — writes `InventoryPosition`
- [ ] Sparse-transmission support: ingestion endpoint tolerates omitted zero-position rows without
      treating them as data-quality errors
- [ ] Feed manifest filter: expected-feed generator consults `ItemPlanningProfile.is_active_for_ide`
      before requesting position data
- [ ] Unit tests: partial-failure snapshot rejected wholesale; idempotent re-ingest of same
      `snapshot_id`; netting formula correctness incl. `qty_blocked` excluded; time-fenced aggregation
      matches full-detail sum inside the fence

---

### Sprint 3C.6 — Inventory Policy Engine (Min/Max, ROP, DDMRP, Forecast Trust)

- [ ] Create `utils/ide/inventory_policy_engine.py`:
  - `compute_edu(item, node)` — `EDU = ForecastTrust × FDU + (1 − ForecastTrust) × HDU`, trust % read
    from the item's `PolicyMatrix` cell (defaults: Smooth 90%, Erratic 60%, Intermittent 60%,
    Lumpy 20%)
  - `compute_lead_time_demand(item, node)`, `compute_safety_stock(item, node)` — per policy cell logic
  - `compute_min_max(item, node)` — `Min = LTD + SS`, `Max = Min + Coverage Demand`
  - `compute_rop(item, node)` — continuous-review reorder point
  - `compute_ddmrp_zones(item, node)` — Red/Yellow/Green buffer zones for **all** items (DDMRP items
    use zones operationally; non-DDMRP items use zones for visual monitoring only)
- [ ] Wire policy resolution: item's ABC + SEIL class → `PolicyMatrix` cell → which formula path
      executes (`formula_used` recorded for explainability downstream)
- [ ] Write results to `InventoryPosition` (min/max/rop/ddmrp zone fields, `projected_inventory`)
- [ ] Admin/API: `GET /api/ide/inventory-position/` filtered by item/node/date range
- [ ] Unit tests: EDU blend at each SEIL default trust %; DDMRP zones computed for non-DDMRP items too
      (monitoring-only path); coverage-days bounds (1–180) enforced

---

### Sprint 3C.7 — Vendor Scheme and Carrying-Cost Engine

- [ ] Create `mysite/models/ide/vendor_scheme.py`:
  - `InventoryCarryingCostRate(client, abc_class, demand_pattern_class, annual_carrying_cost_pct,
    valid_from, valid_to)` — unique on `(client, abc_class, demand_pattern_class, valid_from)`,
    reuses ABC/SEIL as grid axes (no new classification)
  - `ExcessInventoryPenaltyTier(client, abc_class, demand_pattern_class, age_bucket_from_days,
    age_bucket_to_days nullable, additional_annual_pct, valid_from, valid_to)`
  - `VendorScheme`, `VendorSchemeScope`, `VendorSchemeSlab` (exact fields per tech-stack delta;
    `category` TRANSACTIONAL is exclusive/most-specific-wins, `category` REBATE is additive and never
    competes with TRANSACTIONAL in the same resolution)
  - `ResolvedVendorScheme` — materialized, same generic→specific pattern as `ResolvedSupplySource`
  - `VendorRebateAccrual(scheme, vendor, period_start, period_end, cumulative_value_to_date,
    cumulative_qty_to_date, estimated_effective_discount_pct, actual_settled_discount_pct nullable,
    settled_at nullable)`
- [ ] `utils/ide/vendor_scheme_resolver.py`: item-specific → taxonomy path (sub-brand before brand) →
      `OVERALL`, materialized on scheme change (reuse resolver pattern from 3C.3)
- [ ] Celery task `compute_rebate_accrual_estimate(scheme_id)` — median (not mean) of last 3–4 settled
      periods' `actual_settled_discount_pct`
- [ ] Create `utils/ide/vendor_breakpoint_evaluator.py`:
  - `evaluate_order_quantity(item, node, base_qty)` — implements the breakpoint trade-off formula from
    the spec exactly (excess_qty / holding-days / carrying-cost / discount-saving / net-benefit /
    argmax, defaulting to `base_qty` if all `net_benefit <= 0`)
  - Applies `estimated_effective_discount_pct` as a flat reduction to `unit_cost_at(B)` uniformly
  - Guardrails: cap `expected_holding_days` at shelf-life/configurable ceiling; MOQ, warehouse
    capacity, cash/budget ceiling as candidate-set **filters**, never formula inputs
- [ ] Celery task `evaluate_vendor_breakpoints(recommendation_id)`
- [ ] Unit tests: transactional-only resolution; rebate additive on top of transactional never
      competing; median rebate calc with sample settled-period data; breakpoint chosen only when
      `net_benefit > 0`; base_qty returned when no slab clears the carrying-cost hurdle; holding-days
      ceiling caps an absurd slow-mover quantity

---

### Sprint 3C.8 — Recommendation and Explainability Engine

- [ ] Create `mysite/models/ide/recommendation.py`:
  - `ReplenishmentRecommendation(item, node, rec_type PURCHASE/TRANSFER/STOCKING/CENTRALIZATION/
    EMERGENCY/ALTERNATIVE_SUPPLY, recommended_qty, policy_cell FK, inputs JSONField, formula_used,
    trigger_reason, alternatives JSONField, expected_outcome JSONField, status)`
  - `PlannerDecision(recommendation, decided_by, decision APPROVE/REJECT/MODIFY, modified_qty,
    decided_at, note)`
- [ ] Create `utils/ide/recommendation_engine.py`:
  - `generate_purchase_recommendation(item, node)` — netting + breakpoint evaluation → recommendation
  - `generate_transfer_recommendation(item, node)` — evaluated when `ReplenishmentPolicy` favors
    TRANSFER_FIRST or when a sibling/parent node carries excess against this node's shortfall
  - `recommend_stocking_strategy(item, node)` — auto-recommends
    LOCAL/CENTRALIZED/DC/VENDOR_DIRECT/TRANSFER_FIRST/EMERGENCY/NON_STOCK/BUY_TO_ORDER based on ABC,
    SEIL, lead time, network demand, service criticality, annual demand, demand frequency (per spec's
    listed inputs)
  - `generate_centralization_recommendation(item)` — network-level candidate when multiple nodes show
    low, erratic local demand better served by a DC/HO buffer
  - Every generator writes the full explainability payload (`inputs`, `policy_cell`, `formula_used`,
    `trigger_reason`, `alternatives`, `expected_outcome`) at creation time, not reconstructed later
- [ ] Celery task `generate_recommendations(client_id)` — orchestrates all generators after netting +
      breakpoint evaluation complete for a review cycle
- [ ] REST endpoints: `GET /api/ide/recommendations/`, `POST /api/ide/recommendations/{id}/decide/`
- [ ] Unit tests: each rec_type generator produces a populated explainability payload; planner
      approval-rule gating (per `PolicyMatrix.planner_approval_rule`) routes high-value/high-risk
      recommendations to mandatory review instead of auto-approval

---

### Sprint 3C.9 — Planner Workbenches (Django Templates + HTMX)

- [ ] Create `ide_ui/` app: `urls.py`, `views.py`, `views_htmx.py` (mirrors `demand_ui`/`inventory_ui`
      structure — server-rendered, **not** a React SPA)
- [ ] Templates under `templates/ide/workbenches/`, one per workbench:
  - **Service Risk Workbench** — items/nodes below target fill rate, ranked by risk
  - **Replenishment Workbench** — PURCHASE recommendations queue, filter/sort/bulk-approve
  - **Transfer Workbench** — TRANSFER recommendations, source/destination pairing view
  - **Inventory Balancing Workbench** — excess-vs-shortfall cross-node view
  - **Vendor Scheme Workbench** — active schemes, accrual progress, breakpoint evaluation log
  - **Exception Management Workbench** — `ForecastReconciliationException` +
    supply-network-integrity-job findings, unresolved snapshot rejections
  - **Policy Governance Workbench** — `PolicyMatrix` CRUD grid, policy cell editor
- [ ] HTMX-powered filter/pagination pattern reused from Phase 2 catalogue (`hx-get`,
      `hx-target="#..."`, `hx-swap="innerHTML"`)
- [ ] `recommendation_decide` HTMX partial: approve/reject/modify inline, writes `PlannerDecision`,
      updates recommendation `status` without full page reload
- [ ] `ClientGroupPermission` module `inventory_decision_engine` wired to all workbench views
- [ ] Unit/integration tests: each workbench renders its filtered queryset; decide-action HTMX partial
      round-trips correctly; permission gate blocks unauthorized roles

---

### Sprint 3C.10 — Multi-Echelon Centralization and Transfer Refinement

- [ ] Extend `recommend_stocking_strategy()` with explicit network-demand-aggregation awareness — a
      node with low local demand but healthy aggregated parent/DC demand should trend toward
      CENTRALIZED/DC stocking rather than LOCAL, per the multi-echelon design principle
- [ ] Transfer-vs-purchase ranking: when both a TRANSFER and a PURCHASE recommendation are viable for
      the same shortfall, rank by landed cost + lead time, surface both as `alternatives` on the
      chosen recommendation
- [ ] Emergency stock path: `EMERGENCY` rec_type triggered when `InventoryPosition` breaches the
      DDMRP red zone (or ROP with insufficient scheduled receipts) inside lead time
- [ ] Unit tests: centralization candidate correctly identified across a 3-node network fixture;
      transfer beats purchase when landed cost is lower and lead time is acceptable; emergency
      triggers only inside the lead-time-breach window, not on every red-zone dip

---

### Sprint 3C.11 — Production Hardening and Scale Validation

- [ ] Deploy IDE Celery tasks with dedicated queue (`ide` queue, separate from Phase 3B `demand`
      queue) to isolate long-running propagation/netting jobs from forecast-run jobs
- [ ] `EXPLAIN ANALYZE` on all Phase 3C indexes (resolved-supply-source, node-replenishment,
      snapshot-scoped netting inputs, recommendation queue, resolved-vendor-scheme)
- [ ] Load test: 100,000 SKU-location combinations — full propagation + netting + recommendation
      generation cycle completes within an agreed batch window (define per-client SLA, e.g. overnight
      batch < 4 hours)
- [ ] Load test: snapshot ingestion of 500K `StockOnHand`/`OpenSupply` rows completes within
      acceptable bounds using time-fencing + sparse transmission
- [ ] End-to-end test: rule change → nightly resolution → propagation → netting → breakpoint
      evaluation → recommendation → planner decision, full chain
- [ ] Verify conservation-invariant regression test runs in CI on every PR touching `utils/ide/`
- [ ] Wire `django-guardian` / `ClientGroupPermission` to all IDE views and API endpoints
- [ ] Document the "IDE is a standalone service — does not own transactional ERP data" boundary
      clearly (README), mirroring the DuckDB/PostgreSQL boundary note from Phase 3B

---

### Sprint 3C.12 — Phase 3A Integration (Optional, evaluate after 3C.11)

- [ ] `OrderLine`/procurement-side hook: an approved `PURCHASE` `ReplenishmentRecommendation` can seed
      a draft `Order` (3A) or an external PO reference — evaluate against actual client workflow
      before building; this is the only planned contact point between 3A and 3C
- [ ] Unit tests: recommendation-to-order handoff preserves qty/item/vendor; recommendation marked
      `status=ACTIONED` on handoff

---

## Phase 3C Dependency Map

```
3C.0 (Foundation)
  └─▶ 3C.1 (Policy Matrix, reuses 3B ABC/SEIL)
        └─▶ 3C.2 (Two-Stage Forecasting)
              └─▶ 3C.3 (Supply Network Resolution)
                    └─▶ 3C.4 (Demand Propagation)
                          └─▶ 3C.5 (Ingestion + MRP Netting)
                                └─▶ 3C.6 (Inventory Policy Engine: Min/Max/ROP/DDMRP)
                                      ├─▶ 3C.7 (Vendor Scheme + Carrying Cost)  ─┐
                                      └────────────────────────────────────────┴─▶ 3C.8 (Recommendation Engine)
                                                                                       │
                                                                    3C.8 ──────────────┴─▶ 3C.9 (Planner Workbenches)
                                                                                                   │
                                                                    3C.9 ─────────────────────────┴─▶ 3C.10 (Multi-Echelon Refinement)
                                                                                                              │
                                                                    All ─────────────────────────────────────┴─▶ 3C.11 (Hardening)
                                                                                                                          │
                                                            3C.11 + Phase 3A Sprint 3.3 ─────────────────────────────────┴─▶ 3C.12 (3A Integration, optional)
```

`3C.2` depends only on Phase 3B Sprints 3B.3/3B.4 (forecast infrastructure) — Phase 3C can start and
run largely in parallel with Phase 3A once that dependency is satisfied.

---

## Phase 3C Effort Estimates

| Sprint | Effort (solo dev) |
|--------|------------------|
| 3C.0 Foundation | 1–2 days |
| 3C.1 Policy Framework & Matrix | 3–4 days |
| 3C.2 Two-Stage Forecasting | 4–5 days |
| 3C.3 Supply Network Resolution | 5–7 days |
| 3C.4 Demand Propagation Engine | 6–8 days |
| 3C.5 Ingestion & MRP Netting | 7–9 days |
| 3C.6 Inventory Policy Engine | 5–6 days |
| 3C.7 Vendor Scheme & Carrying Cost | 6–8 days |
| 3C.8 Recommendation Engine | 5–6 days |
| 3C.9 Planner Workbenches | 8–10 days |
| 3C.10 Multi-Echelon Refinement | 3–4 days |
| 3C.11 Production Hardening | 3–4 days |
| 3C.12 3A Integration (optional) | 2–3 days |
| **Total (3C.0–3C.11)** | **56–73 days** |
| **Total incl. optional 3C.12** | **58–76 days** |

3C.6 and 3C.7 can run in parallel once 3C.5 is complete (both consume `InventoryPosition`/netting
output independently). 3C.9 (workbenches) can begin scaffolding in parallel with 3C.7/3C.8 once
3C.8's REST endpoints are stubbed, same pattern as 3B.7 running alongside 3B.4/3B.5.

---

## Key Risks and Mitigations (Phase 3C)

| Risk | Mitigation |
|------|-----------|
| Supply network / sales hierarchy conflation | Enforce at the model layer — no shared parent-link field; code review checklist item; the resolver never accepts a sales-hierarchy node as a supply-network input |
| Propagation algorithm correctness at scale | Conservation-invariant regression test (worked example from spec) run in CI on every change to `utils/ide/propagation_engine.py`; never relaxed to a warning |
| Snapshot ingestion partial-apply corrupting netting | Whole-snapshot reject-on-any-row-failure is a hard rule, not a default — no code path partially commits a `SupplyPositionSnapshot` |
| Netting horizon data volume (20K+ items × multiple nodes) | Time-fencing applied first (highest impact); delta/CDC feed explicitly deferred to a v2 optimization, not day-one scope |
| Vendor breakpoint formula producing absurd quantities for slow movers | Hard ceiling on `expected_holding_days`; MOQ/capacity/budget as filters, never formula inputs — both enforced in `vendor_breakpoint_evaluator.py`, tested with slow-mover fixtures |
| Rebate logic drifting into threshold-chasing | Explicitly out of scope per mission non-goals; `compute_rebate_accrual_estimate` only ever *informs* landed cost, never triggers order-qty increases on its own |
| Policy Matrix becoming a hardcoded-logic escape hatch | Code review discipline: any new replenishment behavior must be expressible as a `PolicyMatrix` cell field, not a special-cased branch in `recommendation_engine.py` |
| Workbench UI complexity creeping toward needing a SPA | Default to Django+HTMX per workbench; revisit only a specific workbench (not the whole module) if bulk-edit-at-scale is proven necessary |
| Explainability payload becoming an afterthought | `inputs`/`policy_cell`/`formula_used`/`trigger_reason`/`alternatives`/`expected_outcome` are required (non-nullable where feasible) fields on `ReplenishmentRecommendation`, populated at write time by every generator function — enforced by unit test per generator |

---

## Definition of Done (Phase 3C)

- [ ] `PolicyMatrix` (12 cells) editable per client via Policy Governance Workbench; seeded with the
      reference matrix from the spec as default
- [ ] `OPERATING_PLAN` forecasts derive correctly from `SALES_CONSENSUS` via normalization + cascade;
      manual overrides produce a `ForecastReconciliationException`, never silent clamping
- [ ] `SupplyNetworkRule` resolution is generic→specific with hard failure on no match; split sourcing
      validated to sum to 100% on save and via periodic integrity job
- [ ] Demand propagation passes the conservation-invariant regression test on the spec's worked
      example and on at least one multi-level, asymmetric-bypass fixture
- [ ] `SupplyPositionSnapshot` ingestion is all-or-nothing; idempotent re-ingestion produces no
      duplicate netting inputs
- [ ] MRP netting produces `Net Requirement` correctly incorporating on-hand, scheduled receipts, and
      uncommitted open demand
- [ ] DDMRP zones computed for all items (operational for DDMRP-policy items, monitoring-only for
      others)
- [ ] Vendor breakpoint evaluation selects a quantity above `base_qty` only when net benefit is
      positive, respecting MOQ/capacity/budget filters and the holding-days ceiling
- [ ] Every `ReplenishmentRecommendation` carries a complete explainability payload
- [ ] All seven planner workbenches functional with HTMX-driven filter/decide interactions
- [ ] Load test: 100,000 SKU-location combinations complete a full batch cycle within the agreed SLA
- [ ] `manage.py check` clean; 0 migration errors
- [ ] `django-guardian` / `ClientGroupPermission` enforced on all IDE views and API endpoints

---

## Deferred / Future Consideration (Phase 3C)

| Feature | Rationale |
|---------|-----------|
| Full simulation / what-if engine | High complexity, best validated against a working core engine first — candidate for Phase 3D or Phase 4 |
| Live vendor EDI / direct ERP integration | IDE is a standalone service; snapshot ingestion contract is the deliberate integration boundary |
| Automatic PO/STO creation into Phase 3A | Sprint 3C.12 is optional and evaluated only after 3C.11 is validated against real client data |
| Delta/CDC snapshot feed | Explicitly a v2 optimization on top of the day-one full/sparse snapshot contract |
| ML-based demand models (XGBoost, LightGBM) | Statistical models (Croston/SBA/TSB via `statsforecast`/`darts`) only in Phase 3C, consistent with the same non-goal already stated for Phase 3B |
| AG-Grid-style bulk-edit workbench UI | Default is Django+HTMX; revisit per-workbench only if proven necessary at scale |
