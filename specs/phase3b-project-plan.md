# Phase 3B — Demand Planning: Project Plan

---

## Summary

Phase 3B delivers a full demand planning capability on top of the existing
multi-tenant CMS and item catalogue. It is recommended to build Phase 3B
**before** Phase 3A eCommerce so that approved forecasts can feed directly
into Order creation as suggested quantities.

**New packages:** `statsforecast`, `hierarchicalforecast`, `polars`, `duckdb`,
`prophet`, `openpyxl`, `pandas` (plus `celery` and `redis` shared with 3A).

**New model package:** `mysite/models/demand/` (hierarchy, actuals, forecast).

**New frontend:** React SPA (Vite + TypeScript) served at `/{client_id}/planning/`.

---

## Key Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Nixtla StatsForecast + HierarchicalForecast | Strongest open-source combo for mid-market demand planning; handles thousands of SKUs via vectorised Numba backend; MinTrace reconciliation out of the box |
| DuckDB only inside Celery tasks | DuckDB is a fast in-process OLAP engine for aggregation; all writes go to PostgreSQL only. This boundary must never be crossed — document it explicitly |
| Polars for actuals matrix construction | Significantly faster than pandas for 10K SKU × 200 customer × 36 month tensors |
| Materialized path on SalesNode and ClientLocation | Enables efficient subtree queries without recursive CTEs; same pattern as TaxonomyNode from Phase 2 |
| ForecastVersion as first-class entity | Multiple versions coexist per client and period; enables statistical vs consensus vs approved comparison without data loss |
| Append-only ActualSale | Corrections post as negative delta rows (like an accounting ledger); full audit trail; a `resolved_actuals` view aggregates the net position |
| AG Grid Community for consensus override grid | Spreadsheet-like inline editing is the UX planners expect; Community licence is sufficient through Phase 3B |
| Django session cookie auth on SPA | Same origin; no JWT complexity in Phase 3B; DRF SessionAuthentication handles it |

---

## Sprint Plan

### Sprint 3B.0 — Foundation and Prerequisites

**Estimated effort:** 1–2 days
**Dependencies:** None — begin immediately after Phase 2 is stable.

**Deliverable:** Clean migrations; all packages installed; ClientLocation tree fields present; 0 errors on `manage.py check`.

**Tasks:**
- Add to `requirements.txt`: `statsforecast`, `hierarchicalforecast`, `polars`, `duckdb`, `prophet`, `openpyxl`, `pandas`
- Add `ClientFeatureControl` keys: `demand_planning`, `actuals_upload`, `forecast_run`, `consensus_override`, `forecast_approval`
- Add `ClientLocation.parent` self-FK (nullable) + `path` CharField for materialized path
- Add `ix_clientlocation_path` index (`text_pattern_ops`) via `RunSQL` in migration
- `python manage.py makemigrations && migrate`
- `python manage.py check` — 0 issues

---

### Sprint 3B.1 — Sales Hierarchy Models

**Estimated effort:** 2–3 days
**Dependencies:** Sprint 3B.0

**Deliverable:** Full sales org tree is configurable in Admin. Hierarchy APIs return correct nested JSON for both the sales tree and the location tree.

**Tasks:**
- Create `mysite/models/demand/hierarchy.py`:
  - `SalesNode(client, name, level_label, parent→self FK nullable, location→ClientLocation FK nullable, path CharField)`
  - `CustomerSalesAssignment(customer, sales_node, valid_from, valid_to)`
- `pre_save` signal on `SalesNode` computes materialized `path` from parent chain
- Add `ix_salesnode_path` index (`text_pattern_ops`) via `RunSQL` in migration
- Admin: `SalesNodeAdmin` with tree indent display; `CustomerSalesAssignmentInline`
- REST endpoint: `GET /api/demand/sales-hierarchy/` → full `SalesNode` tree JSON
- REST endpoint: `GET /api/demand/location-hierarchy/` → `ClientLocation` tree JSON
- Unit tests:
  - `path` computed correctly on create and on reparent
  - Subtree query via `path__startswith` returns all descendants
  - `CustomerSalesAssignment` date effectivity: overlapping assignments for same customer rejected

---

### Sprint 3B.2 — Actuals Models and Import Pipeline

**Estimated effort:** 3–4 days
**Dependencies:** Sprint 3B.1

**Deliverable:** Client staff can upload monthly SKU × Customer × Location actuals via CSV or Excel. Import is idempotent; per-row errors are reported without failing the entire batch.

**Tasks:**
- Create `mysite/models/demand/actuals.py`:
  - `ActualSale(client, item, variant nullable, customer, location, year, month, qty, revenue MoneyField)`
  - Unique constraint: `(client, item, customer, location, year, month)`
  - `ActualSaleLocation(client, location, year, month, total_qty, total_revenue MoneyField)`
  - `ActualSaleImport(client, import_date, source_file, row_count, status, errors JSONField)`
- Add DB indexes via `RunSQL`:
  - `ix_actualsale_client_period` on `(client_id, year, month)`
  - `ix_actualsale_item_customer` on `(item_id, customer_id, location_id)`
- Django Admin: `ActualSaleImport` with status display; `ActualSaleLocationAdmin`
- REST endpoints:
  - `POST /api/demand/actuals/upload/` — multipart file upload; creates `ActualSaleImport` job
  - `GET /api/demand/actuals/upload/{id}/` — poll import job status
  - `GET /api/demand/actuals/` — filtered query (item, customer, location, period range)
- Celery task `process_actuals_import(import_id)`:
  - Parse CSV / Excel with `pandas`
  - Validate all FKs exist; collect errors per row into `ActualSaleImport.errors`
  - `bulk_create` with `update_conflicts=True` (idempotent re-upload)
  - Update `ActualSaleImport.status` → `COMPLETE` / `FAILED`
- Celery task `process_summary_actuals_import(import_id)` for `ActualSaleLocation`
- Management command `generate_actuals_template` → produces `.xlsx` with correct column headers for client download
- Unit tests:
  - Duplicate upload → idempotent; row count unchanged on second upload
  - Invalid item FK → error collected in `errors` JSONField; other rows still imported
  - Valid upload → `ActualSale` row count matches file row count

---

### Sprint 3B.3 — Forecast Models and Version Management

**Estimated effort:** 3–4 days
**Dependencies:** Sprint 3B.2

**Deliverable:** Forecast version lifecycle works end-to-end. REST endpoints are fully stubbed, unblocking React SPA development to begin in parallel.

**Tasks:**
- Create `mysite/models/demand/forecast.py`:
  - `ForecastVersion(client, version_label, base_period_end, horizon_months, engine_config JSONField, status, created_by, approved_by nullable, approved_at nullable)`
  - `ForecastLine(version, item, customer, location, year, month, statistical_qty, override_qty nullable, final_qty)` — `final_qty = override_qty if set, else statistical_qty`, computed on save
  - `ForecastAggregate(version, agg_level, agg_key JSONField, year, month, statistical_qty, override_qty, final_qty)`
  - `ForecastOverride(version, override_level, override_key JSONField, year, month, override_qty nullable, override_pct nullable, disagg_method, override_note, created_by)`
  - `OverrideSplitWeight(override, child_key JSONField, weight)` — for `CUSTOM` disaggregation method
  - `ForecastAccuracy(version, item, customer, location, year, month, actual_qty, forecast_qty, mape, bias)`
- Add DB indexes via `RunSQL`:
  - `ix_forecastline_version` on `(version_id, year, month)`
  - `ix_forecastaggregate_version_level` on `(version_id, agg_level, year, month)`
- `ForecastVersion.status` state machine: `DRAFT → IN_REVIEW → APPROVED → LOCKED`
  - `LOCKED` versions reject all edits, overrides, and further status transitions
  - `LOCKED` versions can be copied to a new `DRAFT`
- REST endpoints:
  - `GET / POST /api/demand/forecast-versions/`
  - `GET /api/demand/forecast-versions/{id}/`
  - `GET /api/demand/forecast-versions/{id}/lines/` (paginated, filterable by item, customer, location, period)
  - `GET /api/demand/forecast-versions/{id}/aggregates/`
  - `POST /api/demand/forecast-versions/{id}/approve/`
- Admin: `ForecastVersionAdmin` with status display; read-only `ForecastLineInline` (paginated)
- Unit tests:
  - `final_qty` = `override_qty` when set; falls back to `statistical_qty`
  - Status transition guard: `LOCKED` → all mutation attempts return `HTTP 403`
  - Version copy: new version created in `DRAFT` with lines cloned

---

### Sprint 3B.4 — Statistical Forecast Engine

**Estimated effort:** 5–7 days
**Dependencies:** Sprint 3B.3
**Can run in parallel with:** Sprint 3B.5

**Deliverable:** Triggering a `ForecastVersion` run produces auditable `ForecastLine` records with hierarchically reconciled quantities.

**Tasks:**
- Create `utils/demand/forecast_engine.py`:
  - `build_actuals_dataframe(client_id, period_start, period_end)` — DuckDB in-process query over `ActualSale` → Polars DataFrame with columns `unique_id` (`{item_id}|{customer_id}|{location_id}`), `ds`, `y`
  - `build_summing_matrix(client_id)` — walks `TaxonomyNode` tree (`product_planning` slug), `ClientLocation` parent tree, and `SalesNode` tree; constructs numpy `S` matrix + `tags` dict in Nixtla `HierarchicalForecast` format
  - `run_statsforecast(actuals_df, horizon_months, model_config)` — runs `AutoETS`, `AutoARIMA`, `Theta`; auto-selects `CrostonSBA` for series with zero rate above configurable threshold (default 50%)
  - `run_hierarchical_reconciliation(forecasts_df, actuals_df, S, tags, method)` — supports `BottomUp`, `TopDown (AHP)`, `MinTrace (OLS)`, `MinTrace (WLS)`; method is per-client configurable via `ForecastVersion.engine_config`
  - `write_forecast_lines(version_id, reconciled_df)` — `bulk_create` in batches of 5000
  - `write_forecast_aggregates(version_id)` — rolls up `ForecastLine` into `ForecastAggregate` for all `agg_level` values (`LOCATION`, `SALES_NODE`, `PRODUCT_GROUP`, `CLIENT`)
- Celery task `run_forecast(version_id)`:
  - Orchestrates the pipeline steps above
  - Updates `ForecastVersion.status` → `READY` on success, `FAILED` on error
  - Writes `celery_task_id` to `ForecastVersion` for client-side progress polling
  - Notifies requesting user
- `engine_config` JSONField controls: model list, reconciliation method, intermittent threshold
- Cache `pricing_procedure:{client_id}` pattern extended: add `forecast_aggregates:{version_id}:{agg_level}` (invalidated on `ForecastVersion` status change)
- Unit tests:
  - `build_summing_matrix` produces correct `S` shape for a known 3-level hierarchy
  - Reconciled top-level total equals manually summed bottom-up (within float tolerance)
  - `CrostonSBA` automatically selected for a series with > 50% zero months
  - `write_forecast_lines` `bulk_create` produces correct row count for a known input DataFrame

---

### Sprint 3B.5 — Consensus Override Engine

**Estimated effort:** 4–5 days
**Dependencies:** Sprint 3B.3
**Can run in parallel with:** Sprint 3B.4

**Deliverable:** A planner can override at any level of any hierarchy; the override disaggregates correctly to leaf `ForecastLine` records; reverting an override restores statistical quantities.

**Tasks:**
- Create `utils/demand/override_engine.py`:
  - `resolve_leaf_lines(version_id, override_key, override_level)` — subtree walk via `path__startswith` on `SalesNode` or `ClientLocation` or `TaxonomyNode`; returns list of leaf `ForecastLine` PKs
  - `compute_proportional_shares(leaf_pks, base_year, base_month_range)` — queries `ActualSale` for the reference period; returns `{leaf_pk: share}` dict; falls back to equal split if actuals absent
  - `apply_override(override_id)` — updates `ForecastLine.override_qty` for each leaf; sets `final_qty`
  - `recompute_aggregates(version_id, affected_agg_keys)` — re-rolls `ForecastAggregate` records for all affected agg_level + agg_key combinations
- Routing: subtree with < 500 leaf lines → run synchronously; ≥ 500 → submit Celery task `propagate_override(override_id)`
- REST endpoints:
  - `GET / POST /api/demand/forecast-versions/{id}/overrides/`
  - `DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/` — reverts all leaf `ForecastLine.override_qty` to `NULL`; `final_qty` falls back to `statistical_qty`
- Unit tests:
  - Proportional disaggregation: sum of updated `override_qty` across leaves = original override total (within rounding tolerance)
  - Override revert: all leaf `override_qty` set to `NULL`; `final_qty` = `statistical_qty`
  - `LOCKED` version: `POST` to `/overrides/` returns `HTTP 403`
  - Large subtree (≥ 500 leaves): Celery task submitted rather than synchronous execution

---

### Sprint 3B.6 — Accuracy Tracking

**Estimated effort:** 2–3 days
**Dependencies:** Sprints 3B.4 and 3B.5

**Deliverable:** After each month closes, accuracy metrics are computed automatically for all clients with `demand_planning` enabled and are accessible via API.

**Tasks:**
- Celery task `compute_forecast_accuracy(version_id, year, month)`:
  - Loads approved `ForecastLine` records for the given version and period
  - Joins against `ActualSale` on `(item, customer, location, year, month)`
  - Computes per-leaf: `mape = abs(actual - forecast) / actual`, `bias = (forecast - actual) / actual`
  - Computes `WMAPE = sum(abs(actual - forecast)) / sum(actual)` at each `ForecastAggregate` level
  - Writes `ForecastAccuracy` records via `bulk_create` with `update_conflicts=True`
- Celery beat schedule: monthly trigger for all `Client` records with `ClientFeatureControl('demand_planning')` enabled
- REST endpoint: `GET /api/demand/forecast-versions/{id}/accuracy/` (filterable by agg_level, item, location, period)
- Unit tests:
  - MAPE formula verified against known inputs
  - WMAPE aggregate computation verified
  - Division-by-zero guard: `actual = 0` → MAPE stored as `None`, not `inf`

---

### Sprint 3B.7 — React SPA Frontend

**Estimated effort:** 7–10 days
**Dependencies:** Sprint 3B.3 (REST endpoints stubbed) — **can begin in parallel with Sprints 3B.4 and 3B.5**

**Deliverable:** Planners can upload actuals, trigger forecast runs, make consensus overrides, compare versions, and view accuracy — all in the browser without touching Django Admin.

**Stack:** Vite + TypeScript, AG Grid Community, Apache ECharts, Zustand, axios + React Query.

**Tasks:**

- Scaffold React app under `frontend/planning/` (Vite + TypeScript)
- Django catch-all view at `/{client_id}/planning/` returns `planning.html` shell
- Auth: Django session cookie; `X-CSRFToken` header on all mutating requests; DRF `SessionAuthentication`

**View 1 — Actuals Dashboard:**
  - Drag-and-drop upload widget (CSV / Excel) → `POST /actuals/upload/` → polls import job status
  - Location × Month revenue heatmap (ECharts)
  - SKU drill-down table (AG Grid): item × customer × location × month; sortable, filterable

**View 2 — Forecast Run:**
  - Selectors: base period, horizon months, reconciliation method, model list
  - Submit → `POST /forecast-versions/` → polls `ForecastVersion.status` via `celery_task_id`
  - Progress bar; on `READY`: navigate to Consensus Grid

**View 3 — Consensus Override Grid (AG Grid):**
  - Rows: groupable by product group / location / sales node (switchable)
  - Columns: one per forecast month
  - Cell values: `final_qty`; editable at any aggregate level
  - On cell edit: `POST /overrides/` → optimistic UI update; background propagation via Celery
  - Colour coding: statistical (white), overridden (yellow), locked (grey)
  - Revert button per override row: `DELETE /overrides/{id}/`

**View 4 — Version Comparison:**
  - Select two `ForecastVersion` records
  - ECharts line chart overlay at any chosen aggregate level

**View 5 — Accuracy Report:**
  - MAPE / Bias / WMAPE displayed in sortable AG Grid by product group / location / sales node
  - ECharts horizontal bar chart: top N worst-performing SKUs by MAPE
  - Period selector for historical accuracy navigation

- Vitest unit tests: AG Grid cell edit triggers correct API call; polling interval and backoff logic; proportional share display in override confirmation

---

### Sprint 3B.8 — Phase 3A Integration

**Estimated effort:** 2–3 days
**Dependencies:** Sprint 3B.7 + Phase 3A Sprint 3.3 (Order model must exist)

**Deliverable:** Approved forecasts surface as suggested order quantities on Quotation and Order line forms. The plan-to-order loop is closed.

**Tasks:**
- Add `OrderLine.forecast_line` nullable FK → `ForecastLine`
- On `Quotation` and `Order` line creation: query approved `ForecastVersion` for the `Customer × Item × Location` combination → display suggested quantity as a hint field on the line form (not auto-populated; planner accepts or ignores)
- `ForecastAccuracy` model extended: add `actual_order_qty` column, populated from `OrderLine` quantities (separate from `ActualSale` upload path, giving a second accuracy signal)
- Unit tests:
  - Suggested quantity displayed when an approved `ForecastVersion` exists for the combination
  - `forecast_line` FK set on `OrderLine` when the planner accepts the suggestion
  - No error when no approved version exists for the combination

---

### Sprint 3B.9 — Production Hardening

**Estimated effort:** 2–3 days
**Dependencies:** All prior sprints

**Deliverable:** Phase 3B live in production; load tests passed; all demand API endpoints enforce `ClientGroupPermission`.

**Tasks:**
- Deploy Celery worker to Railway / Render `Procfile` (separate dyno from web)
- Set `CELERYD_TASK_SOFT_TIME_LIMIT = 1800` — forecast jobs can run up to 30 minutes
- Verify DuckDB pure-Python wheel installs cleanly in the production container (no native install required)
- Run `EXPLAIN ANALYZE` on the actuals matrix pull query; confirm `ix_actualsale_client_period` and `ix_actualsale_item_customer` indexes are used
- Load test: 10K SKU × 200 customer × 36 month forecast run completes in < 15 minutes
- Load test: 50K row actuals upload completes in < 60 seconds
- End-to-end test: upload → run → override → approve → order suggestion visible in Phase 3A Order form
- Wire `ClientGroupPermission` (module: `demand_planning`) to all demand REST API endpoints and SPA views
- `manage.py check` — 0 issues; 0 migration errors

---

## Sprint Dependencies

```
3B.0 (Foundation)
  └─▶ 3B.1 (Sales hierarchy)
        └─▶ 3B.2 (Actuals import)
              └─▶ 3B.3 (Forecast models)
                    ├─▶ 3B.4 (Statistical engine)  ──┐
                    ├─▶ 3B.5 (Override engine)      ──┤
                    └─▶ 3B.7 (React SPA)*            │
                                                       ▼
                              3B.4 + 3B.5 ──▶ 3B.6 (Accuracy)
                                                       │
                              3B.6 + 3B.7 ──▶ 3B.8 (3A integration)
                                                       │
                              3B.8 ──────────▶ 3B.9 (Hardening)
```

\* 3B.7 can begin as soon as 3B.3 REST endpoints are stubbed (before 3B.4 and 3B.5 complete).
Sprints 3B.4 and 3B.5 can run in parallel once 3B.3 is merged.

---

## Effort Estimates

| Sprint | Name | Effort (solo dev) |
|--------|------|------------------|
| 3B.0 | Foundation and prerequisites | 1–2 days |
| 3B.1 | Sales hierarchy models | 2–3 days |
| 3B.2 | Actuals models and import pipeline | 3–4 days |
| 3B.3 | Forecast models and version management | 3–4 days |
| 3B.4 | Statistical forecast engine | 5–7 days |
| 3B.5 | Consensus override engine | 4–5 days |
| 3B.6 | Accuracy tracking | 2–3 days |
| 3B.7 | React SPA frontend | 7–10 days |
| 3B.8 | Phase 3A integration | 2–3 days |
| 3B.9 | Production hardening | 2–3 days |
| **Total** | | **31–44 days** |

With parallelisation of 3B.4 + 3B.5, and 3B.7 started at 3B.3, calendar time
reduces to approximately **22–30 days** for a solo developer able to context-switch,
or **15–20 days** with a second developer taking the SPA.

---

## Recommended Overall Sequencing (3B relative to 3A)

```
Phase 2 complete
    │
    ▼
3B.0–3B.6   Actuals ingestion + forecast engine, no UI yet    ~20 days
    │
    ├──▶  3B.7  React SPA (start at 3B.3)                     ~8–10 days  ─┐
    │                                                                        │
    └──▶  3A.0–3A.3  eCommerce foundation, pricing, order     ~20 days  ───┤
                                                                             │
    ◀────────────────────────────────────────────────────────────────────────┘
    │
    ▼
3B.8   Forecast → Order integration                            ~2–3 days
    │
    ▼
3A.4–3A.12   Delivery through production hardening            ~27 days
    │
    ▼
Phase 4   Beckn BPP · probabilistic forecasting · ML models
```

This ordering ensures:
- The forecast engine is validated against real actuals before it feeds into any order flow.
- The `Order` model exists (3A Sprint 3.3) before the integration sprint (3B.8) begins.
- No phase blocks another; each sprint delivers standalone value that can be demoed.

---

## Key Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Nixtla library API changes between versions | Pin `statsforecast` and `hierarchicalforecast` versions in `requirements.txt`. Isolate all library calls inside `utils/demand/forecast_engine.py` — a library swap touches one file, not model code. |
| Summing matrix `S` construction is wrong — reconciliation silently produces bad numbers | Unit-test `S` matrix shape and column ordering independently before integrating with `HierarchicalForecast`. Compare reconciled top-level total against manually summed bottom-up for a known dataset. This is the single highest-risk technical step in Phase 3B. |
| Forecast Celery task times out for large clients | Set `CELERYD_TASK_SOFT_TIME_LIMIT = 1800`. Write progress checkpoints into `ForecastVersion.status` so a restarted task can skip completed steps. Consider chunking by product group for the largest clients. |
| Actuals data quality — missing FKs, wrong item codes, date format inconsistencies | Row-level error collection into `ActualSaleImport.errors` JSONField. Never fail the whole batch for a single bad row. Surface per-row errors in the upload UI so the planner can correct and re-upload. |
| React SPA auth complexity — session vs token confusion | Use Django session cookie (same origin). No JWT in Phase 3B. DRF `SessionAuthentication` on all demand endpoints. Send CSRF token in `X-CSRFToken` header via axios interceptor. |
| DuckDB + PostgreSQL dual-engine causes accidental writes to the wrong store | Hard rule: DuckDB is used **only inside Celery tasks** for fast read aggregation. All writes go to PostgreSQL only. Document this boundary in `tech-stack.md` and enforce in code review. |
| AG Grid Community licence missing server-side row model for very large grids | Community is sufficient through Phase 3B. For grids > 100K rows, implement pagination in the API and virtual row loading. Enterprise server-side row model deferred to Phase 4 if needed. |

---

## Definition of Done

- [ ] Client staff can upload monthly actuals (CSV or Excel) for SKU × Customer × Location
- [ ] Upload is idempotent — re-uploading the same file produces no duplicate rows
- [ ] Forecast run completes for 10K SKU × 200 customer × 36 month history in < 15 minutes
- [ ] Hierarchical reconciliation: top-level total of reconciled forecast equals sum of bottom-up within float tolerance
- [ ] Consensus override at Location level disaggregates correctly to SKU leaf `ForecastLine` records
- [ ] `LOCKED` `ForecastVersion` rejects all edits, overrides, and approval API calls
- [ ] Accuracy report shows MAPE / Bias / WMAPE after actuals close for an approved version period
- [ ] Approved forecast version shows suggested quantity on Quotation / Order line form
- [ ] All demand API endpoints enforce `ClientGroupPermission` (module: `demand_planning`)
- [ ] `manage.py check` clean; 0 migration errors
- [ ] Load tests passed: forecast run < 15 min; actuals upload (50K rows) < 60 sec
