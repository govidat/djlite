from django import template
from django.conf import settings
register = template.Library()

#@register.simple_tag
#def get_languages():
#    return settings.LANGUAGES

#@register.simple_tag
#def project_language():
#    return settings.LANGUAGE_CODE

