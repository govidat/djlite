# mysite/tests/demand/test_taxonomy_tree.py
"""
Tests for the taxonomy / sales-hierarchy tree filter widgets:

  * taxonomy_tree_panel       — lazy multi-select tree, optional
                                taxonomy_slug restriction, eager
                                expansion of branches to a selected node.
  * taxonomy_tree_children    — htmx lazy-load endpoint (one level).
  * sales_tree_panel/children — same pattern for the SalesNode hierarchy.

Run: python -m pytest mysite/tests/demand/test_taxonomy_tree.py -q --tb=short
"""

import pytest
from django.urls import reverse


# ── Helpers to inspect a rendered node / checkbox state ────────────────

def _node_block(body, node_id):
    """Extract one <li class="tx-node" data-node-id="...">...</li> block."""
    import re
    m = re.search(
        r'<li class="tx-node" data-node-id="%s">.*?(?=<li class="tx-node" data-node-id=|</ul>)' % node_id,
        body, re.S,
    )
    return m.group(0) if m else ''


def _checkbox(block, node_id, name='taxonomy_node_ids'):
    import re
    m = re.search(
        r'<input[^>]*name="%s"[^>]*value="%s"[^>]*>' % (name, node_id),
        block,
    )
    return m.group(0) if m else ''


def _is_checked(block, node_id, name='taxonomy_node_ids'):
    return 'checked' in _checkbox(block, node_id, name)


# ── Local fixtures (mirror test_aggregates; conftest provides
#    client_obj, sales_root, sales_leaf) ────────────────────────────────

@pytest.fixture
def taxonomy_common(db, client_obj):
    from mysite.models import Taxonomy
    return Taxonomy.objects.create(
        client=client_obj, slug='gpc', name='GPC', taxonomy_type='gpc',
    )


@pytest.fixture
def tax_root(db, client_obj, taxonomy_common):
    from mysite.models import TaxonomyNode
    node = TaxonomyNode.objects.create(
        taxonomy=taxonomy_common, client=client_obj,
        slug='seg', name='Segment', order=1,
    )
    node.refresh_from_db()
    return node


@pytest.fixture
def tax_leaf(db, client_obj, taxonomy_common, tax_root):
    from mysite.models import TaxonomyNode
    node = TaxonomyNode.objects.create(
        taxonomy=taxonomy_common, client=client_obj, parent=tax_root,
        slug='brick-a', name='Brick A', order=1,
    )
    node.refresh_from_db()
    return node


@pytest.fixture
def other_taxonomy(db, client_obj):
    from mysite.models import Taxonomy
    return Taxonomy.objects.create(
        client=client_obj, slug='brand', name='Brand', taxonomy_type='brand',
    )


@pytest.fixture
def other_root(db, client_obj, other_taxonomy):
    from mysite.models import TaxonomyNode
    node = TaxonomyNode.objects.create(
        taxonomy=other_taxonomy, client=client_obj,
        slug='brand-root', name='AcmeBrand', order=1,
    )
    node.refresh_from_db()
    return node


# ── Taxonomy tree widget ─────────────────────────────────────────────────

@pytest.mark.django_db
class TestTaxonomyTreeWidget:

    def _panel(self, client_obj, **params):
        base = reverse(
            'demand_ui:taxonomy_tree_panel',
            kwargs={'client_code': client_obj.client_code},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def _children(self, client_obj, node_id, **params):
        base = reverse(
            'demand_ui:taxonomy_tree_children',
            kwargs={'client_code': client_obj.client_code, 'node_id': node_id},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def test_panel_restricts_to_planning_taxonomy(
        self, client_obj, tax_root, other_root,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj, taxonomy_slug='gpc'))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Segment' in body
        assert 'AcmeBrand' not in body

    def test_panel_without_slug_shows_all_taxonomies(
        self, client_obj, tax_root, other_root,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj))
        body = resp.content.decode()
        assert 'Segment' in body
        assert 'AcmeBrand' in body

    def test_panel_marks_selected_and_expands_ancestors(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj, taxonomy_node_ids=f'{tax_leaf.pk}'))
        body = resp.content.decode()
        # selected leaf is rendered as a checked box named taxonomy_node_ids
        assert 'name="taxonomy_node_ids"' in body
        assert f'value="{tax_leaf.pk}"' in body
        # its parent branch is open (not collapsed), toggle arrow open
        assert f'id="tx-children-{tax_root.pk}"' in body
        assert 'tx-toggle-open' in body

    def test_panel_defaults_to_collapsed(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj))
        body = resp.content.decode()
        assert 'tx-collapsed' in body
        assert 'tx-toggle-open' not in body

    def test_children_endpoint_returns_one_level(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._children(client_obj, tax_root.pk))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert f'value="{tax_leaf.pk}"' in body

    def test_children_endpoint_404_for_unknown_node(self, client_obj):
        from django.test import Client
        c = Client()
        resp = c.get(self._children(client_obj, 999999))
        assert resp.status_code == 404

    def test_panel_selected_leaf_marks_ancestors_partial(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        body = c.get(
            self._panel(client_obj, taxonomy_node_ids=f'{tax_leaf.pk}')
        ).content.decode()
        root_block = _node_block(body, tax_root.pk)
        assert root_block, 'root node should be rendered'
        # leaf is checked; root is NOT checked but partial (indeterminate)
        assert _is_checked(root_block, tax_root.pk) is False
        assert 'data-partial' in root_block
        assert _is_checked(_node_block(body, tax_leaf.pk), tax_leaf.pk)

    def test_panel_selected_root_ticks_all_rendered_descendants(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        body = c.get(
            self._panel(client_obj, taxonomy_node_ids=f'{tax_root.pk}')
        ).content.decode()
        assert _is_checked(_node_block(body, tax_root.pk), tax_root.pk)
        leaf_block = _node_block(body, tax_leaf.pk)
        assert leaf_block, 'descendant should render open (eager)'
        assert _is_checked(leaf_block, tax_leaf.pk)
        assert 'data-partial' not in _node_block(body, tax_root.pk)

    def test_children_endpoint_ticks_descendants_of_checked_ancestor(
        self, client_obj, tax_root, tax_leaf,
    ):
        from django.test import Client
        c = Client()
        body = c.get(
            self._children(client_obj, tax_root.pk,
                           taxonomy_node_ids=f'{tax_root.pk}')
        ).content.decode()
        assert _is_checked(body, tax_leaf.pk, 'taxonomy_node_ids')


# ── Sales-hierarchy tree widget ──────────────────────────────────────────

@pytest.mark.django_db
class TestSalesTreeWidget:

    def _panel(self, client_obj, **params):
        base = reverse(
            'demand_ui:sales_tree_panel',
            kwargs={'client_code': client_obj.client_code},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def _children(self, client_obj, node_id, **params):
        base = reverse(
            'demand_ui:sales_tree_children',
            kwargs={'client_code': client_obj.client_code, 'node_id': node_id},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def test_panel_renders_roots_with_code_name_labels(
        self, client_obj, sales_root, sales_leaf,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'name="sales_node_ids"' in body
        assert 'NSM — National' in body

    def test_panel_marks_selected_and_expands_ancestors(
        self, client_obj, sales_root, sales_leaf,
    ):
        from django.test import Client
        c = Client()
        resp = c.get(self._panel(client_obj, sales_node_ids=f'{sales_leaf.pk}'))
        body = resp.content.decode()
        assert f'value="{sales_leaf.pk}"' in body
        assert f'id="tx-children-{sales_root.pk}"' in body
        assert 'tx-toggle-open' in body

    def test_children_endpoint(self, client_obj, sales_root, sales_leaf):
        from django.test import Client
        c = Client()
        resp = c.get(self._children(client_obj, sales_root.pk))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body

    def test_children_endpoint_404_for_unknown_node(self, client_obj):
        from django.test import Client
        c = Client()
        resp = c.get(self._children(client_obj, 999999))
        assert resp.status_code == 404

    def test_panel_selected_leaf_marks_root_partial(
        self, client_obj, sales_root, sales_leaf,
    ):
        from django.test import Client
        c = Client()
        body = c.get(
            self._panel(client_obj, sales_node_ids=f'{sales_leaf.pk}')
        ).content.decode()
        root_block = _node_block(body, sales_root.pk)
        assert root_block, 'root should render open'
        assert _is_checked(root_block, sales_root.pk, 'sales_node_ids') is False
        assert 'data-partial' in root_block
        assert _is_checked(_node_block(body, sales_leaf.pk), sales_leaf.pk,
                           'sales_node_ids')

    def test_panel_selected_root_ticks_descendants(
        self, client_obj, sales_root, sales_leaf,
    ):
        from django.test import Client
        c = Client()
        body = c.get(
            self._panel(client_obj, sales_node_ids=f'{sales_root.pk}')
        ).content.decode()
        assert _is_checked(_node_block(body, sales_root.pk), sales_root.pk,
                           'sales_node_ids')
        leaf_block = _node_block(body, sales_leaf.pk)
        assert leaf_block, 'descendant should render open (eager)'
        assert _is_checked(leaf_block, sales_leaf.pk, 'sales_node_ids')
        assert 'data-partial' not in _node_block(body, sales_root.pk)
