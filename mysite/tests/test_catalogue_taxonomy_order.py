"""Client catalogue_taxonomy_slugs — LHS filter subset/order tests.

Covers:
- get_resolved_taxonomies honors Client.catalogue_taxonomy_slugs
  (subset + display order, unknown slugs skipped)
- NULL/empty config falls back to legacy behavior (all active, Taxonomy.order)
- Client-specific override still beats global for retained slugs
- ClientForm CSV capture: parse/dedupe/validate, blank -> None
"""
import pytest
from django.db.models import Q

from mysite.forms import ClientForm
from mysite.models import Client, Taxonomy
from utils.catalogue_queries import get_resolved_taxonomies


pytestmark = pytest.mark.django_db


@pytest.fixture
def tax_setup():
    """Three active global taxonomies in non-alphabetical default order."""
    gpc = Taxonomy.objects.create(slug='gpc', name='GPC', order=10, is_active=True)
    brand = Taxonomy.objects.create(slug='brand', name='Brand', order=20, is_active=True)
    geo = Taxonomy.objects.create(slug='geography', name='Geography', order=30, is_active=True)
    Taxonomy.objects.create(slug='dept', name='Dept', order=40, is_active=False)  # inactive: never resolved
    return {'gpc': gpc, 'brand': brand, 'geography': geo}


def make_client(**kwargs):
    return Client.objects.create(client_code='zztax-client', **kwargs)


def slugs(client):
    return [t.slug for t in get_resolved_taxonomies(client)]


# ── Resolution ───────────────────────────────────────────────────────

def test_unconfigured_client_shows_all_active_in_default_order(tax_setup):
    client = make_client()
    result = slugs(client)
    # migration-seeded global 'sector' taxonomy may also resolve; check ours
    mine = [s for s in result if s in ('gpc', 'brand', 'geography')]
    assert mine == ['gpc', 'brand', 'geography']
    assert 'dept' not in result  # inactive → excluded


def test_empty_list_falls_back_to_all(tax_setup):
    client = make_client(catalogue_taxonomy_slugs=[])
    mine = [s for s in slugs(client) if s in ('gpc', 'brand', 'geography')]
    assert mine == ['gpc', 'brand', 'geography']


def test_configured_subset_and_order_respected(tax_setup):
    client = make_client(catalogue_taxonomy_slugs=['geography', 'gpc'])
    assert slugs(client) == ['geography', 'gpc']  # brand hidden; order not default


def test_unknown_and_inactive_slugs_skipped(tax_setup):
    client = make_client(
        catalogue_taxonomy_slugs=['ghost', 'dept', 'brand'],
    )
    assert slugs(client) == ['brand']


def test_duplicate_slugs_first_occurrence_wins(tax_setup):
    client = make_client(catalogue_taxonomy_slugs=['brand', 'gpc', 'brand'])
    assert slugs(client) == ['brand', 'gpc']


# ── Client-specific override precedence within kept slugs ────────────

def test_client_override_beats_global_for_retained_slug(tax_setup):
    mine = Taxonomy.objects.create(
        slug='brand', name='My Brand', order=99,
        is_active=True, client=make_client(),
    )
    mine.client.catalogue_taxonomy_slugs = ['brand']
    mine.client.save(update_fields=['catalogue_taxonomy_slugs'])
    resolved = get_resolved_taxonomies(mine.client)
    assert [t.slug for t in resolved] == ['brand']
    assert resolved[0].pk == mine.pk  # client row, not the global one


# ── Form capture ─────────────────────────────────────────────────────

def form_data(client, **overrides):
    data = {
        'client_code': client.client_code,
        'parent': '',
        'name': 'Test Client',
        'nb_title': '',
        'nb_title_svg_pre': '',
        'nb_title_svg_suf': '',
        'language_choices': ['en'],
        'default_language': 'en',
        'distribution_channel_choices': [],
        'catalogue_taxonomy_order': '',
    }
    data.update(overrides)
    return data


def test_form_saves_ordered_slug_list(tax_setup):
    client = make_client()
    form = ClientForm(
        form_data(client, catalogue_taxonomy_order='geography, gpc'),
        instance=client,
    )
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.catalogue_taxonomy_slugs == ['geography', 'gpc']


def test_form_normalizes_whitespace_and_case(tax_setup):
    client = make_client()
    form = ClientForm(
        form_data(client, catalogue_taxonomy_order='  Brand , gpc ,'),
        instance=client,
    )
    assert form.is_valid(), form.errors
    assert form.save().catalogue_taxonomy_slugs == ['brand', 'gpc']


def test_form_dedupes_keeping_first_position(tax_setup):
    client = make_client()
    form = ClientForm(
        form_data(client, catalogue_taxonomy_order='gpc, brand, gpc'),
        instance=client,
    )
    assert form.is_valid(), form.errors
    assert form.save().catalogue_taxonomy_slugs == ['gpc', 'brand']


def test_form_blank_stores_null(tax_setup):
    client = make_client(catalogue_taxonomy_slugs=['brand'])
    form = ClientForm(form_data(client), instance=client)
    assert form.is_valid(), form.errors
    assert form.save().catalogue_taxonomy_slugs is None


def test_form_rejects_unknown_slug(tax_setup):
    client = make_client()
    form = ClientForm(
        form_data(client, catalogue_taxonomy_order='gpc, ghost'),
        instance=client,
    )
    assert not form.is_valid()
    assert 'ghost' in str(form.errors)


def test_form_accepts_own_client_specific_slug(tax_setup):
    client = make_client()
    Taxonomy.objects.create(
        slug='mytree', name='Mine', is_active=True, client=client,
    )
    form = ClientForm(
        form_data(client, catalogue_taxonomy_order='mytree, gpc'),
        instance=client,
    )
    assert form.is_valid(), form.errors
    assert form.save().catalogue_taxonomy_slugs == ['mytree', 'gpc']
