from django import template
from django.utils.translation import get_language

register = template.Library()


@register.simple_tag(takes_context=True)
def mytext_static_tag(context, lv_token_id='', lv_ln=''):

    
    """
    Input is a lv_token; optional lv_ln = "en', 'hi'...
    Output is a text. 
    This has to be derived from texts_static_dict which is of form:
    texts_static_dict - {token_id: {client_id: {page_id: {en: val1, fr: val2}}}}
    client_hierarchy_list = ['bahushira', parent, grandparent, 'default']
    LANGUAGE_CODE 
    CURRENT_LANGUAGE_CODE
    page_id

    """    
    cv_client_hier_list = context.get("client_hierarchy_list")
    cv_data_dict = context.get("texts_static_dict")
    cv_base_ln_code = context.get("LANGUAGE_CODE")
    cv_curr_ln_code = get_language()
    cv_page_id = context.get("page")

    # a hierarchy of page is with global followed by current page
    cv_ln_hier_list = [cv_curr_ln_code]
    if cv_base_ln_code != cv_curr_ln_code:
        cv_ln_hier_list.append(cv_base_ln_code)
    # if a lv_ln is passed to the function ie. the preferred ln code, then put this as the first entry in ln_hier_list
    if lv_ln != '':
        if lv_ln in cv_ln_hier_list:
            cv_ln_hier_list.remove(lv_ln) # Removes the first occurrence by value
        cv_ln_hier_list.insert(0, lv_ln) # Inserts the item at index 0 (the beginning)

    cv_page_hier_list = [cv_page_id, 'global']
    """
    Attempts to retrieve a value from a 4-level nested dictionary 
    using predefined paths in order of preference.
    
    Returns the value found or None if no valid path exists.
    token > client > ln > page 
    token > client > ln > general 
    token > client > baseln > page 
    token > client > baseln > general 

    token > client_parent...
    token > default ....
      
    # If none of the paths are found
    return None
    """
    """
    default = 'ERR001'

    token_data = cv_data_dict.get(lv_token_id)
    if not token_data:
        return default

    for client_id in cv_client_hier_list:
        client_data = token_data.get(client_id)
        if not client_data:
            continue

        for language_id in cv_ln_hier_list:
            lang_data = client_data.get(language_id)
            if not lang_data:
                continue

            for page_id in cv_page_hier_list:
                if page_id in lang_data:
                    return lang_data[page_id]

    return default

    """
    # Check if the target token_id exists in the main dictionary
    if lv_token_id not in cv_data_dict:
        return 'ERR001'

    # Get the dictionary for the specific token
    client_dict = cv_data_dict[lv_token_id]

    # Iterate through the client priorities
    for client_id in cv_client_hier_list:
        if client_id in client_dict:
            language_dict = client_dict[client_id]
            

            # Iterate through the language priorities
            for language_id in cv_ln_hier_list:
                if language_id in language_dict:
                    page_dict = language_dict[language_id]
                                
                    # Iterate through the page priorities
                    for page_id in cv_page_hier_list:
                        if page_id in page_dict:
                            # Found the first prioritized value
                            return page_dict[page_id]
                            
    # If no value was found after checking all priorities
    return 'ERR001'
    
@register.simple_tag(takes_context=True)
def myimage_static_tag(context, lv_token_id=''):

    
    """
    Input is a image_id
    Output is an object of form {image_url: xyz , alt: xyz}. 
    This has to be derived from images_static_dict which is of form:
    images_static_dict - {image_id: {client_id: {page_id: {image_url: xyz, alt: xyz}}}}
    client_hierarchy_list = ['bahushira', parent, grandparent, 'default']
    page_id

    """    
    cv_client_hier_list = context.get("client_hierarchy_list")
    cv_data_dict = context.get("images_static_dict")
    cv_page_id = context.get("page")

    # a hierarchy of page is with current_page followed by global
    cv_page_hier_list = [cv_page_id, 'global']
    """
    Attempts to retrieve a value from a 4-level nested dictionary 
    using predefined paths in order of preference.
    
    Returns the value found or None if no valid path exists.
    token > client > page 
    token > client > general 
    token > client2 > page 
    token > client2 > general 

    token > client_parent...
    token > default ....
      
    # If none of the paths are found
    return None
    """

    # Check if the target token_id exists in the main dictionary
    if lv_token_id not in cv_data_dict:
        return {'image_url': '', 'alt': 'ERR001'}

    # Get the dictionary for the specific token
    client_dict = cv_data_dict[lv_token_id]

    # Iterate through the client priorities
    for client_id in cv_client_hier_list:
        if client_id in client_dict:
            page_dict = client_dict[client_id]
                        
            # Iterate through the page priorities
            for page_id in cv_page_hier_list:
                if page_id in page_dict:
                    # Found the first prioritized value
                    return page_dict[page_id]
                            
    # If no value was found after checking all priorities
    return {'image_url': '', 'alt': 'ERR001'}    

@register.simple_tag(takes_context=True)
def mysvg_static_tag(context, lv_token_id=''):

    
    """
    Input is a svg_id
    Output is an object of form {svg_text: xyz}. 
    This has to be derived from svgs_static_dict which is of form:
    svgs_static_dict - {svg_id: {client_id: {page_id: {svg_text: xyz}}}}
    client_hierarchy_list = ['bahushira', parent, grandparent, 'default']
    page_id

    """    
    cv_client_hier_list = context.get("client_hierarchy_list")
    cv_data_dict = context.get("svgs_static_dict")
    cv_page_id = context.get("page")

    # a hierarchy of page is with current_page followed by global
    cv_page_hier_list = [cv_page_id, 'global']
    """
    Attempts to retrieve a value from a 4-level nested dictionary 
    using predefined paths in order of preference.
    
    Returns the value found or None if no valid path exists.
    token > client > page 
    token > client > general 
    token > client2 > page 
    token > client2 > general 

    token > client_parent...
    token > default ....
      
    # If none of the paths are found
    return None
    """

    # Check if the target token_id exists in the main dictionary
    if lv_token_id not in cv_data_dict:
        return {'svg_text': ''}

    # Get the dictionary for the specific token
    client_dict = cv_data_dict[lv_token_id]

    # Iterate through the client priorities
    for client_id in cv_client_hier_list:
        if client_id in client_dict:
            page_dict = client_dict[client_id]
                        
            # Iterate through the page priorities
            for page_id in cv_page_hier_list:
                if page_id in page_dict:
                    # Found the first prioritized value
                    return page_dict[page_id]
                            
    # If no value was found after checking all priorities
    return {'svg_text': ''}