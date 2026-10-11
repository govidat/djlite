"""Catalogue LHS: rolled-up counts, tri-state selection annotations,
own-facet-excluded node + attribute value counts, taxonomy-wins dedupe.

Tree fixture (global 'gpc' taxonomy, materialized paths via save()):
    R (order 1)
      A (order 1)   ← i1, i3 tagged; + derived i4 via GlobalItem tag
      B (order 2)
        B1 (order 1) ← i2, i3 tagged
"""
import pytest
from django.core.cache import cache

from mysite.models import Client, Taxonomy
from mysite.models.catalogue import (
    GlobalItem,
    GlobalItemAttributeValue,
    GlobalItemTaxonomyNode,
    Item,
    ItemAttributeValue,
    ItemTaxonomyNode,
    NodeAttributeType,
    NodeAttributeValue,
    TaxonomyNode,
)
from utils.catalogue_queries import (
    _facet_value_counts,
    build_catalogue_payload,
    get_item_queryset,
    get_taxonomy_tree,
)


pytestmark = pytest.mark.django_db


def mk_item(client, iid):
    return Item.objects.create(
        client=client, item_code=iid, domain='product', status='active',
        name=iid,
    )


@pytest.fixture
def setup():
    cache.clear()
    client = Client.objects.create(client_code='zlhs-client')
    tax = Taxonomy.objects.create(slug='gpc', name='GPC', is_active=True)

    def node(parent, order, slug):
        return TaxonomyNode.objects.create(
            taxonomy=tax, client=None, slug=slug, name=slug.upper(),
            parent=parent, order=order,
        )

    R = node(None, 1, 'root')
    A = node(R, 1, 'a')
    B = node(R, 2, 'b')
    B1 = node(B, 1, 'b1')

    i1 = mk_item(client, 'i1')
    i2 = mk_item(client, 'i2')
    i3 = mk_item(client, 'i3')
    ItemTaxonomyNode.objects.create(item=i1, node=A)
    ItemTaxonomyNode.objects.create(item=i2, node=B1)
    ItemTaxonomyNode.objects.create(item=i3, node=A)   # cross-child double tag
    ItemTaxonomyNode.objects.create(item=i3, node=B1)

    # Derived item: tagging lives only on the GlobalItem
    gitem = GlobalItem.objects.create(global_item_code='g-lhs-1', status='active')
    i4 = Item.objects.create(
        client=client, item_code='i4', global_item=gitem,
        domain='product', status='active', name='i4',
    )
    GlobalItemTaxonomyNode.objects.create(global_item=gitem, node=A)

    return {
        'client': client, 'tax': tax,
        'R': R, 'A': A, 'B': B, 'B1': B1,
        'i1': i1, 'i2': i2, 'i3': i3, 'i4': i4,
    }


def tree_by_slug(client, **kwargs):
    qs = get_item_queryset(client, {})
    tree = get_taxonomy_tree(
        client, 'gpc', include_counts=True, base_qs=qs, **kwargs
    )
    flat = {}

    def walk(nodes):
        for n in nodes:
            flat[n['slug']] = n
            walk(n['children'])

    walk(tree)
    return flat


# ── Rolled-up counts ─────────────────────────────────────────────────

def test_counts_roll_up_subtree_and_dedupe(setup):
    flat = tree_by_slug(setup['client'])
    assert flat['a']['count'] == 3      # i1, i3 direct + i4 via GlobalItem
    assert flat['b']['count'] == 2      # i2, i3 (i3 deduped within subtree)
    assert flat['root']['count'] == 4   # i1..i4 — every badge matches the query


def test_global_derived_tags_counted(setup):
    flat = tree_by_slug(setup['client'])
    assert flat["a"]["count"] == 3


# ── Tri-state selection annotations ─────────────────────────────────

def test_selecting_parent_selects_descendants(setup):
    flat = tree_by_slug(setup['client'], selected_node_ids=[setup['B'].id])
    assert flat['b']['is_selected']
    assert flat['b1']['is_selected']         # rendered child shows checked
    # Ancestor above the chosen node is only PARTIALLY covered (Value-Summary
    # semantics): its other subtree 'a' is untouched.
    assert flat['root']['is_partial']
    assert not flat['root']['is_selected']
    assert not flat['a']['is_selected']
    assert not flat['a']['is_partial']


def test_selecting_child_marks_ancestors_partial(setup):
    flat = tree_by_slug(setup['client'], selected_node_ids=[setup['A'].id])
    assert flat['a']['is_selected']
    assert flat['root']['is_partial']
    assert not flat['b']['is_selected'] and not flat['b']['is_partial']


def test_no_selection_flags_when_empty(setup):
    flat = tree_by_slug(setup['client'], selected_node_ids=None)
    for slug in ('root', 'a', 'b', 'b1'):
        assert not flat[slug]['is_selected']
        assert not flat[slug]['is_partial']


# ── Node badge counts (own-facet excluded, payload level) ────────────

def test_selecting_node_keeps_sibling_badges(setup):
    """Ticking A narrows the grid to i1/i3/i4 but B and R badges must
    keep their un-narrowed values (own-facet-excluded counting)."""
    c = setup['client']
    payload = build_catalogue_payload(
        client=c, filters={'node_ids': [setup['A'].id]},
        page_number=1, per_page=24,
    )

    assert payload['pagination']['total_count'] == 3   # grid narrowed

    gpc = next(t for t in payload['taxonomies'] if t['slug'] == 'gpc')
    flat = {}

    def walk(nodes):
        for n in nodes:
            flat[n['slug']] = n
            walk(n['children'])

    walk(gpc['tree'])
    assert flat['a']['count'] == 3
    assert flat['b']['count'] == 2      # sibling unaffected by selection
    assert flat['b1']['count'] == 2
    assert flat['root']['count'] == 4

    assert flat['a']['is_selected']     # checkbox state still annotated
    assert flat['root']['is_partial']


# ── Attribute facet counts (own-facet excluded) ──────────────────────

@pytest.fixture
def attr_setup(setup):
    T_color = NodeAttributeType.objects.create(
        node=setup['R'], slug='color', name='Color', is_filterable=True,
    )
    red = NodeAttributeValue.objects.create(
        attribute_type=T_color, slug='red', name='Red',
    )
    blue = NodeAttributeValue.objects.create(
        attribute_type=T_color, slug='blue', name='Blue',
    )
    T_size = NodeAttributeType.objects.create(
        node=setup['R'], slug='size', name='Size', is_filterable=True,
    )
    big = NodeAttributeValue.objects.create(
        attribute_type=T_size, slug='big', name='Big',
    )
    ItemAttributeValue.objects.create(
        item=setup['i1'], attribute_type=T_color, predefined_value=red)
    ItemAttributeValue.objects.create(
        item=setup['i2'], attribute_type=T_color, predefined_value=blue)
    ItemAttributeValue.objects.create(
        item=setup['i3'], attribute_type=T_color, predefined_value=red)
    ItemAttributeValue.objects.create(
        item=setup['i1'], attribute_type=T_size, predefined_value=big)
    ItemAttributeValue.objects.create(
        item=setup['i2'], attribute_type=T_size, predefined_value=big)
    setup.update(T_color=T_color, red=red, blue=blue, T_size=T_size, big=big)
    return setup


def test_own_facet_exclusion_keeps_siblings_visible(attr_setup):
    c = attr_setup['client']
    qs = get_item_queryset(c, {})  # no attr constraints — base scope
    counts = _facet_value_counts(
        qs, {attr_setup['T_color'].id: [attr_setup['red'].id]},
        attr_setup['T_color'].id,
    )
    assert counts[attr_setup['red'].id] == 2   # i1, i3
    assert counts[attr_setup['blue'].id] == 1  # sibling stays visible


def test_other_facet_selection_narrows_counts(attr_setup):
    c = attr_setup['client']
    qs = get_item_queryset(c, {})
    selections = {
        attr_setup['T_color'].id: [attr_setup['red'].id],
        attr_setup['T_size'].id: [attr_setup['big'].id],
    }
    counts = _facet_value_counts(
        qs, selections, attr_setup['T_color'].id,
    )
    # size=big narrows to {i1,i2}; within them color: red(i1)=1, blue(i2)=1
    assert counts[attr_setup['red'].id] == 1
    assert counts[attr_setup['blue'].id] == 1


# ── Taxonomy-wins dedupe ─────────────────────────────────────────────

def test_flat_brand_taxonomy_suppresses_duplicates(attr_setup):
    c = attr_setup['client']

    brand_tax = Taxonomy.objects.create(slug='brand', name='Brand', is_active=True)
    br1 = TaxonomyNode.objects.create(
        taxonomy=brand_tax, client=None, slug='acme', name='Acme', order=1,
    )
    br2 = TaxonomyNode.objects.create(
        taxonomy=brand_tax, client=None, slug='zen', name='Zen', order=2,
    )
    ItemTaxonomyNode.objects.create(item=attr_setup['i1'], node=br1)
    ItemTaxonomyNode.objects.create(item=attr_setup['i2'], node=br2)

    # Duplicate facet: a 'brand'-slugged attribute type on the gpc root
    dup = NodeAttributeType.objects.create(
        node=attr_setup['R'], slug='brand', name='Brand', is_filterable=True,
    )
    bv = NodeAttributeValue.objects.create(
        attribute_type=dup, slug='acme-attr', name='Acme',
    )
    ItemAttributeValue.objects.create(
        item=attr_setup['i1'], attribute_type=dup, predefined_value=bv)

    payload = build_catalogue_payload(
        client=c, filters={}, page_number=1, per_page=24,
    )

    assert payload['brands'] == []  # flat section dropped

    brand_block = next(
        t for t in payload['taxonomies'] if t['slug'] == 'brand'
    )
    names = {n['name'] for n in brand_block['tree']}
    assert {'Acme', 'Zen'} <= names
    by_name = {n['name']: n for n in brand_block['tree']}
    assert by_name['Acme']['count'] == 1
    assert by_name['Zen']['count'] == 1

    for t in payload['taxonomies']:
        slugs = {a['slug'] for a in t['attr_types']}
        assert 'brand' not in slugs  # duplicate attribute suppressed


# ── Markup contract ──────────────────────────────────────────────────

def test_filter_node_renders_tx_markup_with_states(setup):
    from django.template import Context, Template

    flat = tree_by_slug(setup['client'], selected_node_ids=[setup['A'].id])
    tpl = Template(
        "{% include 'catalogue/partials/filter_node.html' %}"
    )
    html = tpl.render(Context({
        'node': flat['root'],
        'active_node_ids': [],
        'counts': {},
        'taxonomy_slug': 'gpc',
        'client': setup['client'],
    }))
    assert 'class="tx-node"' in html
    assert 'tx-checkbox' in html
    assert 'hx-include="#filter-form"' in html          # items stay wired
    assert 'data-partial' in html                        # root above selection
    assert 'txToggleNode(this)' in html                  # collapse toggle
    assert 'badge-sm badge-ghost' in html                # count badge renders…
    assert str(flat['root']['count']) in html            # …with node's own count
