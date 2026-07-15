# Mission — Delta Updates (Phase 3C)

Apply these changes to `mission.md`.

---

## CHANGE 1 — Update §7 "Phased Feature Expansion" table

Replace the table with:

| Phase | Scope |
|-------|-------|
| 1 | Multi-tenant CMS: page builder, multilingual content, theme system, user auth — **substantially complete** |
| 2 | Generic Item Catalogue: domain-agnostic items, multi-taxonomy, HTMX faceted filters — **complete** |
| 3B | Demand Planning: actuals ingestion, statistical forecasting, hierarchical reconciliation, consensus override — **builds before 3A; feeds into 3A order creation and 3C** |
| 3A | eCommerce: Inquiry → Quotation → Order lifecycle, SAP-style pricing engine, Beckn-aligned models — **in progress** |
| 3C | **Inventory Decision Engine**: policy-driven replenishment, multi-echelon supply network propagation, MRP-style netting, DDMRP, vendor-scheme cost optimization, exception-driven planner workbenches — **builds after 3B; consumes `OPERATING_PLAN` forecasts only, never `SALES_CONSENSUS`; independent of 3A except for shared `Item`/`ClientLocation` master data** |
| 4 | Beckn / ONDC network participation: BPP role, async callbacks, digital signatures, ONDC registry; probabilistic forecasting; ML demand models |

---

## CHANGE 2 — Add new §10, after §9 "Demand Planning Module (Phase 3B)"

### 10. Inventory Decision Engine (Phase 3C)

#### Naming and Scope Correction

This module is named the **Inventory Decision Engine (IDE)**, not a "replenishment engine." Replenishment
is only one of the decisions it makes. The engine also makes forecast-consumption decisions,
stocking-location decisions, transfer decisions, procurement-quantity decisions, centralization
decisions, and service-level decisions — all policy-driven and all explainable.

#### Business Context

Each Client operates a multi-tier physical stocking network (Vendor → HO → DC → Location) carrying
20,000+ SKUs. The IDE converts inventory position, demand classification, forecast, and supply-network
data into ranked, explainable replenishment/transfer/stocking recommendations — reducing the planning
surface from tens of thousands of SKU-locations down to a small set of exceptions a human planner
actually reviews and decides on.

#### Core Design Principles

- **Policy-driven, never hardcoded.** Every decision (review cadence, replenishment method, coverage
  days, safety-stock logic, preferred supply source, forecast trust, stocking strategy, transfer
  strategy, approval threshold) is derived from a configurable `PolicyMatrix` cell, not from
  code-level branching.
- **Exception-driven planner workflow.** Target funnel: 80,000 SKU-locations → ~5,000 system
  recommendations → ~500 exceptions surfaced → ~50 planner decisions per cycle. Planners work
  workbenches, not SKU lists.
- **Multi-echelon aware.** Every recommendation accounts for the local node, its parent(s), the
  distribution center, and the ultimate vendor source, recognizing demand-aggregation effects across
  the network — not just local reorder math.
- **Explainable by construction.** Every recommendation persists its inputs, the policy cell that
  fired, the formula used, the trigger reason, alternative options considered, and the expected
  outcome. Nothing is a black-box number.

#### Two Hierarchies, Kept Structurally Separate

The Sales/Forecast Hierarchy (Total → Region → Branch → Location, from Phase 3B) and the Supply
Network (Vendor → HO → DC → Location) are **not the same tree** and must never share a parent-link
field. The Supply Network is item-specific, time-dependent, and may diverge in shape from the sales
hierarchy at any node. The IDE resolves *where demand is sourced from* by walking the Supply Network,
while reading *how much demand exists* from FCST values that live on the Sales Hierarchy.

#### Two-Stage Forecasting Feeds the IDE

Phase 3B's `ForecastVersion`/`ForecastLine` machinery is extended with two forecast "stages" rather
than replaced:
- **`SALES_CONSENSUS`** — the existing Phase 3B consensus forecast. Not guaranteed additive up the
  tree; owned by the sales team.
- **`OPERATING_PLAN`** — derived from `SALES_CONSENSUS` by applying a planner-set normalization factor
  at an anchor node, then cascading down using the same revenue-share disaggregation logic already
  built for Total→Region→Branch→Item. Additive by construction unless a planner manually overrides a
  node (flagged `is_manual_override`).

**The IDE consumes `OPERATING_PLAN` exclusively.** `SALES_CONSENSUS` never reaches supply planning
directly. Non-additivity introduced by manual overrides is never silently clamped — it is written to a
`ForecastReconciliationException` for planner review.

#### Demand Classification (reused, not reinvented)

ABC classification and Syntetos-Boylan (SEIL: Smooth/Erratic/Intermittent/Lumpy, via ADI/CV²
thresholds) already exist from Phase 3B (`AbcClassDefinition` and the SEIL classifier). Phase 3C
**reuses these as the two axes of a 3×4 `PolicyMatrix`** rather than introducing a parallel
classification scheme. Thresholds remain client-configurable.

#### Policy Matrix

A 12-cell matrix (ABC × SEIL) where each cell configures: Review Policy, Replenishment Policy,
Coverage Days, Safety Stock Logic, Preferred Supply Source, Forecast Trust %, Stocking Strategy,
Transfer Strategy, and Planner Approval Rules. Effective review frequency for any SKU-location is
`MAX(policy_frequency, data_refresh_frequency)`.

#### Effective Daily Usage

`EDU = ForecastTrust × FDU + (1 − ForecastTrust) × HDU`, where Forecast Trust is a per-SEIL-class
configurable percentage (Smooth 90%, Erratic 60%, Intermittent 60%, Lumpy 20% as defaults).

#### Non-Goals for Phase 3C

- No full simulation / what-if engine (deferred — candidate for Phase 3D or Phase 4).
- No live vendor EDI integration — supply-position data arrives via a versioned snapshot ingestion
  contract the client pushes to; the IDE is a standalone service that does not own transactional ERP
  data.
- No automatic PO/STO creation against 3A `Order`/`Delivery` — Phase 3C produces recommendations only;
  wiring a recommendation into an actual purchase/transfer document is a 3A/3C integration step
  evaluated after 3C's core engine is validated.
- No probabilistic/ML forecasting — reuses Phase 3B's `StatsForecast`/Nixtla stack (Croston, SBA, TSB
  added for intermittent/lumpy demand); ML models remain deferred to Phase 4.
- No rebate-threshold-chasing logic — rebate accrual only *informs* landed-cost comparisons; it never
  by itself triggers a bulk order.

#### Success Criteria (Phase 3C)

- Inventory investment reduction of 15–30% at target service levels, measured against a client's
  pre-IDE baseline (directional target, not a hard gate).
- Explainable recommendation surfaced for 100% of SKU-locations in scope — every recommendation
  traceable to its policy cell, formula, and inputs.
- Exception funnel demonstrably narrows: system recommendations → flagged exceptions → planner
  decisions, at roughly the 80,000 → 5,000 → 500 → 50 ratio described in design principles.
- `Σ RR` (replenishment requirement) at every vendor-facing leg equals `Σ FCST (OPERATING_PLAN)` at
  every end node — the conservation invariant holds as a standing regression test.
- Engine scales to 100,000+ SKU-location combinations per client without exceeding the netting-run
  time budget established in Sprint 3C production hardening.
