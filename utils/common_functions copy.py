from collections import defaultdict
from django.core.cache import cache
#from mysite.models import Translation, TextStatic
#from mysite.models import Client, ClientLanguage, ClientTheme, ClientPage, TextStatic, Image, Svg, Layout, Hero, Card, Client2
from mysite.models import Client, TextContent, TextBlock, TextBlockItem, Card, Hero, Layout, Page
from django.db.models import Prefetch

""" 
def build_nested_hierarchy_old(flat_list):
    # Create a dictionary for quick lookup of items by their ID
    item_map = {item['id']: item for item in flat_list}

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
"""

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


# filtered_data = list(filter(lambda item: not item.get('is_active'), data))
#sorted_by_age = sorted(data, key=lambda x: x['age']) ;

"""
def fetch_textstatic(client_ids=None, as_dict=False, use_cache=True, timeout=3600):
    
    # Fetch textstatic with optional caching.
    # Works when client_id as primary key.
    
    
    # Build cache key
    cache_key = None
    if use_cache and client_ids:
        cache_key = f"translations:{','.join(map(str, client_ids))}:{as_dict}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
    
    # Build query
    # qs = Translation.objects.select_related("client", "token", "language")
    if client_ids:    
        qs = TextStatic.objects.filter(client_id__in=client_ids)

    # Reshape result
    result = {}
    for t in qs:
        client = str(t.client_id)
        token = str(t.token_id)
        page = str(t.page_id)        
        lang = str(t.language_id)

        key = (client, token, page)
        if key not in result:
            result[key] = {
                "client_id": client,
                "token_id": token,
                "page_id": page,
                "text": {}
            }
        result[key]["text"][lang] = t.value

    # Return format
    if as_dict:
        nested = defaultdict(lambda: defaultdict(dict))
        for entry in result.values():
            client = entry["client_id"]
            token = entry["token_id"]
            page = entry["page_id"]
            nested[client][token][page] = entry["text"]
        final_data = dict(nested)
    else:
        final_data = list(result.values())
    
    # Cache it
    if cache_key:
        cache.set(cache_key, final_data, timeout=timeout)
    
    return final_data

"""

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
                        "translations",
                    ),
                )
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
        ),
        Prefetch(
            "herocard__herocardtext__textcontents",
            queryset=textcontent_prefetch.queryset,
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
    if lv_client_id:
        # do many sql calls and update the list
        if Client.objects.filter(client_id=lv_client_id).exists():
            #client_static['client'] = Client.objects.get(client_id=lv_client_id)
            #Step 4: Page + Client Query (The Entry Point)

            qs_client = (
                Client.objects
                .filter(client_id=lv_client_id)
                .prefetch_related(
                    "translations",
                    Prefetch(
                        "pages",
                        queryset=Page.objects.prefetch_related(
                            "translations",
                            layout_prefetch,
                        ).order_by("order"),
                    ),
                )
                .get()
            )
            """
            qs_client = (
                Client.objects
                .filter(client_id=lv_client_id)
                .prefetch_related(
                    "translations",
                    "pages",
                    "pages__translations",
                    "pages__layouts",
                    
                )
            )
            """
            client_static['client'] = qs_client.pages.all()
            #client_static['pages'] = qs_client[0].pages
            """
            # If the code reaches here, the object exists, and you have it in 'obj'
            # TODO if Client Model has some more values that we want to pull in, then we will have to add code here

            # get other client specific support model data
            client_static['client_language_ids'] = ClientLanguage.objects.filter(client__client_id=lv_client_id).values_list('language_id', flat=True).order_by('order')
            client_static['client_theme_ids'] = ClientTheme.objects.filter(client__client_id=lv_client_id).values_list('theme_id', flat=True).order_by('order')

            client_ancestors=client_static['client'].get_ancestors()
            client_static['client_hierarchy_list'] = [lv_client_id] + client_ancestors + ['default']
            # expected value is a list of client_ids

            # Build query for client_nb_items
            #client_static['client_nb_items'] = ClientNavbar.objects.filter(client__client_id=lv_client_id).values('id', 'page_id', 'client_page', 'parent', 'order').order_by('order')        
            #client_static['client_nb_items_nested'] = build_nested_hierarchy(client_static['client_nb_items'], 'client_page')

            # using a function module here leads to some async errors, hence explicitly doing the reshape here
            qsnb = ClientPage.objects.filter(client__client_id=lv_client_id).values('id', 'page_id', 'comp_unique', 'parent', 'order').order_by('order')
            # reshape result
                # Create a dictionary for quick lookup of items by their client_page
            item_map = {item['id']: item for item in qsnb}

            # Initialize a list to store the top-level items (roots)
            nested_list = []

            # Iterate through each item to build the hierarchy
            for item in qsnb:
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
            client_static['nb_items_nested'] = nested_list

            # Build query for textstatic
            # qs = Translation.objects.select_related("client", "token", "language")
            #qs = TextStatic.objects.filter(client_id__in=client_static['client_hierarchy_list'])
            qs = TextStatic.objects.filter(client_id__in=client_static['client_hierarchy_list']).order_by("token_id").values("token_id", "client_id", "page_id", "language_id", "value")

            # Reshape result2

            reshaped_data = {}

            for item in qs:
                token_id = item['token_id']
                client_id = item['client_id']
                page_id = item['page_id']
                language_id = item['language_id']
                value = item['value']

                # Check and create nested dictionaries as needed
                if token_id not in reshaped_data:
                    reshaped_data[token_id] = {}
                if client_id not in reshaped_data[token_id]:
                    reshaped_data[token_id][client_id] = {}
                if language_id not in reshaped_data[token_id][client_id]:
                    reshaped_data[token_id][client_id][language_id] = {}
                
                # Assign the final value
                reshaped_data[token_id][client_id][language_id][page_id] = value
            client_static['texts_static_dict'] = reshaped_data

            # Build query for Image
            qsi = Image.objects.filter(client_id__in=client_static['client_hierarchy_list']).order_by("image_id").values("image_id", "client_id", "page_id", "image_url", "alt")

            # Reshape result2

            reshaped_data = {}

            for item in qsi:
                image_id = item['image_id']
                client_id = item['client_id']
                page_id = item['page_id']
                image_url = item['image_url']
                alt = item['alt']

                # Check and create nested dictionaries as needed
                if image_id not in reshaped_data:
                    reshaped_data[image_id] = {}
                if client_id not in reshaped_data[image_id]:
                    reshaped_data[image_id][client_id] = {}
                #if page_id not in reshaped_data[image_id][client_id]:
                #    reshaped_data[token_id][client_id][page_id] = {}
                
                # Assign the final value
                reshaped_data[image_id][client_id][page_id] = {'image_url': image_url, 'alt': alt}
            client_static['images_static_dict'] = reshaped_data

            # Build query for Svg
            qss = Svg.objects.filter(client_id__in=client_static['client_hierarchy_list']).order_by("svg_id").values("svg_id", "client_id", "page_id", "svg_text")

            # Reshape result2

            reshaped_data = {}

            for item in qss:
                svg_id = item['svg_id']
                client_id = item['client_id']
                page_id = item['page_id']
                svg_text = item['svg_text']
                
                # Check and create nested dictionaries as needed
                if svg_id not in reshaped_data:
                    reshaped_data[svg_id] = {}
                if client_id not in reshaped_data[svg_id]:
                    reshaped_data[svg_id][client_id] = {}
                #if page_id not in reshaped_data[svg_id][client_id]:
                #    reshaped_data[token_id][client_id][page_id] = {}
                
                # Assign the final value
                reshaped_data[svg_id][client_id][page_id] = {'svg_text': svg_text}
            client_static['svgs_static_dict'] = reshaped_data

            client_static['client'] = (
                Client.objects.filter(client_id=lv_client_id)
                .prefetch_related(
                            "pages",
                            "pages__translations",
                            "translations"
                            )
            )
            """
        else:
            # push some content into this to display an error message
            client_static = {}
    else:
        # push some content into this to display an error message
        client_static = {}

    """
    select_related(
        "hero",
        "hero__herotext__textcontent",
        "hero__herocard__herocardtext__textcontent",
        "card__cardtext__textcontent",
    ).prefetch_related(
        "hero__herotext__textcontent__blocks__items__values",
        "hero__herocard__herocardtext__textcontent__blocks__items__values",
        "card__cardtext__textcontent__blocks__items__values",
    )

    """
    
    # Cache it
    if cache_key:
        cache.set(cache_key, client_static, timeout=timeout)

    
    return client_static

def serialize_instance(
    obj,
    *,
    fields=None,
    rename=None,
    nested=None,
):
    """
    Generic Django model serializer.

    fields: list[str]              → fields to include
    rename: dict[str, str]         → rename output keys
    nested: dict[str, callable]    → nested serializers
    """
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

"""
def serialize_image(img):
    if not img:
        return None

    return {
        "image_id": img.image_id,
        "image_url": img.image_url if img.image_url else None,
        "alt": img.alt,
    }
"""
def get_attr(obj, attr):
    try:
        return getattr(obj, attr)
    except Exception:
        return None

def visible(obj):
    return obj if obj and not getattr(obj, "hidden", False) else None
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