from django import template
import html
from django.utils.translation import get_language
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

register = template.Library()

from django.template import Context, Template
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


# ── Client/Sector template resolution helpers ─────────────────────────

def get_client_sector_chain(client_id):
    """
    IDs of the client's sector node plus all its ancestors
    (e.g. AutoComponents → Automotive → Industrial).

    Cached per client as 'sector_chain:{client_id}'.
    Invalidated by signals on Client save and on Taxonomy/TaxonomyNode saves
    (sector tree edits can change ancestry).
    """
    cache_key = f"sector_chain:{client_id}"
    chain = cache.get(cache_key)
    if chain is not None:
        return chain

    chain = []
    try:
        from mysite.models import Client, TaxonomyNode
        sector_id = (
            Client.objects
            .filter(client_id=client_id)
            .values_list('sector_id', flat=True)
            .first()
        )
        if sector_id:
            node = TaxonomyNode.objects.filter(id=sector_id).first()
            if node is not None:
                chain.append(node.id)
                # Materialized path '001.002.003' → ancestor path prefixes
                parts = [p for p in node.path.split('.') if p]
                prefixes = ['.'.join(parts[:i]) for i in range(1, len(parts))]
                if prefixes:
                    chain.extend(
                        TaxonomyNode.objects
                        .filter(
                            taxonomy_id=node.taxonomy_id,
                            client=node.client_id,
                            path__in=prefixes,
                        )
                        .exclude(id__in=chain)
                        .values_list('id', flat=True)
                    )
    except Exception:
        logger.exception("get_client_sector_chain failed for client=%s", client_id)

    cache.set(cache_key, chain, timeout=3600)
    return chain


def _resolve_template_html(client_id, template_key, country_code=None):
    """
    Resolution order (first non-empty wins):
      1. ClientTemplate (client + country=X)
      2. ClientTemplate (client + country=NULL)
      3. SectorTemplate @ client's sector chain (deepest sector, country=X)
      4. SectorTemplate @ NULL sector (global + country=X)
      5. SectorTemplate @ client's sector chain (deepest sector, country=NULL)
      6. SectorTemplate @ NULL sector (global default, country=NULL)
      7. ''                        (unseeded key — caller logs a warning)

    Defaults are DB-seeded by migration — there is no filesystem fallback.
    """
    from mysite.models.client import ClientTemplate, SectorTemplate
    from django.db.models import Q

    country_id = country_code  # Country PK is the ISO code string

    # 1. ClientTemplate with country=X (highest priority)
    if country_id:
        ct = (
            ClientTemplate.objects
            .filter(
                client__client_id=client_id,
                template_key=template_key,
                country__code=country_id,
                is_active=True,
            )
            .first()
        )
        if ct and ct.htmlblob and ct.htmlblob.strip():
            return ct.htmlblob

    # 2. ClientTemplate with country=NULL (existing behavior)
    ct = (
        ClientTemplate.objects
        .filter(
            client__client_id=client_id,
            template_key=template_key,
            country__isnull=True,
            is_active=True,
        )
        .first()
    )
    if ct and ct.htmlblob and ct.htmlblob.strip():
        return ct.htmlblob

    chain_ids = get_client_sector_chain(client_id)

    # 3. SectorTemplate: sector chain + country=X
    if country_id and chain_ids:
        blobs = (
            SectorTemplate.objects
            .filter(
                sector_node_id__in=chain_ids,
                country__code=country_id,
                template_key=template_key,
                is_active=True,
            )
            .order_by('-sector_node__depth')
            .values_list('htmlblob', flat=True)
        )
        for blob in blobs:
            if blob and blob.strip():
                return blob

    # 4. SectorTemplate: global (NULL sector) + country=X
    if country_id:
        blobs = (
            SectorTemplate.objects
            .filter(
                sector_node__isnull=True,
                country__code=country_id,
                template_key=template_key,
                is_active=True,
            )
            .values_list('htmlblob', flat=True)
        )
        for blob in blobs:
            if blob and blob.strip():
                return blob

    # 5. SectorTemplate: sector chain + country=NULL (existing behavior)
    if chain_ids:
        blobs = (
            SectorTemplate.objects
            .filter(
                sector_node_id__in=chain_ids,
                country__isnull=True,
                template_key=template_key,
                is_active=True,
            )
            .order_by('-sector_node__depth')
            .values_list('htmlblob', flat=True)
        )
        for blob in blobs:
            if blob and blob.strip():
                return blob

    # 6. SectorTemplate: global default (NULL sector, NULL country)
    blobs = (
        SectorTemplate.objects
        .filter(
            sector_node__isnull=True,
            country__isnull=True,
            template_key=template_key,
            is_active=True,
        )
        .values_list('htmlblob', flat=True)
    )
    for blob in blobs:
        if blob and blob.strip():
            return blob

    return ''


# this is to be used for getting the gentext like name, nb_title for further passing to svgtextbadge
@register.simple_tag(takes_context=True)
def mylist_bykey(context, lv_list=[], lv_val0="name", lv_key0="block_type"):
     
    """ 
    Input:
      "textblocks": [
            {
            "block_type": "name",
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
            "block_type": "nb_title",
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
            "block_type": "name",
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
    Renders a template fragment for the current client, resolved in order:
      1. ClientTemplate (client-specific DB row)
      2. SectorTemplate at the client's sector, deepest node first
      3. SectorTemplate at ancestor sectors
      4. SectorTemplate global default (sector_node = NULL)
    All defaults are seeded into the DB — no filesystem fallback remains.

    Usage in templates:
      {% load client_template_tags %}
      {% render_client_template 'catalogue_item_card' item=item %}
    """
    request = context.get('request')
    client  = context.get('client', {})
    client_id = client.get('client_id') if isinstance(client, dict) else getattr(client, 'client_id', None)

    if not client_id:
        return ''

    # modeltranslation already resolves language automatically
    country_code = getattr(request, 'active_country_code', None)
    cache_key = f"client_template:{client_id}:{template_key}:{country_code or 'global'}"

    cached_html = cache.get(cache_key)

    if cached_html is None:
        cached_html = _resolve_template_html(client_id, template_key, country_code=country_code)
        cache.set(cache_key, cached_html, timeout=3600)

    if cached_html and cached_html.strip():
        # Render the DB template string with the current context
        # Merge context + extra_context
        render_context = dict(context.flatten())
        render_context.update(extra_context)
        try:
            t = Template(cached_html)
            return t.render(Context(render_context))
        except Exception:
            logger.exception(
                "render_client_template: error rendering client=%s key=%s",
                client_id, template_key,
            )
            return ''  # fail silently — don't break the page

    logger.warning(
        "render_client_template: no template resolved for client=%s key=%s "
        "(missing global default row?)",
        client_id, template_key,
    )
    return ''