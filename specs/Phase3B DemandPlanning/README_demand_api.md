# Demand Planning API — `mysite/api/demand/`

Sprint 3B module. Self-contained REST API for the Demand Planning workstream.
All endpoints are client-scoped (resolved from `request.client` set by middleware),
require authentication, and are gated by `ClientFeatureControl` feature flags.

---

## Table of Contents

1. [Module structure](#1-module-structure)
2. [Feature flags](#2-feature-flags)
3. [Authentication and client scope](#3-authentication-and-client-scope)
4. [Hierarchy endpoints](#4-hierarchy-endpoints)
5. [Actuals endpoints](#5-actuals-endpoints)
6. [Forecast version endpoints](#6-forecast-version-endpoints)
7. [Override endpoints](#7-override-endpoints)
8. [Series profile endpoints](#8-series-profile-endpoints)
9. [Forecasting config endpoint](#9-forecasting-config-endpoint)
10. [Accuracy endpoint](#10-accuracy-endpoint)
11. [Export endpoint](#11-export-endpoint)
12. [Error reference](#12-error-reference)
13. [End-to-end testing guide](#13-end-to-end-testing-guide)

---

## 1. Module structure

```
mysite/
  api/demand/
    __init__.py
    views.py          ← all API views (this file)
    serializers.py    ← DRF serializers for all models
    urls.py           ← URL patterns, mounted at /api/demand/

  models/demand/
    __init__.py
    hierarchy.py      ← PlanningLocation, PlanningCustomer, SalesNode,
                           CustomerSalesAssignment
    actuals.py        ← ActualSale, ActualSaleImport, PERIOD_TYPE_CHOICES
    forecast.py       ← ForecastVersion, ForecastLine, ForecastAggregate,
                           ForecastOverride, OverrideSplitWeight,
                           SeriesProfile, SeriesLevelEvaluation,
                           ForecastingConfig, ForecastAccuracy

  tasks/demand/
    import_actuals.py          ← process_actuals_import (Celery)
    compute_series_profiles.py ← compute_series_profiles (Celery)
    run_forecast.py            ← run_forecast, apply_overrides (Celery)
    notifications.py           ← send_forecast_status_email (Celery)

  management/commands/
    generate_actuals_template.py

  utils/demand/
    forecast_engine.py         ← write_forecast_aggregates helper

  utils/
    feature_control.py         ← is_demand_feature_disabled(client, feature)
```

---

## 2. Feature flags

Every view checks one or more `ClientFeatureControl` feature keys.
A missing or disabled flag returns HTTP 403.

| Key | Controls |
|---|---|
| `demand_planning` | Master switch. All demand endpoints check this first via `DemandFeatureMixin`. |
| `actuals_upload` | `POST /actuals/upload/` |
| `forecast_run` | `POST /forecast-versions/` and `POST /forecast-versions/{id}/run/` |
| `forecast_approval` | `POST /forecast-versions/{id}/approve/` |
| `consensus_override` | `PATCH /series-profiles/{id}/` |

---

## 3. Authentication and client scope

All views require `IsAuthenticated`. The `request.client` object is set by
your `ClientScopedMixin` / middleware using the `/{client_id}/` URL prefix.
Every queryset is filtered to `client=request.client` before any other logic runs.

---

## 4. Hierarchy endpoints

### `GET /api/demand/location-hierarchy/`

Returns the full `PlanningLocation` tree for the client, assembled in Python
from a single flat query ordered by materialized path. All parent nodes appear
before their children.

**Query params**

| Param | Default | Description |
|---|---|---|
| `active_only` | `true` | Exclude `is_active=False` nodes |
| `leaves_only` | `false` | Return a flat list of leaf nodes only (no nesting) |

**Response shape (nested tree)**
```json
[
  {
    "id": 1, "code": "NORTH", "name": "North Region",
    "level_label": "Region", "is_leaf": false,
    "is_active": true, "depth": 0, "path": "1/",
    "children": [
      {
        "id": 3, "code": "DEL", "name": "Delhi Branch",
        "level_label": "Branch", "is_leaf": true,
        "is_active": true, "depth": 1, "path": "1/3/",
        "children": []
      }
    ]
  }
]
```

**Implementation note** — `build_tree()` assembles the tree in O(n) using a
`{pk: node}` lookup dict. One DB query; no recursive SQL.

---

### `GET /api/demand/sales-hierarchy/`

Returns the full `SalesNode` tree with active `CustomerSalesAssignment` records
attached to each node. Assignments are pre-fetched in a single extra query and
grouped by `sales_node_id` in Python.

**Query params**

| Param | Default | Description |
|---|---|---|
| `active_only` | `true` | Exclude `is_active=False` nodes |
| `with_assignments` | `true` | Attach `active_assignments` list to each node |

**Response shape**
```json
[
  {
    "id": 1, "code": "NSM", "name": "National Sales Manager",
    "level_label": "National", "is_active": true,
    "depth": 0, "path": "1/",
    "location_code": null, "location_name": null,
    "active_assignments": [],
    "children": [
      {
        "id": 4, "code": "REP-MUM-01", "name": "Mumbai Rep 1",
        "level_label": "Sales Rep", "depth": 2, "path": "1/2/4/",
        "active_assignments": [
          {
            "customer_code": "CUST-001",
            "customer_name": "Acme Pvt Ltd",
            "valid_from": "2024-01-01",
            "valid_to": null
          }
        ],
        "children": []
      }
    ]
  }
]
```

---

## 5. Actuals endpoints

### `POST /api/demand/actuals/upload/`

Accepts a multipart file, creates an `ActualSaleImport` record, and fires
`process_actuals_import.delay(import_job.pk)`. Returns immediately with HTTP 202.

**Feature flag required:** `actuals_upload`

**Request** — `multipart/form-data`

| Field | Required | Description |
|---|---|---|
| `file` | Yes | `.csv`, `.xlsx`, or `.xls` |
| `period_type` | Yes | One of: `second minute hour day week month bimonth quarter halfyear year` |
| `notes` | No | Free-text description |

**Response 202**
```json
{
  "import_id": 42,
  "status": "pending",
  "poll_url": "/api/demand/actuals/upload/42/"
}
```

**Error responses**
- `400` — missing file, unsupported extension, or invalid `period_type`
- `403` — `actuals_upload` feature disabled

---

### `GET /api/demand/actuals/upload/{id}/`

Poll the status of an import job.

**Response 200**
```json
{
  "id": 42,
  "file_name": "demand/actuals_imports/upload.xlsx",
  "period_type": "month",
  "row_count": 480,
  "status": "done",
  "error_log": "",
  "uploaded_at": "2025-01-15T10:30:00Z",
  "uploaded_by_name": "Govind K"
}
```

`status` values: `pending → processing → done | failed`

---

### `GET /api/demand/actuals/`

Query paginated actuals for the client.

**Query params**

| Param | Description |
|---|---|
| `item_id` | Exact match on `Item.item_id` |
| `location_code` | Exact match on `PlanningLocation.code` |
| `customer_code` | Exact match on `PlanningCustomer.code` |
| `period_type` | Filter by period bucket type |
| `period_start` | ISO date — `period_start >= value` |
| `period_end` | ISO date — `period_end <= value` |
| `page` | Page number (default 1) |
| `page_size` | Results per page (default 100, max 1000) |

**Response 200**
```json
{
  "count": 480,
  "next": "/api/demand/actuals/?page=2",
  "previous": null,
  "results": [{ "...ActualSale fields..." }]
}
```

---

### `GET /api/demand/actuals/template/`

Generates and streams a client-specific `.xlsx` upload template.
Calls the `generate_actuals_template` management command internally.

**Query params**

| Param | Default | Description |
|---|---|---|
| `period_type` | `month` | One of the valid `PERIOD_TYPE_CHOICES` keys |

**Response** — `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
Content-Disposition: `attachment; filename="actuals_template_{client_id}_{period_type}.xlsx"`

---

## 6. Forecast version endpoints

### `GET /api/demand/forecast-versions/`

List all `ForecastVersion` records for the client, most recent first.
Each version is annotated with `line_count`.

**Query params**

| Param | Description |
|---|---|
| `status` | Filter by status: `DRAFT`, `IN_REVIEW`, `APPROVED`, `LOCKED` |

---

### `POST /api/demand/forecast-versions/`

Create a new DRAFT version.

**Feature flag required:** `forecast_run`

**Request body** — fields defined by `ForecastVersionCreateSerializer`
(at minimum: `version_label`, `period_type`, horizon fields).

**Response 201** — `ForecastVersionSerializer` output.

---

### `GET /api/demand/forecast-versions/{id}/`

Full detail for one version, including `line_count`.

---

### `GET /api/demand/forecast-versions/{id}/lines/`

Paginated `ForecastLine` records for a version.

**Query params**

| Param | Description |
|---|---|
| `item_id` | Filter by `Item.item_id` |
| `location_code` | Filter by `PlanningLocation.code` |
| `customer_code` | Filter by `PlanningCustomer.code` |
| `period_start` | ISO date — `period_start >= value` |
| `period_end` | ISO date — `period_end <= value` |
| `has_override` | `true` / `false` — presence of `override_qty` |
| `forecast_level` | Filter by grain string, e.g. `item_client`, `item_loc_depth_2` |
| `page` / `page_size` | Default 100, max 500 |

---

### `GET /api/demand/forecast-versions/{id}/aggregates/`

Returns `ForecastAggregate` rows (rolled-up totals) for a version.

**Query params:** `agg_level`, `period_start`, `period_end`

---

### `POST /api/demand/forecast-versions/{id}/approve/`

Drives the approval state machine. The version moves through:

```
DRAFT → (submit) → IN_REVIEW → (approve) → APPROVED → (lock) → LOCKED
                             ↘ (reject) → DRAFT
any   → (copy)   → new DRAFT (HTTP 201)
```

**Feature flag required:** `forecast_approval`

**Request body**
```json
{ "action": "submit|approve|reject|lock|copy", "note": "Optional note" }
```

A Celery task (`send_forecast_status_email`) is fired after every successful transition.

**Response**
- `200` — updated `ForecastVersionSerializer` output for all actions except `copy`
- `201` — new version serializer output for `copy`
- `400` — unknown action
- `403` — invalid transition (e.g. approving a DRAFT directly)

---

### `POST /api/demand/forecast-versions/{id}/run/`

Chains `compute_series_profiles → run_forecast` as a Celery task chain.
Returns HTTP 202 immediately.

**Feature flag required:** `forecast_run`

**Guards**
- Version must be DRAFT (`is_editable=True`)
- No run already in progress (`run_status` not in `QUEUED/PROFILING/RUNNING/…`)

**Response 202**
```json
{
  "version_id": 7,
  "run_status": "QUEUED",
  "celery_task_id": "abc-123",
  "poll_url": "/api/demand/forecast-versions/7/run-status/"
}
```

---

### `GET /api/demand/forecast-versions/{id}/run-status/`

Poll the run progress.

**Response 200**
```json
{
  "version_id": 7,
  "run_status": "RUNNING",
  "celery_task_id": "abc-123",
  "run_error": "",
  "line_count": 12480,
  "aggregate_count": 360
}
```

`run_status` values: `QUEUED → PROFILING → RUNNING → RECONCILING → AGGREGATING → DONE | FAILED`

---

## 7. Override endpoints

All override endpoints require the version to be DRAFT (`is_editable=True`).

### `GET /api/demand/forecast-versions/{id}/overrides/`

List all overrides for a version.

**Query params:** `override_level`, `period_start` (ISO date), `is_applied` (`true`/`false`)

**Response**
```json
{
  "version_id": 7,
  "version_label": "Jan-2025 Baseline",
  "version_status": "DRAFT",
  "count": 3,
  "results": [{ "...ForecastOverride fields..." }]
}
```

---

### `POST /api/demand/forecast-versions/{id}/overrides/`

Create one `ForecastOverride` and immediately fire `apply_overrides.delay(version_id)`.

**Request body** — fields from `ForecastOverrideCreateSerializer` plus an optional
`split_weights_json` string (JSON array of `{child_key, weight}` objects) when
`disagg_method` is `CUSTOM`.

`split_weights_json` is parsed and bulk-created into `OverrideSplitWeight` before the task fires.

**Response 202** — `ForecastOverrideDetailSerializer` output.

---

### `GET /api/demand/forecast-versions/{id}/overrides/{override_id}/`

Detail of one override, including any `OverrideSplitWeight` rows for CUSTOM overrides.

---

### `DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/`

Remove an override.

- If `is_applied=False`: deletes the row only.
- If `is_applied=True`: calls `_revert_override_lines()` to null out
  `override_qty` on the affected `ForecastLine` rows (line-by-line via `save()`
  so `final_qty`, `override_value`, `final_value` recompute), then deletes the
  row, then calls `write_forecast_aggregates()` to refresh rollups.

**Response 204** — no content.

---

### `GET /api/demand/forecast-versions/{id}/overrides/{override_id}/affected-lines/`

Shows which `ForecastLine` rows are (or will be) affected by the override.

- **Applied override** — returns lines where `override_qty IS NOT NULL` and key matches.
- **Pending override** — returns candidate lines (preview without the NOT NULL condition).

**Query params:** `page` / `page_size` (default 50, max 200)

---

### `GET /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/`

List `OverrideSplitWeight` rows for a CUSTOM override.

---

### `PUT /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/`

Atomically replace all split weights for a CUSTOM override.

**Request body** — `OverrideSplitWeightBulkSerializer` (`{"weights": [{child_key, weight}, …]}`)

Weights must sum to 1.0. After replacing, `is_applied` is reset to `False` so
`apply_overrides` re-disaggregates with the new weights.

---

## 8. Series profile endpoints

`SeriesProfile` records are created/updated by the `compute_series_profiles` Celery task
and are not directly writable (except for planner overrides via PATCH).

### `GET /api/demand/series-profiles/`

Paginated list of series profiles (lightweight — no nested evaluation log).

**Query params**

| Param | Description |
|---|---|
| `demand_class` | `SMOOTH`, `ERRATIC`, `INTERMITTENT`, `LUMPY`, `INSUFFICIENT`, `ZERO` |
| `abc_class` | `A`, `B`, `C`, `D` |
| `chosen_grain` | Exact grain string |
| `has_override` | `true` / `false` — whether override_grain/strategy are set |
| `is_manual` | `true` — only profiles with `chosen_strategy=MANUAL` |
| `location_code` | Filter by `PlanningLocation.code` |
| `period_type` | Filter by period bucket type |
| `page` / `page_size` | Default 100, max 500 |

---

### `GET /api/demand/series-profiles/{id}/`

Full profile detail including nested `SeriesLevelEvaluation` audit trail.

---

### `PATCH /api/demand/series-profiles/{id}/`

Planner override — only `override_grain`, `override_strategy`, and `override_note`
are writable. Attempting to update any other field returns HTTP 400.

**Feature flag required:** `consensus_override`

Sets `override_set_by` and `override_set_at` on save.

---

### `GET /api/demand/series-profiles/{id}/evaluations/`

Lazy-load alternative to the nested evaluations in the detail endpoint.
Returns all `SeriesLevelEvaluation` rows for this series, ordered with rejected
levels first and the accepted level last (mirrors the algorithm's search path).

---

## 9. Forecasting config endpoint

### `GET /api/demand/forecasting-config/`

Returns the `ForecastingConfig` for the client plus `AbcClassDefinition` tiers
and derived time horizons.

**Query params:** `period_type` (default `month`) — used to compute derived horizon values.

---

### `PATCH /api/demand/forecasting-config/`

Update classification thresholds. Staff users only (`request.user.is_staff`).
ABC tiers must be managed via Django admin.

---

## 10. Accuracy endpoint

### `GET /api/demand/forecast-versions/{id}/accuracy/`

Aggregates `ForecastAccuracy` records using DuckDB in-process for fast
grouping over large result sets. Pulls data into a pandas DataFrame, registers
it with DuckDB, and runs grouping SQL before returning.

**Query params**

| Param | Default | Description |
|---|---|---|
| `group_by` | `category` | `category`, `location`, `period`, `item` |
| `period_start` | — | ISO date — include only periods >= this date |
| `period_end` | — | ISO date — include only periods <= this date |

**Response 200**
```json
{
  "version_id": 7,
  "version_label": "Jan-2025 Baseline",
  "group_by": "location",
  "count": 12,
  "overall": {
    "mean_mape": "14.32",
    "mean_bias": "2.10",
    "record_count": 1440
  },
  "results": [
    {
      "group_key": "DEL",
      "mean_mape": "9.41",
      "mean_bias": "-1.20",
      "min_mape": "3.10",
      "max_mape": "18.90",
      "record_count": 120,
      "over_forecast_pct": "38.33"
    }
  ]
}
```

Returns an empty `results: []` with a detail message if no accuracy records exist yet.
Accuracy records are populated by a separate `compute_accuracy` task after actuals land.

---

## 11. Export endpoint

### `GET /api/demand/forecast-versions/{id}/export/`

Streams an `.xlsx` workbook for the version. Built with `openpyxl` inline
(no temp files). The workbook contains:
- **Sheet 1** — `ForecastLine` detail (all lines, with override columns)
- **Sheet 2** — Period summary (qty total, value total, override count per period)
  with an Excel SUM formula totals row appended automatically.

**Response** — `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`

---

## 12. Error reference

| Status | Cause |
|---|---|
| 400 | Validation failure (invalid field values, date format errors, unknown action) |
| 403 | Feature flag disabled, wrong version status, non-staff PATCH on config |
| 404 | Resource not found or belongs to a different client |
| 409 | Forecast run already in progress |
| 202 | Async operation accepted (upload, run, override create) — poll the returned URL |

Date fields everywhere expect ISO 8601: `YYYY-MM-DD`.

---

## 13. End-to-end testing guide

The minimal happy path to verify the full demand planning flow:

### Step 1 — Enable feature flags (Django admin)

Enable at least `demand_planning`, `actuals_upload`, and `forecast_run` for your
test client (`bahushira`).

### Step 2 — Seed hierarchies

POST location and sales node data, or create `PlanningLocation` / `SalesNode`
records directly in the shell or via fixtures.

### Step 3 — Download the actuals template

```
GET /api/demand/actuals/template/?period_type=month
```

Fill in the downloaded `.xlsx` with test rows. At minimum include columns for
`item_id`, `location_code`, `period_start`, `period_end`, `qty`, `value`.

### Step 4 — Upload actuals

```
POST /api/demand/actuals/upload/
Content-Type: multipart/form-data

file=<filled_template.xlsx>
period_type=month
```

Poll `GET /api/demand/actuals/upload/{import_id}/` until `status=done`.

Verify: `GET /api/demand/actuals/?period_type=month` returns rows.

### Step 5 — Create a forecast version

```
POST /api/demand/forecast-versions/
{
  "version_label": "Test Run 01",
  "period_type": "month",
  ...
}
```

Note the returned `id`.

### Step 6 — Trigger the forecast run

```
POST /api/demand/forecast-versions/{id}/run/
```

Poll `GET /api/demand/forecast-versions/{id}/run-status/` until `run_status=DONE`.

### Step 7 — Inspect results

```
GET /api/demand/forecast-versions/{id}/lines/
GET /api/demand/forecast-versions/{id}/aggregates/
GET /api/demand/series-profiles/
```

### Step 8 — Apply an override

```
POST /api/demand/forecast-versions/{id}/overrides/
{
  "override_level": "location",
  "override_key": {"location_code": "DEL"},
  "period_type": "month",
  "period_start": "2025-01-01",
  "override_qty": 1500,
  "disagg_method": "PROPORTIONAL"
}
```

Poll the affected-lines endpoint to verify propagation:
```
GET /api/demand/forecast-versions/{id}/overrides/{override_id}/affected-lines/
```

### Step 9 — Submit for approval

```
POST /api/demand/forecast-versions/{id}/approve/
{ "action": "submit", "note": "Ready for review" }
```

Approve:
```
POST /api/demand/forecast-versions/{id}/approve/
{ "action": "approve" }
```

### Step 10 — Export

```
GET /api/demand/forecast-versions/{id}/export/
```

Download and open the `.xlsx` to verify line detail and period summary sheets.
