# utils/i18n.py

from django.conf import settings
from modeltranslation.utils import build_localized_fieldname
from django.utils.translation import get_language
from modeltranslation.translator import (
    translator,
    NotRegistered,
)

# fir a given field name, it will return name_en, name_fr...
def translated_fields(base_field_names):
    fields = []

    for field in base_field_names:
        fields.append(field)

        for lang, _ in settings.LANGUAGES:
            fields.append(
                build_localized_fieldname(field, lang)
            )

    return fields

def get_client_language(client=None):
    """
    Resolve fallback/base language for a client.
    """
    if (
        client
        and hasattr(client, 'default_language')
        and client.default_language
    ):
        return client.default_language

    return settings.LANGUAGE_CODE or 'en'

def resolve_translated_value(
    instance,
    field_name,
    client=None,
    empty_value='',
):
    """
    Resolve translated field value with fallback.

    Priority:
      1. active language
      2. client.default_language
      3. empty_value
    """

    client_lang = get_client_language(client)

    active_lang = get_language() or client_lang

    # Active language
    value = getattr(
        instance,
        f'{field_name}_{active_lang}',
        None
    )

    if value:
        return value

    # Client fallback language
    if active_lang != client_lang:

        value = getattr(
            instance,
            f'{field_name}_{client_lang}',
            None
        )

        if value:
            return value

    return empty_value

def get_translated_fields(instance):
    """
    Returns set of modeltranslation base fields.
    """
    try:
        opts = translator.get_options_for_model(type(instance))
        return set(opts.fields)
    except NotRegistered:
        return set()

def get_generated_translation_columns(translated_fields):
    """
    Returns generated columns:
    name_en, name_hi, etc.
    """
    cols = set()

    for field_name in translated_fields:
        for lang_code, _ in settings.LANGUAGES:
            cols.add(f'{field_name}_{lang_code}')

    return cols

def DEPRECATEDresolve_translated_value(
    instance,
    field_name,
    client=None,
    fallback_language='en',
):
    """
    Resolve translated value with fallback chain.

    Priority:
      1. active language
      2. client.default_language
      3. fallback_language
      4. ''

    Works with django-modeltranslation fields.
    a field like name will have multiple fields name_en, name_fr, name_hi... 
    This function will return field name with appropriate value
    """

    # ── client fallback ──────────────────────────────────────
    client_lang = settings.LANGUAGE_CODE or fallback_language

    if (
        client
        and hasattr(client, 'default_language')
        and client.default_language
    ):
        client_lang = client.default_language

    # ── active language ──────────────────────────────────────
    active_lang = get_language() or client_lang

    # ── 1. active language ───────────────────────────────────
    value = getattr(
        instance,
        f"{field_name}_{active_lang}",
        None
    )

    if value:
        return value

    # ── 2. client default language ──────────────────────────
    if client_lang != active_lang:

        value = getattr(
            instance,
            f"{field_name}_{client_lang}",
            None
        )

        if value:
            return value

    # ── 3. global fallback language ─────────────────────────
    if fallback_language not in [active_lang, client_lang]:

        value = getattr(
            instance,
            f"{field_name}_{fallback_language}",
            None
        )

        if value:
            return value

    return ''