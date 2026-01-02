from collections import defaultdict
from django.core.cache import cache
#from mysite.models import Translation, TextStatic
from mysite.models import TextStatic
 
def build_nested_hierarchy(flat_list):
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


def fetch_textstatic(client_ids=None, as_dict=False, use_cache=True, timeout=3600):
    """
    Fetch textstatic with optional caching.
    Works when client_id as primary key.
    """
    
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
        """
        # Always fetch raw PK if possible, else fallback to object.pk
        client = getattr(t, "client_id", None) or str(t.client.pk)
        token = getattr(t, "token_id", None) or str(t.token.pk)
        lang = getattr(t, "language_id", None) or str(t.language.pk)

        # Since PKs are text, make sure we treat them as str
        client, token, lang = str(client), str(token), str(lang)
        """
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