# Sprint 3B.0 — Foundation and Prerequisites
## Demand Planning Module — Detailed Implementation Instructions

**App label:** `mysite`  
**Django version:** 5.2.x  
**Stack:** Django · Celery · Redis · PostgreSQL · DaisyUI / HTMX  
**Estimated effort:** 1–2 days  

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

Run in your virtualenv:

```bash
pip install -r requirements.txt
```

Verify the four core Nixtla packages:

```bash
python -c "
import statsforecast, hierarchicalforecast, polars, duckdb
print('statsforecast   ', statsforecast.__version__)
print('hierarchicalforecast', hierarchicalforecast.__version__)
print('polars          ', polars.__version__)
print('duckdb          ', duckdb.__version__)
"
```

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

### 2b. Run `makemigrations`

```bash
python manage.py makemigrations mysite --name clientfeaturecontrol_demand_planning_choices
```

The generated migration will look like this (verify it matches before applying):

```python
from django.db import migrations
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ("mysite", "PREVIOUS_MIGRATION"),  # auto-filled by Django
    ]

    operations = [
        migrations.AlterField(
            model_name="clientfeaturecontrol",
            name="feature",
            field=django.db.models.fields.CharField(
                choices=[
                    ("catalogue",          "Catalogue"),
                    ("ecommerce",          "E-Commerce"),
                    ("demand_planning",    "Demand Planning Module"),
                    ("actuals_upload",     "Actuals Upload"),
                    ("forecast_run",       "Run Statistical Forecast"),
                    ("consensus_override", "Consensus Override"),
                    ("forecast_approval",  "Forecast Approval Workflow"),
                ],
                max_length=30,
            ),
        ),
    ]
```

Apply it:

```bash
python manage.py migrate
```

### 2c. Create the initial feature control rows via Django admin

Once migrated, log into `/admin/` as superadmin and create one `ClientFeatureControl` row per feature, with `client=NULL` (applies globally) and `is_disabled=True` initially. This acts as the master off-switch until you are ready to enable per client.

| feature | is_disabled | from_date / to_date | Notes |
|---|---|---|---|
| `demand_planning` | `True` | Far future | Master switch — disable all sub-features if this is off |
| `actuals_upload` | `True` | Far future | Enable when import pipeline is ready (Sprint 3B.2) |
| `forecast_run` | `True` | Far future | Enable when Celery task is wired (Sprint 3B.2) |
| `consensus_override` | `True` | Far future | Enable when override UI is ready (Sprint 3B.3) |
| `forecast_approval` | `True` | Far future | Enable when approval workflow is ready (Sprint 3B.3) |

Set `from_date = now` and `to_date = 2099-12-31` as a practical "always on" sentinel while the module is in development. Flip `is_disabled` to `False` per client when you are ready to go live.

### 2d. Helper to check flags in views and Celery tasks

Add `mysite/utils/feature_flags.py` (create if absent). This replaces the incorrect `GlobalVal`-based version from the earlier draft:

```python
"""
mysite/utils/feature_flags.py

Utility for checking ClientFeatureControl flags in views and Celery tasks.
"""
# ─────────────────────────────────────────────────────────────────────────────
# DELTA ADDITIONS to utils/feature_control.py
# Paste these below your existing is_feature_disabled() function.
# No changes needed to the existing function.
# ─────────────────────────────────────────────────────────────────────────────

# Add this import at the top of the file (with your existing imports):
#   from functools import wraps
#   from django.core.exceptions import PermissionDenied
#   from django.shortcuts import render


# ── 1. Demand Planning sub-feature hierarchy ──────────────────────────────────
#
# The five demand planning features have a parent-child relationship:
# if "demand_planning" (master switch) is disabled, all sub-features
# are implicitly disabled regardless of their own rows.
#
# Sub-features that require the master switch to be on first:
_DEMAND_SUBFEATURES = frozenset({
    "actuals_upload",
    "forecast_run",
    "consensus_override",
    "forecast_approval",
})


def is_demand_feature_disabled(client, feature):
    """
    Like is_feature_disabled(), but also checks the master "demand_planning"
    switch before checking the sub-feature.

    Returns the same dict shape as is_feature_disabled():
        {"disabled": bool, "message": str}

    Usage (views):
        result = is_demand_feature_disabled(request.client, "actuals_upload")
        if result["disabled"]:
            return render(request, "demand/feature_disabled.html",
                          {"message": result["message"]}, status=403)

    Usage (Celery tasks):
        result = is_demand_feature_disabled(client, "forecast_run")
        if result["disabled"]:
            return {"status": "skipped", "reason": result["message"]}
    """
    # Check master switch first (only for sub-features)
    if feature in _DEMAND_SUBFEATURES:
        master = is_feature_disabled(client, "demand_planning")
        if master["disabled"]:
            return {
                "disabled": True,
                "message": master["message"] or "Demand Planning is not enabled for this account.",
            }

    return is_feature_disabled(client, feature)


# ── 2. View decorator ─────────────────────────────────────────────────────────
#
# Usage:
#   @demand_feature_required("actuals_upload")
#   def upload_actuals_view(request, client_slug):
#       ...
#
# Expects the view to have `request.client` set (via your ClientScopedMixin
# or middleware). Renders demand/feature_disabled.html on block; raise
# PermissionDenied if you prefer a hard 403 instead.
#
# The template receives: {{ message }}

def demand_feature_required(feature, template="demand/feature_disabled.html"):
    """
    Decorator factory for class-based or function-based views.

    For function-based views:
        @demand_feature_required("forecast_run")
        def my_view(request): ...

    For class-based views, apply in urls.py:
        path("...", demand_feature_required("forecast_run")(MyView.as_view()))
    """
    from functools import wraps
    from django.shortcuts import render

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            client = getattr(request, "client", None)
            result = is_demand_feature_disabled(client, feature)
            if result["disabled"]:
                return render(
                    request,
                    template,
                    {"message": result["message"] or "This feature is currently unavailable."},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


# ── 3. Celery task guard ──────────────────────────────────────────────────────
#
# Usage inside a Celery task:
#
#   from mysite.models import Client
#   from utils.feature_control import celery_demand_feature_guard
#
#   @app.task(bind=True)
#   def run_forecast_task(self, client_id):
#       client = Client.objects.get(pk=client_id)
#       skip = celery_demand_feature_guard(client, "forecast_run")
#       if skip:
#           return skip           # {"status": "skipped", "reason": "..."}
#       # ... proceed with forecast

def celery_demand_feature_guard(client, feature):
    """
    Returns a skip-result dict if the feature is disabled, else None.

    Callers treat a non-None return as an early exit:
        skip = celery_demand_feature_guard(client, "forecast_run")
        if skip:
            return skip

    Return shape on skip:
        {"status": "skipped", "feature": str, "reason": str}
    Return on proceed:
        None
    """
    result = is_demand_feature_disabled(client, feature)
    if result["disabled"]:
        return {
            "status": "skipped",
            "feature": feature,
            "reason": result["message"] or f"Feature '{feature}' is currently disabled.",
        }
    return None


# ── 4. Cache invalidation helper ─────────────────────────────────────────────
#
# Call this from a post_save signal or admin action whenever a
# ClientFeatureControl row is saved, so the 15-minute cache doesn't
# serve stale data after an admin toggles a feature.
#
# Wire the signal in apps.py:
#
#   from django.db.models.signals import post_save
#   from mysite.models import ClientFeatureControl
#   from utils.feature_control import bust_feature_cache
#
#   class MysiteConfig(AppConfig):
#       def ready(self):
#           post_save.connect(bust_feature_cache, sender=ClientFeatureControl)

def bust_feature_cache(sender, instance, **kwargs):
    """
    post_save signal handler for ClientFeatureControl.
    Clears the cache key for the affected (client, feature) combination.
    Also clears the global key in case a client-specific row shadows it.
    """
    feature = instance.feature
    client_id = instance.client.client_id if instance.client else "global"

    keys_to_delete = [
        f"feature_control:{client_id}:{feature}",
        f"feature_control:global:{feature}",   # always clear global too
    ]
    cache.delete_many(keys_to_delete)
```
---

## 3. Model File Layout

Create the demand package inside your existing models directory:

```
mysite/models/demand/
    __init__.py
    hierarchy.py      ← PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
    actuals.py        ← ActualSale, ActualSaleImport
    forecast.py       ← ForecastVersion, ForecastLine, ForecastOverride  (Sprint 3B.1+)
```

The `forecast.py` file is scaffolded in Sprint 3B.1. Create it as an empty module now so imports don't break.

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

from django.db import models
from django.utils.translation import gettext_lazy as _


# ─────────────────────────────────────────────────────────────────────────────
# Materialized-path mixin (same pattern as TaxonomyNode)
# ─────────────────────────────────────────────────────────────────────────────

class MaterializedPathMixin(models.Model):
    """
    Adds `path` (materialized path, separator '/') alongside the parent self-FK.

    Convention: path stores the *full* ancestor chain of PKs, e.g. '1/4/12/'.
    Root nodes have path = '<own_pk>/'.

    Subclass must declare:
        parent = models.ForeignKey('self', null=True, blank=True,
                                   on_delete=models.PROTECT,
                                   related_name='children')
    """
    path = models.CharField(
        _("materialized path"),
        max_length=1024,
        db_index=True,
        editable=False,
        default="",
    )

    class Meta:
        abstract = True

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def build_path(self) -> str:
        if self.parent_id is None:
            return f"{self.pk}/"
        return f"{self.parent.path}{self.pk}/"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        new_path = self.build_path()
        if self.path != new_path:
            self.path = new_path
            # Use update() to avoid infinite recursion from another save()
            type(self).objects.filter(pk=self.pk).update(path=new_path)
            # Cascade path update to all descendants
            self._update_descendant_paths()

    def _update_descendant_paths(self):
        for child in self.children.all():
            child.path = child.build_path()
            type(child).objects.filter(pk=child.pk).update(path=child.path)
            child._update_descendant_paths()

    def get_descendants(self):
        """Return queryset of all descendants (not including self)."""
        return type(self).objects.filter(path__startswith=self.path).exclude(pk=self.pk)

    def get_ancestors(self):
        """Return list of ancestor PKs parsed from materialized path."""
        parts = [p for p in self.path.split("/") if p]
        ancestor_pks = [int(p) for p in parts[:-1]]
        return type(self).objects.filter(pk__in=ancestor_pks).order_by("path")

    @property
    def depth(self) -> int:
        return self.path.count("/") - 1


# ─────────────────────────────────────────────────────────────────────────────
# 1. Planning Location Hierarchy
# ─────────────────────────────────────────────────────────────────────────────

class PlanningLocation(MaterializedPathMixin):
    """
    Standalone location hierarchy for Demand Planning.

    Completely independent of ClientLocation (which has eCommerce / operational
    significance). Planners can model any geographic or organisational tree:
        Region → State → City → Distribution Centre → Branch

    Leaf nodes represent the physical stocking points whose demand is planned.
    """

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="planning_locations",
        verbose_name=_("client"),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name=_("parent location"),
    )
    code = models.CharField(_("code"), max_length=64)
    name = models.CharField(_("name"), max_length=255)
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        blank=True,
        help_text=_("Human label for this level, e.g. 'Region', 'Branch', 'DC'."),
    )
    is_leaf = models.BooleanField(
        _("is leaf"),
        default=False,
        help_text=_("True if this node represents an actual stocking/planning point. "
                    "Actuals and forecasts are stored only at leaf nodes."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "code")]
        ordering = ["path"]
        verbose_name = _("planning location")
        verbose_name_plural = _("planning locations")
        indexes = [
            models.Index(fields=["client", "is_leaf"], name="ix_planloc_client_leaf"),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent.client_id != self.client_id:
            raise ValidationError(_("Parent location must belong to the same client."))


# ─────────────────────────────────────────────────────────────────────────────
# 2. Planning Customer Hierarchy
# ─────────────────────────────────────────────────────────────────────────────

class PlanningCustomer(MaterializedPathMixin):
    """
    Standalone customer / customer-group hierarchy for Demand Planning.

    Completely independent of CustomerProfile (eCommerce buyer tied to auth.User).
    Two kinds of nodes are used:

    1. REAL customer   — leaf node representing a specific buyer (is_group=False).
    2. PLANNING group  — aggregate node representing unattributed or grouped
                         demand (is_group=True), e.g. 'Walk-in / Retail'.

    ActualSale.planning_customer is nullable (null = truly unattributed demand).
    When a real customer is not individually tracked, create a group node instead
    and assign all such demand to it.
    """

    CUSTOMER_TYPE_CHOICES = [
        ("real",  _("Real customer")),
        ("group", _("Planning group")),
    ]

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="planning_customers",
        verbose_name=_("client"),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name=_("parent"),
    )
    code = models.CharField(_("code"), max_length=64)
    name = models.CharField(_("name"), max_length=255)
    customer_type = models.CharField(
        _("customer type"),
        max_length=16,
        choices=CUSTOMER_TYPE_CHOICES,
        default="real",
    )
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        blank=True,
        help_text=_("E.g. 'Channel', 'Key Account', 'Customer'."),
    )
    # Optional: store the external ERP / CRM ID for sync purposes
    external_id = models.CharField(
        _("external ID"),
        max_length=128,
        blank=True,
        db_index=True,
        help_text=_("ERP / CRM identifier. Used during data import to match rows."),
    )
    is_active = models.BooleanField(_("active"), default=True)
    notes = models.TextField(_("notes"), blank=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "code")]
        ordering = ["path"]
        verbose_name = _("planning customer")
        verbose_name_plural = _("planning customers")
        indexes = [
            models.Index(
                fields=["client", "customer_type"],
                name="ix_plancust_client_type",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent.client_id != self.client_id:
            raise ValidationError(_("Parent customer must belong to the same client."))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sales Node Hierarchy (Sales Force Org Chart)
# ─────────────────────────────────────────────────────────────────────────────

class SalesNode(MaterializedPathMixin):
    """
    Represents the sales-force organisational chart for demand planning.

    Levels might be: National Sales Manager → Regional Manager → Area Manager → Sales Rep
    Leaf nodes are individual sales reps who are assigned to PlanningCustomers.

    Optionally linked to a PlanningLocation (the geography this node covers),
    but that link is informational — it does not drive data access.
    """

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="sales_nodes",
        verbose_name=_("client"),
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name=_("parent node"),
    )
    # Optional soft link to a planning location (purely informational)
    planning_location = models.ForeignKey(
        PlanningLocation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sales_nodes",
        verbose_name=_("planning location"),
        help_text=_("The location this sales node primarily covers. Informational only."),
    )
    code = models.CharField(_("code"), max_length=64)
    name = models.CharField(_("name"), max_length=255)
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        blank=True,
        help_text=_("E.g. 'National Manager', 'Area Manager', 'Sales Rep'."),
    )
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "code")]
        ordering = ["path"]
        verbose_name = _("sales node")
        verbose_name_plural = _("sales nodes")

    def __str__(self):
        return f"{self.code} — {self.name}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent.client_id != self.client_id:
            raise ValidationError(_("Parent sales node must belong to the same client."))
        if self.planning_location_id and self.planning_location.client_id != self.client_id:
            raise ValidationError(_("Planning location must belong to the same client."))


# ─────────────────────────────────────────────────────────────────────────────
# 4. Customer → Sales Node Assignment (date-effective)
# ─────────────────────────────────────────────────────────────────────────────

class CustomerSalesAssignment(models.Model):
    """
    Date-effective assignment of a PlanningCustomer leaf to a SalesNode leaf.

    A customer can be re-assigned (e.g. territory realignment) by closing the
    current row (valid_to = today) and creating a new row.

    For historical forecast accuracy, actuals are always attributed to the
    SalesNode that was active *at the time of sale* (join on valid_from/valid_to).
    """

    planning_customer = models.ForeignKey(
        PlanningCustomer,
        on_delete=models.CASCADE,
        related_name="sales_assignments",
        verbose_name=_("planning customer"),
    )
    sales_node = models.ForeignKey(
        SalesNode,
        on_delete=models.PROTECT,
        related_name="customer_assignments",
        verbose_name=_("sales node"),
    )
    valid_from = models.DateField(_("valid from"))
    valid_to = models.DateField(
        _("valid to"),
        null=True,
        blank=True,
        help_text=_("Leave blank for the currently active assignment."),
    )

    class Meta:
        app_label = "mysite"
        verbose_name = _("customer sales assignment")
        verbose_name_plural = _("customer sales assignments")
        indexes = [
            models.Index(
                fields=["planning_customer", "valid_from"],
                name="ix_custsales_cust_from",
            ),
            models.Index(
                fields=["sales_node", "valid_from"],
                name="ix_custsales_node_from",
            ),
        ]

    def __str__(self):
        to = self.valid_to or "present"
        return f"{self.planning_customer} → {self.sales_node} ({self.valid_from}–{to})"

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError(_("valid_to must be on or after valid_from."))
        if self.planning_customer.client_id != self.sales_node.client_id:
            raise ValidationError(
                _("Planning customer and sales node must belong to the same client.")
            )
```

---

## 5. `actuals.py` — Actuals Grain and Import Log

### Design: flexible period buckets

The period is **not fixed to a month**. Each `ActualSale` row carries a `period_type` (the bucket granularity chosen for that client's planning cycle) and an explicit `period_start` / `period_end` date pair. This makes the model work for any of:

```
second  minute  hour  day  week  month  bimonth  quarter  halfyear  year
```

**Rules:**

- `period_type` is set at the **client level** (or per forecast run). All rows for a given client's actuals series must use the same `period_type`, because StatsForecast requires a uniform, regular time series per `unique_id`.
- `period_start` is always the **first instant** of the bucket, stored as a `DateField` (for sub-day granularities like hour/minute/second, use `DateTimeField` — but in practice demand planning never operates below day level, so `DateField` is correct here).
- `period_end` is stored explicitly (not computed on the fly) so DuckDB range queries are fast. The `save()` override computes and stores it automatically.
- The natural key becomes `(client, planning_location, item, planning_customer, period_type, period_start)`.

**StatsForecast `freq` mapping** — the Celery forecast task reads the client's `period_type` and maps it to the correct pandas offset alias before calling `sf.forecast()`:

```python
PERIOD_FREQ_MAP = {
    "second":   "s",
    "minute":   "min",
    "hour":     "h",
    "day":      "D",
    "week":     "W-MON",   # ISO week, Monday anchor
    "month":    "MS",      # Month Start
    "bimonth":  "2MS",
    "quarter":  "QS",
    "halfyear": "2QS",
    "year":     "YS",
}
```

### The model

Create `mysite/models/demand/actuals.py`:

```python
"""
mysite/models/demand/actuals.py

ActualSale  — lowest-level demand actuals:
              client × planning_location × item × planning_customer × period

ActualSaleImport — audit log of each upload batch (CSV / Excel).

Period design:
  Every row carries period_type (the bucket granularity), period_start (first
  day of the bucket), and period_end (last day, stored for fast range queries).
  period_end is auto-computed in save() using compute_period_end().

  All rows for a given client's actuals series MUST share the same period_type.
  StatsForecast requires a uniform, regular time series — mixing monthly and
  weekly rows for the same unique_id will cause forecasting errors.

  Supported period types and their pandas/StatsForecast freq aliases:
      second   → "s"       minute  → "min"    hour     → "h"
      day      → "D"       week    → "W-MON"  month    → "MS"
      bimonth  → "2MS"     quarter → "QS"     halfyear → "2QS"
      year     → "YS"

Natural key: (client, planning_location, item, planning_customer,
              period_type, period_start)
Use update_or_create on this key to make uploads idempotent.
"""

import datetime
from dateutil.relativedelta import relativedelta

from django.db import models
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer


# ─────────────────────────────────────────────────────────────────────────────
# Period helpers
# ─────────────────────────────────────────────────────────────────────────────

PERIOD_TYPE_CHOICES = [
    ("second",   _("Second")),
    ("minute",   _("Minute")),
    ("hour",     _("Hour")),
    ("day",      _("Day")),
    ("week",     _("Week")),
    ("month",    _("Month")),
    ("bimonth",  _("Bi-Monthly (2 months)")),
    ("quarter",  _("Quarter")),
    ("halfyear", _("Half-Year")),
    ("year",     _("Year")),
]

# Maps period_type → pandas/StatsForecast freq string.
# Imported by the Celery forecast task.
PERIOD_FREQ_MAP: dict[str, str] = {
    "second":   "s",
    "minute":   "min",
    "hour":     "h",
    "day":      "D",
    "week":     "W-MON",
    "month":    "MS",
    "bimonth":  "2MS",
    "quarter":  "QS",
    "halfyear": "2QS",
    "year":     "YS",
}


def compute_period_end(period_start: datetime.date, period_type: str) -> datetime.date:
    """
    Return the last day (inclusive) of the bucket that starts on period_start.

    Examples:
        compute_period_end(date(2024, 1, 1), "month")    → date(2024, 1, 31)
        compute_period_end(date(2024, 1, 1), "quarter")  → date(2024, 3, 31)
        compute_period_end(date(2024, 1, 1), "week")     → date(2024, 1, 7)
        compute_period_end(date(2024, 1, 1), "day")      → date(2024, 1, 1)
    """
    d = period_start
    if period_type == "second":
        return d                       # same-day; sub-day precision not in DateField
    elif period_type == "minute":
        return d
    elif period_type == "hour":
        return d
    elif period_type == "day":
        return d
    elif period_type == "week":
        return d + datetime.timedelta(days=6)
    elif period_type == "month":
        return d + relativedelta(months=1) - datetime.timedelta(days=1)
    elif period_type == "bimonth":
        return d + relativedelta(months=2) - datetime.timedelta(days=1)
    elif period_type == "quarter":
        return d + relativedelta(months=3) - datetime.timedelta(days=1)
    elif period_type == "halfyear":
        return d + relativedelta(months=6) - datetime.timedelta(days=1)
    elif period_type == "year":
        return d + relativedelta(years=1) - datetime.timedelta(days=1)
    else:
        raise ValueError(f"Unknown period_type: {period_type!r}")


def validate_period_start(period_start: datetime.date, period_type: str) -> None:
    """
    Raise ValueError if period_start is not a valid anchor for the given period_type.

    Rules:
      week     → must be a Monday (weekday() == 0)
      month    → must be the 1st of the month
      bimonth  → must be 1st of an odd month (Jan, Mar, May …)
      quarter  → must be 1st of Jan / Apr / Jul / Oct
      halfyear → must be 1st of Jan or Jul
      year     → must be 1st of Jan
    """
    d = period_start
    if period_type == "week" and d.weekday() != 0:
        raise ValueError(f"period_start for week must be a Monday, got {d} ({d.strftime('%A')}).")
    if period_type in ("month", "bimonth", "quarter", "halfyear", "year") and d.day != 1:
        raise ValueError(f"period_start for {period_type} must be the 1st of the month, got {d}.")
    if period_type == "bimonth" and d.month % 2 != 1:
        raise ValueError(f"period_start for bimonth must be an odd month (Jan/Mar/…), got month {d.month}.")
    if period_type == "quarter" and d.month not in (1, 4, 7, 10):
        raise ValueError(f"period_start for quarter must be Jan/Apr/Jul/Oct, got month {d.month}.")
    if period_type == "halfyear" and d.month not in (1, 7):
        raise ValueError(f"period_start for halfyear must be Jan or Jul, got month {d.month}.")
    if period_type == "year" and d.month != 1:
        raise ValueError(f"period_start for year must be January, got month {d.month}.")


# ─────────────────────────────────────────────────────────────────────────────
# ActualSaleImport — upload audit log
# ─────────────────────────────────────────────────────────────────────────────

class ActualSaleImport(models.Model):
    """Audit log for each actuals upload batch."""

    STATUS_CHOICES = [
        ("pending",    _("Pending")),
        ("processing", _("Processing")),
        ("done",       _("Done")),
        ("failed",     _("Failed")),
    ]

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="actual_sale_imports",
    )
    uploaded_by = models.ForeignKey(
        "auth.User",
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    uploaded_at  = models.DateTimeField(auto_now_add=True)
    file_name    = models.CharField(max_length=512)
    period_type  = models.CharField(
        _("period type"),
        max_length=16,
        choices=PERIOD_TYPE_CHOICES,
        default="month",
        help_text=_("Bucket granularity of the data in this upload."),
    )
    row_count    = models.PositiveIntegerField(default=0)
    status       = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_log    = models.TextField(blank=True)

    class Meta:
        app_label = "mysite"
        ordering = ["-uploaded_at"]
        verbose_name = _("actual sale import")
        verbose_name_plural = _("actual sale imports")

    def __str__(self):
        return f"{self.file_name} [{self.period_type}] ({self.status}) — {self.uploaded_at:%Y-%m-%d}"


# ─────────────────────────────────────────────────────────────────────────────
# ActualSale — atomic demand actuals at flexible period grain
# ─────────────────────────────────────────────────────────────────────────────

class ActualSale(models.Model):
    """
    One row = one (location, item, customer, period) combination.

    period_type + period_start define the bucket. period_end is stored
    explicitly (computed in save()) for fast DuckDB range queries.

    This is the atomic grain that StatsForecast consumes. During the Celery
    forecast task, rows are aggregated up the three hierarchies using DuckDB
    and then passed to hierarchicalforecast with the freq from PERIOD_FREQ_MAP.
    """

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="actual_sales",
    )
    # ── Location ──────────────────────────────────────────────────────────────
    planning_location = models.ForeignKey(
        PlanningLocation,
        on_delete=models.PROTECT,
        related_name="actual_sales",
        verbose_name=_("planning location"),
    )
    # ── Item: leaf TaxonomyNode from product_planning Taxonomy ────────────────
    item = models.ForeignKey(
        "mysite.TaxonomyNode",
        on_delete=models.PROTECT,
        related_name="actual_sales",
        verbose_name=_("item"),
        help_text=_(
            "Must be a leaf node of the Taxonomy with slug='product_planning'."
        ),
    )
    # ── Customer (nullable = unattributed) ────────────────────────────────────
    planning_customer = models.ForeignKey(
        PlanningCustomer,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actual_sales",
        verbose_name=_("planning customer"),
        help_text=_(
            "Null means demand is not attributed to any specific customer or group."
        ),
    )
    # ── Period ────────────────────────────────────────────────────────────────
    period_type = models.CharField(
        _("period type"),
        max_length=16,
        choices=PERIOD_TYPE_CHOICES,
        default="month",
        help_text=_(
            "Granularity of this period bucket. All rows in one forecast run "
            "must share the same period_type."
        ),
    )
    period_start = models.DateField(
        _("period start"),
        help_text=_(
            "First day of the period bucket (e.g. 2024-01-01 for a January month bucket, "
            "2024-01-01 for Q1 2024, 2024-01-01 for ISO week starting Mon 1 Jan 2024)."
        ),
    )
    period_end = models.DateField(
        _("period end"),
        editable=False,
        help_text=_(
            "Last day of the period bucket (inclusive). Auto-computed from "
            "period_type + period_start. Stored for fast range queries."
        ),
    )
    # ── Measures ──────────────────────────────────────────────────────────────
    qty = models.DecimalField(
        _("quantity"),
        max_digits=14,
        decimal_places=3,
        help_text=_("Sales quantity in base UoM."),
    )
    revenue = models.DecimalField(
        _("revenue"),
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Revenue in client's base currency. Optional."),
    )
    # ── Import provenance ─────────────────────────────────────────────────────
    import_batch = models.ForeignKey(
        ActualSaleImport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="actual_sales",
    )

    class Meta:
        app_label = "mysite"
        # Natural key — enforces idempotent imports across any period type
        unique_together = [
            (
                "client", "planning_location", "item",
                "planning_customer", "period_type", "period_start",
            ),
        ]
        ordering = ["period_type", "period_start", "planning_location", "item"]
        verbose_name = _("actual sale")
        verbose_name_plural = _("actual sales")
        indexes = [
            # Fast subtree queries: actuals for a location across any period range
            models.Index(
                fields=["client", "planning_location", "period_type", "period_start"],
                name="ix_actualsale_loc_period",
            ),
            # Fast item-level time-series extraction
            models.Index(
                fields=["client", "item", "period_type", "period_start"],
                name="ix_actualsale_item_period",
            ),
            # Customer-level drill-down
            models.Index(
                fields=["client", "planning_customer", "period_type", "period_start"],
                name="ix_actualsale_cust_period",
            ),
            # Range queries: "give me all actuals between date A and date B"
            models.Index(
                fields=["client", "period_type", "period_start", "period_end"],
                name="ix_actualsale_period_range",
            ),
        ]

    def save(self, *args, **kwargs):
        # Auto-compute period_end before every save
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        cust = self.planning_customer or "unattributed"
        return (
            f"{self.period_type}:{self.period_start} | {self.planning_location} | "
            f"{self.item} | {cust} | qty={self.qty}"
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        # Enforce planning_location belongs to client
        if self.planning_location_id and self.planning_location.client_id != self.client_id:
            raise ValidationError(_("Planning location must belong to the same client."))
        # Enforce planning_customer belongs to client
        if self.planning_customer_id and self.planning_customer.client_id != self.client_id:
            raise ValidationError(_("Planning customer must belong to the same client."))
        # Enforce period_start is a valid anchor for the chosen period_type
        if self.period_start and self.period_type:
            try:
                validate_period_start(self.period_start, self.period_type)
            except ValueError as exc:
                raise ValidationError({"period_start": str(exc)})
```

### `period_end` in the migration — add a `NOT NULL` default

`period_end` is `editable=False` but **not** nullable. The generated migration will need a default for the `AddField` operation to apply cleanly on a table that already has rows. Edit the migration to provide a temporary default:

```python
# In the generated migration, change:
migrations.AddField(
    model_name="actualsale",
    name="period_end",
    field=models.DateField(editable=False, verbose_name="period end"),
),

# To:
migrations.AddField(
    model_name="actualsale",
    name="period_end",
    field=models.DateField(editable=False, verbose_name="period end",
                           default=datetime.date(2000, 1, 1)),
    preserve_default=False,
),
```

Since this is Sprint 3B.0 and the table is empty (no actuals yet), the default is academic — but it must be present for Django to generate valid SQL.

---

## 6. `forecast.py` — Scaffold Only (Sprint 3B.1+)

Create `mysite/models/demand/forecast.py` as an empty scaffold so the package imports cleanly:

```python
"""
mysite/models/demand/forecast.py

Populated in Sprint 3B.1:
  ForecastVersion, ForecastLine, ForecastAggregate,
  ForecastOverride, OverrideSplitWeight, ForecastAccuracy
"""
# Models will be added in Sprint 3B.1.
```

---

## 7. `__init__.py` — Expose Models from the Package

Create `mysite/models/demand/__init__.py`:

```python
from mysite.models.demand.hierarchy import (
    PlanningLocation,
    PlanningCustomer,
    SalesNode,
    CustomerSalesAssignment,
)
from mysite.models.demand.actuals import (
    ActualSaleImport,
    ActualSale,
)

__all__ = [
    "PlanningLocation",
    "PlanningCustomer",
    "SalesNode",
    "CustomerSalesAssignment",
    "ActualSaleImport",
    "ActualSale",
]
```

---

## 8. Wire the Package into `mysite/models/__init__.py`

Your existing `mysite/models/__init__.py` imports from sub-modules. Add the demand package imports at the bottom:

```python
# --- Phase 3B: Demand Planning ---
from mysite.models.demand import (   # noqa: F401
    PlanningLocation,
    PlanningCustomer,
    SalesNode,
    CustomerSalesAssignment,
    ActualSaleImport,
    ActualSale,
)
```

---

## 9. Migration — Step by Step

Run migrations in this exact order to avoid dependency issues.

### Step 1 — Generate the demand models migration

```bash
python manage.py makemigrations mysite --name demand_planning_foundation
```

This should produce one new migration covering:
- `PlanningLocation`
- `PlanningCustomer`
- `SalesNode`
- `CustomerSalesAssignment`
- `ActualSaleImport`
- `ActualSale`

### Step 2 — Add the `path` index with `text_pattern_ops`

The `path` field on all three hierarchy models needs a `text_pattern_ops` index for efficient `LIKE 'prefix%'` subtree queries. Django's `db_index=True` creates a plain btree index; you need to add the opclass index via `RunSQL`.

**Edit the generated migration** and add `RunSQL` operations at the end of the `operations` list:

```python
from django.db import migrations

class Migration(migrations.Migration):
    # ... (auto-generated operations above) ...

    operations = [
        # ... all auto-generated CreateModel operations ...

        # ── Materialized-path prefix indexes (text_pattern_ops) ───────────────
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS ix_planloc_path_tpo
                    ON mysite_planninglocation (path text_pattern_ops);
                CREATE INDEX IF NOT EXISTS ix_plancust_path_tpo
                    ON mysite_planningcustomer (path text_pattern_ops);
                CREATE INDEX IF NOT EXISTS ix_salesnode_path_tpo
                    ON mysite_salesnode (path text_pattern_ops);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS ix_planloc_path_tpo;
                DROP INDEX IF EXISTS ix_plancust_path_tpo;
                DROP INDEX IF EXISTS ix_salesnode_path_tpo;
            """,
        ),
    ]
```

### Step 3 — `ClientFeatureControl` choices migration

This is generated automatically by `makemigrations` because you extended `FEATURE_CHOICES` in Section 2a. It should already be included in the migration from Step 1 above (Django picks up the `AlterField` automatically). If it produces a separate migration file, that is also fine — apply them in dependency order.

No manual data migration is needed. The admin row creation described in Section 2c is done by hand after `migrate` completes.

### Step 4 — Apply all migrations

```bash
python manage.py migrate
```

Expected output: each new migration listed as `OK`.

### Step 5 — Verify indexes

```bash
python manage.py dbshell
```

In psql:

```sql
-- Confirm text_pattern_ops indexes exist
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename IN (
    'mysite_planninglocation',
    'mysite_planningcustomer',
    'mysite_salesnode'
)
ORDER BY tablename, indexname;
```

You should see both a regular `path` btree index (from `db_index=True`) and the `text_pattern_ops` variant for each table.

---

## 10. `manage.py check` — Zero Issues

```bash
python manage.py check --deploy 2>&1
```

Common issues to resolve before proceeding:

| Error | Fix |
|---|---|
| `fields.E005` — Field `path` clashes | Ensure `MaterializedPathMixin.path` has `editable=False` — it does in the model above |
| `models.E006` — `unique_together` references invalid field | Confirm `code` is declared before `unique_together` in `Meta` |
| `models.W042` — Auto-created primary key warning | Set `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` in `settings.py` if not already present |
| Import error — `mysite.TaxonomyNode` not found | Confirm `TaxonomyNode` is exported from `mysite/models/__init__.py` |

Run again without `--deploy` for a pure model/config check:

```bash
python manage.py check
```

Target: `System check identified no issues (0 silenced).`

---

## 11. Admin Registration (Optional but Recommended for Sprint 3B.0)

Add to `mysite/admin.py` (or a new `mysite/admin/demand.py`):

```python
from django.contrib import admin
from mysite.models.demand.hierarchy import (
    PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
)
from mysite.models.demand.actuals import ActualSaleImport, ActualSale


class PlanningLocationAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "level_label", "is_leaf", "depth", "is_active"]
    list_filter   = ["client", "is_leaf", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["path", "depth"]


class PlanningCustomerAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "customer_type", "level_label", "is_active"]
    list_filter   = ["client", "customer_type", "is_active"]
    search_fields = ["code", "name", "external_id"]
    readonly_fields = ["path", "depth"]


class SalesNodeAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "level_label", "is_active"]
    list_filter   = ["client", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["path", "depth"]


class CustomerSalesAssignmentAdmin(admin.ModelAdmin):
    list_display  = ["planning_customer", "sales_node", "valid_from", "valid_to"]
    list_filter   = ["sales_node__client"]
    search_fields = ["planning_customer__code", "sales_node__code"]


class ActualSaleAdmin(admin.ModelAdmin):
    list_display  = [
        "period_type", "period_start", "period_end",
        "planning_location", "item", "planning_customer", "qty", "revenue",
    ]
    list_filter   = ["client", "period_type", "planning_location"]
    search_fields = ["item__name", "planning_customer__code"]
    date_hierarchy = "period_start"


admin.site.register(PlanningLocation,          PlanningLocationAdmin)
admin.site.register(PlanningCustomer,          PlanningCustomerAdmin)
admin.site.register(SalesNode,                 SalesNodeAdmin)
admin.site.register(CustomerSalesAssignment,   CustomerSalesAssignmentAdmin)
admin.site.register(ActualSaleImport)
admin.site.register(ActualSale,                ActualSaleAdmin)
```

---

## 12. Final Checklist

Work through this list top-to-bottom before declaring Sprint 3B.0 done:

- [x] `pip install -r requirements.txt` completes without errors
- [x] Four new packages importable (see verification command in Section 1)
- [x] `mysite/models/demand/` directory created with all four files
- [x] `mysite/models/__init__.py` imports all six new models
- [x] `python manage.py makemigrations` produces exactly one new migration (demand_planning_foundation)
- [x] `text_pattern_ops` RunSQL block added to that migration
- [x] `ClientFeatureControl` `FEATURE_CHOICES` updated and `AlterField` migration applied cleanly
- [x] `python manage.py migrate` runs cleanly
- [ ] psql index check confirms three `text_pattern_ops` indexes
- [x] `python manage.py check` → `0 issues`
- [x] Django admin accessible at `/admin/` with six new model sections visible
- [x] Can create a `PlanningLocation` root node and a child node via admin; `path` auto-populates correctly
- [x] Can create a `PlanningCustomer` and assign it to a `SalesNode` via `CustomerSalesAssignment`

---

## 13. What Comes Next (Sprint 3B.1 Preview)

Sprint 3B.1 will populate `forecast.py` with:

- `ForecastVersion` — one row per client × run date × horizon, tracks status (draft / approved)
- `ForecastLine` — one row per (version, hierarchy node, month) for every level of all three hierarchies
- `ForecastOverride` — planner-entered consensus overrides at any node × month
- `OverrideSplitWeight` — how a top-level override disaggregates to lower levels
- `ForecastAccuracy` — MAPE / WMAPE / Bias computed per version after actuals land

The Celery task in Sprint 3B.2 will:

1. Pull `ActualSale` rows via DuckDB (in-process, no full-table load)
2. Build the `Y_long` DataFrame and `S_df` summing matrix from the three hierarchy trees
3. Run `StatsForecast.forecast()` on all nodes
4. Run `HierarchicalReconciliation.reconcile()` with MinTrace
5. Persist `ForecastLine` rows and trigger the approval workflow
