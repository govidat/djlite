"""Seed global-default SectorTemplate rows (sector_node = NULL) for every
key in ClientTemplate.TEMPLATE_CHOICES.

From this migration on, template DEFAULTS are DB-owned: deploys no longer
change them — edit via Django Admin (00-03F Sector Templates).

Notes:
- 'navbar' is seeded as an {% include %} wrapper because cotton/navbar_v001.html
  uses django-cotton component tags (<c-*>), which only compile when loaded
  through the cotton template loader — not through plain Template() rendering.
- All other sources are plain Django templates and are seeded inline verbatim.
- Idempotent: get_or_create per key; existing rows (incl. translations) untouched.
"""
import logging
from pathlib import Path

from django.conf import settings
from django.db import migrations

logger = logging.getLogger(__name__)

# template_key → source file relative to BASE_DIR, or None for include-wrapper
SEED_SOURCES = {
    'catalogue_filter_sidebar': 'templates/catalogue/partials/filter_sidebar.html',
    'catalogue_item_card':      'templates/catalogue/partials/item_card.html',
    'catalogue_item_detail':    'templates/catalogue/partials/item_detail.html',
    'catalogue_items_list':     'templates/catalogue/partials/items_list.html',
    'catalogue_pagination':     'templates/catalogue/partials/pagination.html',
    'demand_sidebar_nav':       'templates/demand/partials/sidebar_nav.html',
    'footer':                   'templates/cotton/footer_v001.html',
}

INCLUDE_WRAPPERS = {
    # cotton component tree — must go back through the loader chain
    'navbar': "{% include 'cotton/navbar_v001.html' %}\n",
}


def _html_field_names(model):
    """Original + per-language columns added by django-modeltranslation."""
    return [
        f.name for f in model._meta.fields
        if f.name == 'htmlblob' or f.name.startswith('htmlblob_')
    ]


def _seed_row(SectorTemplate, template_key, html):
    """
    Populate every language column so the default serves all locales.
    Repairs pre-existing rows that were created empty.
    """
    values = {name: html for name in _html_field_names(SectorTemplate)}
    values['is_active'] = True
    obj, created = SectorTemplate.objects.get_or_create(
        sector_node=None,
        template_key=template_key,
        defaults=values,
    )
    if not created:
        stale = not any(
            getattr(obj, name) and getattr(obj, name).strip()
            for name in values
        )
        if stale:
            for name, value in values.items():
                setattr(obj, name, value)
            obj.save(update_fields=list(values))


def seed_global_default_templates(apps, schema_editor):
    SectorTemplate = apps.get_model('mysite', 'SectorTemplate')
    base_dir = Path(settings.BASE_DIR)

    for template_key, rel_path in SEED_SOURCES.items():
        html = (base_dir / rel_path).read_text(encoding='utf-8')
        _seed_row(SectorTemplate, template_key, html)

    for template_key, html in INCLUDE_WRAPPERS.items():
        _seed_row(SectorTemplate, template_key, html)


def unseed(apps, schema_editor):
    SectorTemplate = apps.get_model('mysite', 'SectorTemplate')
    SectorTemplate.objects.filter(
        sector_node=None,
        template_key__in=list(SEED_SOURCES) + list(INCLUDE_WRAPPERS),
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0082_seed_sector_taxonomy'),
    ]

    operations = [
        migrations.RunPython(seed_global_default_templates, unseed),
    ]
