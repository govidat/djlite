# mysite/models/catalogue.py
"""
Generic Item Catalogue — Phase 2 (Revised)

Key design decisions:
1. GlobalItem + Item (client derives from global, can override)
2. TaxonomyNode attribute inheritance: grandparent → parent → node → item
3. GS1 GPC aligned: GTIN, GPC Brick code, Segment/Family/Class/Brick hierarchy
4. Typed sub-models (ProductItem, SongItem, DocumentItem, ServiceItem)
5. Beckn protocol schema-aligned for Phase 3 eCommerce
6. Multi-tenant: client=None means global (superuser-managed)
"""

from django.db import models
#from django.contrib.contenttypes.fields import GenericRelation
from .base import LowercaseCharField, text_field_validators

import uuid
from django.contrib.auth.models import User
from .client import Client
from django.utils.translation import get_language
from django.core.exceptions import ObjectDoesNotExist


# ── 0. Scope helper ──────────────────────────────────────────────────
"""
def is_global(instance):
    #True if this record is global (not client-specific).
    return getattr(instance, 'client', None) is None

def resolve_i18n_field(self, field, language=None):
    lang = language or get_language()

    local_value = getattr(self, f"{field}_{lang}", None)
    if local_value:
        return local_value

    if self.global_item:
        return getattr(self.global_item, f"{field}_{lang}", '')

    return ''
"""

class I18nFallbackMixin:

    def resolve_i18n_field(self, field, language=None):

        lang = language or get_language()

        local_value = getattr(self, f"{field}_{lang}", None)

        if local_value:
            return local_value

        global_item = getattr(self, "global_item", None)

        if global_item:
            return getattr(global_item, f"{field}_{lang}", '')

        return ''

"""
If a domain like product, song etc is added:
1. Add the model + admin
2. In get_item_queryset
qs = Item.objects.filter(...).select_related(
    'client',
    'product_detail',   # ← add these
    'song_detail',
    'document_detail',
    'service_detail',
).prefetch_related(...)

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
        # Item base table
        #""CREATE INDEX IF NOT EXISTS item_attributes_gin_idx ON mysite_item USING GIN (attributes jsonb_path_ops)#"",
        #""CREATE INDEX IF NOT EXISTS item_domain_idx ON mysite_item (client_id, domain, status)#"",

        # Item base table
        #""CREATE INDEX IF NOT EXISTS item_client_domain_status_idx ON mysite_item (client_id, domain, status)#""',
        #""CREATE INDEX IF NOT EXISTS item_client_status_order_idx ON mysite_item (client_id, status, "order")#""',
        #""CREATE INDEX IF NOT EXISTS item_global_item_idx ON mysite_item (global_item_id, client_id)'#"",
        #""CREATE INDEX IF NOT EXISTS item_gtin_idx ON mysite_item (gtin) WHERE gtin != ''#"",

        # GlobalItem
        #""CREATE INDEX IF NOT EXISTS globalitem_gtin_idx ON mysite_globalitem (gtin) WHERE gtin != ''#"",
        #""CREATE INDEX IF NOT EXISTS globalitem_gpc_idx ON mysite_globalitem (gpc_brick_code) WHERE gpc_brick_code != ''#"",
        #""CREATE INDEX IF NOT EXISTS globalitem_attributes_gin_idx ON mysite_globalitem USING GIN (attributes jsonb_path_ops)#"",        

        ## TaxonomyNode
        #""CREATE INDEX IF NOT EXISTS taxonomy_node_path_idx ON mysite_taxonomynode USING BTREE (taxonomy_id, path text_pattern_ops)#"",
        #""CREATE INDEX IF NOT EXISTS taxonomynode_gpc_idx ON mysite_taxonomynode (gpc_code) WHERE gpc_code != ''#"",

        ## ProductItem
        #""CREATE INDEX IF NOT EXISTS productitem_attributes_gin_idx ON mysite_productitem USING GIN (attributes jsonb_path_ops)#"",
        #""CREATE INDEX IF NOT EXISTS productitem_sku_idx ON mysite_productitem (sku) WHERE sku != ''#"",
        #""CREATE INDEX IF NOT EXISTS productitem_price_idx ON mysite_productitem (price) WHERE price IS NOT NULL#"",


        ## SongItem
        #""CREATE INDEX IF NOT EXISTS songitem_attributes_gin_idx ON mysite_songitem USING GIN (attributes jsonb_path_ops)#"",
        #""CREATE INDEX IF NOT EXISTS songitem_artist_idx ON mysite_songitem (artist) WHERE artist != ''#"",
        #""CREATE INDEX IF NOT EXISTS songitem_album_idx ON mysite_songitem (album) WHERE album != ''#"",        
        ## DocumentItem
        #""CREATE INDEX IF NOT EXISTS documentitem_attributes_gin_idx ON mysite_documentitem USING GIN (attributes jsonb_path_ops)#"",
        #""CREATE INDEX IF NOT EXISTS documentitem_format_idx ON mysite_documentitem (format) WHERE artist != ''#"",        
        ## ServiceItem
        #""CREATE INDEX IF NOT EXISTS serviceitem_attributes_gin_idx ON mysite_serviceitem USING GIN (attributes jsonb_path_ops)#"",
        #""CREATE INDEX IF NOT EXISTS serviceitem_fulfillment_type_idx ON mysite_serviceitem (fulfillment_type) WHERE artist != ''#"",        
        # ItemAttributeValue — critical for faceted filter queries
        #""CREATE INDEX IF NOT EXISTS itemattributevalue_lookup_idx ON mysite_itemattributevalue (attribute_type_id, predefined_value_id)#""',
        #""CREATE INDEX IF NOT EXISTS globalitemattributevalue_lookup_idx ON mysite_globalitemattributevalue (attribute_type_id, predefined_value_id)#"",
         

    ]
    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS item_attributes_gin_idx',
        'DROP INDEX IF EXISTS item_client_status_idx',
        'DROP INDEX IF EXISTS item_domain_idx',
        'DROP INDEX IF EXISTS item_client_domain_status_idx',
        'DROP INDEX IF EXISTS item_client_status_order_idx',
        'DROP INDEX IF EXISTS item_global_item_idx',
        'DROP INDEX IF EXISTS item_gtin_idx',

        'DROP INDEX IF EXISTS globalitem_gtin_idx',
        'DROP INDEX IF EXISTS globalitem_gpc_idx',
        'DROP INDEX IF EXISTS globalitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS taxonomy_node_path_idx',
        'DROP INDEX IF EXISTS taxonomynode_gpc_idx',        
        'DROP INDEX IF EXISTS productitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS productitem_sku_idx',
        'DROP INDEX IF EXISTS productitem_price_idx',
        'DROP INDEX IF EXISTS songitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS songitem_artist_idx',
        'DROP INDEX IF EXISTS songitem_album_idx',    
        'DROP INDEX IF EXISTS documentitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS documentitem_format_idx', 
        'DROP INDEX IF EXISTS serviceitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS serviceitem_fulfillment_type_idx',  
        'DROP INDEX IF EXISTS itemattributevalue_lookup_idx',
        'DROP INDEX IF EXISTS globalitemattributevalue_lookup_idx',                             
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
# ── 1. Taxonomy (Hierarchy type) ─────────────────────────────────────
 
class Taxonomy(models.Model):
    """
    Defines the TYPE of hierarchy.
    GS1 alignment: 'gpc' taxonomy uses Segment/Family/Class/Brick levels.
    Custom taxonomies: 'geography', 'department', or client-defined.

    Scope:
      client=None → global taxonomy (superuser-managed, available to all clients)
      client=X    → client-specific taxonomy (overrides global of same slug)
    """
    TAXONOMY_TYPES = [
        ('gpc',        'GS1 GPC (Segment/Family/Class/Brick)'),
        ('geography',  'Geography'),
        ('department', 'Department'),
        ('brand',      'Brand'),
        ('custom',     'Custom'),
    ]
    client      = models.ForeignKey(
        'mysite.Client',
        null=True, blank=True,           # null = global taxonomy
        on_delete=models.CASCADE,
        related_name='taxonomies'
    )
    slug        = LowercaseCharField(max_length=50, db_index=True)
    #
    taxonomy_type = models.CharField(
        max_length=20, choices=TAXONOMY_TYPES, default='custom'
    )
    name        = models.CharField(max_length=100, blank=True)   # modeltranslation expands blank=True to be added
    description = models.CharField(max_length=300, blank=True) # modeltranslation expands

    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)

    # GS1: reference to GPC segment code if this is a GPC taxonomy
    gpc_segment_code = models.CharField(
        max_length=20, blank=True,
        help_text="GS1 GPC Segment code e.g. '50' for Food/Beverage/Tobacco"
    )

    class Meta:
        unique_together = ('client', 'slug')
        ordering        = ['order', 'slug']
        verbose_name    = '01-01 Item Taxonomy'
        indexes         = [
            models.Index(fields=['client', 'slug']),
            models.Index(fields=['client', 'is_active']),
        ]

    def __str__(self):
        scope = self.client.client_id if self.client else 'GLOBAL'
        return f"[{scope}] {self.slug}"
    

# ── 2. TaxonomyNode (tree node within a hierarchy) ───────────────────

class TaxonomyNode(models.Model):
    """
    A node in a taxonomy tree.

    GS1 GPC alignment:
      depth=0 → Segment   (e.g. "Food, Beverage and Tobacco")
      depth=1 → Family    (e.g. "Beverages")
      depth=2 → Class     (e.g. "Alcoholic Beverages")
      depth=3 → Brick     (e.g. "Beer")
      depth=4+ → custom sub-brick (non-GS1, client-defined)

    Scope:
      client=None → global node (superuser-managed)
      client=X    → client-specific node

    Materialized path for efficient subtree queries without recursion.
    path format: "001.002.003" — zero-padded 3-digit segments.

    Attribute inheritance:
      Item resolves attributes by walking up the path:
      grandparent node attrs → parent node attrs → node attrs → item attrs
      Lower level values override higher level values.

    To get all descendants: filter(path__startswith="001.")
    To get depth:           len(path.split("."))
    """
    taxonomy    = models.ForeignKey(
        Taxonomy,
        on_delete=models.CASCADE,
        related_name='nodes'
    )
    client      = models.ForeignKey(
        Client, null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='taxonomy_nodes',
        help_text="Null = global node. Client nodes can reference global nodes as parent."
    )    
    parent      = models.ForeignKey(
        'self',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='children'
    )
    slug        = LowercaseCharField(max_length=100, db_index=True)
    name        = models.CharField(max_length=150, blank=True)   # modeltranslation expands
    path        = models.CharField(
        max_length=500, db_index=True,
        help_text="Materialized path e.g. '001.002.003'. Auto-managed."
    )
    depth       = models.PositiveSmallIntegerField(default=0)
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    metadata    = models.JSONField(default=dict, blank=True)

    # GS1 GPC codes (for GPC taxonomy type)
    gpc_code    = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text="GS1 GPC code: Segment(2), Family(4), Class(6), or Brick(8) digits"
    )

    # Reference to global node this client node is based on (optional)
    global_node = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='client_overrides',
        help_text="Global node this client node derives from"
    )

    class Meta:
        unique_together = ('taxonomy', 'client', 'slug')
        ordering        = ['taxonomy', 'path', 'order']
        verbose_name    = '01-02 Item Taxonomy Node'
        indexes         = [
            models.Index(fields=['taxonomy', 'client', 'path']),
            models.Index(fields=['taxonomy', 'client', 'is_active', 'depth']),
            models.Index(fields=['gpc_code']),
        ]

    def __str__(self):
        scope = self.client.client_id if self.client else 'GLOBAL'
        return f"[{scope}] {self.taxonomy.slug} / {self.path} / {self.slug}"

    def save(self, *args, **kwargs):
        if self.parent:
            self.path  = f"{self.parent.path}.{self.order:03d}"
            self.depth = self.parent.depth + 1
        else:
            self.path  = f"{self.order:03d}"
            self.depth = 0
        super().save(*args, **kwargs)

    def get_ancestor_paths(self):
        """Returns list of paths for all ancestors, root-first."""
        parts = self.path.split('.')
        return ['.'.join(parts[:i]) for i in range(1, len(parts))]

    def get_ancestors_qs(self):
        """Queryset of ancestors ordered root-first."""
        paths = self.get_ancestor_paths()
        return TaxonomyNode.objects.filter(
            taxonomy=self.taxonomy,
            path__in=paths
        ).order_by('depth')

    def get_descendant_path_prefix(self):
        return f"{self.path}."

# mysite/models/catalogue.py — updated

"""
The best pattern for your situation: Typed Sub-models + residual JSONB

This is actually a well-established pattern — sometimes called the concrete table inheritance + overflow approach.
Item (base — id, name, description, status, image, order, client)
  ├── ProductItem    (price, currency, sku, weight_g, dimensions)  [OneToOne]
  ├── SongItem       (duration_s, bpm, key, artist, album)         [OneToOne]
  ├── DocumentItem   (page_count, format, file_url, version)       [OneToOne]
  └── attributes     (JSONField on Item — catches anything else)

Each sub-model has a OneToOneField to Item. The base Item.attributes JSONB field remains as an escape hatch for fields that don't fit the sub-model.
Why OneToOne over Django's proxy or multi-table inheritance
Django has built-in multi-table inheritance (class ProductItem(Item)) but it causes problems in your setup:

django-modeltranslation interacts poorly with MTI — translation fields get duplicated up the inheritance chain
django-nested-admin inlines don't work cleanly with MTI
Querying requires awkward select_related patterns
Admin shows ProductItem and Item as separate registered models, confusing staff

OneToOne is cleaner because:

Item is always the base record — all queries, translations, and catalogue logic operate on Item
Sub-model is optional — a SongItem may not exist if the client doesn't use audio
Admin: ProductItemInline sits inside ItemAdmin — one form, clear hierarchy
Translation: ProductItem.name_long translates normally via modeltranslation
Beckn: item.to_beckn() checks which sub-model exists and adds domain-specific tags

"""

class NodeAttributeType(models.Model):
    """
    Defines an attribute TYPE applicable to a TaxonomyNode and its descendants.
    GS1 alignment: Brick Attributes (e.g. "Flavour", "Pack Size", "Material").

    Scope: global (client=None) or client-specific.
    Inherited by: all items under this node (and child nodes).
    """
    FIELD_TYPES = [
        ('text',     'Text'),
        ('number',   'Number'),
        ('boolean',  'Yes/No'),
        ('select',   'Select (predefined values)'),
        ('multiselect', 'Multi-select'),
    ]

    node        = models.ForeignKey(
        TaxonomyNode, on_delete=models.CASCADE, related_name='attribute_types'
    )
    client      = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.CASCADE,
        help_text="Null = global attribute type"
    )
    slug        = LowercaseCharField(max_length=50)
    name        = models.CharField(max_length=100, blank=True)    # modeltranslation
    field_type  = models.CharField(max_length=20, choices=FIELD_TYPES, default='text')
    is_required = models.BooleanField(default=False)
    is_filterable = models.BooleanField(
        default=True,
        help_text="Show in catalogue filter sidebar"
    )
    order       = models.PositiveIntegerField(default=0)

    # GS1 GPC Brick Attribute code (optional)
    gpc_attribute_code = models.CharField(max_length=20, blank=True)

    class Meta:
        unique_together = ('node', 'client', 'slug')
        ordering        = ['node', 'order']
        verbose_name    = '01-03 Item Node Attribute Type'

    def __str__(self):
        return f"{self.node} / {self.slug}"


class NodeAttributeValue(models.Model):
    """
    A predefined VALUE for a NodeAttributeType (for select/multiselect types).
    GS1 alignment: Brick Attribute Values (e.g. Flavour → "Chocolate", "Vanilla").

    These values are INHERITED by items under this node.
    Client can add their own values on top of global values.
    """
    attribute_type = models.ForeignKey(
        NodeAttributeType, on_delete=models.CASCADE, related_name='predefined_values'
    )
    client      = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.CASCADE,
        help_text="Null = global value"
    )
    slug        = LowercaseCharField(max_length=50)
    name        = models.CharField(max_length=200, blank=True)    # modeltranslation
    order       = models.PositiveIntegerField(default=0)

    # GS1 GPC Brick Attribute Value code (optional)
    gpc_value_code = models.CharField(max_length=20, blank=True)

    class Meta:
        unique_together = ('attribute_type', 'client', 'slug')
        ordering        = ['attribute_type', 'order']
        verbose_name    = '01-04 Item Node Attribute Value'

    def __str__(self):
        return f"{self.attribute_type.slug} = {self.name}"


# ═══════════════════════════════════════════════════════════════════
# PART B: GLOBAL ITEM (Reference catalogue — superuser managed)
#GlobalItem
# ├── GlobalItemTaxonomyNode   (FK → GlobalItem)
# └── GlobalItemAttributeValue (FK → GlobalItem)
# ═══════════════════════════════════════════════════════════════════

class GlobalItem(models.Model):
    """
    Reference item maintained at global level by superuser.
    GS1 alignment: analogous to a GTIN record in a brand's master catalogue.

    Examples:
      - "Dove Shampoo 200ml" used by multiple ShopClient distributors
      - "Bosch Spark Plug BP234" used by multiple AutoParts distributors
      - A song from a music label referenced by multiple streaming clients

    Client items can DERIVE from a GlobalItem, inheriting its data
    and selectively overriding fields at the client level.

    Domain sub-models: GlobalProductItem, GlobalSongItem, etc. follow
    the same pattern as client-side sub-models.
    """
    STATUS_CHOICES = [
        ('draft',    'Draft'),
        ('active',   'Active'),
        ('archived', 'Archived'),
    ]
    DOMAIN_CHOICES = [
        ('product',  'Physical Product'),
        ('digital',  'Digital Product / Software'),
        ('song',     'Song / Audio'),
        ('document', 'Document / Publication'),
        ('service',  'Service'),
        ('generic',  'Generic'),
    ]

    # GS1 identification
    gtin        = models.CharField(
        max_length=14, blank=True, db_index=True,
        help_text="GS1 GTIN-8/12/13/14. Globally unique product identifier."
    )
    gpc_brick_code = models.CharField(
        max_length=8, blank=True, db_index=True,
        help_text="GS1 GPC 8-digit Brick code e.g. '10000455' for Dandruff Shampoo"
    )

    # Identity
    global_item_id = LowercaseCharField(max_length=100, unique=True, db_index=True)
    domain         = models.CharField(
        max_length=20, choices=DOMAIN_CHOICES, default='generic', db_index=True
    )
    status         = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True
    )

    # Core translatable content
    name           = models.CharField(max_length=200, blank=True)     # modeltranslation
    description    = models.TextField(blank=True)          # modeltranslation
    #brand          = models.CharField(max_length=100, blank=True) -- moved to Taxonomy
    #subbrand       = models.CharField(max_length=100, blank=True) -- moved to Taxonomy   
    #manufacturer   = models.CharField(max_length=100, blank=True) -- moved to Taxonomy
    country_of_origin = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")

    # Primary image
    image_url      = models.URLField(max_length=500, blank=True)
    image_alt      = models.CharField(max_length=200, blank=True)

    barcode           = models.CharField(max_length=100, blank=True)
    weight_g          = models.PositiveIntegerField(null=True, blank=True)
    length_mm         = models.PositiveIntegerField(null=True, blank=True)
    width_mm          = models.PositiveIntegerField(null=True, blank=True)
    height_mm         = models.PositiveIntegerField(null=True, blank=True)
    care_instructions = models.TextField(blank=True)                   # modeltranslation

    # Overflow attributes
    attributes     = models.JSONField(
        default=dict, blank=True,
        help_text="Global overflow attributes not covered by typed sub-models"
    )

    # Audit
    created_by     = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='global_items_created'
    )
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering     = ['global_item_id']
        verbose_name = '01-05 Global Item'
        indexes      = [
            models.Index(fields=['domain', 'status']),
            models.Index(fields=['gtin']),
            models.Index(fields=['gpc_brick_code']),
            #models.Index(fields=['brand', 'status']),
        ]

    def __str__(self):
        return f"[GLOBAL] {self.global_item_id} — {self.name}"


class GlobalItemTaxonomyNode(models.Model):
    """Maps a GlobalItem to global TaxonomyNodes."""
    global_item = models.ForeignKey(
        GlobalItem, on_delete=models.CASCADE, related_name='taxonomy_mappings'
    )
    node        = models.ForeignKey(
        TaxonomyNode, on_delete=models.CASCADE, related_name='global_item_mappings'
    )
    is_primary  = models.BooleanField(default=False)

    class Meta:
        unique_together = ('global_item', 'node')
        verbose_name    = 'Global Item Taxonomy Node'


class GlobalItemAttributeValue(models.Model):
    """
    Attribute values on a GlobalItem.
    These cascade down to derived client Items (client can override).
    """
    global_item    = models.ForeignKey(
        GlobalItem, on_delete=models.CASCADE, related_name='attribute_values'
    )
    attribute_type = models.ForeignKey(
        NodeAttributeType, on_delete=models.CASCADE, related_name='global_item_values'
    )
    # For select types: FK to predefined value
    predefined_value = models.ForeignKey(
        NodeAttributeValue, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='global_item_usages'
    )
    # For free-text / number types
    value_text   = models.CharField(max_length=500, blank=True)
    value_number = models.DecimalField(
        max_digits=15, decimal_places=4, null=True, blank=True
    )

    class Meta:
        unique_together = ('global_item', 'attribute_type')
        verbose_name    = 'Global Item Attribute Value'

    def resolved_value(self):
        if self.predefined_value:
            return self.predefined_value.name
        if self.value_number is not None:
            return str(self.value_number)
        return self.value_text

# ═══════════════════════════════════════════════════════════════════
# PART C: CLIENT ITEM
# ═══════════════════════════════════════════════════════════════════

class Item(I18nFallbackMixin, models.Model):
    """
    Client-level item. Can exist independently OR derive from a GlobalItem.

    Derivation pattern:
      - If global_item is set: inherit all GlobalItem fields as defaults
      - Client can override: name, description, image, attributes, pricing
      - Fields not overridden fall back to global_item values at query time
      - This mirrors the GS1 GDSN pattern: brand publishes, retailer overrides

    Scope:
      client=None → shared item usable by any client (superuser-created)
      client=X    → belongs to specific client

    Priority for item resolution:
      client-specific item → client=None shared item → GlobalItem reference
    """
    STATUS_CHOICES = [
        ('draft',    'Draft'),
        ('active',   'Active'),
        ('archived', 'Archived'),
    ]
    DOMAIN_CHOICES = [
        ('product',  'Physical Product'),
        ('digital',  'Digital Product / Software'),
        ('song',     'Song / Audio'),
        ('document', 'Document / Publication'),
        ('service',  'Service'),
        ('generic',  'Generic'),
    ]

    # Tenant scope
    client         = models.ForeignKey(
        Client, null=False, blank=False, 
        on_delete=models.CASCADE, related_name='items',
        
    )
    # help_text="Null = shared item (superuser-created, usable by all clients)"
    # Derivation from global reference
    global_item    = models.ForeignKey(
        GlobalItem, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='client_items',
        help_text="Global reference item this derives from. "
                  "Unset fields fall back to GlobalItem values."
    )

    # GS1 identification (copied or overridden from global_item)
    gtin           = models.CharField(max_length=14, blank=True, db_index=True)
    gpc_brick_code = models.CharField(max_length=8, blank=True, db_index=True)

    # Identity
    item_id        = LowercaseCharField(max_length=100, db_index=True)
    domain         = models.CharField(
        max_length=20, choices=DOMAIN_CHOICES, default='generic', db_index=True
    )
    status         = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True
    )
    order          = models.PositiveIntegerField(default=0)

    # Override fields — None/blank means "use GlobalItem value"
    name           = models.CharField(max_length=200, blank=True)   # modeltranslation
    description    = models.TextField(blank=True)                    # modeltranslation

    #brand          = models.CharField(max_length=100, blank=True)-- moved to Taxonomy
    #subbrand       = models.CharField(max_length=100, blank=True)-- moved to Taxonomy   
    #manufacturer   = models.CharField(max_length=100, blank=True)-- moved to Taxonomy
    country_of_origin = models.CharField(max_length=2, blank=True, help_text="ISO 3166-1 alpha-2")

    image_url      = models.URLField(max_length=500, blank=True)
    image_alt      = models.CharField(max_length=200, blank=True)
    # moved from Product
    barcode           = models.CharField(max_length=100, blank=True)
    weight_g          = models.PositiveIntegerField(null=True, blank=True)
    length_mm         = models.PositiveIntegerField(null=True, blank=True)
    width_mm          = models.PositiveIntegerField(null=True, blank=True)
    height_mm         = models.PositiveIntegerField(null=True, blank=True)
    care_instructions = models.TextField(blank=True)                   # modeltranslation


    # Overflow attributes
    attributes     = models.JSONField(
        default=dict, blank=True,
        help_text="Global overflow attributes not covered by typed sub-models"
    )

    # Audit
    created_by     = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL
    )
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)


    class Meta:
        unique_together = ('client', 'item_id')
        ordering        = ['client', 'order', 'item_id']
        verbose_name    = '01-06 Item'
        indexes         = [
            models.Index(fields=['client', 'status', 'domain']),
            models.Index(fields=['client', 'status', 'order']),
            models.Index(fields=['global_item', 'client']),
            models.Index(fields=['gtin']),
        ]

    def __str__(self):
        scope = self.client.client_id if self.client else 'SHARED'
        return f"[{scope}] {self.item_id}"

    # ── Field resolution: client override → global fallback ──────────
    def resolved_name(self):
        return self.resolve_i18n_field('name')

    def resolved_description(self):
        return self.resolve_i18n_field('description')

    def resolved_care_instructions(self):
        return self.resolve_i18n_field('care_instructions')
    """
    def resolved_name(self):
        if self.name:
            return self.name
        return self.global_item.name if self.global_item else ''

    def resolved_description(self):
        if self.description:
            return self.description
        return self.global_item.description if self.global_item else ''
    
    def resolved_care_instructions(self):
        if self.care_instructions:
            return self.care_instructions
        return self.global_item.care_instructions if self.global_item else ''    
    """

    def resolved_barcode(self):
        if self.barcode:
            return self.barcode
        return self.global_item.barcode if self.global_item else ''

    def resolved_weight_g(self):
        if self.weight_g:
            return self.weight_g
        return self.global_item.weight_g if self.global_item else 0        

    def resolved_length_mm(self):
        if self.length_mm:
            return self.length_mm
        return self.global_item.length_mm if self.global_item else 0 
    
    def resolved_width_mm(self):
        if self.width_mm:
            return self.width_mm
        return self.global_item.width_mm if self.global_item else 0    

    def resolved_height_mm(self):
        if self.height_mm:
            return self.height_mm
        return self.global_item.height_mm if self.global_item else 0

    def resolved_image_url(self):
        if self.image_url:
            return self.image_url
        return self.global_item.image_url if self.global_item else ''
    """
    def resolved_brand(self):
        if self.brand:
            return self.brand
        return self.global_item.brand if self.global_item else ''

    def resolved_subbrand(self):
        if self.subbrand:
            return self.subbrand
        return self.global_item.subbrand if self.global_item else ''    
    
    def resolved_manufacturer(self):
        if self.manufacturer:
            return self.manufacturer
        return self.global_item.manufacturer if self.global_item else ''
    """

    def resolved_country_of_origin(self):
        if self.country_of_origin:
            return self.country_of_origin
        return self.global_item.country_of_origin if self.global_item else ''        

    def resolved_attributes(self):
        """Merge: global_item.attributes ← item.attributes (item wins)."""
        base = {}
        if self.global_item:
            base = dict(self.global_item.attributes)
        base.update(self.attributes)
        return base

    def get_domain_object(self):
        """Returns the typed sub-model instance for this item's domain."""
        domain_map = {
            'product':  'product_detail',
            'song':     'song_detail',
            'document': 'document_detail',
            'service':  'service_detail',
        }
        #accessor = domain_map.get(self.domain)
        #return getattr(self, accessor, None) if accessor else None
        accessor = domain_map.get(self.domain)
        if not accessor:
            return None
        try:
            return getattr(self, accessor)
        except ObjectDoesNotExist:
            return None    


    def resolve_attributes_with_inheritance(self, node_ids=None):
        """
        Full attribute resolution with hierarchy inheritance.
        Priority (lowest wins, i.e. overrides higher):
          1. TaxonomyNode ancestor attributes (root → leaf)
          2. Item's TaxonomyNode attributes
          3. GlobalItem attribute values
          4. Item attribute values
          5. Item.attributes JSONB (overflow)

        Returns: dict of {attribute_slug: resolved_value}
        """
        resolved = {}

        # 1+2. Node hierarchy attributes (ancestor → node, deepest wins)
        if node_ids is None:
            node_ids = list(
                self.taxonomy_mappings
                .values_list('node_id', flat=True)
            )

        if node_ids:
            nodes = TaxonomyNode.objects.filter(
                id__in=node_ids
            ).prefetch_related(
                'attribute_types__predefined_values',
            ).order_by('depth')

            for node in nodes:
                # Walk ancestors first (shallower depth = lower priority)
                for attr_type in node.attribute_types.all():
                    # Node-level default value is not stored here —
                    # it comes from GlobalItemAttributeValue or ItemAttributeValue
                    pass  # attribute types define WHAT exists; values set by items

        # 3. GlobalItem attribute values
        if self.global_item:
            for av in self.global_item.attribute_values.select_related(
                'attribute_type', 'predefined_value'
            ).all():
                resolved[av.attribute_type.slug] = av.resolved_value()

        # 4. Item attribute values (override global)
        for av in self.attribute_values.select_related(
            'attribute_type', 'predefined_value'
        ).all():
            resolved[av.attribute_type.slug] = av.resolved_value()

        # 5. JSONB overflow (lowest priority — most specific)
        resolved.update(self.resolved_attributes())

        return resolved


class ItemTaxonomyNode(models.Model):
    """Maps a client Item to TaxonomyNodes (global or client nodes)."""
    item        = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name='taxonomy_mappings'
    )
    node        = models.ForeignKey(
        TaxonomyNode, on_delete=models.CASCADE, related_name='item_mappings'
    )
    is_primary  = models.BooleanField(
        default=False,
        help_text="Primary node for this taxonomy (used for breadcrumbs)"
    )
    order       = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('item', 'node')
        ordering        = ['item', 'node__taxonomy', 'order']
        indexes         = [
            models.Index(fields=['item', 'node']),
            models.Index(fields=['node', 'item']),
        ]

    def __str__(self):
        return f"{self.item} → {self.node}"


class ItemAttributeValue(models.Model):
    """
    Attribute value assigned to a client Item.
    Overrides GlobalItem attribute values of the same attribute_type.

    For inheritance resolution:
      GlobalItem.attribute_values → overridden by → Item.attribute_values
    """
    item           = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name='attribute_values'
    )
    attribute_type = models.ForeignKey(
        NodeAttributeType, on_delete=models.CASCADE, related_name='item_values'
    )
    predefined_value = models.ForeignKey(
        NodeAttributeValue, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='item_usages'
    )
    value_text     = models.CharField(max_length=500, blank=True)
    value_number   = models.DecimalField(
        max_digits=15, decimal_places=4, null=True, blank=True
    )

    class Meta:
        unique_together = ('item', 'attribute_type')
        verbose_name    = 'Item Attribute Value'

    def resolved_value(self):
        if self.predefined_value:
            return self.predefined_value.name
        if self.value_number is not None:
            return str(self.value_number)
        return self.value_text

    def __str__(self):
        return f"{self.item} / {self.attribute_type.slug} = {self.resolved_value()}"


# ═══════════════════════════════════════════════════════════════════
# PART D: TYPED SUB-MODELS (domain-specific fields)
# ═══════════════════════════════════════════════════════════════════

class ProductItem(models.Model):
    """Physical or digital product domain fields."""
    item              = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='product_detail'
    )
    price             = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    compare_price     = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Original price before discount"
    )
    currency          = models.CharField(max_length=3, default='INR')
    sku               = models.CharField(max_length=100, blank=True, db_index=True)
    barcode           = models.CharField(max_length=100, blank=True)   
    track_inventory   = models.BooleanField(default=False)
    stock_quantity    = models.IntegerField(default=0)
    #weight_g          = models.PositiveIntegerField(null=True, blank=True) ---- moved to item
    #length_mm         = models.PositiveIntegerField(null=True, blank=True) ---- moved to item
    #width_mm          = models.PositiveIntegerField(null=True, blank=True) ---- moved to item
    #height_mm         = models.PositiveIntegerField(null=True, blank=True) ---- moved to item
    #short_description = models.CharField(max_length=500, blank=True)  # modeltranslation ---- remoed
    #care_instructions = models.TextField(blank=True)                   # modeltranslation ---- moved to item
    attributes        = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Product Detail'

    def __str__(self):
        return f"Product: {self.item}"

    def to_beckn_tags(self):
        return {
            'price':    str(self.price or ''),
            'currency': self.currency,
            'sku':      self.sku,
            'weight_g': str(self.weight_g or ''),
            **self.attributes,
        }

class SongItem(models.Model):
    """Audio / music domain fields."""
    item        = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='song_detail'
    )
    artist      = models.CharField(max_length=200, blank=True)   # modeltranslation
    album       = models.CharField(max_length=200, blank=True)   # modeltranslation
    duration_s  = models.PositiveIntegerField(null=True, blank=True)
    bpm         = models.PositiveSmallIntegerField(null=True, blank=True)
    musical_key = models.CharField(max_length=10, blank=True)
    genre       = models.CharField(max_length=50, blank=True)
    audio_url   = models.URLField(max_length=500, blank=True)
    preview_url = models.URLField(max_length=500, blank=True)
    isrc        = models.CharField(max_length=20, blank=True)
    attributes  = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Song Detail'

    def to_beckn_tags(self):
        return {'artist': self.artist, 'album': self.album,
                'duration_s': str(self.duration_s or ''), **self.attributes}

class DocumentItem(models.Model):
    """Document / publication domain fields."""
    item         = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='document_detail'
    )
    file_url     = models.URLField(max_length=500, blank=True)
    format       = models.CharField(max_length=20, blank=True)
    page_count   = models.PositiveIntegerField(null=True, blank=True)
    file_size_kb = models.PositiveIntegerField(null=True, blank=True)
    version      = models.CharField(max_length=20, blank=True)
    language     = models.CharField(max_length=10, blank=True)
    is_free      = models.BooleanField(default=True)
    price        = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency     = models.CharField(max_length=3, default='INR')
    attributes   = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Document Detail'

    def to_beckn_tags(self):
        return {'format': self.format, 'pages': str(self.page_count or ''),
                'version': self.version, **self.attributes}

class ServiceItem(models.Model):
    """Service domain fields — appointments, consultations, repairs."""
    item             = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='service_detail'
    )
    price            = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency         = models.CharField(max_length=3, default='INR')
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_location_based = models.BooleanField(default=False)
    service_area     = models.CharField(max_length=200, blank=True)
    fulfillment_type = models.CharField(
        max_length=20, blank=True,
        choices=[('in-person','In Person'),('remote','Remote'),('hybrid','Hybrid')]
    )
    attributes       = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Service Detail'

    def to_beckn_tags(self):
        return {'duration_minutes': str(self.duration_minutes or ''),
                'fulfillment_type': self.fulfillment_type, **self.attributes}


# ── 5. ItemMedia Image/Audio/ Video ──────────────────────────────────────────────────────

class ItemMedia(models.Model):
    #Additional images per item beyond the primary image_url.
    item        = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='medias'
    )
    MEDIA_CHOICES = [
        ('image',  'Image'),
        ('audio',  'Audio'),
        ('video',     'Video')
    ]    
    media_type  = models.CharField(max_length=20, choices=MEDIA_CHOICES, db_index=True)    
    media_url   = models.URLField(max_length=500)
    alt         = models.CharField(max_length=200, blank=True)
    order       = models.PositiveIntegerField(default=0)
    is_primary  = models.BooleanField(default=False)

    class Meta:
        ordering = ['item', 'order']

    def __str__(self):
        return f"{self.item} / media {self.order}"

# ── 6. ItemVariant (Phase 3 eCommerce ready) ─────────────────────────

class ItemVariant(models.Model):
    """
    Optional variants per item (size, colour, etc.).
    Phase 3: CartItem FKs to ItemVariant (or Item if no variants).
    Beckn: maps to Item with different attributes in select/init flow.
    """
    item         = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name='variants'
    )
    variant_id   = LowercaseCharField(max_length=50)
    name         = models.CharField(max_length=100, blank=True) # modeltranslation
    sku          = models.CharField(max_length=100, blank=True, db_index=True)
    gtin         = models.CharField(max_length=14, blank=True,
                                     help_text="Variant-level GTIN if different from item")
    attributes   = models.JSONField(
        default=dict, blank=True,
        help_text='{"color": "red", "size": "XL"}'
    )
    price        = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Overrides item-level price"
    )
    stock        = models.IntegerField(default=0)
    is_active    = models.BooleanField(default=True)

    class Meta:
        unique_together = ('item', 'variant_id')
        ordering        = ['item', 'variant_id']
        verbose_name    = 'Item Variant'

    def __str__(self):
        return f"{self.item} / {self.variant_id}"

    def effective_price(self):
        """Variant price overrides item-level price."""
        if self.price is not None:
            return self.price
        domain_obj = self.item.get_domain_object()
        if domain_obj and hasattr(domain_obj, 'price'):
            return domain_obj.price
        return self.item.attributes.get('price')
