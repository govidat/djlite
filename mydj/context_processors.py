

# my_app/context_processors.py

# ADD this to project/settings.py TEMPLATES . then these are available in all templates 
from django.conf import settings
#from .constants import globalval
from utils.globalval import get_globalval
from utils.common_functions import fetch_clientstatic
import json # this is just for debugging the json outputs of client/ pages..

"""
Runs on every request that renders a template. Its job is to add template-ready variables to context. 
It calls fetch_clientstatic to get the full client dict (with pages, themes, translations etc) and resolves the active theme.
context['client'] → dict (from fetch_clientstatic)
context['theme']  → dict (resolved theme tokens)

"""

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

def client_context(request):
    """
    Single source of truth for client dict and theme in templates.
    Runs on every request. Uses request.client set by middleware
    to avoid resolving client_id twice.
    Key change: uses request.client (already resolved by middleware) instead of re-resolving client_id from URL/session. Now middleware and context processor share the work without duplicating it.
    """
    # Use client already resolved by middleware — no double lookup
    client_obj = getattr(request, 'client', None)
    if not client_obj:
        return {'client': {}, 'theme': {}, 'page': {}}

    # fetch_clientstatic is cached — this is cheap
    client_dict = fetch_clientstatic(lv_client_id=client_obj.client_id)
    client_dict.setdefault('pages', [])
    client_dict.setdefault('themes', [])

    # Resolve active theme
    selected_theme_id = request.session.get('active_theme_id')
    selected_theme = next(
        (t for t in client_dict.get('themes', [])
         if t['theme_id'] == selected_theme_id),
        None
    )
    if not selected_theme:
        selected_theme = next(
            (t for t in client_dict.get('themes', [])
             if t.get('is_default')),
            None
        )
    theme = selected_theme['tokens'] if selected_theme else {}

    # ── Resolve page from URL kwargs ──────────────────────────────
    page_id = None
    #page_dict = {}
    if hasattr(request, 'resolver_match') and request.resolver_match:
        page_id = request.resolver_match.kwargs.get('page', 'home')

    #if page_id != '':
    page_dict = next(
        (p for p in client_dict.get('pages', [])
        if p.get('page_id') == page_id),
        {}
    )

    return {
        'client': client_dict,
        'theme':  theme,
        'page_dict': page_dict,
        'jsonclient': json.dumps(client_dict),        
    }

"""
def client_context(request):
    
    #Ensures client and theme are always available in context.
    #ClientPageView sets these explicitly — this is a fallback
    #for pages like allauth that don't go through ClientPageView.
    
    # If already set by view, don't override
    # Context processors run before view context so we check session
    client_id = None

    if hasattr(request, 'resolver_match') and request.resolver_match:
        client_id = request.resolver_match.kwargs.get('client_id')

    if not client_id:
        client_id = request.session.get('client_id')

    if not client_id:
        return {'client': {}, 'theme': {}}

    client_dict = fetch_clientstatic(lv_client_id=client_id)
    client_dict.setdefault('pages', [])
    client_dict.setdefault('themes', [])

    # Resolve theme
    selected_theme_id = request.session.get('active_theme_id')
    selected_theme = next(
        (t for t in client_dict.get('themes', [])
         if t['theme_id'] == selected_theme_id),
        None
    )
    if not selected_theme:
        selected_theme = next(
            (t for t in client_dict.get('themes', []) if t.get('is_default')),
            None
        )
    theme = selected_theme['tokens'] if selected_theme else {}

    return {
        'client': client_dict,
        'theme':  theme,
    }
"""