def build_nested_hierarchy(flat_list):
    # Create a dictionary for quick lookup of items by their ID
    item_map = {item['id']: item for item in flat_list}

    # Initialize a list to store the top-level items (roots)
    nested_list = []

    # Iterate through each item to build the hierarchy
    for item in flat_list:
        parent_id = item.get('parent_id')

        # If the item has a parent, add it to the parent's children list
        if parent_id is not None and parent_id in item_map:
            parent_item = item_map[parent_id]
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