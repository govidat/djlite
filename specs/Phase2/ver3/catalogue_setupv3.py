# ============================================================
# A. CLIENT-CUSTOMISABLE TEMPLATES — HOW IT WORKS
# ============================================================
"""
The _resolve_client_templates() function in catalogue_queries.py
returns a dict like:

  template_info = {
    'filter_sidebar': 'catalogue/partials/filter_sidebar.html',  # default
    'item_card':      'catalogue/bahushira/item_card.html',       # client override
    'items_list':     'catalogue/partials/items_list.html',       # default
    'pagination':     'catalogue/partials/pagination.html',       # default
  }

This dict is in catalogue.template_info in your templates.

Directory structure for client overrides:
  templates/
    catalogue/
      partials/                          ← default templates (all clients)
        filter_sidebar.html
        filter_node.html
        filter_sidebar_mobile.html
        items_list.html
        item_card.html
        pagination.html
      bahushira/                         ← client-specific overrides
        item_card.html                   ← custom card for this client
        filter_sidebar.html              ← custom sidebar (e.g. fewer sections)
      another_client/
        item_card.html

Usage in page_catalogue_html.html — replace hardcoded includes with:
  {% include catalogue.template_info.filter_sidebar %}
  {% include catalogue.template_info.items_list %}

Usage in items_list.html — replace hardcoded item_card include with:
  {% include catalogue.template_info.item_card with item=item %}

This gives each client a fully customised catalogue UI without
code changes — just drop template files in their named folder.
"""


# ============================================================
# B. DOMAIN-SPECIFIC FILTER SIDEBAR SECTIONS
# ============================================================
"""
Add these sections to filter_sidebar.html after the taxonomy filters.
They are conditionally shown based on catalogue.domain_filters content.

<!-- Price range — shown only if products exist -->
{% if catalogue.price_stats.max > 0 %}
<div class="collapse collapse-arrow border border-base-300 rounded-lg">
  <input type="checkbox" checked />
  <div class="collapse-title font-semibold text-sm">Price Range</div>
  <div class="collapse-content pt-3">
    <div class="flex gap-2 items-center mb-2">
      <input type="number" name="price_min" id="price-min"
             value="{{ catalogue.filters.price_min|default:catalogue.price_stats.min|floatformat:0 }}"
             placeholder="{{ catalogue.price_stats.min|floatformat:0 }}"
             class="input input-sm input-bordered w-24">
      <span class="text-base-content/40 text-sm">to</span>
      <input type="number" name="price_max" id="price-max"
             value="{{ catalogue.filters.price_max|default:catalogue.price_stats.max|floatformat:0 }}"
             placeholder="{{ catalogue.price_stats.max|floatformat:0 }}"
             class="input input-sm input-bordered w-24">
    </div>
    <p class="text-xs text-base-content/40 mb-2">
      ₹{{ catalogue.price_stats.min|floatformat:0 }} —
      ₹{{ catalogue.price_stats.max|floatformat:0 }}
    </p>
    <button type="button"
            class="btn btn-xs btn-outline w-full"
            hx-get="{% url 'catalogue_filter' client_id=client.client_id %}"
            hx-target="#items-container"
            hx-swap="innerHTML"
            hx-include="#filter-form"
            hx-trigger="click">
      Apply
    </button>
  </div>
</div>
{% endif %}

<!-- In Stock — shown only if products exist -->
{% if catalogue.price_stats.max > 0 %}
<label class="flex items-center gap-3 cursor-pointer py-2">
  <input type="checkbox" name="in_stock" value="1"
         class="checkbox checkbox-sm checkbox-primary"
         {% if catalogue.filters.in_stock %}checked{% endif %}
         hx-get="{% url 'catalogue_filter' client_id=client.client_id %}"
         hx-target="#items-container"
         hx-swap="innerHTML"
         hx-include="#filter-form"
         hx-trigger="change">
  <span class="text-sm font-medium">In Stock Only</span>
</label>
{% endif %}

<!-- Genre — shown only if songs exist -->
{% if catalogue.domain_filters.genres %}
<div class="collapse collapse-arrow border border-base-300 rounded-lg">
  <input type="checkbox" checked />
  <div class="collapse-title font-semibold text-sm">Genre</div>
  <div class="collapse-content pt-2">
    <ul class="space-y-1">
      {% for genre in catalogue.domain_filters.genres %}
      <li>
        <label class="flex items-center gap-2 cursor-pointer py-0.5">
          <input type="checkbox" name="genre" value="{{ genre }}"
                 class="checkbox checkbox-xs checkbox-primary"
                 {% if genre == catalogue.filters.genre %}checked{% endif %}
                 hx-get="{% url 'catalogue_filter' client_id=client.client_id %}"
                 hx-target="#items-container"
                 hx-swap="innerHTML"
                 hx-include="#filter-form"
                 hx-trigger="change">
          <span class="text-sm">{{ genre }}</span>
        </label>
      </li>
      {% endfor %}
    </ul>
  </div>
</div>
{% endif %}

<!-- Format — shown only if documents exist -->
{% if catalogue.domain_filters.formats %}
<div class="collapse collapse-arrow border border-base-300 rounded-lg">
  <input type="checkbox" checked />
  <div class="collapse-title font-semibold text-sm">Format</div>
  <div class="collapse-content pt-2">
    <ul class="space-y-1">
      {% for fmt in catalogue.domain_filters.formats %}
      <li>
        <label class="flex items-center gap-2 cursor-pointer py-0.5">
          <input type="checkbox" name="format" value="{{ fmt }}"
                 class="checkbox checkbox-xs checkbox-primary"
                 {% if fmt == catalogue.filters.format %}checked{% endif %}
                 hx-get="{% url 'catalogue_filter' client_id=client.client_id %}"
                 hx-target="#items-container"
                 hx-swap="innerHTML"
                 hx-include="#filter-form"
                 hx-trigger="change">
          <span class="text-sm">{{ fmt }}</span>
        </label>
      </li>
      {% endfor %}
    </ul>
  </div>
</div>
{% endif %}

<!-- Free documents toggle -->
{% if catalogue.domain_filters.has_free_documents %}
<label class="flex items-center gap-3 cursor-pointer py-2">
  <input type="checkbox" name="is_free" value="1"
         class="checkbox checkbox-sm checkbox-primary"
         hx-get="{% url 'catalogue_filter' client_id=client.client_id %}"
         hx-target="#items-container"
         hx-swap="innerHTML"
         hx-include="#filter-form"
         hx-trigger="change">
  <span class="text-sm font-medium">Free Documents Only</span>
</label>
{% endif %}
"""


# ============================================================
# C. N+1 ANALYSIS FROM YOUR SQL LOG
# ============================================================
"""
BEFORE (your current code) — N+1 queries:
  SELECT FROM mysite_globalitemattributevalue WHERE global_item_id = 1  [5 items]
  SELECT FROM mysite_nodeattributetype WHERE id = 1    [16 similar, 4 duplicated]
  SELECT FROM mysite_nodeattributevalue WHERE id = 1   [11 similar, 4 duplicated]
  ... repeats for every item on the page

  Root cause: serialize_item() calls item.global_item.attribute_values.all()
  which triggers a new query per item. Then each AttributeValue's
  attribute_type and predefined_value are lazy-loaded individually.

AFTER (optimised code) — bulk prefetch:
  get_item_queryset() adds:
    Prefetch(
        'global_item__attribute_values',
        queryset=GlobalItemAttributeValue.objects.select_related(
            'attribute_type', 'predefined_value'   ← joins in one query
        ),
        to_attr='prefetched_global_attr_values'
    )

  serialize_item() uses:
    getattr(item.global_item, 'prefetched_global_attr_values', None)

  Result: 1 query for all global attribute values across all items on page.
  NodeAttributeType and NodeAttributeValue loaded via select_related —
  no per-row lookups.

ESTIMATED QUERY REDUCTION:
  5 items × 4 attributes × 2 lookups = 40 queries → 1 prefetch query
  (The 16+11 similar queries in your log disappear entirely)

ItemMedia removal from catalogue list:
  Your log shows no ItemMedia query for the list — you already have
  is_primary=True filter. Keeping only primary image is correct.
  Full media fetch stays in item_detail only.
"""


# ============================================================
# D. SAMPLE ItemMedia DATA — Bosch FR7DC Spark Plug
# ============================================================
"""
Create these records in Django Admin:
Admin → Item Media → Add

For item: bahushira / bosch-fr7dc

Record 1 — Primary product image
  Item:       bosch-fr7dc (bahushira)
  Media Type: image
  Media URL:  https://picsum.photos/seed/bosch-fr7dc-main/800/800
  Alt:        Bosch FR7DC Spark Plug — Main View
  Order:      1
  Is Primary: ✓

Record 2 — Side view
  Item:       bosch-fr7dc
  Media Type: image
  Media URL:  https://picsum.photos/seed/bosch-fr7dc-side/800/800
  Alt:        Bosch FR7DC Spark Plug — Side View
  Order:      2
  Is Primary: ☐

Record 3 — Installation diagram
  Item:       bosch-fr7dc
  Media Type: image
  Media URL:  https://picsum.photos/seed/bosch-fr7dc-diagram/800/600
  Alt:        Bosch FR7DC — Thread and Gap Diagram
  Order:      3
  Is Primary: ☐

Record 4 — Specification sheet (image of spec table)
  Item:       bosch-fr7dc
  Media Type: image
  Media URL:  https://picsum.photos/seed/bosch-fr7dc-specs/800/600
  Alt:        Bosch FR7DC — Technical Specifications
  Order:      4
  Is Primary: ☐

Record 5 — Installation guide audio (use a real MP3 URL for actual testing)
  Item:       bosch-fr7dc
  Media Type: audio
  Media URL:  https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3
  Alt:        Bosch FR7DC — Installation Guide (Audio)
  Order:      1
  Is Primary: ☐

Record 6 — Engine sound before/after (demo audio)
  Item:       bosch-fr7dc
  Media Type: audio
  Media URL:  https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3
  Alt:        Engine Performance — Before and After Replacement
  Order:      2
  Is Primary: ☐

Record 7 — Installation video (use a real MP4 URL for actual testing)
  Item:       bosch-fr7dc
  Media Type: video
  Media URL:  https://www.w3schools.com/html/mov_bbb.mp4
  Alt:        Bosch FR7DC — Step-by-Step Installation Video
  Order:      1
  Is Primary: ☐

Record 8 — Product overview video
  Item:       bosch-fr7dc
  Media Type: video
  Media URL:  https://www.w3schools.com/html/movie.mp4
  Alt:        Bosch FR7DC — Product Overview
  Order:      2
  Is Primary: ☐

Notes on URLs:
  - picsum.photos URLs generate placeholder images — fine for dev testing.
    Use seed parameter to get consistent images per item.
  - soundhelix.com provides free MP3s for testing — real audio plays.
  - w3schools.com MP4s are short clips for testing — real video plays.
  - In production replace with your actual media storage URLs
    (S3, Cloudflare R2, or similar).

Management command to load this data:
  python manage.py load_sample_media bahushira bosch-fr7dc
"""


# ============================================================
# E. MANAGEMENT COMMAND FOR SAMPLE MEDIA
# ============================================================
"""
# mysite/management/commands/load_sample_media.py

from django.core.management.base import BaseCommand
from mysite.models import Client
from mysite.models.catalogue import Item, ItemMedia


class Command(BaseCommand):
    help = 'Load sample ItemMedia records for testing'

    def add_arguments(self, parser):
        parser.add_argument('client_id', type=str)
        parser.add_argument('item_id', type=str)

    def handle(self, *args, **options):
        client = Client.objects.get(client_id=options['client_id'])
        item   = Item.objects.get(client=client, item_id=options['item_id'])

        # Clear existing
        ItemMedia.objects.filter(item=item).delete()

        media_records = [
            # Images
            {
                'media_type': 'image',
                'media_url':  'https://picsum.photos/seed/bosch-fr7dc-main/800/800',
                'alt':        'Bosch FR7DC Spark Plug — Main View',
                'order':      1,
                'is_primary': True,
            },
            {
                'media_type': 'image',
                'media_url':  'https://picsum.photos/seed/bosch-fr7dc-side/800/800',
                'alt':        'Bosch FR7DC Spark Plug — Side View',
                'order':      2,
                'is_primary': False,
            },
            {
                'media_type': 'image',
                'media_url':  'https://picsum.photos/seed/bosch-fr7dc-diagram/800/600',
                'alt':        'Bosch FR7DC — Thread and Gap Diagram',
                'order':      3,
                'is_primary': False,
            },
            {
                'media_type': 'image',
                'media_url':  'https://picsum.photos/seed/bosch-fr7dc-specs/800/600',
                'alt':        'Bosch FR7DC — Technical Specifications',
                'order':      4,
                'is_primary': False,
            },
            # Audio
            {
                'media_type': 'audio',
                'media_url':  'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3',
                'alt':        'Bosch FR7DC — Installation Guide (Audio)',
                'order':      1,
                'is_primary': False,
            },
            {
                'media_type': 'audio',
                'media_url':  'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-2.mp3',
                'alt':        'Engine Performance — Before and After Replacement',
                'order':      2,
                'is_primary': False,
            },
            # Video
            {
                'media_type': 'video',
                'media_url':  'https://www.w3schools.com/html/mov_bbb.mp4',
                'alt':        'Bosch FR7DC — Step-by-Step Installation Video',
                'order':      1,
                'is_primary': False,
            },
            {
                'media_type': 'video',
                'media_url':  'https://www.w3schools.com/html/movie.mp4',
                'alt':        'Bosch FR7DC — Product Overview',
                'order':      2,
                'is_primary': False,
            },
        ]

        for record in media_records:
            ItemMedia.objects.create(item=item, **record)
            self.stdout.write(
                f"  Created: {record['media_type']} / {record['alt'][:40]}"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Loaded {len(media_records)} media records for "
            f"{client.client_id}/{item.item_id}"
        ))
"""