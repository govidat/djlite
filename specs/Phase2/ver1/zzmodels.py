# mysite/models/catalogue.py
"""
Generic Item Catalogue — Phase 2
Supports: multi-tenancy, multiple independent hierarchies,
JSONB attributes, global/client override pattern.
Extendable to eCommerce (Phase 3) via ItemVariant + CartItem.
"""

from django.db import models
from django.contrib.contenttypes.fields import GenericRelation
from .base import LowercaseCharField, text_field_validators
from .client import Client


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
        #""CREATE INDEX IF NOT EXISTS item_client_status_idx  ON mysite_item (client_id, status, "order")#"",
        #""CREATE INDEX IF NOT EXISTS item_domain_idx ON mysite_item (client_id, domain, status)#"",
        ## TaxonomyNode
        #""CREATE INDEX IF NOT EXISTS taxonomy_node_path_idx ON mysite_taxonomynode USING BTREE (taxonomy_id, path text_pattern_ops)#"",
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
        'DROP INDEX IF EXISTS taxonomy_node_path_idx',
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
            add_postgres_indexes,
            remove_postgres_indexes,
        ),
    ]

# 3. Verify it runs cleanly
python manage.py migrate

# 4. Confirm on PostgreSQL (production)
python manage.py dbshell
\d mysite_item   # should show the GIN index


"""
# ── 1. Taxonomy (Hierarchy type) ─────────────────────────────────────

class Taxonomy(models.Model):
    """
    Defines the TYPE of hierarchy — Category, Geography, Department, etc.
    Can be global (client=None) or client-specific.
    Client-specific taxonomy overrides global taxonomy of the same slug.
    """
    client      = models.ForeignKey(
        Client,
        null=True, blank=True,           # null = global taxonomy
        on_delete=models.CASCADE,
        related_name='taxonomies'
    )
    slug        = LowercaseCharField(max_length=50, db_index=True)
    name        = models.CharField(max_length=100)   # modeltranslation expands
    description = models.CharField(max_length=300, blank=True)
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)

    class Meta:
        unique_together = ('client', 'slug')
        ordering        = ['order', 'slug']
        verbose_name    = 'Taxonomy'
        indexes         = [
            models.Index(fields=['client', 'slug']),
            models.Index(fields=['client', 'is_active']),
        ]

    def __str__(self):
        scope = self.client.client_id if self.client else 'global'
        return f"{scope} / {self.slug}"


# ── 2. TaxonomyNode (tree node within a hierarchy) ───────────────────

class TaxonomyNode(models.Model):
    """
    A node in a taxonomy tree. Uses materialized path for efficient
    subtree queries without recursion. Also stores parent FK for
    tree traversal in admin.

    Materialized path example:
      root:         path = "001"
      child:        path = "001.002"
      grandchild:   path = "001.002.003"

    To get all descendants: filter(path__startswith="001.")
    To get depth:           len(path.split("."))
    """
    taxonomy    = models.ForeignKey(
        Taxonomy,
        on_delete=models.CASCADE,
        related_name='nodes'
    )
    parent      = models.ForeignKey(
        'self',
        null=True, blank=True,
        on_delete=models.CASCADE,
        related_name='children'
    )
    slug        = LowercaseCharField(max_length=100, db_index=True)
    name        = models.CharField(max_length=150)   # modeltranslation expands
    path        = models.CharField(
        max_length=500, db_index=True,
        help_text="Materialized path e.g. '001.002.003'. Auto-managed."
    )
    depth       = models.PositiveSmallIntegerField(default=0)
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)
    metadata    = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('taxonomy', 'slug')
        ordering        = ['taxonomy', 'path', 'order']
        verbose_name    = 'Taxonomy Node'
        indexes         = [
            models.Index(fields=['taxonomy', 'path']),
            models.Index(fields=['taxonomy', 'is_active', 'depth']),
        ]

    def __str__(self):
        return f"{self.taxonomy} / {self.path} / {self.slug}"

    def save(self, *args, **kwargs):
        # Auto-compute path and depth from parent
        if self.parent:
            self.path  = f"{self.parent.path}.{self.order:03d}"
            self.depth = self.parent.depth + 1
        else:
            self.path  = f"{self.order:03d}"
            self.depth = 0
        super().save(*args, **kwargs)

    def get_descendants_path_prefix(self):
        """Use for subtree filter: .filter(path__startswith=node.path + '.')"""
        return f"{self.path}."

    def get_ancestors(self):
        """Returns queryset of ancestors ordered root-first."""
        parts  = self.path.split('.')
        paths  = ['.'.join(parts[:i]) for i in range(1, len(parts))]
        return TaxonomyNode.objects.filter(
            taxonomy=self.taxonomy,
            path__in=paths
        ).order_by('depth')


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

class Item(models.Model):
    """
    Base item — domain-agnostic core fields only.
    Domain-specific fields live in sub-models (ProductItem, SongItem, etc.)
    attributes JSONB is the overflow for edge cases not covered by sub-models.
    """
    DOMAIN_CHOICES = [
        ('product',  'Physical Product'),
        ('digital',  'Digital Product'),
        ('song',     'Song / Audio'),
        ('document', 'Document'),
        ('service',  'Service'),
        ('generic',  'Generic'),
    ]

    client      = models.ForeignKey('mysite.Client', null=True, blank=True,
                                     on_delete=models.CASCADE, related_name='items')
    item_id     = LowercaseCharField(max_length=50, db_index=True)
    domain      = models.CharField(max_length=20, choices=DOMAIN_CHOICES,
                                   default='generic', db_index=True)

    # Core translatable fields
    name        = models.CharField(max_length=200)        # modeltranslation
    description = models.TextField(blank=True)            # modeltranslation

    status      = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default='draft', db_index=True)
    order       = models.PositiveIntegerField(default=0)

    # Primary image
    image_url   = models.URLField(max_length=500, blank=True)
    image_alt   = models.CharField(max_length=200, blank=True)

    # Overflow — for fields not covered by any sub-model
    # Keep this — it's your escape hatch and Beckn tags store here
    attributes  = models.JSONField(default=dict, blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('client', 'item_id')
        indexes = [
            models.Index(fields=['client', 'status', 'domain']),
        ]

    def get_domain_object(self):
        """Returns the domain sub-model instance if it exists, else None."""
        domain_map = {
            'product':  'product_detail',
            'song':     'song_detail',
            'document': 'document_detail',
            'service':  'service_detail',
        }
        accessor = domain_map.get(self.domain)
        if accessor:
            return getattr(self, accessor, None)
        return None

    def to_beckn_tags(self):
        """
        Merges sub-model fields + attributes JSONB into Beckn tags list.
        Called by to_beckn() in commerce models.
        """
        tags = dict(self.attributes)  # start with overflow

        domain_obj = self.get_domain_object()
        if domain_obj and hasattr(domain_obj, 'to_beckn_tags'):
            tags.update(domain_obj.to_beckn_tags())

        return [{"code": k, "value": str(v)} for k, v in tags.items()]


class ProductItem(models.Model):
    """
    Physical or digital product domain fields.
    Linked to Item via OneToOne — optional.
    """
    item         = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='product_detail'
    )
    # Pricing — proper decimal fields, not JSON strings
    price        = models.DecimalField(max_digits=12, decimal_places=2,
                                       null=True, blank=True)
    compare_price = models.DecimalField(max_digits=12, decimal_places=2,
                                        null=True, blank=True,
                                        help_text="Original price before discount")
    currency     = models.CharField(max_length=3, default='INR')

    # Inventory
    sku          = models.CharField(max_length=100, blank=True, db_index=True)
    barcode      = models.CharField(max_length=100, blank=True)
    track_inventory = models.BooleanField(default=False)
    stock_quantity  = models.IntegerField(default=0)

    # Physical dimensions
    weight_g     = models.PositiveIntegerField(null=True, blank=True,
                                               help_text="Weight in grams")
    length_mm    = models.PositiveIntegerField(null=True, blank=True)
    width_mm     = models.PositiveIntegerField(null=True, blank=True)
    height_mm    = models.PositiveIntegerField(null=True, blank=True)

    # Product-specific translated fields
    short_description = models.CharField(max_length=500, blank=True)  # modeltranslation
    care_instructions = models.TextField(blank=True)                   # modeltranslation

    # Domain-specific overflow
    attributes   = models.JSONField(default=dict, blank=True,
                                    help_text='e.g. {"material":"cotton","gender":"unisex"}')

    class Meta:
        verbose_name = 'Product Detail'

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
    item         = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='song_detail'
    )
    artist       = models.CharField(max_length=200, blank=True)  # modeltranslation
    album        = models.CharField(max_length=200, blank=True)  # modeltranslation
    duration_s   = models.PositiveIntegerField(null=True, blank=True,
                                               help_text="Duration in seconds")
    bpm          = models.PositiveSmallIntegerField(null=True, blank=True)
    musical_key  = models.CharField(max_length=10, blank=True)
    genre        = models.CharField(max_length=50, blank=True)
    audio_url    = models.URLField(max_length=500, blank=True)
    preview_url  = models.URLField(max_length=500, blank=True,
                                   help_text="30-second preview clip")
    isrc         = models.CharField(max_length=20, blank=True,
                                    help_text="International Standard Recording Code")
    attributes   = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Song Detail'

    def to_beckn_tags(self):
        return {
            'artist':     self.artist,
            'album':      self.album,
            'duration_s': str(self.duration_s or ''),
            'genre':      self.genre,
            **self.attributes,
        }


class DocumentItem(models.Model):
    """Document / file domain fields."""
    item         = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='document_detail'
    )
    file_url     = models.URLField(max_length=500, blank=True)
    format       = models.CharField(max_length=20, blank=True,
                                    help_text="PDF, DOCX, EPUB etc.")
    page_count   = models.PositiveIntegerField(null=True, blank=True)
    file_size_kb = models.PositiveIntegerField(null=True, blank=True)
    version      = models.CharField(max_length=20, blank=True)
    language     = models.CharField(max_length=10, blank=True,
                                    help_text="Primary language of document content")
    is_free      = models.BooleanField(default=True)
    price        = models.DecimalField(max_digits=10, decimal_places=2,
                                       null=True, blank=True)
    currency     = models.CharField(max_length=3, default='INR')
    attributes   = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Document Detail'

    def to_beckn_tags(self):
        return {
            'format':    self.format,
            'pages':     str(self.page_count or ''),
            'version':   self.version,
            **self.attributes,
        }


class ServiceItem(models.Model):
    """Service domain — appointments, consultations, repairs etc."""
    item            = models.OneToOneField(
        Item, on_delete=models.CASCADE, related_name='service_detail'
    )
    price           = models.DecimalField(max_digits=12, decimal_places=2,
                                          null=True, blank=True)
    currency        = models.CharField(max_length=3, default='INR')
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_location_based = models.BooleanField(default=False,
                                             help_text="Service requires physical presence")
    service_area    = models.CharField(max_length=200, blank=True,
                                       help_text="Cities or zones covered")
    # Beckn Fulfillment type hint
    fulfillment_type = models.CharField(
        max_length=20, blank=True,
        choices=[('in-person','In Person'),('remote','Remote'),('hybrid','Hybrid')]
    )
    attributes      = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Service Detail'

    def to_beckn_tags(self):
        return {
            'duration_minutes': str(self.duration_minutes or ''),
            'fulfillment_type': self.fulfillment_type,
            **self.attributes,
        }


# ── 4. ItemTaxonomyNode (M2M: Item ↔ TaxonomyNode) ──────────────────

class ItemTaxonomyNode(models.Model):
    """
    Maps an Item to one or more TaxonomyNodes across any hierarchy.
    This is the core of the faceted filter system.
    """
    item    = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='taxonomy_mappings'
    )
    node    = models.ForeignKey(
        TaxonomyNode,
        on_delete=models.CASCADE,
        related_name='item_mappings'
    )
    order   = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(
        default=False,
        help_text="Primary node for this taxonomy type (used for breadcrumbs)"
    )

    class Meta:
        unique_together = ('item', 'node')
        ordering        = ['item', 'node__taxonomy', 'order']
        indexes         = [
            models.Index(fields=['item', 'node']),
            models.Index(fields=['node', 'item']),
        ]

    def __str__(self):
        return f"{self.item} → {self.node}"


# ── 5. ItemImage ──────────────────────────────────────────────────────

class ItemImage(models.Model):
    """Additional images per item beyond the primary image_url."""
    item        = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='images'
    )
    image_url   = models.URLField(max_length=500)
    alt         = models.CharField(max_length=200, blank=True)
    order       = models.PositiveIntegerField(default=0)
    is_primary  = models.BooleanField(default=False)

    class Meta:
        ordering = ['item', 'order']

    def __str__(self):
        return f"{self.item} / image {self.order}"


# ── 6. ItemVariant (Phase 3 eCommerce ready) ─────────────────────────

class ItemVariant(models.Model):
    """
    Optional variants per item (size, colour, etc.).
    If no variants exist, the item itself is purchasable directly.
    Phase 3: CartItem FKs to ItemVariant (or Item if no variants).
    """
    item        = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='variants'
    )
    variant_id  = LowercaseCharField(max_length=50)
    name        = models.CharField(max_length=100)   # e.g. "Red / XL"
    sku         = models.CharField(max_length=100, blank=True, db_index=True)
    attributes  = models.JSONField(
        default=dict, blank=True,
        help_text='{"color": "red", "size": "XL"}'
    )
    # Pricing — override item-level price if set
    price       = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True
    )
    stock       = models.IntegerField(default=0)
    is_active   = models.BooleanField(default=True)

    class Meta:
        unique_together = ('item', 'variant_id')
        ordering        = ['item', 'variant_id']

    def __str__(self):
        return f"{self.item} / {self.variant_id}"

    def effective_price(self):
        """Variant price overrides item-level price."""
        if self.price is not None:
            return self.price
        return self.item.attributes.get('price')
    
"""
# ── 3. Item WITHOUT SUB ITEMS───────────────────────────────────────────────────────────

class OldItem(models.Model):
    
    #Generic reusable item. Represents a product, project, song,
    #document — anything. Domain-specific fields go in `attributes` JSONB.
    #Can be global (client=None) or client-specific.
    
    STATUS_CHOICES = [
        ('draft',     'Draft'),
        ('active',    'Active'),
        ('archived',  'Archived'),
    ]

    client      = models.ForeignKey(
        Client,
        null=True, blank=True,           # null = global item
        on_delete=models.CASCADE,
        related_name='items'
    )
    item_id     = LowercaseCharField(max_length=50, db_index=True)
    name        = models.CharField(max_length=200)   # modeltranslation expands
    description = models.TextField(blank=True)        # modeltranslation expands
    status      = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True
    )
    order       = models.PositiveIntegerField(default=0)

    # Primary image — additional images via ItemImage
    image_url   = models.URLField(max_length=500, blank=True)
    image_alt   = models.CharField(max_length=200, blank=True)

    # Flexible domain-specific attributes
    # Products:  {"price": 999, "currency": "INR", "sku": "ABC-001", "weight_g": 500}
    # Songs:     {"duration_s": 240, "bpm": 120, "key": "Am"}
    # Documents: {"pages": 42, "format": "PDF"}
    attributes  = models.JSONField(default=dict, blank=True)

    # Timestamps
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('client', 'item_id')
        ordering        = ['client', 'order', 'item_id']
        verbose_name    = 'Item'
        indexes         = [
            models.Index(fields=['client', 'status']),
            models.Index(fields=['client', 'status', 'order']),
            # JSONB index added via migration (see note below)
        ]

    def __str__(self):
        scope = self.client.client_id if self.client else 'global'
        return f"{scope} / {self.item_id}"

    @property
    def display_name(self):
        """Returns translated name (modeltranslation handles this automatically)."""
        return self.name

    # ── Phase 3 eCommerce hooks (non-breaking additions) ──────────────
    # ItemVariant, CartItem, OrderItem will FK to Item.
    # No changes to this model needed for Phase 3.

"""