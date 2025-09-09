from django import template
from django.conf import settings
from django.utils.translation import get_language

register = template.Library()

@register.filter
def my_text(value={}, arg=""):
    """value is expected to be an object like {"en": text-en, "fr": text-fr...}  arg will be like "en" which is forced fit """
    
    current_language = get_language()
    base_language = settings.LANGUAGE_CODE

    """
    Check if the input value is a dictionary object
    """
    if isinstance(value, dict):
        if arg:
            return value.get(arg, value.get(base_language, "ERR Z001"))
            
        else:
            """
            data.get("user", {}).get("profile", {}).get("name", "N/A")

            return value.get([current_language], value.get([base_language], "ERR Z001")) 
            return value.get(current_language, value.get(base_language, "ERR Z001"))
            
            if base_language in list(value):
                return value.get(current_language, None) or value.get(base_language, "ERR Z001")
            else:
                return "ERR Z001"
            """
            
            return value.get(current_language, value.get(base_language, "ERR Z001"))

    else:
        return "ERR Z002"


@register.filter
def my_removetrue(value=[], arg=""):
    """value is expected to be a list like [{hidden: True, a:x, b:y}, {hidden: False, a:p, b:q}] ; arg should be a key in the dictionary. This filter will remove records that have true  """
    # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
    return list(filter(lambda item: not item.get(arg), value))

@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


@register.filter
def get_dictid(dict_array=[], arg=0):
    return next(filter(lambda x: x['id'] == arg, dict_array), None)
    """ To be deprecated and replaced with a combination of get_dict_filtered_by_id; get_dict_by_id_client_and_prioritized_values
    To return the first dictionary item that matches a key value;
    res = next(filter(lambda x: x['Author'] == "Mark", DICTARRAY), None)
    """


@register.filter
def get_previous_and_next_in_list(input_list=[], target_item=""):
    """
    Finds the previous and next items of a target item in a list.

    Args:
        input_list (list): A list.
        target_item (item): The item for which to find previous and next.

    Returns:
        list: A list containing (previous_item, next_item).
               Returns (None, None) if the target_item is not found.
               Returns (Last item, next_item) if target_item is the first element.
               Returns (previous_item, first item) if target_item is the last element.
    """
    try:
        index = input_list.index(target_item)
    except ValueError:
        return None, None  # Target number not found in the list

    previous_item = input_list[-1]
    next_item = input_list[0]

    if index > 0:
        previous_item = input_list[index - 1]

    if index < len(input_list) - 1:
        next_item = input_list[index + 1]

    return [previous_item, next_item]


@register.filter
def get_key_values(list_of_dicts=[], key_to_extract=""):
    """
    Extracts a list of values for a specific key from a list of dictionaries.

    Args:
        list_of_dicts (list): A list of dictionary objects.
        key_to_extract (str): The key whose values are to be extracted.

    Returns:
        list: A list containing the values of the specified key from each dictionary
              where the key exists.
    """
    return sorted([d[key_to_extract] for d in list_of_dicts if key_to_extract in d])

@register.filter
def get_dict_filtered_by_level(value=[], arg=0):
    """value is expected to be a list like [{hidden: True, a:x, b:y}, {hidden: False, a:p, b:q}] ; arg should be a key in the dictionary. This filter will remove records that have true  """
    # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
    return list(filter(lambda item: item.get('level') == arg, value))

@register.filter
def get_dict_filtered_by_parent_id(value=[], arg=0):
    """value is expected to be a list like [{hidden: True, a:x, b:y}, {hidden: False, a:p, b:q}] ; arg should be a key in the dictionary. This filter will remove records that have true  """
    # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
    return list(filter(lambda item: item.get('parent_id') == arg, value))

@register.filter
def get_dict_filtered_by_id(value=[], arg=0):
    # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
    return list(filter(lambda item: item.get('id') == arg, value))

@register.filter
def get_dict_by_id_client_and_prioritized_values(list_of_dicts=[], keyvals=""):
    """
    Retrieves a dictionary from a list of dictionaries based on id_client
    and a prioritized list of values to check for that key.

    Args:
        list_of_dicts: A list of dictionaries to search within.
        'id_client': The key to check for in each dictionary.
        keyvals: A comma separated string of values to check against the id_client value, in order of priority.

    Returns:
        The first dictionary found where the value associated with the key='id_client'
        matches one of the values in value_priority_list, or None if no
        matching dictionary is found.

    """    
    value_priority_list=keyvals.split(',')
    # value_priority_list.append('default')
    key='id_client'
    for priority_value in value_priority_list:
        for d in list_of_dicts:
            if key in d and d[key] == priority_value:
                return d
    return None
    """ Test Data
    source_list = [{'id_client': 'store_porur', 'title': 'Saravana Porur'}, {'id_client': 'store_ho', 'title': 'Saravana HO'}, {'id_client': 'default', 'title': 'Defaut Title'} ]
    keyvals = 'store_porur,store_ho'
    result = get_dict_by_id_client_and_prioritized_values(source_list, keyvals)
    print(result)
    """

@register.filter
def get_listdict_by_id_token(listdict=[], arg=''):
    return list(filter(lambda x: x['id_token'] == arg, listdict))

    """ 
    Returns the listdict by filtering on key id_token;
    """
