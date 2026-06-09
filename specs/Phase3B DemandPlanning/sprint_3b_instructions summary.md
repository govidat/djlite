# Sprint 3B.0 — Foundation and Prerequisites
## Demand Planning Module — Detailed Implementation Instructions

---

## 0. Architecture Decisions (Read Before Writing Any Code)

### Why all four hierarchies are standalone

The sprint description calls for Demand Planning to be self-contained. The implications are:

| Hierarchy | Operational model (DO NOT reuse) | New standalone model |
|---|---|---|
| Location | `ClientLocation` (eCommerce warehouses/branches) | `PlanningLocation` |
| Customer | `CustomerProfile` (eCommerce buyer, FK to `auth.User`) | `PlanningCustomer` |
| Sales | _(none yet)_ | `SalesNode` |
| Product/Item | `TaxonomyNode` slug `product_planning` | **Reused as-is** (read-only reference) |

`PlanningLocation`, `PlanningCustomer`, and `SalesNode` all carry a `parent` self-FK to form arbitrary-depth trees. They share no FK into `ClientLocation` or `CustomerProfile`. Data is pushed directly (CSV/API) and carries no link to eCommerce transactions.

The item hierarchy already exists in the Catalog module via `Taxonomy` / `TaxonomyNode`. A dedicated `Taxonomy` with `slug='product_planning'` holds the 3–5 level grouping (Category → Sub-category → Brand → SKU). No new models are needed for items.

### Lowest-level actuals grain

```
ActualSale: client × planning_location × item (TaxonomyNode leaf) × planning_customer × period
```

`planning_customer` is nullable — a null value means "aggregate / unattributed demand" for that location–item combination. The forecast output targets `location × item` at minimum and `location × customer × item` when customer-level detail exists.

---

## 1. `requirements.txt` — Add Packages

Add the following block to `requirements.txt`. Place it under a `# --- Phase 3B: Demand Planning ---` comment for clarity.

```
# --- Phase 3B: Demand Planning ---
statsforecast>=2.0.0
hierarchicalforecast>=1.0.0
polars>=1.0.0
duckdb>=1.0.0
prophet>=1.1.0
openpyxl>=3.1.0
pandas>=2.0.0
```

**Notes:**

`pandas` is almost certainly already present as a transitive dependency. Add it explicitly so your version constraint is pinned and visible. `prophet` has a heavy install (PyStan / cmdstanpy); if your deployment pipeline is slow, defer it to a separate `requirements-optional.txt` and install only when the Prophet model is enabled per client.


---

## 2. `ClientFeatureControl` Keys

Feature flags in your system live in `ClientFeatureControl`, not `GlobalVal`. The model uses a `FEATURE_CHOICES` list and a `client` FK (null = applies to all clients). Adding a new feature means two things only: extending `FEATURE_CHOICES` in the model, and running a migration to add the new choice values to the database.

### 2a. Extend `FEATURE_CHOICES` in the model

The five demand planning choices are already present in the code you shared. Confirm your `ClientFeatureControl` model in `mysite/models/` (wherever it lives) has exactly this block — add any entries that are missing:

```python
FEATURE_CHOICES = [
    ('catalogue',          'Catalogue'),
    ('ecommerce',          'E-Commerce'),
    # Phase 3B — Demand Planning
    ('demand_planning',    'Demand Planning Module'),
    ('actuals_upload',     'Actuals Upload'),
    ('forecast_run',       'Run Statistical Forecast'),
    ('consensus_override', 'Consensus Override'),
    ('forecast_approval',  'Forecast Approval Workflow'),
]
```

`FEATURE_CHOICES` is a Python-only constraint on the `feature` CharField — no schema change is needed for adding new choices to an existing `CharField`. Django does not alter the column. The migration that results from `makemigrations` will contain only an `AlterField` that records the new choices in migration state; it applies cleanly with zero downtime.



## 3. Model File Layout

Create the demand package inside your existing models directory:

```
mysite/models/demand/
    __init__.py
    hierarchy.py      ← PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
    actuals.py        ← ActualSale, ActualSaleImport
    forecast.py       ← ForecastVersion, ForecastLine, ForecastOverride  (Sprint 3B.1+)
```



---

## 4. `hierarchy.py` — All Three Standalone Hierarchies

Create `mysite/models/demand/hierarchy.py` with the following content in full:

```python
"""
mysite/models/demand/hierarchy.py

Three independent planning hierarchies, fully decoupled from eCommerce models:

  PlanningLocation    — arbitrary location tree (Region → Zone → DC → Branch)
  PlanningCustomer    — arbitrary customer / customer-group tree
  SalesNode           — sales-force org chart
  CustomerSalesAssignment — date-effective assignment of PlanningCustomer → SalesNode leaf

None of these carry FKs to ClientLocation or CustomerProfile.
"""


## 5. `actuals.py` — Actuals Grain and Import Log

### Design: flexible period buckets

The period is **not fixed to a month**. Each `ActualSale` row carries a `period_type` (the bucket granularity chosen for that client's planning cycle) and an explicit `period_start` / `period_end` date pair. This makes the model work for any of:

```
second  minute  hour  day  week  month  bimonth  quarter  halfyear  year
```

## 6. `forecast.py` 

Create `mysite/models/demand/forecast.py` as an empty scaffold so the package imports cleanly:

### 1.2 File layout for new code

```
mysite/
    api/
        demand/
            __init__.py
            serializers.py      ← hierarchy + actuals serializers
            views.py            ← all demand API views
            urls.py             ← demand URL patterns
    tasks/
        demand/
            __init__.py
            import_actuals.py   ← Celery tasks
    management/
        commands/
            generate_actuals_template.py
    tests/
        demand/
            __init__.py
            test_hierarchy_api.py
            test_actuals_import.py
            test_unit_tests.py
```

Attached Models, Views