from collections import defaultdict
from django.core.cache import cache
#from mysite.models import Translation, TextStatic
from mysite.models import Client, ClientLanguage, ClientTheme, ClientNavbar,TextStatic, ImageStatic, SvgStatic

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
def build_nested_hierarchy(flat_list, key_name: str):
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
            client_static['client'] = Client.objects.get(client_id=lv_client_id)
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

            qsnb = ClientNavbar.objects.filter(client__client_id=lv_client_id).values('id', 'page_id', 'comp_unique', 'parent', 'order').order_by('order')
            # reshape result
                # Create a dictionary for quick lookup of items by their client_page
            item_map = {item['comp_unique']: item for item in qsnb}

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
            """
            Expected result:
            {
                "page_title": {
                    "abc123": {
                        "en": {
                            "global": "Home",
                            "about": "About"
                        }
                    }
                }
            }
            """
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

            # Build query for imagestatic
            qsi = ImageStatic.objects.filter(client_id__in=client_static['client_hierarchy_list']).order_by("image_id").values("image_id", "client_id", "page_id", "image_url", "alt")

            # Reshape result2
            """
            Expected result:
            {
                "nike": {
                    "bahushira": {
                        "global": {
                            "image_url": "https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp",
                            "alt": "shoes"
                        }
                    }
                }
            }
            """
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

            # Build query for svgstatic
            qss = SvgStatic.objects.filter(client_id__in=client_static['client_hierarchy_list']).order_by("svg_id").values("svg_id", "client_id", "page_id", "svg_text")

            # Reshape result2
            """
            Expected result:
            {
                "like": {
                    "bahushira": {
                        "global": {
                            "svg_text": 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z',                            
                        }
                    }
                }
            }
            """
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
        else:
            # push some content into this to display an error message
            client_static = {}
    else:
        # push some content into this to display an error message
        client_static = {}

    
    # Cache it
    if cache_key:
        cache.set(cache_key, client_static, timeout=timeout)

    
    return client_static

"""
def fetch_textstatic_dict(client_ids=None, use_cache=True, timeout=3600):
    
    # Build cache key
    cache_key = None
    if use_cache and client_ids:
        cache_key = f"translations_dict:{','.join(map(str, client_ids))}"
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data
    
    # Build query
    # qs = Translation.objects.select_related("client", "token", "language")
    if client_ids:    
        qs = TextStatic.objects.filter(client_id__in=client_ids).order_by("token_id").values("token_id", "client_id", "page_id", "language_id", "value")

    # Reshape result

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

    
    # Cache it
    if cache_key:
        cache.set(cache_key, reshaped_data, timeout=timeout)
    
    return reshaped_data
"""