from django import template
from django.conf import settings
register = template.Library()

#@register.simple_tag
#def get_languages():
#    return settings.LANGUAGES

#@register.simple_tag
#def project_language():
#    return settings.LANGUAGE_CODE
"""
@register.simple_tag
def filter_dictionaries_by_key_value(data_list, myfilter):

    return [d for d in data_list if d.get(myfilter['fkey']) == myfilter['fvalue']]
"""
"""
Filters a list of dictionaries based on a specified key and its value.

Args:
    data_list (list): The list of dictionaries to filter.
    myfilter = {'fkey': xyz, 'fvalue': abc}

Returns:
    list: A new list containing only the dictionaries that match the filter criteria.
"""