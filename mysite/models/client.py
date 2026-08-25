from django.db import models
from .base import (
    LowercaseCharField, default_languages, default_themes, text_field_validators
)
#from .global_config import (ThemePreset)
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class Client(models.Model):
    client_id = LowercaseCharField(max_length=25, unique=True, db_index=True)    

    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    language_list = models.JSONField(null = True, blank = True, default=default_languages, help_text="A JSON array of selected values from Language.")
    default_language = models.CharField(max_length=10, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE)
    theme_list = models.JSONField(null = True, blank = True, default=default_themes)
    # ── NEW ──────────────────────────────────────────────────────────────────
    allowed_distribution_channels = models.JSONField(
        _("allowed distribution channels"),
        null=True, blank=True, default=None,
        help_text=_(
            "List of DistributionChannel codes this client plans with, "
            'e.g. ["00", "01"]. NULL means Distribution Channel is NOT a '
            "meaningful dimension for this client — actuals, grain search, "
            "and validation should all treat the client as channel-less "
            "(everything defaults to '00' / Common) rather than as "
            "'any channel is allowed'. Use is_distribution_channel_enabled() "
            "and get_allowed_distribution_channel_codes() rather than reading "
            "this field directly."
        ),
    )
    allowed_countries = models.JSONField(
        _("allowed countries"),
        null=True, blank=True, default=None,
        help_text=_(
            "List of ISO alpha-2 Country codes this client's website serves, "
            'e.g. ["IN", "US"]. NULL means Country is NOT a '
            "dimension for this client. Use is_country_enabled() "
            "and get_allowed_country_codes() rather than reading "
            "this field directly."
        ),
    )
    default_country_code = models.CharField(
        _("default country"),
        max_length=2, blank=True, default='IN',
        help_text=_(
            "ISO alpha-2 code of the default country shown when no "
            "session country is active. Must be in allowed_countries "
            "if country is enabled."
        ),
    )
    sector = models.ForeignKey(
        'mysite.TaxonomyNode',
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='clients',
        limit_choices_to={'taxonomy__slug': 'sector'},
        help_text=_(
            "Client's finest sector node (e.g. AutoComponents) from the "
            "global 'sector' taxonomy. Drives sector-scoped template "
            "resolution: Client > exact sector > ancestor sectors > global."
        ),
    )
    catalogue_taxonomy_slugs = models.JSONField(
        _("catalogue taxonomy slugs"),
        null=True, blank=True, default=None,
        help_text=_(
            "Ordered JSON array of taxonomy slugs to show in the catalogue "
            'filter sidebar (LHS), e.g. ["gpc", "brand"]. Order = display '
            "order; slugs not listed are hidden; unknown/stale slugs are "
            "skipped at render time. NULL or empty = show ALL active "
            "taxonomies (global + client-specific) in default order."
        ),
    )
   
    #mad_threshold = models.DecimalField(max_digits=6, decimal_places=2, default=3.5,
    #                                    help_text=_("For Actual Sale outlier detection. Leave it untouched if not sure."),
    #)
    #persistence_periods = models.PositiveSmallIntegerField(
    #    default=3, help_text=_("For Actual Sale outlier detection. Leave it untouched if not sure. Number of consecutive periods a sustained elevation must hold "
    #                            "before it's treated as a level shift rather than a candidate."),
    #)
    #min_history_periods = models.PositiveSmallIntegerField(
    #    default=12, help_text=_("For Actual Sale outlier detection. Leave it untouched if not sure. Skip detection for a series with fewer periods of history than this."),
    #)
    #forecast_uses_net_actuals   = models.BooleanField(default=True)
    #reporting_uses_net_actuals   = models.BooleanField(default=True)    
    #abc_classification_uses_net_actuals = models.BooleanField(default=True)
    

    # Translatable fields
    name = models.CharField(max_length=100, blank=True, null=True) # modeltranslation blank=True to be present 
    nb_title = models.CharField(max_length=100, blank=True, null=True) # modeltranslation blank=True to be present

    nb_title_svg_pre = models.CharField(max_length=500, blank=True, null=True)
    nb_title_svg_suf = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return self.client_id

    # if a Model has a recursive relationship and its parent is maintained in the same row
    def get_ancestors(self):
        #Return all ancestors (parent, grandparent, ...) as a list.#
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(str(current.client_id))
            current = current.parent
        return ancestors  
     
    def get_descendants(self):
        #Return all descendants (children, grandchildren, ...) as a list of clients.
        descendants = []

        def collect_children(node):
            for child in node.children.all():
                descendants.append(str(child.client_id))
                collect_children(child)

        collect_children(self)
        return descendants     

    def is_distribution_channel_enabled(self) -> bool:
        """
        False means this client doesn't use the Distribution Channel
        dimension at all — callers should skip channel-based logic entirely
        (no channel breakout in grain search, no channel validation beyond
        the '00' default) rather than treating it as unrestricted.
        """
        return self.allowed_distribution_channels is not None

    def get_allowed_distribution_channel_codes(self) -> set[str]:
        """
        Only meaningful when is_distribution_channel_enabled() is True.
        Callers must check that first — calling this when the feature is
        disabled is a caller bug, not a case to silently paper over, so it
        raises rather than guessing at a fallback.
        """
        if self.allowed_distribution_channels is None:
            raise ValueError(
                f"Client {self.client_id} does not have Distribution Channel "
                f"enabled — check is_distribution_channel_enabled() before calling this."
            )
        return set(self.allowed_distribution_channels)

    def is_country_enabled(self) -> bool:
        """False means this client doesn't use the Country dimension."""
        return self.allowed_countries is not None

    def get_allowed_country_codes(self) -> set[str]:
        """
        Only meaningful when is_country_enabled() is True.
        Returns the set of ISO alpha-2 country codes this client serves.
        """
        if self.allowed_countries is None:
            raise ValueError(
                f"Client {self.client_id} does not have Country "
                f"enabled — check is_country_enabled() before calling this."
            )
        return set(self.allowed_countries)

    class Meta:
        verbose_name = "00-03 Client"
        ordering = ["client_id"]
        permissions = [
            ('view_client_data',   'Can view client data'),
            ('edit_client_data',   'Can edit client data'),
            ('create_client_data', 'Can create client data'),
            ('admin_client_data',  'Can admin client — manage users'),
        ]
    # Change Notes: If Client is modified, then modify the related mysite.forms.py>ClientForm and mysite>admin>client.py

class Theme(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='themes')    
    theme_id = LowercaseCharField(max_length=10)  
    themepreset = models.ForeignKey('mysite.ThemePreset', on_delete=models.SET_NULL, null=True)
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False)

    overrides = models.JSONField(blank=True, null=True)
    is_default = models.BooleanField(default=False)    

    # Translatable fields
    name = models.CharField(max_length=40, blank=True, null=True) # modeltranslation blank=True to be present

    def __str__(self):
        client_id = getattr(self.client, 'client_id', '?')
        return f"{client_id} / {self.theme_id}"        
        #return f"{self.client.client_id} / {self.theme_id}"
      
    # for usage in Admin Panel
    class Meta:
        #verbose_name = "00-04 Project Page"
        #verbose_name_plural = "My Custom Models"
        unique_together = ("client", "theme_id")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["client", "order"]),
        ]
        verbose_name = "00-03-01 Theme"

class ClientTemplate(models.Model):
    """
    Client-specific template fragments stored in DB.
    Overrides filesystem templates for catalogue components.
    Works exactly like PageContent but for reusable partials,
    not full pages.
    Which templates genuinely need client override
    High value — clients will actually want to customise these:
    Template key                Where to replace                                    What clients customise 
    catalogue_item_card         items_list.html — in the {% for item %} loop        Different fields shown, different layout per domain
    catalogue_filter_sidebar    page_catalogue_html.html and page_catalogue.html    Hide certain filter sections, reorder filterscatalogue_item_detail
    item_detail view            item_detail_wrapper                                 Completely different detail layout per domain

    Low value — leave as filesystem includes:
    Template                Why skip DB override
    catalogue_items_list    Just a grid wrapper + loop + pagination. Rarely needs client customisation. The card inside it is already overridable.
    catalogue_pagination    Pure navigation — no business logic. Same for all clients.
    navbar                  
    footer    

    """
    TEMPLATE_CHOICES = [
        ('catalogue_filter_sidebar', 'Catalogue: Filter Sidebar'),
        ('catalogue_item_card',      'Catalogue: Item Card'),
        ('catalogue_item_detail',    'Catalogue: Item Detail'),
        ('catalogue_items_list',     'Catalogue: Items List'),
        ('catalogue_pagination',     'Catalogue: Pagination'),
        ('demand_sidebar_nav',       'Demand Planning: Sidebar Nav'),
        ('navbar',                   'Navbar'),
        ('footer',                   'Footer'),
    ]

    client          = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='templates'
    )
    country = models.ForeignKey(
        'mysite.Country',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='client_templates',
        help_text="Country this template applies to. "
                  "Leave empty for ALL countries.",
    )
    template_key    = models.CharField(
        max_length=50, choices=TEMPLATE_CHOICES,
        help_text="Which template this overrides"
    )
    """
    language_code   = LowercaseCharField(
        max_length=10, default='en',
        help_text="Language this template variant serves. "
                  "Use 'all' to apply regardless of language."
    )
    html            = models.TextField(
        help_text="Django template HTML. Has access to all context variables."
    )
    """
    htmlblob      = models.TextField(blank=True, help_text="Django template HTML. Has access to all context variables.") # modeltranslation blank=True to be present    
    is_active       = models.BooleanField(default=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('client', 'template_key', 'country')
        ordering        = ['client', 'template_key']
        verbose_name = "00-03E Client Templates"
        verbose_name_plural = "00-03E Client Templates"
    def __str__(self):
        client_id = getattr(self.client, 'client_id', '?')
        return f"{client_id} / {self.template_key}"


class SectorTemplate(models.Model):
    """
    Sector-scoped and global-default template fragments stored in DB.

    Resolution tier between ClientTemplate (per-client) and the
    (removed) filesystem defaults:

        1. ClientTemplate                       (client-specific)
        2. SectorTemplate @ client's sector     (deepest node first)
        3. SectorTemplate @ ancestor sectors    (walk up the tree)
        4. SectorTemplate @ sector_node = NULL  (global default)
        5. '' + logger.warning                  (unseeded key)

    sector_node = NULL means "global default" — exactly one active row
    per template_key is enforced by a conditional UniqueConstraint.
    Defaults for every TEMPLATE_CHOICES key are seeded by data migration;
    from then on default content is admin-managed, not git-managed.

    Country dimension (new):
        5. ClientTemplate(country=X)            (client + country)
        6. SectorTemplate(sector + country=X)   (sector + country)
        7. SectorTemplate(country=X, sector=NULL) (global + country)
        8. SectorTemplate(sector + country=NULL)  (sector + no country)
        9. SectorTemplate(sector=NULL, country=NULL) (global default)
    """
    sector_node    = models.ForeignKey(
        'mysite.TaxonomyNode',
        null=True, blank=True,          # NULL = global default
        on_delete=models.CASCADE,
        related_name='templates',
        limit_choices_to={'taxonomy__slug': 'sector'},
        help_text="Sector node this template applies to. "
                  "Leave empty for the GLOBAL DEFAULT template."
    )
    country = models.ForeignKey(
        'mysite.Country',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='sector_templates',
        help_text="Country this template applies to. "
                  "Leave empty for the GLOBAL (all countries) default.",
    )
    template_key   = models.CharField(
        max_length=50, choices=ClientTemplate.TEMPLATE_CHOICES,
        help_text="Which template this provides"
    )
    htmlblob       = models.TextField(
        blank=True,
        help_text="Django template HTML. Has access to all context variables."
    )   # modeltranslation: expands to htmlblob_<lang>
    is_active      = models.BooleanField(default=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['sector_node', 'country', 'template_key'],
                name='uniq_sectortemplate_sector_country_key',
            ),
            models.UniqueConstraint(
                fields=['template_key'],
                condition=models.Q(sector_node__isnull=True, country__isnull=True),
                name='uniq_sectortemplate_global_default',
            ),
        ]
        ordering        = ['template_key', 'sector_node', 'country']
        verbose_name = "00-00C Sector Templates"
        verbose_name_plural = "00-00C Sector Templates"

    def __str__(self):
        scope = getattr(self.sector_node, 'path', None) or 'GLOBAL'
        country_code = getattr(self.country, 'code', None) or 'ALL'
        return f"[{scope}] / {self.template_key} / {country_code}"


# models/client_block.py

class ClientBlock(models.Model):

    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='blocks',
        null=True,
        blank=True,
        help_text="Leave empty to block ALL clients."
    )

    from_date = models.DateTimeField()
    to_date   = models.DateTimeField()

    remarks = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-from_date']
        verbose_name = "00-00A Client Block"
        verbose_name_plural = "00-00A Client Blocks"
        indexes = [
            models.Index(fields=['is_active', 'from_date', 'to_date']),
            models.Index(fields=['client']),
        ]        

    def __str__(self):

        target = (
            self.client.client_id
            if self.client else
            "ALL CLIENTS"
        )

        return (
            f"{target} "
            f"({self.from_date} → {self.to_date})"
        )
    
class ClientFeatureControl(models.Model):
    """
    Superadmin-controlled feature access switch.

    If client=NULL:
        applies globally to ALL clients.

    Used for:
        - disable catalogue
        - disable ecommerce
        - maintenance rollout
        - phased enablement
    """

    FEATURE_CHOICES = [
        ('catalogue', 'Catalogue'),
        ('ecommerce', 'E-Commerce'),
        # Phase 3B Demand Planning
        ('demand_planning',      'Demand Planning Module'),
        ('actuals_upload',       'Actuals Upload'),
        ('outlier_management',   'Actuals Outlier Management'),        
        ('forecast_run',         'Run Statistical Forecast'),
        ('consensus_override',   'Consensus Override'),
        ('forecast_approval',    'Forecast Approval Workflow'),
        ('scheme_management',    'Sales Promotion Scheme Management'),
        ('item_lifecycle',       'Item Substitution / Discontinuation / Introduction'),
    ]

    client = models.ForeignKey(
        'mysite.Client',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='feature_controls',
        help_text='Empty = applies to ALL clients'
    )

    feature = models.CharField(
        max_length=30,
        choices=FEATURE_CHOICES,
    )

    is_disabled = models.BooleanField(default=True)

    from_date = models.DateTimeField()
    to_date   = models.DateTimeField()

    message = models.TextField(
        blank=True,
        default='This feature is temporarily unavailable.'
    )

    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "00-00B Client Feature Control"
        verbose_name_plural = "00-00B Client Feature Controls"

    def __str__(self):
        target = self.client.client_id if self.client else "ALL CLIENTS"
        return f"{target} / {self.feature}"

    @property
    def is_active(self):
        now = timezone.now()
        return (
            self.is_disabled and
            self.from_date <= now <= self.to_date
        )