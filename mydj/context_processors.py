

# my_app/context_processors.py

# ADD this to project/settings.py TEMPLATES . then these are available in all templates 
from django.conf import settings
#from .constants import globalval
from utils.globalval import get_globalval

def settings_constants(request):
    """
    Context processor to make settings constants available in templates.
    """
    return {
        'LANGUAGE_CODE': settings.LANGUAGE_CODE,
        # Add any other settings you want to access in templates
        # 'PC_THEMES': settings.PC_THEMES,
        #'PC_LANGUAGES': settings.PC_LANGUAGES,
    }

"""
def theme_processor(request):
    return {
        "current_theme": request.session.get("theme", "light")
    }
"""    
def globalval(request):
    lang = request.session.get('lang', settings.LANGUAGE_CODE)
    raw  = get_globalval()

    # Resolve entire nested dict to active language
    resolved = {
        cat: {
            key: (translations.get(lang) or translations.get('en') or key)
            for key, translations in keys.items()
        }
        for cat, keys in raw.items()
    }

    return {
        'gv':  resolved,  # {{ gv.accounts.logout }} → "Logout"
        'gvt': raw,       # {{ gvt.accounts.logout.hi }} → "hiLogout"
    }
"""
Template usage:
{# Active language #}
{{ gv.accounts.logout }}
{{ gv.accounts.signin_up }}

{# Specific language #}
{{ gvt.accounts.logout.hi }}

{# In your auth component #}
<c-auth-menu />

{# Inside auth_menu.html #}
{{ gv.accounts.signin }}    {# → "SignIn"      #}
{{ gv.accounts.signup }}    {# → "SignUp"      #}
{{ gv.accounts.logout }}    {# → "Logout"      #}

"""