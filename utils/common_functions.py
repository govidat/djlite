from collections import defaultdict
from django.core.cache import cache

from mysite.models import ThemePreset, Client, Theme, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue
#from mysite.models import Card, Hero, Accordion, Layout, Page, HeroText, HeroCardText, AccordionText
from mysite.models import Page, Layout, Component, ComponentSlot 

from django.db.models import Prefetch
from django.db.models import ForeignKey

from modeltranslation.translator import translator, NotRegistered
from django.conf import settings

from django.contrib.contenttypes.models import ContentType

# Plain model, no translated fields
#serialize_model(layout, exclude={'id'})

# Model with translated fields (name, nb_title)
#serialize_model(client, exclude={'parent', 'language_list'})
# Output includes 'translations': {'name': {'en': ..., 'ta': ...}, 'nb_title': {...}}

# Skip translations if not needed
#serialize_model(client, exclude={'parent'}, include_translations=False)

def serialize_model(instance, exclude=None, include_translations=True):
    exclude = set(exclude or [])

    # ── Identify base translated fields and all their generated columns ──
    base_translated_fields = set()
    generated_lang_columns = set()
    try:
        opts = translator.get_options_for_model(type(instance))
        base_translated_fields = set(opts.fields)   # {'name', 'nb_title'}
        for field_name in base_translated_fields:
            for lang_code, _ in settings.LANGUAGES:
                generated_lang_columns.add(f"{field_name}_{lang_code}")
    except NotRegistered:
        pass  # model has no translated fields — that's fine

    # ── Plain fields ──────────────────────────────────────────────────
    data = {}
    for field in instance._meta.fields:
        name = field.name

        if name in exclude:
            continue
        if name in base_translated_fields:
            continue        # virtual proxy field — skip, handled in translations dict
        if name in generated_lang_columns:
            continue        # e.g. name_en, name_hi — skip, grouped below

        if isinstance(field, ForeignKey):
            value = getattr(instance, f"{name}_id")
        else:
            value = getattr(instance, name)

        if value is not None:
            data[name] = value

    # ── Grouped translations dict ─────────────────────────────────────
    if include_translations and base_translated_fields:
        data['translations'] = {
            field_name: {
                lang_code: getattr(instance, f"{field_name}_{lang_code}", None)
                for lang_code, _ in settings.LANGUAGES
            }
            for field_name in base_translated_fields
        }

    return data
#Step 1: Universal Prefetch for TextContent Tree
# Universal Text Block Tree

stbitem_qs = (
    TextstbItem.objects
    .prefetch_related(
        Prefetch(
            "svgtextbadgevalue_set",
            queryset=SvgtextbadgeValue.objects.all(),  # no select_related needed
            to_attr="prefetched_svgtextbadgevalues"
        )
    )
    .order_by("order")
)

stbitem_prefetch = Prefetch(
    "textstbitems",
    queryset=stbitem_qs,
    to_attr="prefetched_stbitems"
)

"""
comptextblock_qs = ComptextBlock.objects.prefetch_related(
    stbitem_prefetch
).order_by("order")

comptextblock_prefetch = Prefetch(
    "comptextblocks",
    #queryset=ComptextBlock.objects.prefetch_related(stbitem_prefetch).order_by("order"),
    queryset= comptextblock_qs,
    to_attr="prefetched_comptextblocks"
)
"""
gentextblock_qs = GentextBlock.objects.prefetch_related(
    stbitem_prefetch
).order_by("order")

gentextblock_prefetch = Prefetch(
    "gentextblocks",
    #queryset=GentextBlock.objects.prefetch_related(stbitem_prefetch).order_by("order"),
    queryset= gentextblock_qs,
    to_attr="prefetched_gentextblocks"
)

# Option 3 Ccommon Components

comptextblock_qs = ComptextBlock.objects.prefetch_related(
    Prefetch(
        "textstbitems",
        queryset=TextstbItem.objects.prefetch_related(
            Prefetch(
                "svgtextbadgevalue_set",
                queryset=SvgtextbadgeValue.objects.all(),  # no select_related needed
                to_attr="prefetched_svgtextbadgevalues",
            )
        ).order_by("order"),
        to_attr="prefetched_stbitems",
    )
).order_by("order")

slot_qs = ComponentSlot.objects.prefetch_related(
    Prefetch(
        "comptextblocks",
        queryset=comptextblock_qs,
        to_attr="prefetched_comptextblocks",
    )
).order_by("order")

component_prefetch = Prefetch(
    "component",                   # OneToOne — no to_attr
    queryset=Component.objects.prefetch_related(
        Prefetch(
            "slots",
            queryset=slot_qs,
            to_attr="prefetched_slots",
        )
    ),
)

layout_prefetch = Prefetch(
    "layouts",
    queryset=Layout.objects.select_related("parent").prefetch_related(
        component_prefetch,
    ).order_by("level", "order"),
    to_attr="prefetched_layouts3",
)


def visible(obj):
    return obj if obj and not getattr(obj, "hidden", False) else None


# 1️⃣ Lowest Layer — SvgtextbadgeValue

def build_values(item):
    values = getattr(item, "prefetched_svgtextbadgevalues", None)
    if values is None:
        # Fallback — no select_related needed, language_code is a plain column
        values = item.svgtextbadgevalue_set.all()

    return {
        val.language_code: {
            "stext": val.stext,
            "ltext": val.ltext,
        }
        for val in values
    }

# 2️⃣ TextstbItem Builder


def build_stb_item(item):
    if not visible(item):
        return None

    data = {
        "type": item.item_id,
        "order": item.order,
        "css_class": item.css_class,
    }

    if item.item_id == "svg":
        data["svg"] = item.svg_text
    else:
        # ✅ Use optimized function
        data["values"] = build_values(item)

    return data

# 3️⃣ Generic Block Builder

def build_blocks(blocks_queryset):

    blocks = blocks_queryset or []
    result = []
    
    #actbut_items = []
    #actbut_order = None

    for block in blocks:

        if not visible(block):
            continue

        raw_items = getattr(block, "prefetched_stbitems", [])

        items = [build_stb_item(i) for i in raw_items]
        items = [i for i in items if i]

        if not items:
            continue

        href = getattr(block, "href_page", None)

        # ---- normal blocks ----
        result.append({
            "block_id": block.block_id,
            "order": block.order,
            "css_class": block.css_class,
            "ltext": block.ltext,
            "href_page": href,
            "items": items,
        })

    # final ordering safeguard
    result.sort(key=lambda x: x["order"])

    return result
    """
    "textblocks": [
      {
        "block_id": "title",
        "order": 1,
        "items": [...]
      },
      {
        "block_id": "content",
        "order": 2,
        "items": [...]
      },
      {
        "block_id": "actbut",
        "order": 3,
        "items": [...]
      }
    ]
    """

# 6️⃣B Page tree for Navigation bar
def build_page_tree(pages):
    node_map = {}
    roots = []
    
    # Step 1: create flat nodes
    for page in pages:
        page_vis = visible(page)
        if not page_vis:
            return None        
        
        # Use serialize_model to get the grouped translations dict
        # just like build_page does — exclude layout-irrelevant fields
        serialized = serialize_model(
            page,
            exclude={'id', 'ltext', 'hidden'},
            include_translations=True
        )

        node_map[page.id] = {
            "client_id": page.client.client_id,
            "page_id": page.page_id,
            "order": page.order,
            "translations": serialized.get('translations', {}),
            #"textblocks": build_blocks(getattr(page, "prefetched_gentextblocks", [])),
            "children": []
        }

    # Step 2: attach children
    for page in pages:
        page_vis = visible(page)
        if not page_vis:
            return None         

        node = node_map[page.id]

        if page.parent_id:
            parent_node = node_map.get(page.parent_id)
            if parent_node:
                parent_node["children"].append(node)
        else:
            roots.append(node)

    return roots


# Option 3 common Components
def build_slot(slot):
    slot = visible(slot)
    if not slot:
        return None
    
    data = serialize_model(slot, exclude={"id", "component_id"})

    # Works for both slot types safely:
    # - text slot: returns populated list
    # - figure slot: getattr returns [], build_blocks returns [], 
    #                key is simply not added to data
    textblocks = build_blocks(getattr(slot, "prefetched_comptextblocks", []))
    if textblocks:
        data["textblocks"] = textblocks

    return data


def build_component(layout):
    obj = getattr(layout, "component", None)
    obj = visible(obj)
    if not obj:
        return None

    slots = getattr(obj, "prefetched_slots", [])
    built_slots = [build_slot(s) for s in slots]
    built_slots = [s for s in built_slots if s]

    # serialize_model gets all field values generically
    data = serialize_model(obj, exclude={"id", "layout_id"})
    data["slots"] = built_slots

    return data


def build_layout(layout, layout_map):
    layout = visible(layout)
    if not layout:
        return None

    layout_data = {
        "level":     layout.level,
        "slug":      layout.slug,
        "order":     layout.order,
        "css_class": layout.css_class,
        #"comp_id":   layout.comp_id,
    }

    #if layout.comp_id and layout.level == 40:
    if layout.level == 40:        
        component = build_component(layout)
        if component:
            layout_data["component"] = component

    children = [
        build_layout(child, layout_map)
        for child in layout_map.get(layout.id, [])
    ]
    children = [c for c in children if c]
    if children:
        layout_data["children"] = children

    return layout_data


def build_page(page):
    page = visible(page)
    if not page:
        return None

    all_layouts = list(getattr(page, "prefetched_layouts3", []))
    layout_map = {}
    root_layouts = []
    for layout in all_layouts:
        if layout.parent_id:
            layout_map.setdefault(layout.parent_id, []).append(layout)
        else:
            root_layouts.append(layout)
    layouts = [build_layout(l, layout_map) for l in root_layouts]
    layouts = [l for l in layouts if l]

    return {
        **serialize_model(page, exclude={'id'}),
        #"textblocks": build_blocks(getattr(page, "prefetched_gentextblocks", [])),
        "layouts":    layouts,
    }


# 7️⃣ FINAL: build_client_payload()

def build_client_payload(client):
    """
    languages_qs = Language.objects.filter(language_id__in=client.language_list)
    language_lookup = {l.language_id: l for l in languages_qs}
    lv_languages = [
        {
            "language_id": lang_id,
            "labels":      language_lookup[lang_id].label_obj
        }
        for lang_id in client.language_list
        if lang_id in language_lookup
    ]
    """

    lv_themes = []
    for theme in getattr(client, "prefetched_themes", []):
        lv_themes.append({
            **serialize_model(theme, exclude={'id'}),
            #"textblocks": build_blocks(getattr(theme, "prefetched_gentextblocks", [])),
            "tokens":     resolve_theme(theme),
        })

    all_pages = list(getattr(client, "prefetched_pages", []))

    return {
        **serialize_model(client, exclude={'id', 'parent', 'language_list'}),
        "languages":  client.language_list, 
        #lv_languages,
        "themes":     lv_themes,
        #"textblocks": build_blocks(getattr(client, "prefetched_gentextblocks", [])),
        "pages":      [build_page(page) for page in all_pages],
        "page_tree":  build_page_tree([p for p in all_pages if not p.hidden]),
    }
# temporarily marking use_cache = False. To be changed after debugging
# instead of gentext block for name, nb_title have alreaady added modeltranslation fields.
# TBD in PRD use_cache=True
def fetch_clientstatic(lv_client_id=None, as_dict=False, use_cache=False, timeout=3600):
    """
    Fetch clientstatic with optional caching.
    Works when client_id as primary key.
    """
    
    # Build cache key
    cache_key = None
    if use_cache and lv_client_id:
        cache_key = f"clientstatic:{lv_client_id}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
    
    # Build query
    client_static = {}
    # refactored to get all static data in one go and cache the sql call
    #Step 4: Page + Client Query (The Entry Point)
    if lv_client_id:
        try:
          
          qs_client = (
            Client.objects
            #.select_related("parent")  # Add this if you access parent -- also modify build_client_payload
            .prefetch_related(
                #gentextblock_prefetch,
                Prefetch(
                    "pages",
                    queryset=Page.objects.select_related(
                        "parent"
                    ).prefetch_related(
                        #gentextblock_prefetch,
                        layout_prefetch,
                    ).order_by("order"),
                    to_attr="prefetched_pages"
                ),                
                Prefetch(
                    "themes",
                    queryset=Theme.objects
                        .select_related("themepreset")  # IMPORTANT
                        #.prefetch_related(
                        #    gentextblock_prefetch,
                        #)
                        .order_by("order"),
                        to_attr="prefetched_themes"
                ) 
            )
            .get(client_id=lv_client_id)
          )
            # If we get here, the client exists
          client_static = build_client_payload(qs_client)

        except Client.DoesNotExist:
          # If .get() fails, we land here. 
          # client_static remains {} as initialized above.
          pass 
      
  
    # Cache it
    if cache_key:
        cache.set(cache_key, client_static, timeout=timeout)

    
    return client_static




"""
For using clienttheme as the source css instead of standard daisy, steps are:
1. Model ThemePreset to have base values like light, dark (default values)
2. ClientTheme to have Client specific values like light, dark which in turn is linked to ThemePreset light, dark etc; Client Specific values to override defaults
3. resolve_theme(theme) code to do this step 2 above
4. Inject the variables in base.html 
Example code
:root {
  --p: {{ theme.primary }};
  --s: {{ theme.secondary }};
  --a: {{ theme.accent }};
  --n: {{ theme.neutral }};
  --b1: {{ theme.base_100 }};
  --font-main: {{ theme.font_family }};
5. configure daisyui to use these variables: 
A Constant value "clienttheme" is pushed into daisyui. This takes variable values like b1, b2 etc
theme > static_src > src > styles.css  (tailwind.config.js file is not visible in django-tailwind setup) 
Example code
@plugin "daisyui/theme" {
  name: "clienttheme";
  default: true; /* set as default */
  prefersdark: false; /* set as default dark mode (prefers-color-scheme:dark) */
  color-scheme: light; /* color of browser-provided UI */

  --color-base-100: oklch(var(--b1));
  --color-base-2
6. In Views - pass the variable values like b1, b2 etc based on the theme chosen into a dict called theme.
This dict called theme is pulled into base.html and passed on to daisyui.

  
"""
# Cache the preset field names once at import time
THEME_PRESET_FIELDS = [
    f.name
    for f in ThemePreset._meta.get_fields()
    if f.concrete
    and not f.is_relation
    and f.name not in ["id", "themepreset_id", "ltext", "is_system"]
]

def resolve_theme(theme):
    base = theme.themepreset
    overrides = theme.overrides or {}

    data = {}

    for field in THEME_PRESET_FIELDS:
        data[field] = overrides.get(field) or getattr(base, field)

    return data

# some old codes
# this is a helper used in hero/ card prefetch in layout
"""
def get_prefetched(obj, attr):
    if not hasattr(obj, attr):
        raise Exception(f"Missing prefetch: {attr}")

    val = getattr(obj, attr)

    if isinstance(val, list):
        return val[0] if val else None

    return val

"""

"""
def get_translated_fields(instance):

    try:
        opts = translator.get_options_for_model(type(instance))
        translated_field_names = opts.fields.keys()  # e.g. ('name', 'nb_title')
    except Exception:
        return {}

    result = {}
    for field_name in translated_field_names:
        result[field_name] = {
            lang_code: getattr(instance, f"{field_name}_{lang_code}", None)
            for lang_code, _ in settings.LANGUAGES
        }
    return result


def get_non_translated_fields(instance, exclude_fields=None):

    from django.db.models.fields.related import RelatedField
    from django.db.models.fields import AutoField

    exclude_fields = set(exclude_fields or [])

    # Get translated field names to exclude them
    try:
        opts = translator.get_options_for_model(type(instance))
        translated_names = set(opts.fields.keys())
        # Also exclude the language-specific column names e.g. name_en, name_ta
        for field_name in translated_names:
            for lang_code, _ in settings.LANGUAGES:
                translated_names.add(f"{field_name}_{lang_code}")
    except Exception:
        translated_names = set()

    result = {}
    for field in instance._meta.get_fields():
        # Skip relations, auto fields, translated fields, excluded fields
        if isinstance(field, (RelatedField, AutoField)):
            continue
        if not hasattr(field, 'column'):        # skip reverse relations
            continue
        if field.name in translated_names:
            continue
        if field.name in exclude_fields:
            continue
        result[field.name] = getattr(instance, field.name, None)
    return result
"""
# this is used extensively in build programs to serialize data.
"""
def serialize_model(instance, exclude=None):
    exclude = set(exclude or [])
    data = {}

    for field in instance._meta.fields:
        name = field.name
        if name in exclude:
            continue

        value = getattr(instance, name)
        if isinstance(field, ForeignKey):
            value = getattr(instance, f"{name}_id")

        # Only add key if value is not None
        if value is not None:
            data[name] = value

    return data
"""
"""
def build_client_payload(client):

    # Create a lookup dictionary

    languages_qs = Language.objects.filter(
        language_id__in=client.language_list
    )


    # Preserve client order
    language_lookup = {l.language_id: l for l in languages_qs}
    lv_languages = [
        {
            "language_id": lang_id,
            "labels": language_lookup[lang_id].label_obj 
        }
        for lang_id in client.language_list
        if lang_id in language_lookup
    ]

    # To reconstruct the theme values
    lv_themes = []

    all_themes = list(getattr(client, "prefetched_themes", []))

    for theme in all_themes:

      resolved_tokens = resolve_theme(theme)
      lv_themes.append({
          "theme_id": theme.theme_id,
          "ltext": theme.ltext,
          "is_default": theme.is_default,
          "textblocks": build_blocks(getattr(theme, "prefetched_gentextblocks", [])),
          "tokens": resolved_tokens,  # fully resolved
      })

    #all_pages = list(getattr(client, "prefetched_pages", []))
    all_pages = list(getattr(client, "prefetched_pages", []))    
    return {
        "client_id": client.client_id,
        "languages": lv_languages,
        "themes": lv_themes,
        #"parent": client.parent.client_id if client.parent else None,
        "textblocks": build_blocks(getattr(client, "prefetched_gentextblocks", [])),
        #"pages": [
        #    build_page(page)
        #    for page in all_pages
        #],

        #"page_tree": build_page_tree(
        #    [l for l in all_pages if not l.hidden]
        #), # this is for navigation bar requirement. this is nested # xyz.all() without filter works with prefetch
        "pages": [
            build_page(page)
            for page in all_pages
        ],
        "page_tree": build_page_tree(
            [l for l in all_pages if not l.hidden]
        ), # this is for navigation bar requirement. this is nested # xyz.all() without filter works with prefetch


    }
"""
"""
def build_client_payload(client):
    # ── Languages ──────────────────────────────────────────────────
    languages_qs = Language.objects.filter(language_id__in=client.language_list)
    language_lookup = {l.language_id: l for l in languages_qs}
    lv_languages = [
        {
            "language_id": lang_id,
            "labels":      language_lookup[lang_id].label_obj
        }
        for lang_id in client.language_list
        if lang_id in language_lookup
    ]

    # ── Themes ─────────────────────────────────────────────────────
    lv_themes = []
    for theme in getattr(client, "prefetched_themes", []):
        lv_themes.append({
            "theme_id":   theme.theme_id,

            # Auto-extract all plain fields (order, is_default, ltext etc.)
            **get_non_translated_fields(theme, exclude_fields={'theme_id'}),

            # Auto-extract all translated fields (name etc.)
            "translations": get_translated_fields(theme),

            "textblocks": build_blocks(getattr(theme, "prefetched_gentextblocks", [])),
            "tokens":     resolve_theme(theme),
        })

    # ── Pages ──────────────────────────────────────────────────────
    all_pages = list(getattr(client, "prefetched_pages", []))

    return {
        # ── Stable identity fields ─────────────────────────────────
        "client_id":    client.client_id,

        # ── All plain fields auto-extracted ────────────────────────
        # Captures any new fields added to Client automatically.
        **get_non_translated_fields(
            client,
            exclude_fields={'client_id', 'language_list', 'parent'}
        ),

        # ── All translated fields auto-extracted ───────────────────
        # Captures name, nb_title and any future translated fields.
        "translations": get_translated_fields(client),

        # ── Related data ───────────────────────────────────────────
        "languages":    lv_languages,
        "themes":       lv_themes,
        "textblocks":   build_blocks(getattr(client, "prefetched_gentextblocks", [])),
        "pages":        [build_page(page) for page in all_pages],
        "page_tree":    build_page_tree([p for p in all_pages if not p.hidden]),
    }
"""
"""
def build_page(page):
    page = visible(page)
    if not page:
        return None

    all_layouts = list(getattr(page, "prefetched_layouts3", []))

    layout_map = {}
    root_layouts = []
    for layout in all_layouts:
        if layout.parent_id:
            layout_map.setdefault(layout.parent_id, []).append(layout)
        else:
            root_layouts.append(layout)

    layouts = [build_layout(l, layout_map) for l in root_layouts]
    layouts = [l for l in layouts if l]

    return {
        "page_id":    page.page_id,
        "order":      page.order,
        "textblocks": build_blocks(getattr(page, "prefetched_gentextblocks", [])),
        "layouts":    layouts,
    }
"""

"""
def build_page(page):
    page = visible(page)
    if not page:
        return None

    all_layouts = list(getattr(page, "prefetched_layouts3", []))
    layout_map = {}
    root_layouts = []
    for layout in all_layouts:
        if layout.parent_id:
            layout_map.setdefault(layout.parent_id, []).append(layout)
        else:
            root_layouts.append(layout)
    layouts = [build_layout(l, layout_map) for l in root_layouts]
    layouts = [l for l in layouts if l]

    return {
        # ── Stable identity fields ─────────────────────────────────
        "page_id":          page.page_id,

        # ── All plain fields auto-extracted ────────────────────────
        # Captures order, hidden, slug, and any future fields added
        # to Page without needing to update this function.
        **get_non_translated_fields(page, exclude_fields={'page_id'}),

        # ── All translated fields auto-extracted ───────────────────
        # Captures name, nb_title etc. for all languages.
        # Output: {'name': {'en': 'Home', 'ta': 'முகப்பு'}, ...}
        "translations":     get_translated_fields(page),

        # ── Related data ───────────────────────────────────────────
        "textblocks":       build_blocks(getattr(page, "prefetched_gentextblocks", [])),
        "layouts":          layouts,
    }
"""
"""

#Step 2: Component-Level Prefetch
# Hero subtree
hero_prefetch = Prefetch(
    "hero",  # ← reverse OneToOne accessor
    queryset=Hero.objects
        .select_related(
            "herotext",
            "herofigure",
            "herocard",
            "herocard__herocardtext",
            "herocard__herocardfigure",
        )
        .prefetch_related(
            Prefetch(
                "herotext__comptextblocks",
                queryset=ComptextBlock.objects.prefetch_related(
                    Prefetch(
                        "textstbitems",
                        queryset=TextstbItem.objects.prefetch_related(
                            Prefetch(
                                "svgtextbadgevalue_set",
                                queryset=SvgtextbadgeValue.objects.select_related("language"),
                                to_attr="prefetched_svgtextbadgevalues",
                            )
                        ).order_by("order"),
                        to_attr="prefetched_stbitems",
                    )
                ).order_by("order"),
                to_attr="prefetched_ht_comptextblocks",
            ),
            Prefetch(
                "herocard__herocardtext__comptextblocks",
                queryset=ComptextBlock.objects.prefetch_related(
                    Prefetch(
                        "textstbitems",
                        queryset=TextstbItem.objects.prefetch_related(
                            Prefetch(
                                "svgtextbadgevalue_set",
                                queryset=SvgtextbadgeValue.objects.select_related("language"),
                                to_attr="prefetched_svgtextbadgevalues",
                            )
                        ).order_by("order"),
                        to_attr="prefetched_stbitems",
                    )
                ).order_by("order"),
                to_attr="prefetched_hcht_comptextblocks",
            ),
        ),
    #to_attr="prefetched_heros",
)

# Card subtree
card_prefetch = Prefetch(
    "card",       # ← reverse OneToOne accessor
    queryset=Card.objects
        .select_related(
            "cardtext",
            "cardfigure",
        )
        .prefetch_related(
            Prefetch(
                "cardtext__comptextblocks",
                queryset=ComptextBlock.objects.prefetch_related(
                    Prefetch(
                        "textstbitems",
                        queryset=TextstbItem.objects.prefetch_related(
                            Prefetch(
                                "svgtextbadgevalue_set",
                                queryset=SvgtextbadgeValue.objects.select_related("language"),
                                to_attr="prefetched_svgtextbadgevalues",
                            )
                        ).order_by("order"),
                        to_attr="prefetched_stbitems",
                    )
                ).order_by("order"),
                to_attr="prefetched_ct_comptextblocks",
            ),
        ),
    #to_attr="prefetched_cards",
)

accordion_prefetch = Prefetch(
    "accordion",                   # ← reverse OneToOne accessor from Layout
    queryset=Accordion.objects
        .prefetch_related(
            Prefetch(
                "accordiontext",   # ← reverse FK (multiple AccordionText per Accordion)
                queryset=AccordionText.objects.prefetch_related(
                    Prefetch(
                        "comptextblocks",
                        queryset=ComptextBlock.objects.prefetch_related(
                            Prefetch(
                                "textstbitems",
                                queryset=TextstbItem.objects.prefetch_related(
                                    Prefetch(
                                        "svgtextbadgevalue_set",
                                        queryset=SvgtextbadgeValue.objects.select_related("language"),
                                        to_attr="prefetched_svgtextbadgevalues",
                                    )
                                ).order_by("order"),
                                to_attr="prefetched_stbitems",
                            )
                        ).order_by("order"),
                        to_attr="prefetched_at_comptextblocks",  # "at" = accordion text
                    ),
                ).order_by("order"),
                to_attr="prefetched_accordiontext",  # list, since FK not OneToOne
            ),
        ),
    # ← NO to_attr here, same as card/hero
)
#Step 3: Layout Tree (Single Fetch, Ordered)

layout_qs = Layout.objects.select_related("parent").order_by("level", "order") 

layout_prefetch = Prefetch(
    "layouts",
    queryset=layout_qs.prefetch_related(
        hero_prefetch,
        card_prefetch,
        accordion_prefetch,
    ),
    #.order_by("level", "order"),
    to_attr="prefetched_layouts"
)

"""
# Option 1 Individual Builders
"""

# 4️⃣ Component Builders
# HeroText
def build_hero_text(ht):
    ht = visible(ht)
    if not ht:
        return None

    #textblocks = build_blocks(ht.comptextblocks.all())
    textblocks = build_blocks(getattr(ht, "prefetched_ht_comptextblocks", []))    
    
    if not textblocks:
        return None
    
    data = serialize_model(
        ht,
        exclude={"id", "content_type", "object_id", "hero"}
    )

    data["type_id"] = "text"
    data["textblocks"] = textblocks

    return data    

# HeroFigure
def build_hero_figure(hf):
    hf = visible(hf)
    if not hf:
        return None

    data = serialize_model(
        hf,
        exclude={"id", "content_type", "object_id"}
    )

    data["type_id"] = "figure"

    return data


# HeroCardText
def build_herocard_text(obj):
    obj = visible(obj)
    if not obj:
        return None
    
    #textblocks = build_blocks(obj.comptextblocks.all())
    textblocks = build_blocks(getattr(obj, "prefetched_hcht_comptextblocks", []))
    if not textblocks:
        return None
    
    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "herocard_id"}
    )

    data["type_id"] = "text"
    data["textblocks"] = textblocks

    return data

# HeroCardFigure
def build_herocard_figure(obj):
    obj = visible(obj)
    if not obj:
        return None
  
    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "herocard_id"}
    )

    data["type_id"] = "figure"

    return data


# HeroCard
def build_herocard(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_herocard_figure(getattr(obj, "herocardfigure", None))
    if figure:
        contents.append(figure)

    text = build_herocard_text(getattr(obj, "herocardtext", None))
    if text:
        contents.append(text)
    #SORT IS NOT RELEVANT IN CARD 
    contents.sort(key=lambda x: x["order"])

    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "hero_id"}
    )

    data["type_id"] = "herocard"
    data["contents"] = contents

    return data


# Hero
def build_hero(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_hero_figure(getattr(obj, "herofigure", None))
    if figure:
        contents.append(figure)

    text = build_hero_text(getattr(obj, "herotext", None))
    if text:
        contents.append(text)

    herocard = build_herocard(getattr(obj, "herocard", None))
    if herocard:
        contents.append(herocard)

    contents.sort(key=lambda x: x["order"])

    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "layout_id"}
    )

    data["comp_id"] = "hero"
    data["contents"] = contents

    return data

# CardFigure
def build_card_figure(obj):
    obj = visible(obj)
    if not obj:
        return None

    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "card_id"}
    )

    data["type_id"] = "figure"

    return data


# CardText
def build_card_text(obj):
    obj = visible(obj)
    if not obj:
        return None
    textblocks = build_blocks(getattr(obj, "prefetched_ct_comptextblocks", []))
    if not textblocks:
        return None
    
    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "card_id"}
    )

    data["type_id"] = "text"
    data["textblocks"] = textblocks

    return data

# Card
def build_card(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_card_figure(getattr(obj, "cardfigure", None))
    if figure:
        contents.append(figure)

    text = build_card_text(getattr(obj, "cardtext", None))
    if text:
        contents.append(text)

    contents.sort(key=lambda x: x["order"])

    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "layout_id"}
    )

    data["comp_id"] = "card"
    data["contents"] = contents
    
    return data


# AccordionText
def build_accordion_text(obj):
    obj = visible(obj)
    if not obj:
        return None
    textblocks = build_blocks(getattr(obj, "prefetched_at_comptextblocks", []))
    if not textblocks:
        return None
    
    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "accordion_id"}
    )

    data["type_id"] = "text"
    data["textblocks"] = textblocks

    return data

# Accordion
def build_accordion(obj):
    obj = visible(obj)
    if not obj:
        return None

    #contents = []

    # FK = list, so iterate prefetched_accordiontext
    raw_texts = getattr(obj, "prefetched_accordiontext", [])

    accordion_texts = [
        build_accordion_text(at)
        for at in raw_texts
    ]
    accordion_texts = [at for at in accordion_texts if at]
    accordion_texts.sort(key=lambda x: x["order"])

    data = serialize_model(
        obj,
        exclude={"id", "content_type", "object_id", "layout_id"}
    )

    data["comp_id"] = "accordion"
    data["contents"] = accordion_texts
    
    return data
"""

# Option 2 with Component Registry
# ── Component Registry ────────────────────────────────────────
# Each entry describes how to build a component from its model.
# "children" lists the child accessors and their slot types.
# "list_children" are FK (one-to-many) children like AccordionText.

"""
COMPONENT_REGISTRY = {
    "hero": {
        "accessor": "hero",
        "exclude": {"id", "layout_id"},
        "children": [
            {
                "attr": "herofigure",
                "type_id": "figure",
                "prefetch_attr": None,  # no textblocks
            },
            {
                "attr": "herotext",
                "type_id": "text",
                "prefetch_attr": "prefetched_ht_comptextblocks",
            },
            {
                "attr": "herocard",
                "type_id": "herocard",
                "prefetch_attr": None,  # herocard has its own children
                "children": [
                    {
                        "attr": "herocardfigure",
                        "type_id": "figure",
                        "prefetch_attr": None,
                    },
                    {
                        "attr": "herocardtext",
                        "type_id": "text",
                        "prefetch_attr": "prefetched_hcht_comptextblocks",
                    },
                ],
            },
        ],
    },
    "card": {
        "accessor": "card",
        "exclude": {"id", "layout_id"},
        "children": [
            {
                "attr": "cardfigure",
                "type_id": "figure",
                "prefetch_attr": None,
            },
            {
                "attr": "cardtext",
                "type_id": "text",
                "prefetch_attr": "prefetched_ct_comptextblocks",
            },
        ],
    },
    "accordion": {
        "accessor": "accordion",
        "exclude": {"id", "layout_id"},
        # FK list child — same "children" key, with is_list=True
        "children": [
            {
                "attr": "prefetched_accordiontext",  # already a list from prefetch
                "type_id": "text",
                "prefetch_attr": "prefetched_at_comptextblocks",
                "is_list": True,  # ← this is the only difference
            },
        ],
    },
}

# ── Single unified recursive builder ─────────────────────────

def build_child(obj, child_config):
    
    #Handles both single (OneToOne) and list (FK) children
    #based on is_list flag in config. Replaces build_child
    #and build_list_children as separate functions.
    
    obj = visible(obj)
    if not obj:
        return None

    is_list = child_config.get("is_list", False)
    attr = child_config["attr"]
    type_id = child_config["type_id"]
    prefetch_attr = child_config.get("prefetch_attr")
    nested_children = child_config.get("children", [])

    # ── List child (FK, one-to-many) ──
    if is_list:
        raw_list = getattr(obj, attr, [])
        results = []
        for item in raw_list:
            item = visible(item)
            if not item:
                continue
            data = serialize_model(item, exclude={"id"})
            data["type_id"] = type_id
            if prefetch_attr:
                textblocks = build_blocks(getattr(item, prefetch_attr, []))
                if textblocks:
                    data["textblocks"] = textblocks
            results.append(data)
        results.sort(key=lambda x: x.get("order", 0))
        return results  # returns list, not dict

    # ── Single child (OneToOne) ──
    child_obj = getattr(obj, attr, None)
    child_obj = visible(child_obj)
    if not child_obj:
        return None

    data = serialize_model(child_obj, exclude={"id"})
    data["type_id"] = type_id

    # Has textblocks (text slot)
    if prefetch_attr:
        textblocks = build_blocks(getattr(child_obj, prefetch_attr, []))
        if not textblocks:
            return None
        data["textblocks"] = textblocks

    # Has nested children (e.g. herocard → herocardfigure + herocardtext)
    if nested_children:
        contents = []
        for nc in nested_children:
            result = build_child(child_obj, nc)
            if result:
                if isinstance(result, list):
                    contents.extend(result)
                else:
                    contents.append(result)
        contents.sort(key=lambda x: x.get("order", 0))
        data["contents"] = contents

    return data

# ── Top-level component builder driven by registry ───────────

def build_component_from_registry(layout):
    comp_id = layout.comp_id
    if not comp_id:
        return None

    config = COMPONENT_REGISTRY.get(comp_id)
    if not config:
        return None

    accessor = config["accessor"]
    obj = getattr(layout, accessor, None)
    obj = visible(obj)
    if not obj:
        return None

    contents = []
    for child_config in config.get("children", []):
        result = build_child(obj, child_config)
        if result:
            if isinstance(result, list):
                contents.extend(result)   # FK list — flatten into contents
            else:
                contents.append(result)   # OneToOne — append single item

    contents.sort(key=lambda x: x.get("order", 0))

    data = serialize_model(obj, exclude=config.get("exclude", {"id"}))
    data["comp_id"] = comp_id
    data["contents"] = contents
    return data

# 5️⃣ Layout Builder

def build_layout(layout, layout_map):
    layout = visible(layout)
    if not layout:
        return None

    layout_data = {
        "level": layout.level,
        "slug": layout.slug,
        "order": layout.order,
        "css_class": layout.css_class,
        "comp_id": layout.comp_id
    }

    component = None

    lv_option = 2
    
    # Option 1 with individual build functions
    if lv_option == 1:
      if layout.comp_id == "hero":
        hero = getattr(layout, "hero", None)
        if hero:
          component = build_hero(hero)    
        
      elif layout.comp_id == "card":
        card = getattr(layout, "card", None)
        if card:
          component = build_card(card)  
          
      elif layout.comp_id == "accordion":
          accordion = getattr(layout, "accordion", None)
          if accordion:
              component = build_accordion(accordion)            

      if component:
          layout_data["component"] = component`

    elif lv_option == 2:
      # Option 2 with common registry
      if layout.comp_id:
          component = build_component_from_registry(layout)
          if component:
              layout_data["component"] = component
            

    # 🔥 Build children recursively
    children = [
        build_layout(child, layout_map)
        for child in layout_map.get(layout.id, [])
    ]

    children = [c for c in children if c]

    if children:
        layout_data["children"] = children

    return layout_data

# 6️⃣ Page Builder

def build_page(page):
    page = visible(page)
    if not page:
        return None

    all_layouts = list(getattr(page, "prefetched_layouts", []))
    # 🔥 Build parent-child lookup
    layout_map = {}
    root_layouts = []

    for layout in all_layouts:
        if layout.parent_id:
            layout_map.setdefault(layout.parent_id, []).append(layout)
        else:
            root_layouts.append(layout)

    # 🔥 Build tree from roots
    layouts = [
        build_layout(layout, layout_map)
        for layout in root_layouts
    ]

    layouts = [l for l in layouts if l]

    return {
        "page_id": page.page_id,
        "order": page.order,
        "textblocks": build_blocks(getattr(page, "prefetched_gentextblocks", [])),
        "layouts": layouts,
    }
"""

"""
# Theme Resolution Engine (Core Logic)
def resolve_theme(theme):
    base = theme.preset
    data = {}

    for field in [f.name for f in ThemePreset._meta.fields]:
        if field in ["id", "name", "slug", "is_system"]:
            continue

        override = theme.overrides.get(field) if theme.overrides else None
        data[field] = override or getattr(base, field)

    return data
"""
