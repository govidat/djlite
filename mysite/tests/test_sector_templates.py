"""Client Sector Classification + SectorTemplate resolution tests.

Covers:
- Seed guard: every TEMPLATE_CHOICES key has an active global default row
- get_client_sector_chain ancestry walk
- _resolve_template_html precedence:
    Client > exact sector > ancestor sectors > global default
"""
import pytest
from django.core.cache import cache

from mysite.models import Client, SectorTemplate, TaxonomyNode
from mysite.models.client import ClientTemplate
from mysite.templatetags.my_tags import (
    _resolve_template_html,
    get_client_sector_chain,
)


pytestmark = pytest.mark.django_db


def make_global(template_key, html):
    """Update-or-create the single allowed global default row."""
    obj, created = SectorTemplate.objects.get_or_create(
        sector_node=None, template_key=template_key,
        defaults={'htmlblob': html},
    )
    if not created and obj.htmlblob != html:
        obj.htmlblob = html
        obj.save(update_fields=['htmlblob'])
    return obj


def make_sector(node, template_key, html):
    return SectorTemplate.objects.create(
        sector_node=node, template_key=template_key, htmlblob=html,
    )


@pytest.fixture
def sector_tree():
    """The globally-seeded sector taxonomy tree."""
    qs = TaxonomyNode.objects.filter(taxonomy__slug='sector')
    by_slug = {n.slug: n for n in qs}
    assert set(by_slug) >= {'industrial', 'automotive', 'autocomponents'}
    return by_slug


@pytest.fixture
def client_under_autocomponents(sector_tree):
    return Client.objects.create(
        client_code='zztest-auto-comp',
        sector=sector_tree['autocomponents'],
    )


# ── Seed completeness guard ──────────────────────────────────────────

def test_every_template_key_has_active_global_default():
    missing = [
        key for key, _label in ClientTemplate.TEMPLATE_CHOICES
        if not SectorTemplate.objects.filter(
            sector_node__isnull=True, template_key=key, is_active=True,
        ).exists()
    ]
    assert not missing, (
        f"No global default SectorTemplate row(s) for: {missing}. "
        f"Defaults are DB-owned since 0083 — seed them via Admin or migration."
    )


# ── Sector chain ─────────────────────────────────────────────────────

def test_sector_chain_walks_to_root(client_under_autocomponents, sector_tree):
    cache.clear()
    chain_ids = get_client_sector_chain(client_under_autocomponents.client_code)
    expected = [
        sector_tree['autocomponents'].id,
        sector_tree['automotive'].id,
        sector_tree['industrial'].id,
    ]
    assert sorted(chain_ids) == sorted(expected)


def test_sector_chain_empty_for_client_without_sector():
    c = Client.objects.create(client_code='zztest-nosector')
    assert get_client_sector_chain(c.client_code) == []


# ── Resolution precedence ────────────────────────────────────────────

KEY = 'catalogue_item_card'


def test_global_default_used_when_nothing_else(client_under_autocomponents):
    cache.clear()
    make_global(KEY, '<b>global</b>')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == '<b>global</b>'


def test_exact_sector_beats_global(client_under_autocomponents, sector_tree):
    cache.clear()
    make_global(KEY, 'global')
    make_sector(sector_tree['autocomponents'], KEY, 'autocomponents')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'autocomponents'


def test_ancestor_sector_used_when_no_exact_row(client_under_autocomponents, sector_tree):
    cache.clear()
    make_global(KEY, 'global')
    make_sector(sector_tree['automotive'], KEY, 'automotive')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'automotive'


def test_deepest_sector_wins_over_ancestor(client_under_autocomponents, sector_tree):
    cache.clear()
    make_sector(sector_tree['industrial'], KEY, 'industrial')
    make_sector(sector_tree['automotive'], KEY, 'automotive')
    make_sector(sector_tree['autocomponents'], KEY, 'autocomponents')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'autocomponents'


def test_client_template_beats_all_tiers(client_under_autocomponents, sector_tree):
    cache.clear()
    make_global(KEY, 'global')
    make_sector(sector_tree['autocomponents'], KEY, 'autocomponents')
    ClientTemplate.objects.create(
        client=client_under_autocomponents, template_key=KEY, htmlblob='client',
    )
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'client'


def test_inactive_sector_row_is_skipped(client_under_autocomponents, sector_tree):
    cache.clear()
    row = make_sector(sector_tree['autocomponents'], KEY, 'inactive')
    row.is_active = False
    row.save()
    make_global(KEY, 'global')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'global'


def test_inactive_global_default_returns_empty(client_under_autocomponents):
    cache.clear()
    seeded_key = 'catalogue_pagination'
    row = SectorTemplate.objects.get(sector_node=None, template_key=seeded_key)
    row.is_active = False
    row.save()
    assert _resolve_template_html(
        client_under_autocomponents.client_code, seeded_key
    ) == ''


def test_blank_htmlblob_falls_through_to_next_tier(client_under_autocomponents, sector_tree):
    cache.clear()
    make_sector(sector_tree['autocomponents'], KEY, '   ')  # blank
    make_global(KEY, 'global')
    html = _resolve_template_html(client_under_autocomponents.client_code, KEY)
    assert html == 'global'


def test_unseeded_key_returns_empty_string(client_under_autocomponents):
    cache.clear()
    html = _resolve_template_html(client_under_autocomponents.client_code, 'no_such_key')
    assert html == ''
