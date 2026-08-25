"""Seed the global Country lookup table with initial countries."""
from django.db import migrations

COUNTRIES = [
    ('IN', 'India',    '🇮🇳', 1),
    ('US', 'USA',      '🇺🇸', 2),
    ('FR', 'France',   '🇫🇷', 3),
    ('DE', 'Germany',  '🇩🇪', 4),
    ('MY', 'Malaysia', '🇲🇾', 5),
]


def seed_countries(apps, schema_editor):
    Country = apps.get_model('mysite', 'Country')
    for code, name, flag, order in COUNTRIES:
        obj, created = Country.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'flag_emoji': flag,
                'order': order,
                'is_active': True,
            },
        )
        if not created:
            Country.objects.filter(code=code).update(
                name=name, flag_emoji=flag, order=order, is_active=True,
            )


def remove_countries(apps, schema_editor):
    Country = apps.get_model('mysite', 'Country')
    Country.objects.filter(code__in=[c[0] for c in COUNTRIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0085_country_model'),
    ]

    operations = [
        migrations.RunPython(seed_countries, remove_countries),
    ]
