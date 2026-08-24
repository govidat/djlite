# Phase 3B — Demand Planning Module: Complete Project Plan

**App label:** `mysite`  
**Stack:** Django 5.2 · DRF · Celery · Redis · PostgreSQL · DaisyUI · HTMX  
**Document status:** Living document — updated after each sprint  
**Last updated:** Sprint 3B.3 complete + Item Lifecycle (3B.2d) complete  

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Standalone Design Decisions](#2-standalone-design-decisions)
3. [Package Registry](#3-package-registry)
4. [Model Registry](#4-model-registry)
5. [API Endpoint Registry](#5-api-endpoint-registry)
6. [Celery Task Registry](#6-celery-task-registry)
7. [File Layout](#7-file-layout)
8. [Feature Flag Registry](#8-feature-flag-registry)
9. [Sprint Status](#9-sprint-status)
10. [Open Decisions and Risks](#10-open-decisions-and-risks)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    DEMAND PLANNING MODULE                       │
│                                                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  Hierarchy   │  │   Actuals    │  │   Forecast           │  │
│  │  Layer       │  │   Layer      │  │   Layer              │  │
│  │              │  │              │  │                      │  │
│  │ Planning     │  │ ActualSale   │  │ ForecastVersion      │  │
│  │ Location     │  │ (flexible    │  │ ForecastLine         │  │
│  │ (tree)       │  │  period)     │  │ ForecastAggregate    │  │
│  │              │  │              │  │ ForecastOverride     │  │
│  │ Planning     │  │ ActualSale   │  │ OverrideSplitWeight  │  │
│  │ Customer     │  │ Location     │  │ ForecastAccuracy     │  │
│  │ (tree)       │  │ (summary)    │  │                      │  │
│  │              │  │              │  │ SeriesProfile ◄──────┼──┤
│  │ SalesNode    │  │ ActualSale   │  │ (ADI / CV²           │  │
│  │ (tree)       │  │ Import       │  │  classification)     │  │
│  │              │  │ (audit log)  │  │                      │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬───────────┘  │
│         │                 │                      │              │
│         └─────────────────┴──────────────────────┘              │
│                           │                                     │
│                    Item (mysite.Item)                           │
│                    from Catalog module ─────────────────────►  │
│                    (read-only reference, no duplication)        │
└─────────────────────────────────────────────────────────────────┘

External integrations (Sprint 3B.4+):
  StatsForecast / HierarchicalForecast ──► ForecastLine.statistical_qty
  SeriesProfile.effective_strategy     ──► model selection per series
  ForecastLine.final_qty               ──► Purchase Orders / Production Plans
```

---

## 2. Standalone Design Decisions

These decisions are finalised and must not be revisited without a documented reason.

### 2.1 Four hierarchies — three standalone, one reused

| Hierarchy | Operational model | Demand Planning model | Reason for separation |
|---|---|---|---|
| Location | `ClientLocation` | `PlanningLocation` | eCommerce locations have operational significance (shipping, stock). Planning locations are arbitrary groupings. |
| Customer | `CustomerProfile` | `PlanningCustomer` | `CustomerProfile` is tied to `auth.User` (eCommerce buyer). Planning customers are pushed externally, no login required. |
| Sales | _(none)_ | `SalesNode` | New concept — sales org chart for demand attribution only. |
| Product/Item | `TaxonomyNode` | **`mysite.Item` (reused)** | Item catalog already exists. FK to `Item`, not duplicated. |

### 2.2 Item FK correction (applied Sprint 3B.2)

`ActualSale.item` and `ForecastLine.item` point to **`mysite.Item`**, not `TaxonomyNode`. The product planning taxonomy (`slug='product_planning'`) is used for hierarchical rollups but items are the leaf-level reference.

### 2.3 Flexible period design

Periods are **not fixed to monthly**. Every actuals and forecast row carries:

```
period_type   CharField  — second/minute/hour/day/week/month/bimonth/quarter/halfyear/year
period_start  DateField  — first day of the bucket (validated anchor)
period_end    DateField  — last day (auto-computed in save(), stored for fast range queries)
```

`period_type` is set at the **client level per forecast run** — all rows in one forecast series must share the same `period_type`. Mixing periods within a series breaks StatsForecast.

`PERIOD_FREQ_MAP` in `actuals.py` maps each `period_type` to its pandas/StatsForecast offset alias:

```python
PERIOD_FREQ_MAP = {
    'second': 's',    'minute': 'min',  'hour': 'h',
    'day': 'D',       'week': 'W-MON',  'month': 'MS',
    'bimonth': '2MS', 'quarter': 'QS',  'halfyear': '2QS',
    'year': 'YS',
}
```

### 2.4 Actuals grain

```
ActualSale: client × planning_location × item × planning_customer × period_type × period_start
```

`planning_customer` is nullable — null means unattributed / location-level demand.

Two partial unique indexes replace the standard `unique_together` to handle the NULL case correctly in PostgreSQL:

```sql
-- Rows WITH a customer
CREATE UNIQUE INDEX uq_actualsale_with_customer ON mysite_actualsale (
    client_id, planning_location_id, item_id,
    planning_customer_id, period_type, period_start
) WHERE planning_customer_id IS NOT NULL;

-- Rows WITHOUT a customer
CREATE UNIQUE INDEX uq_actualsale_no_customer ON mysite_actualsale (
    client_id, planning_location_id, item_id,
    period_type, period_start
) WHERE planning_customer_id IS NULL;
```

### 2.5 ForecastVersion status state machine

```
DRAFT → IN_REVIEW → APPROVED → LOCKED (terminal)
  ↑          │
  └──────────┘  (send back for rework)

LOCKED.copy() → new DRAFT
```

- Only `DRAFT` versions accept edits and overrides.
- `LOCKED` versions are immutable — used as PO/production plan baseline.
- `transition_to(new_status, user)` enforces allowed transitions and raises `ValidationError` on violation.
- `assert_editable()` is called at the top of every mutation view and Celery task that writes to a version.

### 2.6 SeriesProfile and forecast level selection (added Sprint 3B.3)

Before each forecast run, `compute_series_profiles` Celery task classifies every `(item, customer, location)` series using the **Syntetos-Boylan (2005)** framework:

| ADI | CV² | Class | Strategy |
|---|---|---|---|
| < 1.32 | < 0.49 | SMOOTH | AutoETS |
| < 1.32 | ≥ 0.49 | ERRATIC | AutoARIMA |
| ≥ 1.32 | < 0.49 | INTERMITTENT | CrostonSBA |
| ≥ 1.32 | ≥ 0.49 | LUMPY | Aggregate to location level |
| — | — | INSUFFICIENT (< 6 non-zero periods) | Moving average |
| — | — | ZERO | Manual / skip |

Planners can override the auto-classification by setting `SeriesProfile.override_strategy`. The forecast task always reads `SeriesProfile.effective_strategy` (which honours the override).

`ForecastLine` records what actually happened:
- `forecast_level` — the aggregation level used (e.g. `sku_customer_location`, `location`)
- `model_used` — the StatsForecast model that produced `statistical_qty`

### 2.7 `_("...")` — gettext_lazy throughout

All new Demand Planning models use `gettext_lazy as _` for verbose names, help text, choice labels, and validation messages. `from __future__ import annotations` is at the top of `forecast.py` to resolve forward-reference type hint warnings.

### 2.8 Feature flag utility

`utils/feature_control.py` — existing `is_feature_disabled()` is unchanged. Demand planning adds:

- `is_demand_feature_disabled(client, feature)` — checks master `demand_planning` switch before sub-feature
- `demand_feature_required(feature)` — view decorator
- `celery_demand_feature_guard(client, feature)` — Celery task guard returning skip-dict or None
- `bust_feature_cache(sender, instance)` — `post_save` signal handler for cache invalidation

### 2.9 Item Lifecycle Management (planned Sprint 3B.2d)

Items pass through lifecycle events a naive "one item, one series" model cannot represent. Three events are
supported under one umbrella — one `ForecastingConfig.use_item_lifecycle` flag (default `True`), one
`item_lifecycle` `ClientFeatureControl` key, one HTMX/admin UI — but each lands in a **different layer**:

| Event | Scenario | Layer | Where it runs |
|---|---|---|---|
| `ItemSubstitution` | retired code → successor, qty conversion (`2 old = 1 new`) | baseline re-key | inside `actuals_queryset_with_net()` after scheme + outlier netting |
| `ItemDiscontinuation` | item withdrawn from an effective date | forecast-output filter | `write_forecast_lines` (nil on/after `effective_from`) |
| `ItemIntroduction` | new item with no history borrows a reference forecast × `ratio` | forecast-output copy | `write_forecast_lines` (window-bounded, stops at enough own history) |

**One lifecycle directive per item:** event-subject roles (substitution `old_item`/`new_item`, discontinued
item, introduction `new_item`) are pairwise exclusive — validated in each model's `clean()` via a shared
`_assert_subject_role_free()` helper (chains and cycles impossible). Direct mapping only for substitution.
Discontinuation keeps the item's history (still feeds reporting/ABC/accuracy); it is a forecast-output
filter, not a data mutation. Introduction copies the **reference item's statistical line** (reference is not
retired), tags borrowed lines with `borrowed_from_item` / `borrowed_ratio` on `ForecastLine`, and stops at
the earlier of `copy_to` and `min_history_periods` own periods. Nothing is materialized at save time — the
substitution layer is a live re-key JOIN, and the output layers read the models at write time.

---

## 3. Package Registry

### 3.1 `requirements.txt` additions

```
# --- Phase 3B: Demand Planning ---
statsforecast>=2.0.0
hierarchicalforecast>=1.0.0
polars>=1.0.0
duckdb>=1.0.0
prophet>=1.1.0          # optional — heavy install, defer if pipeline is slow
openpyxl>=3.1.0
pandas>=2.0.0

# --- Task Queue (Phase 3B) ---
celery[redis]>=5.3.0
django-celery-results   # optional — stores task results in DB

# --- Testing ---
pytest>=8.0.0
pytest-django>=4.8.0
pytest-cov>=5.0.0
```

### 3.2 Key API notes

| Package | Version gotcha |
|---|---|
| `statsforecast` | v2.x: `prediction_intervals=ConformalIntervals(h=N, n_windows=2)` passed to `forecast()`, not `__init__()`. `fitted=True` also passed to `forecast()`. |
| `hierarchicalforecast` | v1.5+: `reconcile()` takes `S_df=` not `S=`. `aggregate()` returns `(Y_df, S_df, tags)` — `Y_df` is already long format, do not stack. |
| `celery` | `from celery import shared_task` requires celery installed — add to requirements before using. |
| `pytest` | `import pytest` requires `pytest` and `pytest-django` installed — add to requirements before using. |

---

## 4. Model Registry

All models live under `mysite/models/demand/`.

### 4.1 `hierarchy.py`

| Model | Key fields | Notes |
|---|---|---|
| `PlanningLocation` | `client`, `parent→self`, `code`, `name`, `level_label`, `is_leaf`, `path`, `is_active` | Materialized path mixin. `text_pattern_ops` index via RunSQL. |
| `PlanningCustomer` | `client`, `parent→self`, `code`, `name`, `customer_type`, `external_id`, `path` | `customer_type`: real / group. Nullable FK on ActualSale. |
| `SalesNode` | `client`, `parent→self`, `planning_location→PlanningLocation nullable`, `code`, `name`, `level_label`, `path` | Informational link to PlanningLocation only. |
| `CustomerSalesAssignment` | `planning_customer`, `sales_node`, `valid_from`, `valid_to nullable` | Date-effective. `clean()` rejects overlapping open assignments for same customer. |

**`MaterializedPathMixin`** (abstract): `path` CharField, `build_path()`, `save()` cascade, `get_descendants()`, `get_ancestors()`, `depth` property.

### 4.2 `actuals.py`

| Model | Key fields | Notes |
|---|---|---|
| `ActualSaleImport` | `client`, `uploaded_by`, `file_name`, `period_type`, `row_count`, `status`, `error_log` | Audit log for each upload batch. |
| `ActualSale` | `client`, `planning_location`, `item→mysite.Item`, `planning_customer nullable`, `period_type`, `period_start`, `period_end`, `qty`, `revenue nullable`, `import_batch` | `period_end` auto-computed in `save()`. Two partial unique indexes for NULL customer case. |
| `ActualSaleLocation` | `client`, `planning_location`, `period_type`, `period_start`, `period_end`, `total_qty`, `total_revenue nullable` | Location-level summary. Populated by `process_summary_actuals_import` or rollup task. |

**Module-level exports from `actuals.py`:**
- `PERIOD_TYPE_CHOICES` — list of (value, label) tuples
- `PERIOD_FREQ_MAP` — dict mapping period_type → pandas freq string
- `compute_period_end(period_start, period_type)` → `date`
- `validate_period_start(period_start, period_type)` → raises `ValueError`

### 4.3 `forecast.py`

| Model | Key fields | Notes |
|---|---|---|
| `ForecastVersion` | `client`, `version_label`, `period_type`, `base_period_end`, `horizon_periods`, `engine_config JSONField`, `status`, `created_by`, `approved_by nullable`, `approved_at nullable`, `locked_at nullable`, `copied_from→self nullable` | State machine via `transition_to()`. `copy()` clones to new DRAFT. |
| `ForecastLine` | `version`, `item→mysite.Item`, `planning_customer nullable`, `planning_location`, `period_type`, `period_start`, `period_end`, `statistical_qty`, `override_qty nullable`, `final_qty`, `forecast_level`, `model_used`, `borrowed_from_item→mysite.Item nullable`, `borrowed_ratio nullable` | `final_qty` = `override_qty` if set else `statistical_qty`. Auto-computed in `save()`. `borrowed_from_item`/`borrowed_ratio` tag lines copied from a reference item by `ItemIntroduction` (Sprint 3B.2d). |
| `ForecastAggregate` | `version`, `agg_level`, `agg_key JSONField`, `period_type`, `period_start`, `period_end`, `statistical_qty`, `override_qty nullable`, `final_qty` | Pre-rolled aggregates. Read-only from API. Populated by Celery. |
| `ForecastOverride` | `version`, `override_level`, `override_key JSONField`, `period_type`, `period_start`, `override_qty nullable`, `override_pct nullable`, `disagg_method`, `override_note`, `created_by`, `is_applied` | Exactly one of `override_qty` / `override_pct` must be set. DRAFT only. |
| `OverrideSplitWeight` | `override`, `child_key JSONField`, `weight` | Only for `disagg_method=CUSTOM`. Weights should sum to 1.0. |
| `ForecastAccuracy` | `version`, `item`, `planning_customer nullable`, `planning_location`, `period_type`, `period_start`, `actual_qty`, `forecast_qty`, `mape nullable`, `bias nullable` | Populated after actuals land. Read-only. |
| `SeriesProfile` | `client`, `item`, `planning_customer nullable`, `planning_location`, `period_type`, `analysis_from`, `analysis_to`, `total_periods`, `nonzero_periods`, `total_qty`, `adi nullable`, `cv2 nullable`, `zero_rate`, `demand_class`, `recommended_strategy`, `override_strategy`, `override_note` | Syntetos-Boylan classification. Populated by `compute_series_profiles` Celery task. Planner can set `override_strategy`. |

**`ForecastVersion.Status` choices:** `DRAFT`, `IN_REVIEW`, `APPROVED`, `LOCKED`

**`SeriesProfile.DemandClass` choices:** `SMOOTH`, `ERRATIC`, `INTERMITTENT`, `LUMPY`, `INSUFFICIENT`, `ZERO`

**`SeriesProfile.ForecastStrategy` choices:** `AUTOETS`, `AUTOARIMA`, `CROSTON`, `AGG_LOCATION`, `AGG_ITEM`, `AGG_TOTAL`, `MOVING_AVG`, `MANUAL`

**`SeriesProfile.classify(qty_series, adi_threshold, cv2_threshold, min_nonzero)`** — classmethod, pure function, returns dict with all metrics and classification. No DB access.

### 4.5 `lifecycle.py` (Sprint 3B.2d — Item Lifecycle Management)

| Model | Key fields | Notes |
|---|---|---|
| `ItemSubstitution` | `client`, `old_item`, `new_item`, `conversion_factor`, `effective_from nullable`, `notes` | Scenario 3 — retired code → successor. `unique (client, old_item)`; `conversion_factor > 0`; **direct mapping only** (an item may never be both predecessor and successor → no chains/cycles). Old-item rows with `period_start < effective_from` (NULL = whole history) re-key to the successor, scaled by `conversion_factor` on qty **and** revenue (per-unit price preserved); exclusive cutoff so converted history and the successor's own actuals never overlap. Applied as a live re-key layer in `actuals_queryset_with_net()` after scheme + outlier netting. The retired old item's own forecast is nil on/after `effective_from`. |
| `ItemDiscontinuation` | `client`, `item`, `effective_from nullable`, `notes` | Scenario 1 — item withdrawn. `unique (client, item)`. Forecast-output **filter** at `write_forecast_lines`: no `ForecastLine` for horizon periods `>= effective_from` (NULL = nil immediately); pre-cutoff periods forecast normally from the item's own history. History kept for reporting/ABC/accuracy — not a data mutation, not an `Item` status change. |
| `ItemIntroduction` | `client`, `new_item`, `reference_item`, `ratio`, `copy_from nullable`, `copy_to nullable`, `notes` | Scenario 2 — new item with no history. `unique (client, new_item)`; `ratio > 0`; `copy_to >= copy_from`; no reference chains. Forecast-output **copy** at `write_forecast_lines`: the new item's line = reference statistical line × `ratio`, tagged `borrowed_from_item`/`borrowed_ratio`; borrow bounded by `[copy_from, copy_to]` (NULL bounds) and stops at the earlier of `copy_to` and `min_history_periods` own periods. Reference item not retired. |

All three share the `_assert_subject_role_free(client_id, item_id, exclude_model, exclude_pk)` helper that
enforces **one lifecycle directive per item** (subject roles pairwise exclusive across the three models).
No data signals are needed — the substitution layer is a live JOIN and the output layers read the models at
write time.

### 4.4 Index name reference

All index names follow the convention `ix_{abbreviated_model}_{abbreviated_fields}` and are ≤ 30 characters (enforced by `manage.py check`).

| Index name | Table | Fields |
|---|---|---|
| `ix_planloc_client_leaf` | `mysite_planninglocation` | `client`, `is_leaf` |
| `ix_planloc_path_tpo` | `mysite_planninglocation` | `path text_pattern_ops` |
| `ix_plancust_client_type` | `mysite_planningcustomer` | `client`, `customer_type` |
| `ix_plancust_path_tpo` | `mysite_planningcustomer` | `path text_pattern_ops` |
| `ix_salesnode_path_tpo` | `mysite_salesnode` | `path text_pattern_ops` |
| `ix_custsales_cust_from` | `mysite_customersalesassignment` | `planning_customer`, `valid_from` |
| `ix_custsales_node_from` | `mysite_customersalesassignment` | `sales_node`, `valid_from` |
| `ix_actualsale_loc_period` | `mysite_actualsale` | `client`, `planning_location`, `period_type`, `period_start` |
| `ix_actualsale_item_period` | `mysite_actualsale` | `client`, `item`, `period_type`, `period_start` |
| `ix_actualsale_cust_period` | `mysite_actualsale` | `client`, `planning_customer`, `period_type`, `period_start` |
| `ix_actualsale_period_range` | `mysite_actualsale` | `client`, `period_type`, `period_start`, `period_end` |
| `uq_actualsale_with_customer` | `mysite_actualsale` | partial unique — with customer |
| `uq_actualsale_no_customer` | `mysite_actualsale` | partial unique — without customer |
| `ix_fcstver_client_status` | `mysite_forecastversion` | `client`, `status` |
| `ix_fcstver_client_period` | `mysite_forecastversion` | `client`, `period_type`, `base_period_end` |
| `ix_forecastline_version` | `mysite_forecastline` | `version_id`, `period_start` |
| `ix_forecastline_item_period` | `mysite_forecastline` | `version_id`, `item_id`, `period_start` |
| `ix_forecastline_location_period` | `mysite_forecastline` | `version_id`, `planning_location_id`, `period_start` |
| `ix_forecastaggregate_version_level` | `mysite_forecastaggregate` | `version_id`, `agg_level`, `period_start` |
| `ix_fcastoverride_ver_level` | `mysite_forecastoverride` | `version`, `override_level`, `period_start` |
| `ix_fcastoverride_ver_applied` | `mysite_forecastoverride` | `version`, `is_applied` |
| `ix_fcastacc_ver_period` | `mysite_forecastaccuracy` | `version`, `period_start` |
| `ix_seriespro_client_cls` | `mysite_seriesprofile` | `client`, `demand_class` |
| `ix_seriespro_client_strat` | `mysite_seriesprofile` | `client`, `recommended_strategy` |
| `ix_itemsubst_old` | `mysite_itemsubstitution` | `client`, `old_item` |
| `ix_itemsubst_new` | `mysite_itemsubstitution` | `client`, `new_item` |
| `ix_itemdisc_item` | `mysite_itemdiscontinuation` | `client`, `item` |
| `ix_itemintro_new` | `mysite_itemintroduction` | `client`, `new_item` |
| `ix_itemintro_ref` | `mysite_itemintroduction` | `client`, `reference_item` |

---

## 5. API Endpoint Registry

**Base path:** `/api/demand/`  
**Auth:** `SessionAuthentication` — all endpoints require `IsAuthenticated`  
**Feature gate:** All endpoints check `demand_planning` master flag via `DemandFeatureMixin`

### 5.1 Hierarchy endpoints (Sprint 3B.1)

| Method | URL | View | Feature flag | Notes |
|---|---|---|---|---|
| `GET` | `location-hierarchy/` | `PlanningLocationHierarchyView` | `demand_planning` | Query: `active_only`, `leaves_only` |
| `GET` | `sales-hierarchy/` | `SalesHierarchyView` | `demand_planning` | Query: `active_only`, `with_assignments` |

### 5.2 Actuals endpoints (Sprint 3B.2)

| Method | URL | View | Feature flag | Notes |
|---|---|---|---|---|
| `POST` | `actuals/upload/` | `ActualsUploadView` | `actuals_upload` | Multipart. Returns 202 + job ID immediately. |
| `GET` | `actuals/upload/{id}/` | `ActualsUploadStatusView` | `demand_planning` | Poll import job status. |
| `GET` | `actuals/` | `ActualsQueryView` | `demand_planning` | Query: item_id, location_code, customer_code, period_start, period_end, period_type. Paginated. |
| `GET` | `actuals/template/` | `ActualsTemplateDownloadView` | `demand_planning` | Streams generated .xlsx template. |

### 5.3 Forecast version endpoints (Sprint 3B.3)

| Method | URL | View | Feature flag | Notes |
|---|---|---|---|---|
| `GET` | `forecast-versions/` | `ForecastVersionListCreateView` | `demand_planning` | Query: `status` filter. Annotated with `line_count`. |
| `POST` | `forecast-versions/` | `ForecastVersionListCreateView` | `forecast_run` | Creates DRAFT version. |
| `GET` | `forecast-versions/{id}/` | `ForecastVersionDetailView` | `demand_planning` | Single version with metadata. |
| `GET` | `forecast-versions/{id}/lines/` | `ForecastVersionLinesView` | `demand_planning` | Query: item_id, location_code, customer_code, period_start, period_end, has_override. Paginated (max 500). |
| `GET` | `forecast-versions/{id}/aggregates/` | `ForecastVersionAggregatesView` | `demand_planning` | Query: agg_level, period_start, period_end. |
| `POST` | `forecast-versions/{id}/approve/` | `ForecastVersionApproveView` | `forecast_approval` | Body: `{"action": "submit\|approve\|reject\|lock\|copy", "note": "..."}` |

### 5.4 Series profile endpoints (Sprint 3B.3 — SeriesProfile addition)

| Method | URL | View | Feature flag | Notes |
|---|---|---|---|---|
| `GET` | `series-profiles/` | `SeriesProfileListView` | `demand_planning` | Query: demand_class, recommended_strategy, has_override, location_code, period_type. Paginated. |
| `GET` | `series-profiles/{id}/` | `SeriesProfileDetailView` | `demand_planning` | Single profile. |
| `PATCH` | `series-profiles/{id}/` | `SeriesProfileDetailView` | `consensus_override` | Only `override_strategy` and `override_note` writable. All other fields rejected with 400. |

---

## 6. Celery Task Registry

**Task module:** `mysite/tasks/demand/`

| Task | Module | Triggered by | Description |
|---|---|---|---|
| `process_actuals_import` | `import_actuals.py` | `ActualsUploadView` POST | Parse CSV/Excel, validate rows, bulk-upsert `ActualSale`. Row errors collected, batch continues. |
| `process_summary_actuals_import` | `import_actuals.py` | Separate upload endpoint (Sprint 3B.4) | Parse location-summary file, bulk-upsert `ActualSaleLocation`. |
| `compute_series_profiles` | `compute_series_profiles.py` | Before forecast task | Classify all `(item, customer, location)` series using ADI / CV². Write `SeriesProfile` rows. |
| `run_forecast` *(Sprint 3B.4)* | `run_forecast.py` | `POST forecast-versions/` | Pull actuals via DuckDB, build summing matrix from hierarchy trees, dispatch to StatsForecast by `effective_strategy`, write `ForecastLine` rows. |
| `run_reconciliation` *(Sprint 3B.4)* | `run_forecast.py` | After `run_forecast` | HierarchicalForecast MinTrace reconciliation, write `ForecastAggregate` rows. |
| `apply_overrides` *(Sprint 3B.4)* | `apply_overrides.py` | On `ForecastOverride` save | Disaggregate planner overrides to `ForecastLine.override_qty`, recompute `final_qty`. |
| `compute_accuracy` *(Sprint 3B.4)* | `compute_accuracy.py` | Scheduled nightly | Join `ForecastLine.final_qty` vs `ActualSale.qty`, write `ForecastAccuracy`. |

### Celery task pattern

All tasks follow this structure:

```python
@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def my_task(self, client_id):
    # 1. Feature guard
    skip = celery_demand_feature_guard(client, 'feature_name')
    if skip:
        return skip
    # 2. Set status = processing
    # 3. Call _run_my_task() — separated for direct test invocation
    # 4. On exception: set status = failed, retry
```

The `_run_*` inner function is always separated from the Celery wrapper so tests call it directly without a running Celery worker.

---

## 7. File Layout

```
mysite/
├── models/
│   └── demand/
│       ├── __init__.py          ← exports all 14 models
│       ├── hierarchy.py         ← PlanningLocation, PlanningCustomer,
│       │                           SalesNode, CustomerSalesAssignment
│       ├── actuals.py           ← ActualSale, ActualSaleImport,
│       │                           ActualSaleLocation,
│       │                           PERIOD_TYPE_CHOICES, PERIOD_FREQ_MAP,
│       │                           compute_period_end, validate_period_start
│       ├── lifecycle.py         ← ItemSubstitution, ItemDiscontinuation,
│       │                           ItemIntroduction + _assert_subject_role_free
│       └── forecast.py          ← ForecastVersion, ForecastLine,
│                                   ForecastAggregate, ForecastOverride,
│                                   OverrideSplitWeight, ForecastAccuracy,
│                                   SeriesProfile
├── api/
│   └── demand/
│       ├── __init__.py
│       ├── serializers.py       ← all demand serializers
│       ├── views.py             ← all demand views + build_tree() utility
│       └── urls.py              ← all demand URL patterns
├── tasks/
│   └── demand/
│       ├── __init__.py
│       ├── import_actuals.py    ← process_actuals_import,
│       │                           process_summary_actuals_import
│       └── compute_series_profiles.py  ← compute_series_profiles
├── management/
│   └── commands/
│       └── generate_actuals_template.py
├── admin/
│   ├── demand_forecast.py       ← ForecastVersionAdmin, ForecastLineAdmin,
│   │                               ForecastAccuracyAdmin, SeriesProfileAdmin
│   └── demand_lifecycle.py      ← ItemSubstitutionAdmin, ItemDiscontinuationAdmin,
│                                   ItemIntroductionAdmin (Sprint 3B.2d)
├── migrations/
│   ├── XXXX_demand_planning_foundation.py   ← Sprint 3B.0
│   ├── XXXX_clientfeaturecontrol_choices.py ← Sprint 3B.0
│   ├── XXXX_forecast_models.py              ← Sprint 3B.3
│   ├── XXXX_series_profile.py               ← Sprint 3B.3 (SeriesProfile delta)
│   ├── XXXX_item_lifecycle.py               ← Sprint 3B.2d (3 lifecycle models)
│   └── XXXX_borrowed_forecast_columns.py    ← Sprint 3B.2d (ForecastLine delta)
├── tests/
│   └── demand/
│       ├── __init__.py
│       ├── conftest.py              ← shared fixtures
│       ├── test_hierarchy_api.py    ← path, tree, assignment tests
│       ├── test_actuals_import.py   ← import task tests
│       └── test_forecast.py         ← final_qty, state machine, copy, override
└── utils/
    └── feature_control.py           ← is_feature_disabled (existing) +
                                        is_demand_feature_disabled,
                                        demand_feature_required,
                                        celery_demand_feature_guard,
                                        bust_feature_cache (delta additions)
```

---

## 8. Feature Flag Registry

Managed via `ClientFeatureControl` model (`FEATURE_CHOICES`). Null client = applies globally.

| Feature key | Controls | Default | Enabled when |
|---|---|---|---|
| `demand_planning` | Master switch — gates all sub-features | Disabled | Module is ready for a client |
| `actuals_upload` | `POST /actuals/upload/` + `process_actuals_import` task | Disabled | Import pipeline is wired (Sprint 3B.2 done) |
| `forecast_run` | `POST /forecast-versions/` + `run_forecast` task | Disabled | Forecast engine is wired (Sprint 3B.4 done) |
| `consensus_override` | `POST /forecast-versions/{id}/approve/` override actions + `SeriesProfile PATCH` | Disabled | Override UI is ready (Sprint 3B.3+) |
| `forecast_approval` | `POST /forecast-versions/{id}/approve/` submit/approve/lock actions | Disabled | Approval workflow is ready (Sprint 3B.3 done) |
| `item_lifecycle` | Item Substitution / Discontinuation / Introduction — re-key layer in the netting helper + output layers at `write_forecast_lines` + HTMX UI (`item_lifecycle_ui_visible()`) | Disabled | Lifecycle models are wired (Sprint 3B.2d done) |

---

## 9. Sprint Status

### Sprint 3B.0 — Foundation ✅ COMPLETE
**Effort:** 1–2 days

| Task | Status |
|---|---|
| `requirements.txt` — statsforecast, hierarchicalforecast, polars, duckdb, prophet, openpyxl, pandas | ✅ |
| `requirements.txt` — celery[redis], pytest, pytest-django, pytest-cov | ✅ |
| `ClientFeatureControl.FEATURE_CHOICES` — 5 demand planning keys added | ✅ |
| `utils/feature_control.py` — delta additions (is_demand_feature_disabled, decorator, guard, cache bust) | ✅ |
| `mysite/models/demand/` package created | ✅ |
| `hierarchy.py` — PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment | ✅ |
| `actuals.py` — ActualSale (flexible period), ActualSaleImport | ✅ |
| `forecast.py` — scaffolded empty | ✅ |
| Migration: demand_planning_foundation (hierarchy + actuals models) | ✅ |
| Migration: text_pattern_ops indexes via RunSQL | ✅ |
| Migration: clientfeaturecontrol_choices AlterField | ✅ |
| `manage.py check` — 0 issues | ✅ |
| Django admin — all hierarchy and actuals models registered | ✅ |
| `pytest.ini` / `pyproject.toml` configured | ✅ |
| `mysite/celery.py` created; wired into `__init__.py` | ✅ |
| `settings.py` — CELERY_BROKER_URL, CELERY_RESULT_BACKEND, LocaleMiddleware | ✅ |

---

### Sprint 3B.1 — Sales Hierarchy Models ✅ COMPLETE
**Effort:** 2–3 days

| Task | Status |
|---|---|
| `hierarchy.py` — SalesNode with materialized path | ✅ |
| `hierarchy.py` — CustomerSalesAssignment with date effectivity | ✅ |
| `pre_save` / `save()` signal computes materialized path | ✅ |
| `ix_salesnode_path_tpo` via RunSQL | ✅ |
| Admin: SalesNodeAdmin, CustomerSalesAssignmentInline | ✅ |
| `mysite/api/demand/` package created | ✅ |
| `build_tree()` utility in views.py | ✅ |
| `GET /api/demand/location-hierarchy/` | ✅ |
| `GET /api/demand/sales-hierarchy/` | ✅ |
| Serializers: PlanningLocationTreeSerializer, SalesNodeTreeSerializer, CustomerSalesAssignmentSerializer | ✅ |
| URLs registered | ✅ |
| Unit tests: path computation, reparent, subtree query, overlap assignment rejection | ✅ |

---

### Sprint 3B.2 — Actuals Models and Import Pipeline ✅ COMPLETE
**Effort:** 3–4 days

| Task | Status |
|---|---|
| `ActualSale` — flexible period (period_type + period_start + period_end) | ✅ |
| `ActualSale.item` — FK to `mysite.Item` (not TaxonomyNode) | ✅ |
| `ActualSaleLocation` model | ✅ |
| `ActualSaleImport` model | ✅ |
| Partial unique indexes (with/without customer) via RunSQL | ✅ |
| DB indexes via RunSQL | ✅ |
| Admin: ActualSaleAdmin (autocomplete_fields for item/location/customer), ActualSaleImportAdmin | ✅ |
| `POST /api/demand/actuals/upload/` | ✅ |
| `GET /api/demand/actuals/upload/{id}/` | ✅ |
| `GET /api/demand/actuals/` | ✅ |
| `GET /api/demand/actuals/template/` | ✅ |
| Celery task: `process_actuals_import` | ✅ |
| Celery task: `process_summary_actuals_import` | ✅ |
| Management command: `generate_actuals_template` | ✅ |
| Unit tests: idempotent import, invalid FK, missing columns, invalid anchor, null customer | ✅ |

---

### Sprint 3B.3 — Forecast Models and Version Management ✅ COMPLETE
**Effort:** 3–4 days

| Task | Status |
|---|---|
| `forecast.py` — ForecastVersion with status state machine | ✅ |
| `forecast.py` — ForecastLine (final_qty computed in save) | ✅ |
| `forecast.py` — ForecastAggregate | ✅ |
| `forecast.py` — ForecastOverride (override_qty XOR override_pct validation) | ✅ |
| `forecast.py` — OverrideSplitWeight | ✅ |
| `forecast.py` — ForecastAccuracy | ✅ |
| `forecast.py` — SeriesProfile (Syntetos-Boylan classification) | ✅ |
| `ForecastLine.forecast_level` and `model_used` fields | ✅ |
| `from __future__ import annotations` — resolves User type hint warnings | ✅ |
| Index names ≤ 30 chars — `ix_seriespro_client_cls`, `ix_seriespro_client_strat` | ✅ |
| Migration: forecast_models + RunSQL indexes | ✅ |
| Admin: ForecastVersionAdmin (status badge, readonly on non-DRAFT) | ✅ |
| Admin: ForecastLineAdmin, ForecastAccuracyAdmin | ✅ |
| Admin: SeriesProfileAdmin (has_add=False, has_delete=False, override_strategy editable) | ✅ |
| Serializers: ForecastVersionSerializer, ForecastVersionCreateSerializer | ✅ |
| Serializers: ForecastLineSerializer, ForecastAggregateSerializer | ✅ |
| Serializers: ForecastOverrideSerializer, SeriesProfileSerializer | ✅ |
| `GET/POST /api/demand/forecast-versions/` | ✅ |
| `GET /api/demand/forecast-versions/{id}/` | ✅ |
| `GET /api/demand/forecast-versions/{id}/lines/` | ✅ |
| `GET /api/demand/forecast-versions/{id}/aggregates/` | ✅ |
| `POST /api/demand/forecast-versions/{id}/approve/` | ✅ |
| `GET /api/demand/series-profiles/` | ✅ |
| `GET/PATCH /api/demand/series-profiles/{id}/` | ✅ |
| Celery task: `compute_series_profiles` | ✅ |
| Unit tests: final_qty, state machine, LOCKED → 403, version copy, override validation | ✅ |

---

### Sprint 3B.2d — Item Lifecycle (Substitution / Discontinuation / Introduction) ✅ COMPLETE
**Estimated effort:** 6–9 days  
**Dependencies:** 3B.2/3B.3 patterns (netted helper, admin, feature flags); design decision 2.9

| Task | Status |
|---|---|
| `lifecycle.py` — `ItemSubstitution`, `ItemDiscontinuation`, `ItemIntroduction` + `_assert_subject_role_free()` (one directive per item) | ✅ 0079 |
| Model `clean()` validations — factor/ratio > 0, same-client, old≠new / new≠reference, `copy_to >= copy_from`, duplicate subject, direct-mapping + mixed-role violations | ✅ 0079 |
| Migration: `add_item_lifecycle` (3 models + 5 indexes + CheckConstraints); register in `demand/__init__.py` and `ADMIN_ONLY_MODELS` | ✅ 0079 |
| `ForecastingConfig.use_item_lifecycle` (default True) + `item_lifecycle` feature key + `item_lifecycle_ui_visible()` | ✅ 0079 |
| Admin: `ItemSubstitutionAdmin`, `ItemDiscontinuationAdmin`, `ItemIntroductionAdmin` in `demand_lifecycle.py` | ✅ |
| Baseline re-key layer — `actuals_queryset_with_net(client, use_net, use_substitution)` (Scenario 3): correlated `Subquery` re-keys old rows to successor, scales net_qty/net_revenue by `conversion_factor` when `period_start < effective_from`; identity when flag off | ✅ |
| Re-key consumers to `eff_item_id`/`eff_item_code` — `build_actuals_dataframe`, `update_weighted_avg_prices`, `compute_series_profiles._load_actuals` | ✅ |
| Output layer — Discontinuation filter (Scenario 1): no `ForecastLine` for periods `>= effective_from`; retired substitution old_item also nil on/after its `effective_from` | ✅ |
| Output layer — Introduction borrow (Scenario 2): new-item line = reference statistical line × `ratio` while inside `[copy_from, copy_to]` and below `min_history_periods` own periods; tag `borrowed_from_item`/`borrowed_ratio`; roll-ups include borrowed values | ✅ |
| Migration: `add_borrowed_forecast_columns` (nullable `borrowed_from_item`, `borrowed_ratio` on `ForecastLine`) | ✅ 0080 |
| Detection — `run_outlier_detection` reads successor via the composed helper; skips retired substitution old_items, keeps discontinued items; reporting/ABC share the flag | ✅ |
| HTMX views — `item_*_list/create/edit` for all three models under `/planning/`, gated on `item_lifecycle_ui_visible` (no DRF endpoints) | ✅ |
| Unit tests — `test_item_lifecycle.py`: model validation, helper re-key + cutoff + identity + netting composition, consumers, output layers, detection skip rules, feature gate | ✅ |

---

### Sprint 3B.4 — Forecast Engine and Reconciliation 🔲 PLANNED
**Estimated effort:** 4–5 days  
**Dependencies:** Sprint 3B.3 complete

| Task | Status |
|---|---|
| Celery task: `run_forecast` — dispatch by `SeriesProfile.effective_strategy` | 🔲 |
| Pull actuals via DuckDB into Polars, build `Y_long` and `S_df` from hierarchy trees | 🔲 |
| StatsForecast batch dispatch: AutoETS / AutoARIMA / CrostonSBA per strategy group | 🔲 |
| Aggregation logic for LUMPY series: rollup to location, forecast, disaggregate back | 🔲 |
| Write `ForecastLine` rows with `model_used` and `forecast_level` | 🔲 |
| Celery task: `run_reconciliation` — HierarchicalForecast MinTrace, write `ForecastAggregate` | 🔲 |
| Celery task: `apply_overrides` — disaggregate `ForecastOverride` to `ForecastLine.override_qty` | 🔲 |
| Celery task: `compute_accuracy` — nightly MAPE / Bias vs actuals, write `ForecastAccuracy` | 🔲 |
| `POST /api/demand/forecast-versions/{id}/run/` — trigger forecast task chain | 🔲 |
| `GET /api/demand/forecast-versions/{id}/run-status/` — poll Celery task status | 🔲 |
| Unit tests: LUMPY series aggregated correctly; MinTrace coherence check; MAPE computation | 🔲 |

---

### Sprint 3B.5 — Consensus Override UI 🔲 PLANNED
**Estimated effort:** 3–4 days  
**Dependencies:** Sprint 3B.4 complete

| Task | Status |
|---|---|
| `POST /api/demand/forecast-versions/{id}/overrides/` — create override, fire `apply_overrides` task | 🔲 |
| `GET /api/demand/forecast-versions/{id}/overrides/` — list overrides with `is_applied` status | 🔲 |
| `DELETE /api/demand/forecast-versions/{id}/overrides/{id}/` — remove unapplied override | 🔲 |
| HTMX planner override form — inline edit on forecast grid | 🔲 |
| Override propagation UI — show which child lines were affected | 🔲 |
| `OverrideSplitWeight` management UI — custom disaggregation weights | 🔲 |
| Unit tests: override applied → ForecastLine.final_qty updated; delete override → reverts to statistical | 🔲 |

---

### Sprint 3B.6 — Forecast Approval and PO Export 🔲 PLANNED
**Estimated effort:** 2–3 days  
**Dependencies:** Sprint 3B.5 complete

| Task | Status |
|---|---|
| Approval workflow UI (submit / approve / reject / lock) | 🔲 |
| Email notification on status transition | 🔲 |
| `GET /api/demand/forecast-versions/{id}/export/` — export final_qty as .xlsx | 🔲 |
| Export format: Location × Item × Period (for purchase order input) | 🔲 |
| `ForecastAccuracy` dashboard endpoint — MAPE / Bias summary by category / location | 🔲 |
| Unit tests: export row count matches ForecastLine count; locked version export works | 🔲 |

---

## 10. Open Decisions and Risks

| # | Topic | Decision needed | Sprint |
|---|---|---|---|
| 1 | **ADI / CV² thresholds** | Default 1.32 / 0.49 (Syntetos-Boylan). Client-configurable via `engine_config` JSONField on ForecastVersion? | 3B.4 |
| 2 | **Min non-zero observations** | Default `min_nonzero=6`. Should this be a per-client setting or fixed? | 3B.4 |
| 3 | **Disaggregation weights for LUMPY** | When aggregating LUMPY series to location level then disaggregating, use historical share weights. Weights based on last 12 periods or full history? | 3B.4 |
| 4 | **Prophet model** | Optional model for series with strong seasonality + holiday effects. Deferred due to heavy install. Enable per client via `engine_config`? | 3B.4 |
| 5 | **`compute_series_profiles` trigger** | Currently planned as a pre-forecast Celery task. Should it also run nightly (scheduled) so planners can see classifications before triggering a forecast? | 3B.4 |
| 6 | **ForecastAggregate population** | Populated by Celery reconciliation task. Should it also be computable on-demand via API for partial/draft versions? | 3B.4 |
| 7 | **Override UI granularity** | Overrides at total/category/region level require disaggregation weights. PROPORTIONAL (default) uses historical shares. What if historical share is zero for a new item? | 3B.5 |
| 8 | **LOCKED version grace period** | Should APPROVED → LOCKED transition be manual (superadmin only) or auto after N days? | 3B.6 |
| 9 | **Accuracy computation timing** | `compute_accuracy` runs nightly. Should it be triggered immediately when actuals are uploaded for periods already forecasted? | 3B.6 |
