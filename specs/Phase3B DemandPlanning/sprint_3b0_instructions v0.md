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
ActualSale: client × planning_location × item (TaxonomyNode leaf) × planning_customer × month
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

Your `GlobalVal` / `GlobalValCat` system already manages per-client feature flags. Add the five demand-planning keys.

### 2a. Create the category (if not present)

In a data migration or via the Django admin, create a `GlobalValCat` entry:

```python
# In a data migration: mysite/migrations/XXXX_add_demand_planning_feature_keys.py
from django.db import migrations

DEMAND_KEYS = [
    ("demand_planning",      "bool", "Master switch — enables the Demand Planning module for this client"),
    ("actuals_upload",       "bool", "Allow planners to upload actuals via CSV/Excel"),
    ("forecast_run",         "bool", "Allow triggering a statistical forecast run"),
    ("consensus_override",   "bool", "Allow planners to override forecast values at any hierarchy node"),
    ("forecast_approval",    "bool", "Require manager approval before a forecast version is finalised"),
]

def add_demand_keys(apps, schema_editor):
    GlobalValCat = apps.get_model("mysite", "GlobalValCat")
    GlobalVal    = apps.get_model("mysite", "GlobalVal")

    cat, _ = GlobalValCat.objects.get_or_create(
        slug="demand_planning_features",
        defaults={"name": "Demand Planning Feature Flags"},
    )
    for key, dtype, description in DEMAND_KEYS:
        GlobalVal.objects.get_or_create(
            cat=cat,
            key=key,
            defaults={
                "val_type": dtype,
                "description": description,
                "default_val": "false",
            },
        )

def remove_demand_keys(apps, schema_editor):
    GlobalVal = apps.get_model("mysite", "GlobalVal")
    GlobalVal.objects.filter(key__in=[k for k, *_ in DEMAND_KEYS]).delete()

class Migration(migrations.Migration):
    dependencies = [
        ("mysite", "PREVIOUS_MIGRATION"),   # replace with actual last migration
    ]
    operations = [
        migrations.RunPython(add_demand_keys, remove_demand_keys),
    ]
```

### 2b. Helper to check flags in views/tasks

Add this to `mysite/utils/feature_flags.py` (create the file if absent):

```python
from mysite.models import GlobalVal

_DEMAND_FLAGS = frozenset([
    "demand_planning",
    "actuals_upload",
    "forecast_run",
    "consensus_override",
    "forecast_approval",
])

def client_has_feature(client, key: str) -> bool:
    """
    Return True if the client-scoped GlobalVal for `key` is 'true'.
    Falls back to the GlobalVal default_val if no client override exists.
    Usage:
        if not client_has_feature(request.client, "demand_planning"):
            raise PermissionDenied
    """
    assert key in _DEMAND_FLAGS, f"Unknown feature flag: {key}"
    try:
        gv = GlobalVal.objects.get(key=key)
        # If you have per-client overrides, query them here.
        # Otherwise return the global default.
        return gv.default_val.lower() == "true"
    except GlobalVal.DoesNotExist:
        return False
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

Create `mysite/models/demand/actuals.py`:

```python
"""
mysite/models/demand/actuals.py

ActualSale  — lowest-level demand actuals:
              client × planning_location × item (TaxonomyNode) × planning_customer × month

ActualSaleImport — audit log of each upload batch (CSV / Excel).

Design notes:
- item is a FK to TaxonomyNode (leaf of the product_planning Taxonomy).
  This reuses the existing Catalog infrastructure without duplicating it.
- planning_customer is nullable: null means the demand cannot be attributed to
  any specific customer or planning group (e.g. bulk location-level data).
- qty is in base UoM (pieces by default). revenue is optional — upload may
  not always carry revenue.
- (client, planning_location, item, planning_customer, period_month) is the
  natural key. Use update_or_create during import to make uploads idempotent.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer


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
    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_name   = models.CharField(max_length=512)
    row_count   = models.PositiveIntegerField(default=0)
    status      = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_log   = models.TextField(blank=True)

    class Meta:
        app_label = "mysite"
        ordering = ["-uploaded_at"]
        verbose_name = _("actual sale import")
        verbose_name_plural = _("actual sale imports")

    def __str__(self):
        return f"{self.file_name} ({self.status}) — {self.uploaded_at:%Y-%m-%d}"


class ActualSale(models.Model):
    """
    One row = one (location, item, customer, month) combination.

    This is the atomic grain that StatsForecast consumes. During the Celery
    forecast task, rows are aggregated up the three hierarchies using DuckDB
    before being passed to hierarchicalforecast.
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
    # ── Time ──────────────────────────────────────────────────────────────────
    period_month = models.DateField(
        _("period month"),
        help_text=_("Always the first day of the month (e.g. 2024-01-01)."),
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
        # Natural key — enforces idempotent imports
        unique_together = [
            ("client", "planning_location", "item", "planning_customer", "period_month"),
        ]
        ordering = ["period_month", "planning_location", "item"]
        verbose_name = _("actual sale")
        verbose_name_plural = _("actual sales")
        indexes = [
            # Fast subtree queries: all actuals for a location-subtree
            models.Index(
                fields=["client", "planning_location", "period_month"],
                name="ix_actualsale_loc_month",
            ),
            # Fast item-level time-series extraction
            models.Index(
                fields=["client", "item", "period_month"],
                name="ix_actualsale_item_month",
            ),
            # Customer-level drill-down
            models.Index(
                fields=["client", "planning_customer", "period_month"],
                name="ix_actualsale_cust_month",
            ),
        ]

    def __str__(self):
        cust = self.planning_customer or "unattributed"
        return (
            f"{self.period_month:%Y-%m} | {self.planning_location} | "
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
        # Enforce period_month is always first-of-month
        if self.period_month and self.period_month.day != 1:
            raise ValidationError(_("period_month must be the first day of the month."))
```

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

### Step 3 — Generate and run the feature-flag data migration

```bash
python manage.py makemigrations mysite --name demand_planning_feature_flags --empty
```

Then paste the data migration body from Section 2a above. Replace `PREVIOUS_MIGRATION` in `dependencies` with the name of the migration generated in Step 1.

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
        "period_month", "planning_location", "item",
        "planning_customer", "qty", "revenue"
    ]
    list_filter   = ["client", "period_month", "planning_location"]
    search_fields = ["item__name", "planning_customer__code"]
    date_hierarchy = "period_month"


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

- [ ] `pip install -r requirements.txt` completes without errors
- [ ] Four new packages importable (see verification command in Section 1)
- [ ] `mysite/models/demand/` directory created with all four files
- [ ] `mysite/models/__init__.py` imports all six new models
- [ ] `python manage.py makemigrations` produces exactly one new migration (demand_planning_foundation)
- [ ] `text_pattern_ops` RunSQL block added to that migration
- [ ] Feature-flag data migration created and dependency chain is correct
- [ ] `python manage.py migrate` runs cleanly
- [ ] psql index check confirms three `text_pattern_ops` indexes
- [ ] `python manage.py check` → `0 issues`
- [ ] Django admin accessible at `/admin/` with six new model sections visible
- [ ] Can create a `PlanningLocation` root node and a child node via admin; `path` auto-populates correctly
- [ ] Can create a `PlanningCustomer` and assign it to a `SalesNode` via `CustomerSalesAssignment`

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
