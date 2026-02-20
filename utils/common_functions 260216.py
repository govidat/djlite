from collections import defaultdict
from django.core.cache import cache
#from mysite.models import Translation, TextStatic
#from mysite.models import Client, ClientLanguage, ClientTheme, ClientPage, TextStatic, Image, Svg, Layout, Hero, Card, Client2
from mysite.models import Language, Theme, Client, TextContent, TextBlock, TextBlockItem, TextItemValue, Card, Hero, Layout, Page, HeroText, HeroCardText, ComptextBlock, GentextBlock, TextstbItem
from django.db.models import Prefetch
#from django.http import JsonResponse
import json
#from functools import lru_cache

from django.contrib.contenttypes.models import ContentType

# This is a modified version and takes the key_name or the field on which the relationship is built.
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

# This is used to update the values in navbar
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

textcontent_prefetch = Prefetch(
    "textcontents",
    queryset=TextContent.objects.prefetch_related(
        Prefetch(
            "blocks",
            queryset=TextBlock.objects.prefetch_related(
                Prefetch(
                    "items",
                    queryset=TextBlockItem.objects.prefetch_related(
                        Prefetch(
                            "translations",
                            queryset=TextItemValue.objects.select_related("language"),
                            #queryset=TextItemValue.objects.all(),
                        ),
                    ),
                )
            ),
        )
    ),
)

comptextblock_prefetch = Prefetch(
    "comptextblocks",
    queryset=ComptextBlock.objects.prefetch_related(
      Prefetch(
          "items",
          queryset=TextstbItem.objects.prefetch_related(
              Prefetch(
                  "translations",
                  queryset=TextItemValue.objects.select_related("language"),
                  #queryset=TextItemValue.objects.all(),
              ),
          ),
      )
    ),
)

gentextblock_prefetch = Prefetch(
    "gentextblocks",
    queryset=GentextBlock.objects.prefetch_related(
      Prefetch(
          "items",
          queryset=TextstbItem.objects.prefetch_related(
              Prefetch(
                  "translations",
                  queryset=TextItemValue.objects.select_related("language"),
                  #queryset=TextItemValue.objects.all(),
              ),
          ),
      )
    ),
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
            "herotext__textcontents",
            queryset=textcontent_prefetch.queryset,
            #to_attr="prefetched_textcontents"
        ),
        Prefetch(
            "herocard__herocardtext__textcontents",
            queryset=textcontent_prefetch.queryset,
            #to_attr="prefetched_textcontents"
        ),
        Prefetch(
            "herotext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
            #to_attr="prefetched_textcontents"
        ),
        Prefetch(
            "herocard__herocardtext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
            #to_attr="prefetched_textcontents"
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
            "cardtext__textcontents",
            queryset=textcontent_prefetch.queryset,
            #to_attr="prefetched_textcontents"
        ),
        Prefetch(
            "cardtext__comptextblocks",
            queryset=comptextblock_prefetch.queryset,
            #to_attr="prefetched_textcontents"
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

# following code for converting a qs to json
# Target JSON
"""
{

    "client_id": "acme",
    "languages": ["en", "fr"],
    "themes": ["default"],
    "translations": {
      "en": { "stext": "...", "ltext": "..." }
    },

    "pages": [
      {
        "page_id": "home",
        "ltext": "Home",
        "order": 1,
        "hidden": false,
        "translations": { "en": { "stext": "...", "ltext": "..." } },

        "layout_tree": [
          {
            "id": 12,
            "level": 10,
            "slug": "section-1",
            "order": 1,
            "css_class": "",
            "style": "",
            "hidden": false,
            "children": [
              {
                "id": 13,
                "level": 20,
                "slug": "row-1",
                "order": 1,
                "children": [
                  {
                    "id": 14,
                    "level": 30,
                    "slug": "col-1",
                    "order": 1,
                    "children": [
                      {
                        "id": 15,
                        "level": 40,
                        "slug": "cell-hero",
                        "order": 1,
                        "component": {
                          "type": "hero",

                          "hero": {
                            "css_class": "",
                            "overlay": false,
                            "overlay_style": "",

                            "text": {
                              "order": 1,
                              "hidden": false,
                              "ltext": "",
                              "actions": {
                                "class": "",
                                "position": "start"
                              },
                              "contents": [TEXT_CONTENT]
                            },

                            "figure": {
                              "order": 2,
                              "hidden": false,
                              "image_url": "",
                              "alt": "",
                              "position": "end"
                            },

                            "card": {
                              "order": 3,
                              "hidden": false,
                              "ltext": "",
                              "css_class": "",
                              "body_class": "",

                              "text": {
                                "hidden": false,
                                "actions": {
                                  "class": "",
                                  "position": "start"
                                },
                                "contents": [TEXT_CONTENT]
                              },

                              "figure": {
                                "hidden": false,
                                "image_url": "",
                                "alt": "",
                                "position": "end"
                              }
                            }
                          }
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
    ]
  
}
"""
# Text_Content
"""
{
  "id": 91,
  "hidden": false,
  "ltext": "Main Title",

  "blocks": [
    {
      "block_id": "title",
      "hidden": false,
      "css_class": "",
      "items": [
        {
          "item_id": "text",
          "hidden": false,
          "order": 1,
          "css_class": "",
          "svg_text": null,

          "translations": {
            "en": { "stext": "Welcome", "ltext": "Welcome" },
            "fr": { "stext": "Bienvenue", "ltext": "Bienvenue" }
          }
        }
      ]
    }
  ]
}
"""
def get_attr(obj, attr):
    try:
        return getattr(obj, attr)
    except Exception:
        return None

def visible(obj):
    return obj if obj and not getattr(obj, "hidden", False) else None

# A. Translation helper


def build_translations(qs):
    return {    
        t.language.language_id: {
            "stext": t.stext,
            "ltext": t.ltext,
        }
        for t in qs
    }

# B. TextContent builder (core reusable unit)
def build_textcontent(tc):
    return {
        "id": tc.id,
        "hidden": tc.hidden,
        "ltext": tc.ltext,
        "blocks": [
            {
                "block_id": b.block_id,
                "hidden": b.hidden,
                "css_class": b.css_class,
                "items": [
                    {
                        "item_id": i.item_id,
                        "hidden": i.hidden,
                        "order": i.order,
                        "css_class": i.css_class,
                        "svg_text": i.svg_text,
                        "translations": build_translations(i.translations.all()),
                    }
                    for i in b.items.all()
                ],
            }
            for b in tc.blocks.all()
        ],
    }

# C. Hero builder (fully drilled)
def build_hero(hero):
    herotext = visible(get_attr(hero, "herotext"))
    herofigure = visible(get_attr(hero, "herofigure"))  
    herocard = visible(get_attr(hero, "herocard"))
    herocardtext = visible(get_attr(herocard, "herocardtext"))
    herocardfigure = visible(get_attr(herocard, "herocardfigure"))  

    return {
        "css_class": hero.css_class,
        "overlay": hero.overlay,
        "overlay_style": hero.overlay_style,

        "text": (
            {
                "order": hero.herotext.order,
                "hidden": hero.herotext.hidden,
                "ltext": hero.herotext.ltext,
                "actions": {
                    "class": hero.herotext.actions_class,
                    "position": hero.herotext.actions_position_id,
                },
                "contents": [
                    build_textcontent(tc)
                    for tc in hero.herotext.textcontents.all()
                ],
            }
            if herotext else None            
        ),

        "figure": (
            {
                "order": hero.herofigure.order,
                "hidden": hero.herofigure.hidden,
                "image_url": hero.herofigure.image_url,
                "alt": hero.herofigure.alt,
                "position": hero.herofigure.position_id,
            }
            if herofigure else None
        ),

        "card": (
            {
                "order": hero.herocard.order,
                "hidden": hero.herocard.hidden,
                "ltext": hero.herocard.ltext,
                "css_class": hero.herocard.css_class,
                "body_class": hero.herocard.body_class,
                "text": (
                    {
                        "hidden": hero.herocard.herocardtext.hidden,
                        "actions": {
                            "class": hero.herocard.herocardtext.actions_class,
                            "position": hero.herocard.herocardtext.actions_position_id,
                        },
                        "contents": [
                            build_textcontent(tc)
                            for tc in hero.herocard.herocardtext.textcontents.all()
                        ],
                    }
                    if herocardtext else None
                ),

                "figure": (
                    {
                        "hidden": hero.herocard.herocardfigure.hidden,
                        "image_url": hero.herocard.herocardfigure.image_url,
                        "alt": hero.herocard.herocardfigure.alt,
                        "position": hero.herocard.herocardfigure.position_id,
                    }
                    if herocardfigure else None
                ),
            }
            if herocard else None
        ),
    }

# D. Card builder
def build_card(card):
    cardtext = visible(get_attr(card, "cardtext"))
    cardfigure = visible(get_attr(card, "cardfigure"))  

    return {
        "ltext": card.ltext,
        "css_class": card.css_class,
        "body_class": card.body_class,

        "text": (
            {
                "hidden": card.cardtext.hidden,
                "actions": {
                    "class": card.cardtext.actions_class,
                    "position": card.cardtext.actions_position_id,
                },
                "contents": [
                    build_textcontent(tc)
                    for tc in card.cardtext.textcontents.all()
                ],
            }
            if cardtext else None
        ),

        "figure": (
            {
                "hidden": card.cardfigure.hidden,
                "image_url": card.cardfigure.image_url,
                "alt": card.cardfigure.alt,
                "position": card.cardfigure.position_id,
            }
            if cardfigure else None
        ),
    }

# E. Layout tree builder (critical)
def build_layout_tree(layouts):
    by_parent = {}
    for l in layouts:
        by_parent.setdefault(l.parent_id, []).append(l)

    def build_node(l):
        node = {
            "id": l.id,
            "level": l.level,
            "slug": l.slug,
            "order": l.order,
            "css_class": l.css_class,
            "style": l.style,
            "hidden": l.hidden,
            "children": [],
        }

        if l.level == 40:
            if l.comp_id == "hero":
                node["component"] = {
                    "type": "hero",
                    "hero": build_hero(l.hero),
                }
            elif l.comp_id == "card":
                node["component"] = {
                    "type": "card",
                    "card": build_card(l.card),
                }

        node["children"] = [
            build_node(c)
            for c in by_parent.get(l.id, [])
        ]
        return node

    return [
        build_node(l)
        for l in by_parent.get(None, [])
    ]

# F. Page tree for Navigation bar
def build_page_tree(pages):
    node_map = {}
    roots = []
    
    # Step 1: create flat nodes
    for page in pages:
        node_map[page.id] = {
            "client_id": page.client.client_id,
            "page_id": page.page_id,
            "translations": build_translations(page.translations.all()),
            "children": []
        }

    # Step 2: attach children
    for page in pages:
        node = node_map[page.id]

        if page.parent_id:
            parent_node = node_map.get(page.parent_id)
            if parent_node:
                parent_node["children"].append(node)
        else:
            roots.append(node)

    return roots


# G. Final client assembler
def build_client_payload(client):
    # Create a lookup dictionary
    master_language = {c.language_id: c.label_obj for c in Language.objects.filter(language_id__in=client.language_list)}
    master_theme = {c.theme_id: c.label_obj for c in Theme.objects.filter(theme_id__in=client.theme_list)}

    return {
            "client_id": client.client_id,
            "languages": {
              lang_id: master_language[lang_id]
              for lang_id in client.language_list
            },
            "themes": {
              theme_id: master_theme[theme_id]
              for theme_id in client.theme_list
            },            
            "translations": build_translations(client.translations.all()),
            # this is flat and mainly for layout_tree of a page
            "pages": [
                {
                    "page_id": p.page_id,
                    "ltext": p.ltext,
                    "order": p.order,
                    "hidden": p.hidden,
                    "translations": build_translations(p.translations.all()),
                    "layout_tree": build_layout_tree(
                        [l for l in p.layouts.all() if not l.hidden]
                    ) # xyz.all() without filter works with prefetch

                }
                #for p in client.pages.filter(hidden=False)
                for p in [px for px in client.pages.all() if not px.hidden] # xyz.all() without filter works with prefetch

            ],
            "page_tree": build_page_tree(
                [l for l in client.pages.all() if not l.hidden]
            ) # this is for navigation bar requirement. this is nested # xyz.all() without filter works with prefetch
            # this is for navigation bar requirement. this is nested
            #"page_tree" : build_page_tree(client.pages.all()) #filter(hidden=False))
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
          ContentType.objects.get_for_models(
            Client,
            Page,
            HeroText,
            HeroCardText,
            TextBlockItem,
          )
          qs_client = (
            Client.objects
            .select_related("parent")  # Add this if you access parent
            .prefetch_related(
                Prefetch(
                    "translations",
                    queryset=TextItemValue.objects.select_related("language")
                ),
                Prefetch(
                    "pages",
                    queryset=Page.objects.select_related(
                        "parent"
                    ).prefetch_related(
                        Prefetch(
                            "translations",
                            queryset=TextItemValue.objects.select_related("language")
                        ),
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
  "languages": {
    "en": {
      "en": "English",
      "fr": "frEnglish",
      "hi": "hiEnglish"
    },
    "fr": {
      "en": "French",
      "fr": "frFrench",
      "hi": "hiFrench"
    },
    "hi": {
      "en": "Hindi",
      "fr": "frHindi",
      "hi": "hiHindi"
    }
  },
  "themes": {
    "aqua": {
      "en": "Aqua",
      "fr": "frAqua",
      "hi": "hiAqua"
    },
    "dark": {
      "en": "Dark",
      "fr": "frDark",
      "hi": "hiDark"
    },
    "light": {
      "en": "Light",
      "fr": "frLight",
      "hi": "hiLight"
    }
  },
  "translations": {
    "en": {
      "stext": "Bahushira",
      "ltext": "Bahushira Technologies LLP"
    },
    "fr": {
      "stext": "Bahushira",
      "ltext": "frBahushira Technologies LLP"
    },
    "hi": {
      "stext": "Bahushira",
      "ltext": "Bahushira Technologies LLP"
    }
  },
  "pages": [
    {
      "page_id": "home",
      "ltext": "Home",
      "order": 1,
      "hidden": "False",
      "translations": {
        "en": {
          "stext": "Home",
          "ltext": "Home"
        },
        "fr": {
          "stext": "frHome",
          "ltext": "frHome"
        },
        "hi": {
          "stext": "hiHome",
          "ltext": "hiHome"
        }
      },
      "layout_tree": [
        {
          "id": 10,
          "level": 10,
          "slug": "a",
          "order": 1,
          "css_class": "",
          "style": "",
          "hidden": "False",
          "children": [
            {
              "id": 11,
              "level": 20,
              "slug": "a",
              "order": 1,
              "css_class": "",
              "style": "",
              "hidden": "False",
              "children": [
                {
                  "id": 12,
                  "level": 30,
                  "slug": "a",
                  "order": 1,
                  "css_class": "",
                  "style": "",
                  "hidden": "False",
                  "children": [
                    {
                      "id": 13,
                      "level": 40,
                      "slug": "a",
                      "order": 1,
                      "css_class": "",
                      "style": "",
                      "hidden": "False",
                      "children": [],
                      "component": {
                        "type": "hero",
                        "hero": {
                          "css_class": "",
                          "overlay": "False",
                          "overlay_style": "",
                          "text": {
                            "order": 1,
                            "hidden": "False",
                            "ltext": "",
                            "actions": {
                              "class": "",
                              "position": "end"
                            },
                            "contents": [
                              {
                                "id": 1,
                                "hidden": "False",
                                "ltext": "",
                                "blocks": [
                                  {
                                    "block_id": "title",
                                    "hidden": "False",
                                    "css_class": "",
                                    "items": [
                                      {
                                        "item_id": "text",
                                        "hidden": "False",
                                        "order": 1,
                                        "css_class": "",
                                        "svg_text": "",
                                        "translations": {
                                          "en": {
                                            "stext": "Welcome to Bahushira Home Page",
                                            "ltext": "ltext Welcome to Bahushira Home Page"
                                          },
                                          "fr": {
                                            "stext": "frWelcome to Bahushira Home Page",
                                            "ltext": "fr ltext Welcome to Bahushira Home Page"
                                          },
                                          "hi": {
                                            "stext": "hi Welcome to Bahushira Home Page",
                                            "ltext": "hi ltxt Welcome to Bahushira Home Page"
                                          }
                                        }
                                      }
                                    ]
                                  }
                                ]
                              }
                            ]
                          },
                          "figure": {
                            "order": 2,
                            "hidden": "False",
                            "image_url": "https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp",
                            "alt": "Spiderman",
                            "position": "start"
                          },
                          "card": ""
                        }
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
      "ltext": "About",
      "order": 2,
      "hidden": "False",
      "translations": {
        "en": {
          "stext": "About",
          "ltext": "About"
        },
        "fr": {
          "stext": "frAbout",
          "ltext": "frAbout"
        },
        "hi": {
          "stext": "hiAbout",
          "ltext": "hiAbout"
        }
      },
      "layout_tree": []
    },
    {
      "page_id": "team",
      "ltext": "Team",
      "order": 3,
      "hidden": "False",
      "translations": {
        "en": {
          "stext": "Team",
          "ltext": "Team"
        },
        "fr": {
          "stext": "frTeam",
          "ltext": "frTeam"
        },
        "hi": {
          "stext": "hiTeam",
          "ltext": "hiTeam"
        }
      },
      "layout_tree": []
    },
    {
      "page_id": "contact",
      "ltext": "Contact",
      "order": 4,
      "hidden": "False",
      "translations": {
        "en": {
          "stext": "Contact",
          "ltext": "Contact"
        },
        "fr": {
          "stext": "frContact",
          "ltext": "frContact"
        },
        "hi": {
          "stext": "hiContact",
          "ltext": "hiContact"
        }
      },
      "layout_tree": []
    }
  ],
  "page_tree": [
    {
      "client_id": "bahushira",
      "page_id": "home",
      "translations": {
        "en": {
          "stext": "Home",
          "ltext": "Home"
        },
        "fr": {
          "stext": "frHome",
          "ltext": "frHome"
        },
        "hi": {
          "stext": "hiHome",
          "ltext": "hiHome"
        }
      },
      "children": []
    },
    {
      "client_id": "bahushira",
      "page_id": "about",
      "translations": {
        "en": {
          "stext": "About",
          "ltext": "About"
        },
        "fr": {
          "stext": "frAbout",
          "ltext": "frAbout"
        },
        "hi": {
          "stext": "hiAbout",
          "ltext": "hiAbout"
        }
      },
      "children": []
    },
    {
      "client_id": "bahushira",
      "page_id": "team",
      "translations": {
        "en": {
          "stext": "Team",
          "ltext": "Team"
        },
        "fr": {
          "stext": "frTeam",
          "ltext": "frTeam"
        },
        "hi": {
          "stext": "hiTeam",
          "ltext": "hiTeam"
        }
      },
      "children": [
        {
          "client_id": "bahushira",
          "page_id": "contact",
          "translations": {
            "en": {
              "stext": "Contact",
              "ltext": "Contact"
            },
            "fr": {
              "stext": "frContact",
              "ltext": "frContact"
            },
            "hi": {
              "stext": "hiContact",
              "ltext": "hiContact"
            }
          },
          "children": []
        }
      ]
    }
  ]
}
"""


"""
def serialize_instance(
    obj,
    *,
    fields=None,
    rename=None,
    nested=None,
):
    
    #Generic Django model serializer.

    #fields: list[str]              → fields to include
    #rename: dict[str, str]         → rename output keys
    #nested: dict[str, callable]    → nested serializers
    
    if not obj:
        return None

    rename = rename or {}
    nested = nested or {}

    data = {}

    for field in fields or []:
        key = rename.get(field, field)
        data[key] = getattr(obj, field)

    for key, fn in nested.items():
        data[key] = fn(obj)

    return data

def get_attr(obj, attr):
    try:
        return getattr(obj, attr)
    except Exception:
        return None

def visible(obj):
    return obj if obj and not getattr(obj, "hidden", False) else None
"""    
"""
#Phase 4: Recursive tree builder
def build_layout_tree(layouts):
    nodes = {}
    roots = []

    for l in layouts:
        node = {
            "id": l.id,
            "level": l.level,
            "slug": l.slug,
            "order": l.order,
            "css_class": l.css_class,
            "style": l.style,
            "hidden": l.hidden,
            "children": [],
        }

        if l.level == 40:
            node["component"] = build_layout_component(l)

        nodes[l.id] = node

    for l in layouts:
        node = nodes[l.id]

        if l.parent_id:
            nodes[l.parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots


   
def build_layout_component(layout):

    IMAGE_FIELDS = ["image_id", "image_url", "alt"]
    CARD_TEXT_FIELDS = ["hidden", "ltext",
                   "title_class", "title_stb_ids", "contents_class", "contents_stb_ids",
                   "actions_class", "actions_position_id", 
                   "button01_class", "button01_stb_ids",
                   "button02_class", "button02_stb_ids",
                   "button03_class", "button03_stb_ids",
                   "button04_class", "button04_stb_ids",
                   ]    
    HERO_TEXT_FIELDS = ["order", "hidden", "type_id"] + CARD_TEXT_FIELDS

    CARD_FIGURE_FIELDS = ["hidden", "ltext", "figure_class", "position_id", "css_class", "image_url", "alt"]


    HERO_FIGURE_FIELDS = ["order", "hidden", "type_id"] + CARD_FIGURE_FIELDS
    
    if layout.comp_id == "hero":
        #hero = get_attr(layout, "hero")
        hero = visible(get_attr(layout, "hero"))
        herotext = visible(get_attr(hero, "herotext"))
        herofigure = visible(get_attr(hero, "herofigure"))  
        herocard = visible(get_attr(hero, "herocard"))

        serialized_herotext = serialize_instance(herotext, fields= HERO_TEXT_FIELDS, rename={}) if herotext else None
        serialized_herofigure = serialize_instance(herofigure, 
                            fields= HERO_FIGURE_FIELDS, 
                            rename={},
                            nested={"image": lambda o: serialize_instance(o.image, fields = IMAGE_FIELDS, rename={})},
                            ) if herofigure else None
        serialized_herocard = serialize_instance(
                            herocard,
                            fields=["id","order", "hidden", "type_id", "ltext", "ltext", "css_class", "body_class"],
                            nested={
                                "text": lambda o: serialize_instance(
                                    o.herocardtext,
                                    fields=CARD_TEXT_FIELDS,
                                    rename={},
                                ),
                                "figure": lambda o: serialize_instance(
                                    o.herocardfigure,
                                    fields=CARD_FIGURE_FIELDS,
                                    rename={},
                                    nested={"image": lambda o: serialize_instance(o.image, fields = IMAGE_FIELDS, rename={})},
                                ),
                            },
                            )   if herocard else None
        herocontents = []
        if serialized_herotext:
            herocontents.append(serialized_herotext)
        if serialized_herofigure:
            herocontents.append(serialized_herofigure)
        if serialized_herocard:
            herocontents.append(serialized_herocard)

        return {
            "type": "hero",            
            "css_class": hero.css_class,
            "herocontent_class": hero.herocontent_class,
            "overlay": hero.overlay,
            "overlay_style": hero.overlay_style,
            "herocontents" : herocontents,
        }

    if layout.comp_id == "card":
        card = visible(get_attr(layout, "card"))
        cardtext = visible(get_attr(card, "cardtext"))
        cardfigure = visible(get_attr(card, "cardfigure"))        
        serialized_cardtext = { lambda o: serialize_instance(
                    o.cardtext,
                    fields=CARD_TEXT_FIELDS,
                    rename={},
                    )
                    } if cardtext else None
        
        serialized_cardfigure = { lambda o: serialize_instance(
                    o.cardfigure,
                    fields=CARD_FIGURE_FIELDS,
                    rename={},
                    nested={"image": lambda o: serialize_instance(o.image, fields = IMAGE_FIELDS, rename={})},
                    )
                    } if cardfigure else None
        carddata = []
        if serialized_cardtext:
            carddata.append(serialized_cardtext)
        if serialized_cardfigure:
            carddata.append(serialized_cardfigure)

        return serialize_instance(
            card,
            fields=["ltext", "css_class", "body_class"],
            nested={
                "data": carddata
            },
        )


    return None

"""
"""
#from Claude

def fetch_clientstatic2(lv_client_id):
    # Pre-fetch all ContentTypes we'll need
    #ct_client = ContentType.objects.get_for_model(Client)
    #ct_page = ContentType.objects.get_for_model(Page)
    #ct_herotext = ContentType.objects.get_for_model(HeroText)
    #ct_herocardtext = ContentType.objects.get_for_model(HeroCardText)
    #ct_textblockitem = ContentType.objects.get_for_model(TextBlockItem)
    
    # Pre-fetch ALL languages once (they're reused everywhere)
    #all_languages = {lang.id: lang for lang in Language.objects.all()}
    
    # Optimized TextContent prefetch with single language join
    textcontent_prefetch = Prefetch(
        "textcontents",
        queryset=TextContent.objects.prefetch_related(
            Prefetch(
                "blocks",
                queryset=TextBlock.objects.prefetch_related(
                    Prefetch(
                        "items",
                        queryset=TextBlockItem.objects.select_related(
                            "translations__language"  # Single join instead of repeated queries
                        ).prefetch_related(
                            Prefetch(
                                "translations",
                                queryset=TextItemValue.objects.select_related("language")
                            )
                        )
                    )
                )
            )
        ),
        to_attr="prefetched_textcontents"
    )
    
    # Hero with optimized textcontent prefetch
    hero_prefetch = Prefetch(
        "hero",
        queryset=Hero.objects.select_related(
            "herotext",
            "herofigure", 
            "herocard__herocardtext",
            "herocard__herocardfigure"
        ).prefetch_related(
            Prefetch(
                "herotext__textcontents",
                queryset=textcontent_prefetch.queryset,
                to_attr="prefetched_textcontents"
            ),
            Prefetch(
                "herocard__herocardtext__textcontents",
                queryset=textcontent_prefetch.queryset,
                to_attr="prefetched_textcontents"
            ),
        ),
    )
    

    # Card with optimized textcontent prefetch
    card_prefetch = Prefetch(
        "card",
        queryset=Card.objects.select_related(
            "cardtext",
            "cardfigure",
        ).prefetch_related(
            Prefetch(
                "cardtext__textcontents",
                queryset=textcontent_prefetch.queryset,
                to_attr="prefetched_textcontents"
            )
        ),
    )
    
    # Layout prefetch
    layout_prefetch = Prefetch(
        "layouts",
        queryset=Layout.objects.select_related(
            "parent",
        ).prefetch_related(
            hero_prefetch,
            card_prefetch,
        ).order_by("level", "order"),
    )
    
    # Main query
    qs_client = (
        Client.objects
        .filter(client_id=lv_client_id)
        .select_related("parent")  # Add this if you access parent
        .prefetch_related(
            Prefetch(
                "translations",
                queryset=TextItemValue.objects.select_related("language")
            ),
            Prefetch(
                "pages",
                queryset=Page.objects.select_related(
                    "parent"
                ).prefetch_related(
                    Prefetch(
                        "translations",
                        queryset=TextItemValue.objects.select_related("language")
                    ),
                    layout_prefetch,
                ).order_by("order"),
            ),
        )
        .get()
    )
    
    return qs_client

"""    