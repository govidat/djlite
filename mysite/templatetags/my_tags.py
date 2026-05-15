from django import template
import html
from django.utils.translation import get_language
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()

from django.template import Context, Template
from django.core.cache import cache
from django.template.loader import render_to_string


# this is to be used for getting the gentext like name, nb_title for further passing to svgtextbadge
@register.simple_tag(takes_context=True)
def mylist_bykey(context, lv_list=[], lv_val0="name", lv_key0="block_id"):
     
    """ 
    Input:
      "textblocks": [
            {
            "block_id": "name",
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "href_page": "None",
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
            },
            {
            "block_id": "nb_title",
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "href_page": "None",
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
        ],

        Output expected is:
        [   
            {
            "block_id": "name",
            "order": 1,
            "css_class": "None",
            "ltext": "None",
            "href_page": "None",
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
            }...
        ]

    """    
    """
    # Get the filtered list
    lv0_filtered_list = [item for item in lv_list if item.get(lv_key0) == lv_val0]
    
    """
    filtered = [
        item for item in (lv_list or [])
        if item.get(lv_key0) == lv_val0
    ]

    return filtered


@register.simple_tag(takes_context=True)
def zzmytextv2(context, lv_dict={}, lv_key='stext', lv_ln=''):
     
    """ 
    Input is :

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

    Optional lv_ln = "en', 'hi'...
    Output is a text. 

    LANGUAGE_CODE 
    CURRENT_LANGUAGE_CODE

    """    

    if not lv_dict:
        return "ERR001"

    base_ln = context.get("LANGUAGE_CODE")
    curr_ln = get_language()

    # Build priority list
    lang_priority = []

    if lv_ln:
        lang_priority.append(lv_ln)

    if curr_ln and curr_ln not in lang_priority:
        lang_priority.append(curr_ln)

    if base_ln and base_ln not in lang_priority:
        lang_priority.append(base_ln)

    # Build key priority based on user choice
    if lv_key == 'ltext':
        key_priority = ['ltext', 'stext']
    else:
        # default: stext first, ltext as fallback
        key_priority = ['stext', 'ltext']

    # Lookup
    for lang in lang_priority:
        lang_data = lv_dict.get(lang, {})
        for key in key_priority:
            value = lang_data.get(key)
            if value:
                # Step 1: unescape stored entities like &quot; → "
                unescaped = html.unescape(value)
                # Step 2: re-escape any real HTML tags for safety
                safe_value = conditional_escape(unescaped)
                # Step 3: mark safe so Django doesn't double-escape
                return mark_safe(safe_value)

                #return value
    """        
    # Lookup
    for lang in lang_priority:
        value = (
            lv_dict.get(lang, {})
                   .get(lv_key)
        )
        if value:
            return value
    """

    return "ERR001"
    """
    if not lv_dict:
        return "ERR001"
    
    cv_base_ln_code = context.get("LANGUAGE_CODE")
    cv_curr_ln_code = get_language()

    # a hierarchy of page is with global followed by current page
    cv_ln_hier_list = [cv_curr_ln_code]
    if cv_base_ln_code != cv_curr_ln_code:
        cv_ln_hier_list.append(cv_base_ln_code)
    # if a lv_ln is passed to the function ie. the preferred ln code, then put this as the first entry in ln_hier_list
    if lv_ln != '':
        if lv_ln in cv_ln_hier_list:
            cv_ln_hier_list.remove(lv_ln) # Removes the first occurrence by value
        cv_ln_hier_list.insert(0, lv_ln) # Inserts the item at index 0 (the beginning)


    # Get the dictionary for the specific token
    lv_values_dict = lv_dict
         

    # Iterate through the language priorities
    for language_id in cv_ln_hier_list:
        if language_id in lv_values_dict:
            return lv_values_dict[language_id][lv_key]
                                                           
    # If no value was found after checking all priorities
    return 'ERR001'
    """

@register.simple_tag(takes_context=True)
def zzmytext_labelv2(context, lv_dict={}):
     
    """ 
    Option 2
    Input is :

      "labels": {
        "en": "Aqua",
        "fr": "frAqua",
        "hi": "hiAqua"
      }

    Output is a text. 

    LANGUAGE_CODE 
    CURRENT_LANGUAGE_CODE

    """    
    cv_base_ln_code = context.get("LANGUAGE_CODE")
    cv_curr_ln_code = get_language()

    # a hierarchy of page is with global followed by current page
    cv_ln_hier_list = [cv_curr_ln_code]
    if cv_base_ln_code != cv_curr_ln_code:
        cv_ln_hier_list.append(cv_base_ln_code)
    """
    Attempts to retrieve a value from a nested dictionary 
    using predefined paths in order of preference.
    
    # If none of the paths are found
    return None
    """

    # Get the dictionary for the specific token
    """
    Option 1
    lv_values_dict = lv_text_list[0]["items"][0]["values"]
    Option
    """
    lv_values_dict = lv_dict
         

    # Iterate through the language priorities
    for language_id in cv_ln_hier_list:
        if language_id in lv_values_dict:
            return lv_values_dict[language_id]
                                

                            
    # If no value was found after checking all priorities
    return 'ERR001'    

@register.simple_tag(takes_context=True)
def render_client_template(context, template_key, **extra_context):
    """
    Renders a client-specific template from DB, falling back to
    the filesystem template if no DB record exists.

    Usage in templates:
      {% load client_template_tags %}
      {% render_client_template 'catalogue_item_card' item=item %}
    """
    request = context.get('request')
    client  = context.get('client', {})
    client_id = client.get('client_id') if isinstance(client, dict) else getattr(client, 'client_id', None)

    if not client_id:
        return ''

    #active_lang = get_language() or 'en'

    # Cache key per client + template_key + language
    # cache_key = f"client_template:{client_id}:{template_key}:{active_lang}"

    # modeltranslation already resolves language automatically
    cache_key = f"client_template:{client_id}:{template_key}"

    cached_html = cache.get(cache_key)



    if cached_html is None:
        from mysite.models.client import ClientTemplate
        # Try active language first, then 'all', then None (not found)
        db_template = (
            ClientTemplate.objects
            .filter(
                client__client_id=client_id,
                template_key=template_key,
                is_active=True,
            )
            .first()
            #.filter(
            #    models.Q(language_code=active_lang) |
            #    models.Q(language_code='all')
            #)
            #.order_by('-language_code')  # active_lang before 'all'
            #.first()
        )
        # IMPORTANT:
        # htmlblob auto-resolves to current language
 
        cached_html = db_template.htmlblob if db_template else ''
        cache.set(cache_key, cached_html, timeout=3600)

    if cached_html:
        # Render the DB template string with the current context
        # Merge context + extra_context
        render_context = dict(context.flatten())
        render_context.update(extra_context)
        try:
            t = Template(cached_html)
            return t.render(Context(render_context))
        except Exception:
            return ''  # fail silently — don't break the page

    # Fallback to filesystem template
    # from django.template.loader import render_to_string
    filesystem_map = {
        'catalogue_filter_sidebar': 'catalogue/partials/filter_sidebar.html',
        'catalogue_item_card':      'catalogue/partials/item_card.html',
        'catalogue_items_list':     'catalogue/partials/items_list.html',
        'catalogue_pagination':     'catalogue/partials/pagination.html',
        'catalogue_item_detail':    'catalogue/partials/item_detail.html',  # have put a wrapper and moved content to partials
        'navbar':                   'cotton/navbar_v001.html',
        'footer':                   'cotton/footer.html',
    }
    fs_template = filesystem_map.get(template_key)
    if fs_template:
        render_context = dict(context.flatten())
        render_context.update(extra_context)
        return render_to_string(fs_template, render_context, request=request)

    return ''