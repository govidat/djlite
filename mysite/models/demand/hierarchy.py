"""

3. Add to the indexing pattern kept in migration
# 1. Generate the migration normally
python manage.py makemigrations

# 2. Open the generated file and add the two functions
#    above the Migration class, then add RunPython at the
#    end of operations[]

# These functions live here — not imported from anywhere
def add_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    indexes = [
        # Item base table - REPLACE # in the beginning and # at the end of each line with ". So the line should read 3doubequote-Create - 3doublequote
        #""CREATE INDEX IF NOT EXISTS planloc_path_tpo_idx ON  ON mysite_planninglocation (path text_pattern_ops)#"",
        #""CREATE INDEX IF NOT EXISTS plancust_path_tpo_idx ON  ON mysite_planningcustomer (path text_pattern_ops)#"",
        #""CREATE INDEX IF NOT EXISTS salesnode_path_tpo_idx ON  ON mysite_salesnode (path text_pattern_ops)#"",

    ]

    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS planloc_path_tpo_idx',   
        'DROP INDEX IF EXISTS plancust_path_tpo_idx',
        'DROP INDEX IF EXISTS salesnode_path_tpo_idx',

        # ... rest of drops
    ]
    for sql in drops:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0001_initial'),
    ]

    operations = [
        # ... all auto-generated model operations first ...

        migrations.RunPython(
            add_postgres_indexes,      # ← runs on: python manage.py migrate (forward)
            remove_postgres_indexes,   # ← runs on: python manage.py migrate <app> <prev> (reverse)

        ),
    ]

# 3. Verify it runs cleanly
python manage.py migrate

# 4. Confirm on PostgreSQL (production)
#python manage.py dbshell
# slash d mysite_item   # should show the GIN index

5. Add the new sub model to signals.py, translation.py, admin
"""
"""
mysite/models/demand/hierarchy.py

Three independent planning hierarchies, fully decoupled from eCommerce models:

  PlanningLocation    — arbitrary location tree (Region → Zone → DC → Branch)
  PlanningCustomer    — arbitrary customer / customer-group tree
  SalesNode           — sales-force org chart
  
  SalesForecastLink - Linking a Planning_Location (leaf), Planning_Customer, distribution_channel and lowest Sales_Node leaf
None of these carry FKs to ClientLocation or CustomerProfile.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone

def first_day_of_current_year():
    return timezone.localdate().replace(month=1, day=1)
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
        #return f"{self.parent.path}{self.pk}/"
        parent = type(self).objects.get(pk=self.parent_id)
        return f"{parent.path}{self.pk}/"
    """
    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        new_path = self.build_path()
        if self.path != new_path:
            self.path = new_path
            super().save(update_fields=["path"])
            self._update_descendant_paths()   
    """
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        new_path = self.build_path()
        if self.path != new_path:
            self.path = new_path
            # Use update() to avoid infinite recursion from another save()
            type(self).objects.filter(pk=self.pk).update(path=new_path)
            # Cascade path update to all descendants
            self._update_descendant_paths()
    """
    def _update_descendant_paths(self):
        for child in self.children.all():
            new_path = child.build_path()
            if child.path != new_path:
                child.path = new_path
                child.save(update_fields=["path"])

            child._update_descendant_paths()
    """

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
    name = models.CharField(_("name"), max_length=255, blank=True)   # modeltranslation blank=True to be present expands blank=True to be added
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        blank=True, # modeltranslation blank=True to be present expands blank=True to be added
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
        verbose_name = _("02-01 Planning Location")
        verbose_name_plural = _("02-01 Planning Locations")
        indexes = [
            models.Index(fields=["client", "is_leaf"], name="ix_planloc_client_leaf"),
            models.Index(
                fields=["path"],
                name="planloc_path_tpo_idx",
                opclasses=["text_pattern_ops"],
            ),
        ]
        permissions = [
            ('override_at_location', 'Can create/edit forecast overrides at this location and below'),
            ('view_at_location',     'Can view demand planning data at this location and below'),
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
        ("pseudo", _("Dummy customer")),
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
    name = models.CharField(_("name"), max_length=255, blank=True)   # modeltranslation blank=True to be present expands blank=True to be added
    customer_type = models.CharField(
        _("customer type"),
        max_length=16,
        choices=CUSTOMER_TYPE_CHOICES,
        default="real",
        help_text=_("Actuals and forecasts are NOT stored at group level"),
    )
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        help_text=_("E.g. 'Channel', 'Key Account', 'Customer'."),
        blank=True   # modeltranslation blank=True to be present expands blank=True to be added
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
        verbose_name = _("02-02 Planning Customer")
        verbose_name_plural = _("02-02 Planning Customers")
        indexes = [
            models.Index(
                fields=["client", "customer_type"],
                name="ix_plancust_client_type",
            ),
            models.Index(
                fields=["path"],
                name="plancust_path_tpo_idx",
                opclasses=["text_pattern_ops"],
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
    name = models.CharField(_("name"), max_length=255, blank=True)   # modeltranslation blank=True to be present expands blank=True to be added
    level_label = models.CharField(
        _("level label"),
        max_length=64,
        help_text=_("E.g. 'National Manager', 'Area Manager', 'Sales Rep'."), 
        blank=True)   # modeltranslation blank=True to be present expands blank=True to be added
    is_active = models.BooleanField(_("active"), default=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "code")]
        ordering = ["path"]
        verbose_name = _("02-03 Sales Node")
        verbose_name_plural = _("02-03 Sales Nodes")
        indexes = [
            models.Index(
                fields=["path"],
                name="salesnode_path_tpo_idx",
                opclasses=["text_pattern_ops"],
            ),
        ]

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

"""
class ZZCustomerSalesAssignment(models.Model):

    client = models.ForeignKey(
        "mysite.Client",
        on_delete=models.CASCADE,
        related_name="customer_sales_nodes",
        verbose_name=_("client")
    )
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
        verbose_name = _("02-04 Customer Sales Assignment")
        verbose_name_plural = _("02-04 Customer Sales Assignments")
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
        #if not self.client_id:
        #    self.client = self.planning_customer.client        
        overlapping = CustomerSalesAssignment.objects.filter(
            planning_customer=self.planning_customer,
            valid_to__isnull=True,
        ).exclude(pk=self.pk)

        if overlapping.exists():
            raise ValidationError(
                _("Customer already has an open assignment.")
            )
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError(_("valid_to must be on or after valid_from."))
        if self.planning_customer.client_id != self.sales_node.client_id:
            raise ValidationError(
                _("Planning customer and sales node must belong to the same client.")
            )
"""        
class SalesForecastLink(models.Model):
    """
    Date-effective link from a demand-side key to a SalesNode leaf, used for
    forecast grain resolution AND (now) sales-team territory history —
    replaces CustomerSalesAssignment.

    Exactly one of three shapes per row, same as before:
      a) planning_location (leaf) + distribution_channel + planning_customer
      b) planning_location (leaf) + distribution_channel   (customer NULL)
      c) planning_location (leaf) only                     (channel & customer NULL)

    valid_to NULL = currently active. Historical rows (valid_to set) are kept
    for territory-history reporting; grain search resolves against whatever
    is active as of a given date (see resolve_sales_forecast_link).
    """
    client = models.ForeignKey(
        "mysite.Client", on_delete=models.CASCADE,
        related_name="sales_forecast_links",
    )
    sales_node = models.ForeignKey(
        SalesNode, on_delete=models.PROTECT,           # PROTECT, not CASCADE — see note below
        related_name="forecast_links",
        limit_choices_to={'children__isnull': True},
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.CASCADE,
        related_name="sales_forecast_links",
        limit_choices_to={'is_leaf': True},
    )
    distribution_channel = models.ForeignKey(
        "mysite.DistributionChannel", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    planning_customer = models.ForeignKey(
        PlanningCustomer, on_delete=models.CASCADE,
        null=True, blank=True, related_name="sales_forecast_links",
    )

    # ── NEW: date-effectivity ──────────────────────────────────────────────
    valid_from = models.DateField(_("valid from"), default=first_day_of_current_year,)

    valid_to = models.DateField(
        _("valid to"), null=True, blank=True,
        help_text=_("Leave blank for the currently active link."),
    )

    class Meta:
        app_label = "mysite"
        constraints = [
            # DB-level: at most one OPEN row per key combo. Overlapping
            # CLOSED ranges are still possible at the DB level — caught in
            # clean() below, same limitation CustomerSalesAssignment had.
            models.UniqueConstraint(
                fields=["client", "planning_location", "distribution_channel", "planning_customer"],
                condition=models.Q(valid_to__isnull=True),
                name="uq_sales_forecast_link_open",
            ),
        ]
        indexes = [
            models.Index(fields=["client", "planning_location"], name="ix_sfl_client_loc"),
            models.Index(fields=["client", "planning_location", "valid_from"], name="ix_sfl_loc_from"),
        ]
        verbose_name = _("02-15 Sales Forecast Link")
        verbose_name_plural = _("02-15 Sales Forecast Links")

    @property
    def link_type(self) -> str:
        if self.planning_customer_id and self.distribution_channel_id:
            return 'a'
        if self.distribution_channel_id:
            return 'b'
        return 'c'

    @property
    def is_active(self) -> bool:
        #from django.utils import timezone
        today = timezone.now().date()
        return self.valid_from <= today and (self.valid_to is None or self.valid_to >= today)

    def clean(self):
        from django.core.exceptions import ValidationError
        import datetime

        if self.sales_node_id and self.sales_node.children.exists():
            raise ValidationError(_("Sales forecast links must point to a leaf SalesNode."))
        if self.planning_location_id and not self.planning_location.is_leaf:
            raise ValidationError(_("Sales forecast links must use a leaf PlanningLocation."))
        for fk_name in ("sales_node", "planning_location", "planning_customer"):
            obj = getattr(self, fk_name, None)
            if obj is not None and obj.client_id != self.client_id:
                raise ValidationError(_(f"{fk_name} must belong to the same client."))
        if self.planning_customer_id and not self.distribution_channel_id:
            raise ValidationError(_(
                "A customer-level link also requires a distribution_channel (shape 'a' only)."
            ))

        # ── NEW: date validation, same pattern as CustomerSalesAssignment ──
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError(_("valid_to must be on or after valid_from."))

        overlapping = SalesForecastLink.objects.filter(
            client_id=self.client_id,
            planning_location_id=self.planning_location_id,
            distribution_channel_id=self.distribution_channel_id,
            planning_customer_id=self.planning_customer_id,
        ).exclude(pk=self.pk)

        self_to = self.valid_to or datetime.date.max
        for other in overlapping:
            other_to = other.valid_to or datetime.date.max
            if self.valid_from <= other_to and other.valid_from <= self_to:
                raise ValidationError(
                    _("Overlapping date range for this location/channel/customer link.")
                )