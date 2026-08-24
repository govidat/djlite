"""Seed the global 'sector' taxonomy tree used for Client Sector
Classification (Industrial > Automotive > AutoComponents ...).

Idempotent — safe to re-run (get_or_create everywhere).
"""
from django.db import migrations


TAXONOMY_SLUG = 'sector'

# (slug, name, parent_slug, order)
SECTOR_NODES = [
    ('industrial',     'Industrial',      None,        1),
    ('automotive',     'Automotive',      'industrial', 2),
    ('autocomponents', 'Auto Components', 'automotive', 3),
]


def _materialize(node, parent):
    """Mirror TaxonomyNode.save() path logic (unavailable on historical models)."""
    if parent is not None:
        node.parent = parent
        node.path = f"{parent.path}.{node.order:03d}"
        node.depth = parent.depth + 1
    else:
        node.parent = None
        node.path = f"{node.order:03d}"
        node.depth = 0


def seed_sector_taxonomy(apps, schema_editor):
    Taxonomy = apps.get_model('mysite', 'Taxonomy')
    TaxonomyNode = apps.get_model('mysite', 'TaxonomyNode')

    taxonomy, _ = Taxonomy.objects.get_or_create(
        client=None,
        slug=TAXONOMY_SLUG,
        defaults={
            'taxonomy_type': 'sector',
            'name': 'Client Sector',
            'description': 'Industry classification of clients '
                           '(e.g. Industrial > Automotive > Auto Components). '
                           'Drives sector-scoped template resolution.',
            'is_active': True,
        },
    )

    node_by_slug = {}
    for slug, name, parent_slug, order in SECTOR_NODES:
        parent = node_by_slug.get(parent_slug)
        node, _ = TaxonomyNode.objects.get_or_create(
            taxonomy=taxonomy,
            client=None,
            slug=slug,
            defaults={
                'name': name,
                'order': order,
                'is_active': True,
            },
        )
        # Keep materialized path correct even if the row pre-existed
        node.order = order
        _materialize(node, parent)
        node.save()
        node_by_slug[slug] = node


def remove_sector_taxonomy(apps, schema_editor):
    Taxonomy = apps.get_model('mysite', 'Taxonomy')
    Taxonomy.objects.filter(client=None, slug=TAXONOMY_SLUG).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0081_client_sector_alter_clienttemplate_template_key_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_sector_taxonomy, remove_sector_taxonomy),
    ]
