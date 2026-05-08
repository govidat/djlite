# ============================================================
# CATALOGUE V2 — SETUP REFERENCE FILE
# Contains: translation.py, admin, signals, urls, migration,
#           implementation plan, sample data
# ============================================================
 

# ============================================================
# A. TRANSLATION REGISTRATIONS
# Add to mysite/translation.py
# ============================================================
"""
from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItem, Item, ProductItem, SongItem, DocumentItem, ServiceItem,
)

class TaxonomyTranslationOptions(TranslationOptions):
    fields = ('name',)

class TaxonomyNodeTranslationOptions(TranslationOptions):
    fields = ('name',)

class NodeAttributeTypeTranslationOptions(TranslationOptions):
    fields = ('name',)

class NodeAttributeValueTranslationOptions(TranslationOptions):
    fields = ('name',)

class GlobalItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description',)

class ItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description',)

class ProductItemTranslationOptions(TranslationOptions):
    fields = ('short_description', 'care_instructions',)

class SongItemTranslationOptions(TranslationOptions):
    fields = ('artist', 'album',)

translator.register(Taxonomy,            TaxonomyTranslationOptions)
translator.register(TaxonomyNode,        TaxonomyNodeTranslationOptions)
translator.register(NodeAttributeType,   NodeAttributeTypeTranslationOptions)
translator.register(NodeAttributeValue,  NodeAttributeValueTranslationOptions)
translator.register(GlobalItem,          GlobalItemTranslationOptions)
translator.register(Item,                ItemTranslationOptions)
translator.register(ProductItem,         ProductItemTranslationOptions)
translator.register(SongItem,            SongItemTranslationOptions)
"""


# ============================================================
# B. ADMIN
# mysite/admin/catalogue.py
# ============================================================
"""
from django.contrib import admin
from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItem, GlobalItemTaxonomyNode, GlobalItemAttributeValue,
    Item, ItemTaxonomyNode, ItemAttributeValue, ItemImage, ItemVariant,
    ProductItem, SongItem, DocumentItem, ServiceItem,
)


# ── Global Item Admin ─────────────────────────────────────────────────

class GlobalItemTaxonomyNodeInline(admin.TabularInline):
    model       = GlobalItemTaxonomyNode
    extra       = 1
    fields      = ('node', 'is_primary')
    autocomplete_fields = ['node']


class GlobalItemAttributeValueInline(admin.TabularInline):
    model       = GlobalItemAttributeValue
    extra       = 1
    fields      = ('attribute_type', 'predefined_value', 'value_text', 'value_number')
    autocomplete_fields = ['attribute_type', 'predefined_value']


@admin.register(GlobalItem)
class GlobalItemAdmin(admin.ModelAdmin):
    list_display    = ('global_item_id', 'domain', 'name', 'brand', 'gtin',
                       'gpc_brick_code', 'status')
    list_filter     = ('domain', 'status')
    search_fields   = ('global_item_id', 'name', 'brand', 'gtin', 'gpc_brick_code')
    readonly_fields = ('created_at', 'updated_at')
    inlines         = [GlobalItemTaxonomyNodeInline, GlobalItemAttributeValueInline]
    fieldsets = (
        ('GS1 Identification', {
            'fields': ('gtin', 'gpc_brick_code', 'global_item_id', 'domain', 'status'),
            'description': 'GTIN: 8/12/13/14 digit GS1 identifier. '
                           'GPC Brick Code: 8-digit GS1 GPC code.'
        }),
        ('Brand / Manufacturer', {
            'fields': ('brand', 'manufacturer', 'country_of_origin'),
        }),
        ('Content', {
            'fields': ('name', 'description', 'image_url', 'image_alt'),
        }),
        ('Overflow Attributes', {
            'fields': ('attributes',),
            'classes': ('collapse',),
            'description': 'JSON overflow for attributes not in typed sub-models'
        }),
        ('Audit', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


# ── Taxonomy Admin ────────────────────────────────────────────────────

class NodeAttributeTypeInline(admin.TabularInline):
    model  = NodeAttributeType
    extra  = 1
    fields = ('slug', 'name', 'field_type', 'is_filterable', 'is_required', 'order', 'gpc_attribute_code')
    show_change_link = True


class NodeAttributeValueInline(admin.TabularInline):
    model  = NodeAttributeValue
    extra  = 1
    fields = ('slug', 'name', 'client', 'order', 'gpc_value_code')


@admin.register(TaxonomyNode)
class TaxonomyNodeAdmin(admin.ModelAdmin):
    list_display    = ('slug', 'taxonomy', 'client', 'parent', 'path',
                       'depth', 'gpc_code', 'is_active')
    list_filter     = ('taxonomy', 'client', 'is_active', 'depth')
    search_fields   = ('slug', 'name', 'path', 'gpc_code')
    readonly_fields = ('path', 'depth')
    autocomplete_fields = ['parent', 'global_node']
    inlines         = [NodeAttributeTypeInline]


@admin.register(Taxonomy)
class TaxonomyAdmin(admin.ModelAdmin):
    list_display  = ('slug', 'client', 'taxonomy_type', 'name', 'order', 'is_active')
    list_filter   = ('client', 'taxonomy_type', 'is_active')
    search_fields = ('slug', 'name')


# ── Client Item Admin ─────────────────────────────────────────────────

class ItemTaxonomyNodeInline(admin.TabularInline):
    model               = ItemTaxonomyNode
    extra               = 1
    fields              = ('node', 'is_primary', 'order')
    autocomplete_fields = ['node']


class ItemAttributeValueInline(admin.TabularInline):
    model               = ItemAttributeValue
    extra               = 1
    fields              = ('attribute_type', 'predefined_value', 'value_text', 'value_number')
    autocomplete_fields = ['attribute_type', 'predefined_value']


class ItemImageInline(admin.TabularInline):
    model  = ItemImage
    extra  = 1
    fields = ('image_url', 'alt', 'order', 'is_primary')


class ItemVariantInline(admin.TabularInline):
    model  = ItemVariant
    extra  = 1
    fields = ('variant_id', 'name', 'sku', 'gtin', 'price', 'stock', 'is_active', 'attributes')


class ProductItemInline(admin.StackedInline):
    model  = ProductItem
    extra  = 0
    fields = ('price', 'compare_price', 'currency', 'sku', 'barcode',
              'weight_g', 'stock_quantity', 'short_description',
              'care_instructions', 'attributes')


class SongItemInline(admin.StackedInline):
    model  = SongItem
    extra  = 0
    fields = ('artist', 'album', 'duration_s', 'bpm', 'genre',
              'audio_url', 'preview_url', 'isrc', 'attributes')


class DocumentItemInline(admin.StackedInline):
    model  = DocumentItem
    extra  = 0
    fields = ('file_url', 'format', 'page_count', 'file_size_kb',
              'version', 'language', 'is_free', 'price', 'currency', 'attributes')


class ServiceItemInline(admin.StackedInline):
    model  = ServiceItem
    extra  = 0
    fields = ('price', 'currency', 'duration_minutes', 'is_location_based',
              'service_area', 'fulfillment_type', 'attributes')


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display    = ('item_id', 'client', 'domain', 'resolved_name_display',
                       'status', 'global_item', 'order')
    list_filter     = ('client', 'domain', 'status')
    search_fields   = ('item_id', 'name', 'gtin', 'product_detail__sku')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ['global_item']
    inlines         = [
        ItemTaxonomyNodeInline,
        ItemAttributeValueInline,
        ItemImageInline,
        ItemVariantInline,
        ProductItemInline,
        SongItemInline,
        DocumentItemInline,
        ServiceItemInline,
    ]
    fieldsets = (
        ('Scope & Identity', {
            'fields': ('client', 'item_id', 'domain', 'status', 'order'),
        }),
        ('Global Reference (optional)', {
            'fields': ('global_item', 'gtin', 'gpc_brick_code'),
            'description': 'Link to a GlobalItem to inherit its data. '
                           'Fields below override the global values.'
        }),
        ('Content (overrides GlobalItem if set)', {
            'fields': ('name', 'description', 'brand', 'image_url', 'image_alt'),
        }),
        ('Overflow Attributes', {
            'fields': ('attributes',),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def resolved_name_display(self, obj):
        return obj.resolved_name()
    resolved_name_display.short_description = 'Resolved Name'
"""


# ============================================================
# C. URLS — add to mydj/urls.py
# ============================================================
"""
from mysite.views.catalogue import (
    catalogue_page, catalogue_filter, item_detail
)

# Add BEFORE <str:client_id>/<str:page>/ catch-all:
path('<str:client_id>/catalogue/',
     catalogue_page, name='catalogue_page'),
path('<str:client_id>/catalogue/filter/',
     catalogue_filter, name='catalogue_filter'),
path('<str:client_id>/catalogue/<str:item_id>/',
     item_detail, name='item_detail'),
"""


# ============================================================
# D. SIGNALS UPDATE — add to mysite/signals.py register_signals()
# ============================================================
"""
def register_signals():
    # ... existing CMS models ...

    from mysite.models.catalogue import (
        Taxonomy, TaxonomyNode,
        GlobalItem, GlobalItemAttributeValue, GlobalItemTaxonomyNode,
        Item, ItemTaxonomyNode, ItemAttributeValue,
        NodeAttributeType, NodeAttributeValue,
    )

    # ── Taxonomy tree cache invalidation ──────────────────────────
    TAXONOMY_MODELS = [Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue]
    for model in TAXONOMY_MODELS:
        post_save.connect(invalidate_taxonomy_cache, sender=model)
        post_delete.connect(invalidate_taxonomy_cache, sender=model)

    # ── Item and GlobalItem: no clientstatic cache to invalidate ──
    # Items are queried per-request. No bulk caching needed.
    # GlobalItem changes DO affect client items that derive from them —
    # but since we query live, no cache invalidation needed here.
    # If you add item-level caching in Phase 3, add signals here.
"""


# ============================================================
# E. MIGRATION NOTES
# Add to the catalogue migration file (generated by makemigrations)
# ============================================================
"""
def add_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    indexes = [
        # Item base table
        'CREATE INDEX IF NOT EXISTS item_client_domain_status_idx '
        'ON mysite_item (client_id, domain, status)',

        'CREATE INDEX IF NOT EXISTS item_client_status_order_idx '
        'ON mysite_item (client_id, status, "order")',

        'CREATE INDEX IF NOT EXISTS item_global_item_idx '
        'ON mysite_item (global_item_id, client_id)',

        'CREATE INDEX IF NOT EXISTS item_gtin_idx '
        'ON mysite_item (gtin) WHERE gtin != \'\'',

        # Item JSONB
        'CREATE INDEX IF NOT EXISTS item_attributes_gin_idx '
        'ON mysite_item USING GIN (attributes jsonb_path_ops)',

        # GlobalItem
        'CREATE INDEX IF NOT EXISTS globalitem_gtin_idx '
        'ON mysite_globalitem (gtin) WHERE gtin != \'\'',

        'CREATE INDEX IF NOT EXISTS globalitem_gpc_idx '
        'ON mysite_globalitem (gpc_brick_code) WHERE gpc_brick_code != \'\'',

        'CREATE INDEX IF NOT EXISTS globalitem_attributes_gin_idx '
        'ON mysite_globalitem USING GIN (attributes jsonb_path_ops)',

        # TaxonomyNode path — CRITICAL for subtree queries
        'CREATE INDEX IF NOT EXISTS taxonomynode_path_idx '
        'ON mysite_taxonomynode USING BTREE (taxonomy_id, path text_pattern_ops)',

        'CREATE INDEX IF NOT EXISTS taxonomynode_gpc_idx '
        'ON mysite_taxonomynode (gpc_code) WHERE gpc_code != \'\'',

        # ProductItem
        'CREATE INDEX IF NOT EXISTS productitem_sku_idx '
        'ON mysite_productitem (sku) WHERE sku != \'\'',

        'CREATE INDEX IF NOT EXISTS productitem_price_idx '
        'ON mysite_productitem (price) WHERE price IS NOT NULL',

        'CREATE INDEX IF NOT EXISTS productitem_attributes_gin_idx '
        'ON mysite_productitem USING GIN (attributes jsonb_path_ops)',

        # ItemAttributeValue — critical for faceted filter queries
        'CREATE INDEX IF NOT EXISTS itemattributevalue_lookup_idx '
        'ON mysite_itemattributevalue (attribute_type_id, predefined_value_id)',

        'CREATE INDEX IF NOT EXISTS globalitemattributevalue_lookup_idx '
        'ON mysite_globalitemattributevalue (attribute_type_id, predefined_value_id)',
    ]

    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS item_client_domain_status_idx',
        'DROP INDEX IF EXISTS item_client_status_order_idx',
        'DROP INDEX IF EXISTS item_global_item_idx',
        'DROP INDEX IF EXISTS item_gtin_idx',
        'DROP INDEX IF EXISTS item_attributes_gin_idx',
        'DROP INDEX IF EXISTS globalitem_gtin_idx',
        'DROP INDEX IF EXISTS globalitem_gpc_idx',
        'DROP INDEX IF EXISTS globalitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS taxonomynode_path_idx',
        'DROP INDEX IF EXISTS taxonomynode_gpc_idx',
        'DROP INDEX IF EXISTS productitem_sku_idx',
        'DROP INDEX IF EXISTS productitem_price_idx',
        'DROP INDEX IF EXISTS productitem_attributes_gin_idx',
        'DROP INDEX IF EXISTS itemattributevalue_lookup_idx',
        'DROP INDEX IF EXISTS globalitemattributevalue_lookup_idx',
    ]
    for sql in drops:
        schema_editor.execute(sql)
"""


# ============================================================
# F. SAMPLE DATA — Auto Components use case
# python manage.py load_sample_autoparts bahushira
# ============================================================
"""
# mysite/management/commands/load_sample_autoparts.py

from django.core.management.base import BaseCommand
from mysite.models import Client
from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItem, GlobalItemTaxonomyNode, GlobalItemAttributeValue,
    Item, ItemTaxonomyNode, ItemAttributeValue, ProductItem,
)


class Command(BaseCommand):
    help = 'Load sample auto parts catalogue data'

    def add_arguments(self, parser):
        parser.add_argument('client_id', type=str)

    def handle(self, *args, **options):
        client = Client.objects.get(client_id=options['client_id'])

        # ── Global GPC Taxonomy (Superuser managed) ──────────────────
        gpc_tax, _ = Taxonomy.objects.get_or_create(
            client=None, slug='gpc',
            defaults={
                'name':          'GS1 GPC Classification',
                'taxonomy_type': 'gpc',
                'order':         1,
            }
        )

        # GPC Hierarchy for Auto Parts:
        # Segment: Automotive Parts & Accessories (code: 47)
        seg, _ = TaxonomyNode.objects.get_or_create(
            taxonomy=gpc_tax, client=None, slug='automotive',
            defaults={
                'name':     'Automotive Parts & Accessories',
                'order':    1, 'path': '001', 'depth': 0,
                'gpc_code': '47',
            }
        )
        # Family: Engine Parts
        fam, _ = TaxonomyNode.objects.get_or_create(
            taxonomy=gpc_tax, client=None, slug='engine-parts',
            defaults={
                'name':     'Engine Parts',
                'parent':   seg, 'order': 1,
                'path':     '001.001', 'depth': 1,
                'gpc_code': '4701',
            }
        )
        # Class: Ignition System
        cls, _ = TaxonomyNode.objects.get_or_create(
            taxonomy=gpc_tax, client=None, slug='ignition-system',
            defaults={
                'name':     'Ignition System',
                'parent':   fam, 'order': 1,
                'path':     '001.001.001', 'depth': 2,
                'gpc_code': '470101',
            }
        )
        # Brick: Spark Plugs
        brick, _ = TaxonomyNode.objects.get_or_create(
            taxonomy=gpc_tax, client=None, slug='spark-plugs',
            defaults={
                'name':     'Spark Plugs',
                'parent':   cls, 'order': 1,
                'path':     '001.001.001.001', 'depth': 3,
                'gpc_code': '47010101',
            }
        )

        # ── GPC Brick Attributes for Spark Plugs ─────────────────────
        thread_attr, _ = NodeAttributeType.objects.get_or_create(
            node=brick, client=None, slug='thread-size',
            defaults={
                'name':           'Thread Size',
                'field_type':     'select',
                'is_filterable':  True,
                'order':          1,
                'gpc_attribute_code': 'AT001',
            }
        )
        for val_slug, val_name in [('m14', 'M14'), ('m18', 'M18'), ('m10', 'M10')]:
            NodeAttributeValue.objects.get_or_create(
                attribute_type=thread_attr, client=None, slug=val_slug,
                defaults={'name': val_name, 'order': 1}
            )

        gap_attr, _ = NodeAttributeType.objects.get_or_create(
            node=brick, client=None, slug='electrode-gap',
            defaults={
                'name':          'Electrode Gap (mm)',
                'field_type':    'number',
                'is_filterable': True,
                'order':         2,
            }
        )

        # ── Global Items (brand-level, superuser managed) ─────────────
        bosch_plug, _ = GlobalItem.objects.get_or_create(
            global_item_id='bosch-fr7dc',
            defaults={
                'domain':         'product',
                'status':         'active',
                'name':           'Bosch FR7DC Spark Plug',
                'description':    'OE-quality spark plug for petrol engines.',
                'brand':          'Bosch',
                'manufacturer':   'Robert Bosch GmbH',
                'country_of_origin': 'DE',
                'gtin':           '4047024119328',
                'gpc_brick_code': '47010101',
                'image_url':      'https://picsum.photos/seed/sparkplug/400/400',
            }
        )
        GlobalItemTaxonomyNode.objects.get_or_create(
            global_item=bosch_plug, node=brick,
            defaults={'is_primary': True}
        )

        # Global attribute values for this item
        m14_val = NodeAttributeValue.objects.get(
            attribute_type=thread_attr, slug='m14', client=None
        )
        GlobalItemAttributeValue.objects.get_or_create(
            global_item=bosch_plug, attribute_type=thread_attr,
            defaults={'predefined_value': m14_val}
        )
        GlobalItemAttributeValue.objects.get_or_create(
            global_item=bosch_plug, attribute_type=gap_attr,
            defaults={'value_number': 0.7}
        )

        # ── Client Item (derives from global) ─────────────────────────
        # This distributor client references the Bosch global item
        # and adds their own pricing and SKU
        client_item, created = Item.objects.get_or_create(
            client=client, item_id='bosch-fr7dc',
            defaults={
                'global_item':  bosch_plug,
                'domain':       'product',
                'status':       'active',
                'order':        1,
                # name/description/brand intentionally blank — fall back to GlobalItem
                'gtin':         '',  # inherit from global
                'gpc_brick_code': '47010101',
            }
        )

        # Client-level product detail (pricing, their SKU)
        from mysite.models.catalogue import ProductItem
        ProductItem.objects.get_or_create(
            item=client_item,
            defaults={
                'price':          149.00,
                'currency':       'INR',
                'sku':            'BSH-FR7DC-001',  # distributor's own SKU
                'stock_quantity': 500,
                'weight_g':       50,
            }
        )

        # Map to the global GPC node
        ItemTaxonomyNode.objects.get_or_create(
            item=client_item, node=brick,
            defaults={'is_primary': True}
        )

        # Client can override thread size attribute if needed
        # (in this case they don't — global value is inherited)

        self.stdout.write(self.style.SUCCESS(
            f'Loaded auto parts sample for {client.client_id}. '
            f'GlobalItem: {bosch_plug.global_item_id}, '
            f'ClientItem: {client_item.item_id} '
            f'({"created" if created else "updated"})'
        ))
"""


# ============================================================
# G. IMPLEMENTATION PLAN — Sprint by Sprint
# ============================================================
"""
Sprint 2.1 — Models and Migration
  [x] Replace models_catalogue.py with the revised version
  [x] Run makemigrations — verify clean output
  [x] Add add_postgres_indexes / remove_postgres_indexes to migration file
  [x] Run migrate
  [x] python manage.py check — 0 issues
  [ ] Verify table names in dbshell

Sprint 2.2 — Translations
  [x] Add all TranslationOptions to translation.py
  [x] Run sync_translation_fields
  [ ] Verify _en / _hi columns exist in DB

Sprint 2.3 — Admin
  [x] Create mysite/admin/catalogue.py with full admin classes
  [x] Register in mysite/admin/__init__.py
  [ ] Test: Create a GlobalItem in admin
  [ ] Test: Create a client Item linked to GlobalItem — confirm name fallback
  [ ] Test: Create TaxonomyNode with NodeAttributeType and NodeAttributeValue

Sprint 2.4 — Query Layer
  [x] Replace catalogue_queries.py with v2 version
  [ ] Unit test: global item override by client item of same item_id
  [ ] Unit test: attribute inheritance (global → item)
  [ ] Unit test: subtree filter includes descendants
  [ ] Unit test: AND logic across taxonomies

Sprint 2.5 — Views and URLs
  [x] Update views/catalogue.py to use build_catalogue_payload (v2)
  [x] Wire URLs (same as before)
  [x] Add django-htmx to requirements + MIDDLEWARE

Sprint 2.6 — Templates
  [x] Update filter_sidebar.html to show NodeAttributeType filters
  [x] Add attribute value checkboxes to sidebar
  [x] Update item_card.html to show resolved_name (not raw name)
  [ ] Test: language switch correctly resolves translated name

Sprint 2.7 — Signals
  [x] Add NodeAttributeType, NodeAttributeValue to taxonomy signal models
  [ ] Test: edit a TaxonomyNode → taxonomy tree cache cleared

Sprint 2.8 — Sample Data and E2E Test
  [ ] Run: python manage.py load_sample_autoparts bahushira
  [ ] Visit /{client_id}/catalogue/
  [ ] Filter by Spark Plugs node → only spark plugs appear
  [ ] Filter by Thread Size M14 → only M14 plugs appear
  [ ] Verify item shows Bosch name (from GlobalItem, not overridden)
  [ ] Verify item shows client SKU (from ProductItem)
  [ ] Switch language → translated node names appear

Sprint 2.9 — Authorization
  [ ] Superuser only: GlobalItem, Taxonomy (client=None), TaxonomyNode (client=None)
  [ ] ClientAdmin: Item (for their client), TaxonomyNode (for their client)
  [ ] In admin: use get_queryset() to filter by request.user's client
  [ ] In GlobalItem admin: restrict to superuser (is_superuser check)
  [ ] In Item admin: only show global_item dropdown to select from
         (ClientAdmin cannot create GlobalItems)

Sprint 2.10 — Production Hardening
  [ ] Deploy to PaaS with PostgreSQL
  [ ] Verify all GIN and path indexes via EXPLAIN ANALYZE
  [ ] Load test: 20k items + 3-level taxonomy, 50 concurrent filter requests
  [ ] Verify taxonomy tree cache hits (Redis MONITOR or cache.get() checks)
"""


# ============================================================
# H. DELTA ADDITIONS TO .MD FILES (summary)
# ============================================================
"""
mission.md additions:
  - Two-tier item catalogue: GlobalItem (superuser, GS1-aligned) + Item (client-derived)
  - GS1 GPC 4-level hierarchy: Segment → Family → Class → Brick
  - Attribute inheritance: TaxonomyNode attrs inherited by items, overridable at item level
  - Client can reference and derive from global items and global taxonomy nodes

tech-stack.md additions:
  New models: GlobalItem, GlobalItemTaxonomyNode, GlobalItemAttributeValue,
              NodeAttributeType, NodeAttributeValue, ItemAttributeValue
  GS1 fields: gtin (GTIN-8/12/13/14), gpc_brick_code (8-digit)
  Derivation pattern: Item.global_item FK, resolved_name()/resolved_attributes() methods
  Attribute inheritance: NodeAttributeType → NodeAttributeValue → GlobalItemAttributeValue
                         → ItemAttributeValue (deepest wins)

roadmap.md:
  Sprint 2.9 (Authorization) added:
    Superuser-only GlobalItem admin
    ClientAdmin can select from GlobalItems but not create them
    TaxonomyNode (client=None) admin restricted to superuser
"""


