# utils/serializers.py

from django.db.models import ForeignKey

from utils.i18n import (
    resolve_translated_value,
    get_translated_fields,
    get_generated_translation_columns,
)


def serialize_model_resolved(
    instance,
    exclude=None,
    client=None,
):
    """
    Serialize model with resolved translated values.
    """

    exclude = set(exclude or [])

    translated_fields = get_translated_fields(instance)

    generated_lang_columns = (
        get_generated_translation_columns(
            translated_fields
        )
    )

    data = {}

    for field in instance._meta.fields:

        name = field.name

        if name in exclude:
            continue

        # Skip generated translation columns
        if name in generated_lang_columns:
            continue

        # Translated fields
        if name in translated_fields:

            value = resolve_translated_value(
                instance,
                name,
                client=client,
            )

        # FK fields
        elif isinstance(field, ForeignKey):

            value = getattr(instance, f'{name}_id')

        # Normal fields
        else:

            value = getattr(instance, name)

        if value not in [None, '']:
            data[name] = value

    return data