# utils/globalval.py
from django.core.cache import cache
from django.conf import settings
from mysite.models import GlobalVal
from django.utils.translation import get_language

"""
GlobalVal modeltranslation
    ↓
get_globalval()
    ↓
context processor
    ↓
templates
"""

lang = get_language() or settings.LANGUAGE_CODE

CACHE_KEY = 'globalval_nested'
CACHE_TTL = 3600  # match your fetch_clientstatic timeout

def get_globalval():
    """
    Returns resolved values using active language.

    Structure:
    {
        "accounts": {
            "logout": "Logout",
            "login": "Login",
        },
        "language": {
            "en": "English",
            "hi": "Hindi",
        }
    }
    """
    lang = get_language() or settings.LANGUAGE_CODE

    cache_key = f"globalval_resolved:{lang}"

    data = cache.get(cache_key)

    if data is not None:
        return data

    qs = (
        GlobalVal.objects
        .select_related('globalvalcat')
        .only(
            'key',
            'keyval',
            'globalvalcat__globalvalcat_id',
        )
    )

    data = {}

    for obj in qs:

        cat = obj.globalvalcat.globalvalcat_id

        data.setdefault(cat, {})

        # modeltranslation auto-resolves:
        # obj.keyval -> active language
        data[cat][obj.key] = obj.keyval or obj.key

    cache.set(CACHE_KEY, data, CACHE_TTL)

    return data


"""
def get_globalval():
    data = cache.get(CACHE_KEY)
    if data is not None:
        return data

    lang_codes = [code for code, _ in settings.LANGUAGES]
    qs = GlobalVal.objects.select_related('globalvalcat').values(
        'globalvalcat__globalvalcat_id',
        'key',
        *[f'keyval_{code}' for code in lang_codes]
    )

    data = {}
    for row in qs:
        cat = row['globalvalcat__globalvalcat_id']
        key = row['key']
        data.setdefault(cat, {})[key] = {
            code: row[f'keyval_{code}'] or ''
            for code in lang_codes
        }

    cache.set(CACHE_KEY, data, CACHE_TTL)
    return data


def get_val(category, key, lang=None, fallback='en'):
    lang = lang or settings.LANGUAGE_CODE
    data = get_globalval()
    translations = data.get(category, {}).get(key, {})
    return (
        translations.get(lang)
        or translations.get(fallback)
        or f"{category}.{key}"
    )
"""

def bust_globalval_cache():
    cache.delete(CACHE_KEY)