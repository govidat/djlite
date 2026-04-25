from collections import defaultdict
from django.core.cache import cache

from mysite.models import ThemePreset, Client, Theme, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue
#from mysite.models import Card, Hero, Accordion, Layout, Page, HeroText, HeroCardText, AccordionText
from mysite.models import Page, Layout, NavItem, Component, ComponentSlot

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
"""
def build_nav_item(item, client_id):
    return {
        'name':           item.name,   # modeltranslation will expand to label_en etc.
        'url':             item.get_url(client_id),
        'nav_type':        item.nav_type,
        'open_in_new_tab': item.open_in_new_tab,
        'children': [
            build_nav_item(child, client_id)
            for child in getattr(item, 'prefetched_children', [])
        ],
    }
"""
def build_nav_item(item, client_id):
    data = serialize_model(item, exclude={'id', 'parent_id', 'page_id'})
    #data['url']      = item.get_url(client_id)
    data['href'] = item.get_url(client_id)   # ← resolved full URL, separate from raw 'url' field
    data['children'] = [
        build_nav_item(child, client_id)
        for child in getattr(item, 'prefetched_children', [])
    ]
    return data

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

    all_nav_items = getattr(client, 'prefetched_nav_items', [])
    client_id     = client.client_id

    header_nav = [
        build_nav_item(item, client_id)
        for item in all_nav_items
        if item.location == 'header'
    ]
    footer_nav = [
        build_nav_item(item, client_id)
        for item in all_nav_items
        if item.location == 'footer'
    ]

    all_pages = list(getattr(client, "prefetched_pages", []))

    return {
        **serialize_model(client, exclude={'id', 'parent', 'language_list'}),
        "languages":  client.language_list, 
        #lv_languages,
        "themes":     lv_themes,
        #"textblocks": build_blocks(getattr(client, "prefetched_gentextblocks", [])),
        "pages":      [p for p in (build_page(page) for page in all_pages) if p], # [build_page(page) for page in all_pages],
        "page_tree":  build_page_tree([p for p in all_pages if not p.hidden]),
        'header_nav':  header_nav,
        'footer_nav':  footer_nav,        
    }
# temporarily marking use_cache = False. To be changed after debugging
# instead of gentext block for name, nb_title have alreaady added modeltranslation fields.
# TBD in PRD use_cache=True
def fetch_clientstatic(lv_client_id=None, as_dict=False, use_cache=True, timeout=3600):
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
                ),
                Prefetch(
                    "nav_items",
                    queryset=NavItem.objects
                        .filter(hidden=False)
                        .select_related("page")          # to resolve page.page_id for URL building
                        .prefetch_related(
                            Prefetch(
                                "children",
                                queryset=NavItem.objects
                                    .filter(hidden=False)
                                    .select_related("page")
                                    .order_by("order"),
                                to_attr="prefetched_children",
                            )
                        )
                        .filter(parent=None)             # root items only — children come via prefetched_children
                        .order_by("location", "order"),
                    to_attr="prefetched_nav_items",
                ),                               
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
django-tailwind 4.x uses styles.css instead of tailwind.config.js for configuration. Tailwind v4 moved away 
from a JS config file entirely.

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

""" jsonclient
{
   "client_id":"bahushira",
   "theme_list":[
      
   ],
   "translations":{
      "name":{
         "en":"Bahushira",
         "hi":"hiBahushira",
         "fr":"frBahushira",
         "ta":null
      },
      "nb_title":{
         "en":"Bahushira Title",
         "hi":"hiBahushira Title",
         "fr":"frBahushira Title",
         "ta":null
      }
   },
   "languages":[
      "en",
      "hi",
      "fr"
   ],
   "themes":[
      {
         "client":1,
         "theme_id":"light",
         "themepreset":1,
         "ltext":"",
         "order":1,
         "hidden":false,
         "is_default":true,
         "translations":{
            "name":{
               "en":"Light",
               "hi":"hiLight",
               "fr":"frLight",
               "ta":null
            }
         },
         "tokens":{
            "primary":"#570df8",
            "secondary":"#f000b8",
            "accent":"#37cdbe",
            "neutral":"#3d4451",
            "primary_content":"#ffffff",
            "secondary_content":"#ffffff",
            "accent_content":"#163835",
            "neutral_content":"#ffffff",
            "base_100":"#ffffff",
            "base_200":"#f2f2f2",
            "base_300":"#e5e6e6",
            "base_content":"#1f2937",
            "success":"#00c853",
            "warning":"#ff9800",
            "error":"#ff5724",
            "info":"#2094f3",
            "success_content":"#ffffff",
            "warning_content":"#ffffff",
            "error_content":"#ffffff",
            "info_content":"#ffffff",
            "font_body":"",
            "font_heading":"",
            "base_font_size":"16px",
            "scale_ratio":1.2,
            "section_gap":"4rem",
            "container_padding":"1rem",
            "radius_btn":"0.5rem",
            "radius_card":"1rem",
            "radius_input":"0.5rem",
            "shadow_sm":"0 1px 2px 0 rgb(0 0 0 / 0.05)",
            "shadow_md":"0 4px 6px -1px rgb(0 0 0 / 0.1)",
            "shadow_lg":"0 10px 15px -3px rgb(0 0 0 / 0.1)"
         }
      },
      {
         "client":1,
         "theme_id":"dark",
         "themepreset":2,
         "ltext":"",
         "order":2,
         "hidden":false,
         "is_default":false,
         "translations":{
            "name":{
               "en":"Dark",
               "hi":"hiDark",
               "fr":"frDark",
               "ta":null
            }
         },
         "tokens":{
            "primary":"#661ae6",
            "secondary":"#d926aa",
            "accent":"#1fb2a6",
            "neutral":"#191d24",
            "primary_content":"#ffffff",
            "secondary_content":"#ffffff",
            "accent_content":"#ffffff",
            "neutral_content":"#a6adbb",
            "base_100":"#2a303c",
            "base_200":"#242933",
            "base_300":"#1d232a",
            "base_content":"#a6adbb",
            "success":"#36d399",
            "warning":"#fbbd23",
            "error":"#f87272",
            "info":"#3abff8",
            "success_content":"#000000",
            "warning_content":"#000000",
            "error_content":"#000000",
            "info_content":"#000000",
            "font_body":"",
            "font_heading":"",
            "base_font_size":"16px",
            "scale_ratio":1.2,
            "section_gap":"4rem",
            "container_padding":"1rem",
            "radius_btn":"0.5rem",
            "radius_card":"1rem",
            "radius_input":"0.5rem",
            "shadow_sm":"0 1px 2px 0 rgb(0 0 0 / 0.05)",
            "shadow_md":"0 4px 6px -1px rgb(0 0 0 / 0.1)",
            "shadow_lg":"0 10px 15px -3px rgb(0 0 0 / 0.1)"
         }
      }
   ],
   "pages":[
      {
         "client":1,
         "page_id":"home",
         "ltext":"Home Page",
         "order":1,
         "hidden":false,
         "translations":{
            "name":{
               "en":"Home",
               "hi":"hiHome",
               "fr":"frHome",
               "ta":null
            }
         },
         "layouts":[
            {
               "level":10,
               "slug":"a",
               "order":1,
               "css_class":"",
               "children":[
                  {
                     "level":20,
                     "slug":"a",
                     "order":1,
                     "css_class":"",
                     "children":[
                        {
                           "level":30,
                           "slug":"a",
                           "order":1,
                           "css_class":"",
                           "children":[
                              {
                                 "level":40,
                                 "slug":"a",
                                 "order":1,
                                 "css_class":"",
                                 "component":{
                                    "layout":4,
                                    "comp_id":"hero",
                                    "ltext":"Home Hero",
                                    "css_class":"",
                                    "card_body_class":"",
                                    "hero_content_class":"",
                                    "hero_overlay":true,
                                    "hero_overlay_style":"",
                                    "config":{
                                       
                                    },
                                    "hidden":false,
                                    "order":1,
                                    "slots":[
                                       {
                                          "component":1,
                                          "slot_type":"text",
                                          "order":1,
                                          "hidden":false,
                                          "ltext":"",
                                          "css_class":"",
                                          "figure_class":"",
                                          "actions_class":"",
                                          "accordion_checked":false,
                                          "textblocks":[
                                             {
                                                "block_id":"title",
                                                "order":1,
                                                "css_class":"",
                                                "ltext":"Home Title",
                                                "href_page":"",
                                                "items":[
                                                   {
                                                      "type":"text",
                                                      "order":1,
                                                      "css_class":"",
                                                      "values":{
                                                         "en":{
                                                            "stext":"Home Title",
                                                            "ltext":""
                                                         },
                                                         "fr":{
                                                            "stext":"frHome Title",
                                                            "ltext":""
                                                         }
                                                      }
                                                   }
                                                ]
                                             },
                                             {
                                                "block_id":"content",
                                                "order":2,
                                                "css_class":"",
                                                "ltext":"Home content",
                                                "href_page":"",
                                                "items":[
                                                   {
                                                      "type":"text",
                                                      "order":1,
                                                      "css_class":"",
                                                      "values":{
                                                         "en":{
                                                            "stext":"Home Content",
                                                            "ltext":""
                                                         },
                                                         "fr":{
                                                            "stext":"frHome Content",
                                                            "ltext":""
                                                         }
                                                      }
                                                   }
                                                ]
                                             }
                                          ]
                                       },
                                       {
                                          "component":1,
                                          "slot_type":"figure",
                                          "order":2,
                                          "hidden":false,
                                          "ltext":"",
                                          "css_class":"",
                                          "image_url":"https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp",
                                          "alt":"Spiderman",
                                          "figure_class":"px-0 pt-0",
                                          "actions_class":"",
                                          "accordion_checked":false
                                       }
                                    ]
                                 }
                              }
                           ]
                        }
                     ]
                  }
               ]
            }
         ]
      },
      {
         "client":1,
         "page_id":"about",
         "ltext":"About Page",
         "order":2,
         "hidden":false,
         "translations":{
            "name":{
               "en":"About",
               "hi":"hiAbout",
               "fr":"frAbout",
               "ta":null
            }
         },
         "layouts":[
            {
               "level":10,
               "slug":"a",
               "order":1,
               "css_class":"",
               "children":[
                  {
                     "level":20,
                     "slug":"a",
                     "order":1,
                     "css_class":"",
                     "children":[
                        {
                           "level":30,
                           "slug":"a",
                           "order":1,
                           "css_class":"",
                           "children":[
                              {
                                 "level":40,
                                 "slug":"a",
                                 "order":1,
                                 "css_class":"",
                                 "component":{
                                    "layout":8,
                                    "comp_id":"hero",
                                    "ltext":"About Hero",
                                    "css_class":"hero min-h-screen",
                                    "card_body_class":"",
                                    "hero_content_class":"",
                                    "hero_overlay":true,
                                    "hero_overlay_style":"",
                                    "config":{
                                       
                                    },
                                    "hidden":false,
                                    "order":1,
                                    "slots":[
                                       {
                                          "component":2,
                                          "slot_type":"figure",
                                          "order":1,
                                          "hidden":false,
                                          "ltext":"",
                                          "css_class":"",
                                          "image_url":"https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp",
                                          "alt":"Spiderman",
                                          "figure_class":"px-0 pt-0",
                                          "actions_class":"",
                                          "accordion_checked":false
                                       },
                                       {
                                          "component":2,
                                          "slot_type":"text",
                                          "order":2,
                                          "hidden":false,
                                          "ltext":"",
                                          "css_class":"",
                                          "figure_class":"",
                                          "actions_class":"",
                                          "accordion_checked":false,
                                          "textblocks":[
                                             {
                                                "block_id":"title",
                                                "order":1,
                                                "css_class":"",
                                                "ltext":"About Title",
                                                "href_page":"",
                                                "items":[
                                                   {
                                                      "type":"text",
                                                      "order":1,
                                                      "css_class":"",
                                                      "values":{
                                                         "en":{
                                                            "stext":"About Title",
                                                            "ltext":""
                                                         },
                                                         "fr":{
                                                            "stext":"frAbout Title",
                                                            "ltext":""
                                                         }
                                                      }
                                                   }
                                                ]
                                             },
                                             {
                                                "block_id":"content",
                                                "order":2,
                                                "css_class":"",
                                                "ltext":"About content",
                                                "href_page":"",
                                                "items":[
                                                   {
                                                      "type":"text",
                                                      "order":1,
                                                      "css_class":"",
                                                      "values":{
                                                         "en":{
                                                            "stext":"About Content",
                                                            "ltext":""
                                                         },
                                                         "fr":{
                                                            "stext":"frAbout Content",
                                                            "ltext":""
                                                         }
                                                      }
                                                   }
                                                ]
                                             }
                                          ]
                                       }
                                    ]
                                 }
                              }
                           ]
                        }
                     ]
                  }
               ]
            }
         ]
      }
   ],
   "page_tree":[
      {
         "client_id":"bahushira",
         "page_id":"home",
         "order":1,
         "translations":{
            "name":{
               "en":"Home",
               "hi":"hiHome",
               "fr":"frHome",
               "ta":null
            }
         },
         "children":[
            
         ]
      },
      {
         "client_id":"bahushira",
         "page_id":"about",
         "order":2,
         "translations":{
            "name":{
               "en":"About",
               "hi":"hiAbout",
               "fr":"frAbout",
               "ta":null
            }
         },
         "children":[
            
         ]
      }
   ],
   "header_nav":[
      {
         "client":1,
         "location":"header",
         "nav_type":"page",
         "page":1,
         "url":"",
         "order":1,
         "hidden":false,
         "open_in_new_tab":false,
         "translations":{
            "name":{
               "en":"home2",
               "hi":"hihome2",
               "fr":"frhome2",
               "ta":null
            }
         },
         "href":"home",
         "children":[
            
         ]
      },
      {
         "client":1,
         "location":"header",
         "nav_type":"page",
         "page":2,
         "url":"",
         "order":2,
         "hidden":false,
         "open_in_new_tab":false,
         "translations":{
            "name":{
               "en":"about2",
               "hi":"hiabout2",
               "fr":"frabout2",
               "ta":null
            }
         },
         "href":"about",
         "children":[
            
         ]
      }
   ],
   "footer_nav":[
      
   ]
}
"""