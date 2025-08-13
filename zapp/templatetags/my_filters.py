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


