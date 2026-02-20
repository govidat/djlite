from collections import defaultdict
from django.core.cache import cache

#from mysite.models import Client, ClientLanguage, ClientTheme, ClientPage, TextStatic, Image, Svg, Layout, Hero, Card, Client2
from mysite.models import Language, Theme, Client, Card, Hero, Layout, Page, HeroText, HeroCardText, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue
from django.db.models import Prefetch
#from django.http import JsonResponse
#import json
#from functools import lru_cache

from django.contrib.contenttypes.models import ContentType


# This is NOT USED a modified version and takes the key_name or the field on which the relationship is built.
# But used in ZAPP - to evaluate ZAPP
def build_nested_hierarchy(flat_list, key_name="id"):
    # Create a dictionary for quick lookup of items by their ID
    item_map = {item[key_name]: item for item in flat_list}

    # Initialize a list to store the top-level items (roots)
    nested_list = []

    # Iterate through each item to build the hierarchy
    for item in flat_list:
        parent = item.get('parent')

        # If the item has a parent, add it to the parent's children list
        if parent is not None and parent in item_map:
            parent_item = item_map[parent]
            if 'children' not in parent_item:
                parent_item['children'] = []
            parent_item['children'].append(item)
        # If the item has no parent, it's a top-level item
        else:
            nested_list.append(item)

    return nested_list

# This is NOT USED used to update the values in navbar
def update_list_of_dictionaries(smaller_list, larger_list, key_field):
    """
    Updates dictionaries in the smaller_list with values from matching dictionaries
    in the larger_list based on a common key.

    Args:
        smaller_list (list): The list of dictionaries to be updated.
        larger_list (list): The list of dictionaries containing the source values.
        key_field (str): The common key used for matching dictionaries in both lists.

    Returns:
        list: The updated smaller_list of dictionaries.
    """
    # Create a dictionary for efficient lookup in the larger_list
    larger_dict_map = {d[key_field]: d for d in larger_list if key_field in d}

    for smaller_dict in smaller_list:
        if key_field in smaller_dict and smaller_dict[key_field] in larger_dict_map:
            matching_larger_dict = larger_dict_map[smaller_dict[key_field]]
            # Update the smaller dictionary with values from the larger one
            smaller_dict.update(matching_larger_dict)
    return smaller_list


#Step 1: Universal Prefetch for TextContent Tree
# Universal Text Block Tree
stbitem_prefetch = Prefetch(
    "textstbitems",
    queryset=TextstbItem.objects.prefetch_related(
        Prefetch(
            "svgtextbadgevalue_set",
            queryset=SvgtextbadgeValue.objects.select_related("language"),
        )
    ).order_by("order"),
)

comptextblock_prefetch = Prefetch(
    "comptextblocks",
    queryset=ComptextBlock.objects.prefetch_related(
        stbitem_prefetch
    ).order_by("order"),
)

gentextblock_prefetch = Prefetch(
    "gentextblocks",
    queryset=GentextBlock.objects.prefetch_related(
        stbitem_prefetch
    ).order_by("order"),
)


#Step 2: Component-Level Prefetch
# Hero subtree

hero_prefetch = Prefetch(
    "hero",
    queryset=Hero.objects.select_related(
        "herotext",
        "herofigure",
        "herocard",
        "herocard__herocardtext",
        "herocard__herocardfigure"
    ).prefetch_related(
        Prefetch(
            "herotext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
        ),
        Prefetch(
            "herocard__herocardtext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
        ),
    ),
)

# Card subtree

card_prefetch = Prefetch(
    "card",
    queryset=Card.objects.select_related(
        "cardtext",
        "cardfigure",
    ).prefetch_related(
        Prefetch(
            "cardtext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
        )
    ),
)


#Step 3: Layout Tree (Single Fetch, Ordered)
layout_prefetch = Prefetch(
    "layouts",
    queryset=Layout.objects.select_related(
        "parent",
    ).prefetch_related(
        hero_prefetch,
        card_prefetch,
    ).order_by("level", "order"),
)


def get_attr(obj, attr):
    return getattr(obj, attr, None)

def visible(obj):
    return obj if obj and not getattr(obj, "hidden", False) else None



# 1️⃣ Lowest Layer — SvgtextbadgeValue
def build_values(item):
    return {
        val.language.language_id: {
            "stext": val.stext,
            "ltext": val.ltext,
        }
        for val in item.svgtextbadgevalue_set.all()
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
        data["values"] = {
            val.language.language_id: {
                "stext": val.stext,
                "ltext": val.ltext,
            }
            for val in item.svgtextbadgevalue_set.all()
        }

    return data

# 3️⃣ Generic Block Builder
# (Works for both ComptextBlock and GentextBlock)
def build_blocks(blocks_queryset):
    result = {}

    for block in blocks_queryset:
        if not visible(block):
            continue

        items = [
            build_stb_item(item)
            for item in block.textstbitems.all()
        ]

        # Remove None items
        items = [i for i in items if i]

        if not items:
            continue  # skip empty blocks

        block_data = {
            "order": block.order,
            "css_class": block.css_class,
            "ltext": block.ltext,
            "items": items,
        }

        result.setdefault(block.block_id, []).append(block_data)

    return result


# 4️⃣ Component Builders
# HeroText
def build_hero_text(ht):
    ht = visible(ht)
    if not ht:
        return None

    textblocks = build_blocks(ht.comptextblocks.all())
    if not textblocks:
        return None

    return {
        "hidden": ht.hidden,
        "type_id": "text",
        "order": ht.order,
        "ltext": ht.ltext,
        "actions_class": ht.actions_class,
        "actions_position": ht.actions_position_id,
        "textblocks": textblocks,
    }
# HeroFigure
def build_hero_figure(hf):
    hf = visible(hf)
    if not hf:
        return None

    return {
        "hidden": hf.hidden,
        "type_id": "figure",
        "order": hf.order,
        "ltext": hf.ltext,
        "figure_class": hf.figure_class,
        "position_id": hf.position_id,
        "image_url": hf.image_url if hf.image_url else None,
        "css_class": hf.css_class,
        "alt": hf.alt,
    }



# HeroCardText
def build_herocard_text(obj):
    obj = visible(obj)
    if not obj:
        return None

    return {
        "hidden": obj.hidden,
        "type_id": "text",
        "order": obj.order,
        "ltext": obj.ltext,
        "actions_class": obj.actions_class,
        "actions_position": obj.actions_position_id,
        "textblocks": build_blocks(obj.comptextblocks.all()),
    }

# HeroCardFigure
def build_herocard_figure(obj):
    obj = visible(obj)
    if not obj:
        return None

    return {
        "hidden": obj.hidden,
        "type_id": "figure",
        "order": obj.order,
        "ltext": obj.ltext,
        "figure_class": obj.figure_class,
        "position_id": obj.position_id,
        "image_url": obj.image_url if obj.image_url else None,
        "css_class": obj.css_class,
        "alt": obj.alt,
    }

# HeroCard
def build_herocard(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_herocard_figure(get_attr(obj, "herocardfigure"))
    if figure:
        contents.append(figure)

    text = build_herocard_text(get_attr(obj, "herocardtext"))
    if text:
        contents.append(text)

    contents.sort(key=lambda x: x["order"])

    return {
        "hidden": obj.hidden,
        "type_id": "herocard",
        "order": obj.order,
        "ltext": obj.ltext,
        "css_class": obj.css_class,
        "contents": contents,
    }

# Hero
def build_hero(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_hero_figure(get_attr(obj, "herofigure"))
    if figure:
        contents.append(figure)

    text = build_hero_text(get_attr(obj, "herotext"))
    if text:
        contents.append(text)

    herocard = build_herocard(get_attr(obj, "herocard"))
    if herocard:
        contents.append(herocard)

    contents.sort(key=lambda x: x["order"])

    return {
        "css_class": obj.css_class,
        "herocontent_class": obj.herocontent_class,
        "overlay": obj.overlay,
        "overlay_style": obj.overlay_style,
        "herocontents": contents,
        "comp_id": "hero",
    }


# CardFigure
def build_card_figure(obj):
    obj = visible(obj)
    if not obj:
        return None

    return {
        "hidden": obj.hidden,
        "type_id": "figure",
        "order": obj.order,
        "ltext": obj.ltext,
        "figure_class": obj.figure_class,
        "position_id": obj.position_id,
        "image_url": obj.image_url if obj.image_url else None,
        "css_class": obj.css_class,
        "alt": obj.alt,
    }

# CardText
def build_card_text(obj):
    obj = visible(obj)
    if not obj:
        return None

    return {
        "hidden": obj.hidden,
        "type_id": "text",
        "order": obj.order,
        "ltext": obj.ltext,
        "actions_class": obj.actions_class,
        "actions_position": obj.actions_position_id,
        "textblocks": build_blocks(obj.comptextblocks.all()),
    }


# Card
def build_card(obj):
    obj = visible(obj)
    if not obj:
        return None

    contents = []

    figure = build_card_figure(get_attr(obj, "cardfigure"))
    if figure:
        contents.append(figure)

    text = build_card_text(get_attr(obj, "cardtext"))
    if text:
        contents.append(text)

    contents.sort(key=lambda x: x["order"])

    return {
        "hidden": obj.hidden,
        "comp_id": "card",
        "order": obj.order,
        "ltext": obj.ltext,
        "css_class": obj.css_class,
        "contents": contents,
    }

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

    if layout.comp_id == "hero":
      component = build_hero(get_attr(layout, "hero"))

    elif layout.comp_id == "card":
        component = build_card(get_attr(layout, "card"))

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
"""
def build_layout(layout):
    layout = visible(layout)
    if not layout:
        return None

    layout_data = {
        "level": layout.level,
        "slug": layout.slug,
        "order": layout.order,
        "css_class": layout.css_class,
    }

    component = None

    if layout.comp_id == "hero":
        hero = visible(get_attr(layout, "hero"))
        if hero:
            component = {
                "type": "hero",
                "herotext": build_herotext(
                    visible(get_attr(hero, "herotext"))
                ),
            }

    elif layout.comp_id == "card":
        card = visible(get_attr(layout, "card"))
        if card:
            component = {
                "type": "card",
                "cardtext": build_cardtext(
                    visible(get_attr(card, "cardtext"))
                ),
            }

    if not component:
        return None

    layout_data["component"] = component
    return layout_data
"""

# 6️⃣ Page Builder

def build_page(page):
    page = visible(page)
    if not page:
        return None

    all_layouts = list(page.layouts.all())

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
        "textblocks": build_blocks(page.gentextblocks.all()),
        "layouts": layouts,
    }
"""
def build_page(page):
    page = visible(page)
    if not page:
        return None

    layouts = [
        build_layout(layout)
        for layout in page.layouts.all()
    ]

    layouts = [l for l in layouts if l]

    return {
        "page_id": page.page_id,
        "order": page.order,
        "textblocks": build_blocks(page.gentextblocks.all()),
        "layouts": layouts,
    }
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

        node_map[page.id] = {
            "client_id": page.client.client_id,
            "page_id": page.page_id,
            "order": page.order,
            "textblocks": build_blocks(page.gentextblocks.all()),
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

# 7️⃣ FINAL: build_client_payload()
def build_client_payload(client):

    # Create a lookup dictionary
    """
    master_language = {c.language_id: c.label_obj for c in Language.objects.filter(language_id__in=client.language_list)}
    master_theme = {c.theme_id: c.label_obj for c in Theme.objects.filter(theme_id__in=client.theme_list)}
    """
    languages_qs = Language.objects.filter(
        language_id__in=client.language_list
    )

    themes_qs = Theme.objects.filter(
        theme_id__in=client.theme_list
    )

    # Preserve client order
    language_lookup = {l.language_id: l for l in languages_qs}
    theme_lookup = {t.theme_id: t for t in themes_qs}
    lv_languages = [
        {
            "language_id": lang_id,
            "labels": language_lookup[lang_id].label_obj 
        }
        for lang_id in client.language_list
        if lang_id in language_lookup
    ]

    lv_themes = [
        {
            "theme_id": theme_id,
            "labels": theme_lookup[theme_id].label_obj
        }
        for theme_id in client.theme_list
        if theme_id in theme_lookup
    ]
    
    return {
        "client_id": client.client_id,
        "languages": lv_languages,
        "themes": lv_themes,
    
        "parent": client.parent.client_id if client.parent else None,

        "textblocks": build_blocks(client.gentextblocks.all()),

        "pages": [
            build_page(page)
            for page in client.pages.all()
        ],
        "page_tree": build_page_tree(
            [l for l in client.pages.all() if not l.hidden]
        ), # this is for navigation bar requirement. this is nested # xyz.all() without filter works with prefetch
        # this is for navigation bar requirement. this is nested
        "client_theme": "light"

    }



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
          #ContentType.objects.get_for_models(
          #  Client,
          #  Page,
          #  HeroText,
          #  HeroCardText,
          #)
          qs_client = (
            Client.objects
            .select_related("parent")  # Add this if you access parent
            .prefetch_related(
                gentextblock_prefetch,
                Prefetch(
                    "pages",
                    queryset=Page.objects.select_related(
                        "parent"
                    ).prefetch_related(
                        gentextblock_prefetch,
                        layout_prefetch,
                    ).order_by("order"),
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
      
        # do many sql calls and update the list
        """    
            
            #client_ancestors=client_static['client'].get_ancestors()
            #client_static['client_hierarchy_list'] = [lv_client_id] + client_ancestors + ['default']
            # expected value is a list of client_ids

            # Build query for client_nb_items
            #client_static['client_nb_items'] = ClientNavbar.objects.filter(client__client_id=lv_client_id).values('id', 'page_id', 'client_page', 'parent', 'order').order_by('order')        
            #client_static['client_nb_items_nested'] = build_nested_hierarchy(client_static['client_nb_items'], 'client_page')

            # using a function module here leads to some async errors, hence explicitly doing the reshape here
            #qsnb = ClientPage.objects.filter(client__client_id=lv_client_id).values('id', 'page_id', 'comp_unique', 'parent', 'order').order_by('order')
            # reshape result
                # Create a dictionary for quick lookup of items by their client_page
            #item_map = {item['id']: item for item in qsnb}

            # Initialize a list to store the top-level items (roots)
            #nested_list = []

            # Iterate through each item to build the hierarchy
            #for item in qsnb:
            #    parent = item.get('parent')

                # If the item has a parent, add it to the parent's children list
            #    if parent is not None and parent in item_map:
            #        parent_item = item_map[parent]
            #        if 'children' not in parent_item:
            #            parent_item['children'] = []
            #        parent_item['children'].append(item)
                # If the item has no parent, it's a top-level item
            #    else:
            #        nested_list.append(item)
            #client_static['nb_items_nested'] = nested_list

            
        else:
            # push some content into this to display an error message
            client_static = {}
        """  
    #else:
        # push some content into this to display an error message
    #    client_static = {}

  
    # Cache it
    if cache_key:
        cache.set(cache_key, client_static, timeout=timeout)

    
    return client_static
"""
{
  "client_id": "bahushira",
  "languages": [
    {
      "language_id": "en",
      "labels": {
        "en": "English",
        "fr": "frEnglish",
        "hi": "hiEnglish"
      }
    },
    {
      "language_id": "fr",
      "labels": {
        "en": "French",
        "fr": "frFrench",
        "hi": "hiFrench"
      }
    },
    {
      "language_id": "hi",
      "labels": {
        "en": "Hindi",
        "fr": "frHindi",
        "hi": "hiHindi"
      }
    }
  ],
  "themes": [
    {
      "theme_id": "aqua",
      "labels": {
        "en": "Aqua",
        "fr": "frAqua",
        "hi": "hiAqua"
      }
    },
    {
      "theme_id": "dark",
      "labels": {
        "en": "Dark",
        "fr": "frDark",
        "hi": "hiDark"
      }
    },
    {
      "theme_id": "light",
      "labels": {
        "en": "Light",
        "fr": "frLight",
        "hi": "hiLight"
      }
    }
  ],
  "parent": "None",
  "textblocks": {
    "name": [
      {
        "order": 1,
        "css_class": "None",
        "ltext": "None",
        "items": [
          {
            "type": "text",
            "order": 1,
            "css_class": "None",
            "values": {
              "en": {
                "stext": "Bahushira",
                "ltext": "ltBahushira"
              },
              "fr": {
                "stext": "frBahushira",
                "ltext": "ltfrBahushira"
              },
              "hi": {
                "stext": "hiBahushira",
                "ltext": "lthiBahushira"
              }
            }
          }
        ]
      }
    ],
    "nb_title": [
      {
        "order": 1,
        "css_class": "None",
        "ltext": "None",
        "items": [
          {
            "type": "text",
            "order": 1,
            "css_class": "None",
            "values": {
              "en": {
                "stext": "Bahushira Nav Bar",
                "ltext": ""
              },
              "fr": {
                "stext": "frBahushira Nav Bar",
                "ltext": ""
              },
              "hi": {
                "stext": "hiBahushira Nav Bar",
                "ltext": ""
              }
            }
          }
        ]
      }
    ]
  },
  "pages": [
    {
      "page_id": "home",
      "order": 1,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "Home",
                    "ltext": ""
                  },
                  "fr": {
                    "stext": "frHome",
                    "ltext": ""
                  },
                  "hi": {
                    "stext": "hiHome",
                    "ltext": ""
                  }
                }
              }
            ]
          }
        ]
      },
      "layouts": 
        [
          {
            "level": 10,
            "slug": "a",
            "order": 1,
            "css_class": "",
            "comp_id": "",
            "children": [
              {
                "level": 20,
                "slug": "a",
                "order": 1,
                "css_class": "",
                "comp_id": "",
                "children": [
                  {
                    "level": 30,
                    "slug": "a",
                    "order": 1,
                    "css_class": "",
                    "comp_id": "",
                    "children": [
                      {
                        "level": 40,
                        "slug": "a",
                        "order": 1,
                        "css_class": "",
                        "comp_id": "hero",
                        "component": {
                          "css_class": "",
                          "herocontent_class": "",
                          "overlay": "False",
                          "overlay_style": "",
                          "herocontents": [
                            {
                              "hidden": "False",
                              "type_id": "text",
                              "order": 1,
                              "ltext": "None",
                              "actions_class": "None",
                              "actions_position": "end",
                              "textblocks": {
                                "title": [
                                  {
                                    "order": 1,
                                    "css_class": "None",
                                    "ltext": "None",
                                    "items": [
                                      {
                                        "type": "text",
                                        "order": 1,
                                        "css_class": "None",
                                        "values": {
                                          "en": {
                                            "stext": "Bahushira Home Page Hero",
                                            "ltext": "ltBahushira Home Page Hero"
                                          },
                                          "fr": {
                                            "stext": "frBahushira Home Page Hero",
                                            "ltext": "ltfrBahushira Home Page Hero"
                                          },
                                          "hi": {
                                            "stext": "hiBahushira Home Page Hero",
                                            "ltext": "lthiBahushira Home Page Hero"
                                          }
                                        }
                                      }
                                    ]
                                  }
                                ]
                              }
                            },
                            {
                              "hidden": "False",
                              "type_id": "figure",
                              "order": 2,
                              "ltext": "None",
                              "figure_class": "px-0 pt-0",
                              "position_id": "start",
                              "image_url": "https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp",
                              "css_class": "None",
                              "alt": "Spiderman"
                            }
                          ],
                          "comp_id": "hero"
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
      "page_id": "about",
      "order": 2,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "About",
                    "ltext": "ltAbout"
                  },
                  "fr": {
                    "stext": "frAbout",
                    "ltext": "ltfrAbout"
                  },
                  "hi": {
                    "stext": "hiAbout",
                    "ltext": "lthiAbout"
                  }
                }
              }
            ]
          }
        ]
      },
      "layouts": []
    },
    {
      "page_id": "team",
      "order": 3,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "Team",
                    "ltext": "ltTeam"
                  },
                  "fr": {
                    "stext": "frTeam",
                    "ltext": "ltfrTeam"
                  },
                  "hi": {
                    "stext": "hiTeam",
                    "ltext": "lthiTeam"
                  }
                }
              }
            ]
          }
        ]
      },
      "layouts": []
    },
    {
      "page_id": "contact",
      "order": 4,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "Contact",
                    "ltext": "ltContact"
                  },
                  "fr": {
                    "stext": "frContact",
                    "ltext": "ltfrContact"
                  },
                  "hi": {
                    "stext": "hiContact",
                    "ltext": "lthiContact"
                  }
                }
              }
            ]
          }
        ]
      },
      "layouts": []
    }
  ],
  "page_tree": [
    {
      "client_id": "bahushira",
      "page_id": "home",
      "order": 1,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "Home",
                    "ltext": ""
                  },
                  "fr": {
                    "stext": "frHome",
                    "ltext": ""
                  },
                  "hi": {
                    "stext": "hiHome",
                    "ltext": ""
                  }
                }
              }
            ]
          }
        ]
      },
      "children": []
    },
    {
      "client_id": "bahushira",
      "page_id": "about",
      "order": 2,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "About",
                    "ltext": "ltAbout"
                  },
                  "fr": {
                    "stext": "frAbout",
                    "ltext": "ltfrAbout"
                  },
                  "hi": {
                    "stext": "hiAbout",
                    "ltext": "lthiAbout"
                  }
                }
              }
            ]
          }
        ]
      },
      "children": []
    },
    {
      "client_id": "bahushira",
      "page_id": "team",
      "order": 3,
      "textblocks": {
        "name": [
          {
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "items": [
              {
                "type": "text",
                "order": 1,
                "css_class": "None",
                "values": {
                  "en": {
                    "stext": "Team",
                    "ltext": "ltTeam"
                  },
                  "fr": {
                    "stext": "frTeam",
                    "ltext": "ltfrTeam"
                  },
                  "hi": {
                    "stext": "hiTeam",
                    "ltext": "lthiTeam"
                  }
                }
              }
            ]
          }
        ]
      },
      "children": [
        {
          "client_id": "bahushira",
          "page_id": "contact",
          "order": 4,
          "textblocks": {
            "name": [
              {
                "order": 1,
                "css_class": "None",
                "ltext": "None",
                "items": [
                  {
                    "type": "text",
                    "order": 1,
                    "css_class": "None",
                    "values": {
                      "en": {
                        "stext": "Contact",
                        "ltext": "ltContact"
                      },
                      "fr": {
                        "stext": "frContact",
                        "ltext": "ltfrContact"
                      },
                      "hi": {
                        "stext": "hiContact",
                        "ltext": "lthiContact"
                      }
                    }
                  }
                ]
              }
            ]
          },
          "children": []
        }
      ]
    }
  ]
}
"""


