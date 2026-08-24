# mysite/tests/demand/test_aggregates.py
"""
Tests for the multi-hierarchy drill-down aggregates:

  * write_forecast_aggregates  — ForecastAggregate rows grouped by leaf
    SalesNode (SalesForecastLink a->b->c) and by primary TaxonomyNode,
    with null agg_key ids for unassigned rows, and NO 'location' level.
  * version_aggregates view    — renders the sales / item_hierarchy levels
    and applies subtree filters (fail closed on stale ids).
  * actuals_aggregates view    — groups ActualSale rows the same way.

Run: python -m pytest mysite/tests/demand/test_aggregates.py -q --tb=short
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse


# ── Local fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def second_leaf_location(db, client_obj, root_location):
    from mysite.models.demand.hierarchy import PlanningLocation
    leaf = PlanningLocation.objects.create(
        client=client_obj, parent=root_location,
        code='LEAF-02', name='Pune Warehouse', is_leaf=True,
    )
    leaf.refresh_from_db()
    return leaf


@pytest.fixture
def unmapped_location(db, client_obj, root_location):
    from mysite.models.demand.hierarchy import PlanningLocation
    leaf = PlanningLocation.objects.create(
        client=client_obj, parent=root_location,
        code='LEAF-UN', name='Unlinked Warehouse', is_leaf=True,
    )
    leaf.refresh_from_db()
    return leaf


@pytest.fixture
def sales_leaf_b(db, client_obj, sales_root):
    from mysite.models.demand.hierarchy import SalesNode
    leaf = SalesNode.objects.create(
        client=client_obj, code='REP-02', name='Rep 2',
        level_label='Sales Rep', parent=sales_root,
    )
    leaf.refresh_from_db()
    return leaf


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
def tax_leaf_b(db, client_obj, taxonomy_common, tax_root):
    from mysite.models import TaxonomyNode
    node = TaxonomyNode.objects.create(
        taxonomy=taxonomy_common, client=client_obj, parent=tax_root,
        slug='brick-b', name='Brick B', order=2,
    )
    node.refresh_from_db()
    return node


@pytest.fixture
def item2(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(
        client=client_obj, item_id='item-002', name='Wiper',
        status='active',
    )


@pytest.fixture
def unmapped_item(db, client_obj):
    from mysite.models import Item
    return Item.objects.create(
        client=client_obj, item_id='item-UN', name='Unmapped Widget',
        status='active',
    )


@pytest.fixture
def mapped_items(db, active_item, item2, tax_leaf, tax_leaf_b):
    from mysite.models import ItemTaxonomyNode
    ItemTaxonomyNode.objects.create(item=active_item, node=tax_leaf, is_primary=True)
    ItemTaxonomyNode.objects.create(item=item2, node=tax_leaf_b, is_primary=True)


def _make_forecast_line(version, item, loc, period_start, qty, price,
                        cust=None):
    from mysite.models.demand.forecast import ForecastLine
    return ForecastLine.objects.create(
        version=version, item=item, planning_location=loc,
        planning_customer=cust, period_type='month',
        period_start=period_start,
        statistical_qty=Decimal(qty), price_used=Decimal(price),
        model_used='AutoETS', forecast_level='item_cust_location',
    )


def _make_sale(client_obj, loc, item, period_start, qty, revenue, dc,
               cust=None):
    from mysite.models.demand.actuals import ActualSale
    return ActualSale.objects.create(
        client=client_obj, planning_location=loc, item=item,
        planning_customer=cust, distribution_channel=dc,
        period_type='month', period_start=period_start,
        qty=Decimal(qty), revenue=Decimal(revenue),
    )


def _make_link(client_obj, loc, node, dc=None, cust=None):
    from mysite.models.demand.hierarchy import SalesForecastLink
    return SalesForecastLink.objects.create(
        client=client_obj, planning_location=loc, sales_node=node,
        distribution_channel=dc, planning_customer=cust,
        valid_from=datetime.date(2024, 1, 1),
    )


def _admin_client():
    from django.test import Client
    from django.contrib.auth import get_user_model
    admin = get_user_model().objects.create_superuser(
        username='agg-admin', email='agg@example.com', password='x',
    )
    c = Client()
    c.force_login(admin)
    return c


# ── write_forecast_aggregates ─────────────────────────────────────────────

@pytest.mark.django_db
class TestWriteForecastAggregates:

    def _seed(self, draft_version, client_obj, active_item, item2,
              unmapped_item, leaf_location, second_leaf_location,
              unmapped_location, sales_leaf, sales_leaf_b,
              mapped_items):
        _make_link(client_obj, leaf_location, sales_leaf)
        _make_link(client_obj, second_leaf_location, sales_leaf_b)
        # unmapped_location intentionally has NO link.

        p = datetime.date(2025, 1, 1)
        # item1 (→ Brick A) at both mapped locations
        _make_forecast_line(draft_version, active_item, leaf_location, p, '100.000', '150.00')
        _make_forecast_line(draft_version, active_item, second_leaf_location, p, '50.000', '150.00')
        # item2 (→ Brick B) at a mapped location
        _make_forecast_line(draft_version, item2, leaf_location, p, '30.000', '100.00')
        # unmapped item at the unlinked location → both "Unassigned" buckets
        _make_forecast_line(draft_version, unmapped_item, unmapped_location, p, '10.000', '100.00')

    def test_sales_rows_grouped_by_leaf_sales_node(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        from utils.demand.forecast_engine import write_forecast_aggregates
        from mysite.models.demand.forecast import ForecastAggregate

        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        write_forecast_aggregates(draft_version.pk)

        rows = ForecastAggregate.objects.filter(
            version=draft_version, agg_level='sales'
        )
        by_node = {r.agg_key.get('sales_node_id'): r for r in rows}
        assert set(by_node) == {sales_leaf.pk, sales_leaf_b.pk, None}
        assert by_node[sales_leaf.pk].total_final_value == Decimal('18000.00')
        assert by_node[sales_leaf_b.pk].total_final_value == Decimal('7500.00')
        assert by_node[None].total_final_value == Decimal('1000.00')

    def test_item_hierarchy_rows_grouped_by_primary_taxonomy_node(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        from utils.demand.forecast_engine import write_forecast_aggregates
        from mysite.models.demand.forecast import ForecastAggregate

        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        write_forecast_aggregates(draft_version.pk)

        rows = ForecastAggregate.objects.filter(
            version=draft_version, agg_level='item_hierarchy'
        )
        by_node = {r.agg_key.get('taxonomy_node_id'): r for r in rows}
        assert set(by_node) == {tax_leaf.pk, tax_leaf_b.pk, None}
        assert by_node[tax_leaf.pk].total_final_value == Decimal('22500.00')
        assert by_node[tax_leaf_b.pk].total_final_value == Decimal('3000.00')
        assert by_node[None].total_final_value == Decimal('1000.00')

    def test_location_level_no_longer_written(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        from utils.demand.forecast_engine import write_forecast_aggregates
        from mysite.models.demand.forecast import ForecastAggregate

        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        write_forecast_aggregates(draft_version.pk)

        levels = set(
            ForecastAggregate.objects.filter(version=draft_version)
            .values_list('agg_level', flat=True)
        )
        assert 'location' not in levels
        assert {'total', 'sales', 'item_hierarchy'} <= levels


# ── version_aggregates view ───────────────────────────────────────────────

@pytest.mark.django_db
class TestVersionAggregatesView:

    def _seed(self, draft_version, client_obj, active_item, item2,
              unmapped_item, leaf_location, second_leaf_location,
              unmapped_location, sales_leaf, sales_leaf_b, mapped_items):
        _make_link(client_obj, leaf_location, sales_leaf)
        _make_link(client_obj, second_leaf_location, sales_leaf_b)

        p = datetime.date(2025, 1, 1)
        _make_forecast_line(draft_version, active_item, leaf_location, p, '100.000', '150.00')
        _make_forecast_line(draft_version, active_item, second_leaf_location, p, '50.000', '150.00')
        _make_forecast_line(draft_version, item2, leaf_location, p, '30.000', '100.00')
        _make_forecast_line(draft_version, unmapped_item, unmapped_location, p, '10.000', '100.00')

        from utils.demand.forecast_engine import write_forecast_aggregates
        write_forecast_aggregates(draft_version.pk)

    def _url(self, version, client_obj, **params):
        base = reverse(
            'demand_ui:version_aggregates',
            kwargs={'client_id': client_obj.client_id, 'pk': version.pk},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def test_sales_level_renders_nodes_and_unassigned(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(draft_version, client_obj, agg_level='sales'))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' in body
        assert 'Unassigned' in body
        assert 'Sales Hierarchy' in body      # tab label
        assert 'Location' not in body.replace('Unassigned', '')

    def test_item_hierarchy_level_renders_taxonomy_nodes(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(draft_version, client_obj, agg_level='item_hierarchy'))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Brick A' in body
        assert 'Brick B' in body
        assert 'Unassigned' in body

    def test_sales_subtree_filter_restricts_to_that_node(
        self, draft_version, client_obj, sales_root, active_item, item2,
        unmapped_item, leaf_location, second_leaf_location,
        unmapped_location, sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj,
            agg_level='sales', sales_node_id=sales_leaf.pk,
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' not in body
        # Unassigned rows are outside the subtree too.
        assert 'Unassigned' not in body

    def test_sales_subtree_filter_fails_closed_on_stale_id(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj,
            agg_level='sales', sales_node_id=999999,
        ))
        assert resp.status_code == 200
        assert 'No aggregates found.' in resp.content.decode()

    def test_item_hierarchy_subtree_filter_fails_closed(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj,
            agg_level='item_hierarchy', taxonomy_node_id=999999,
        ))
        assert resp.status_code == 200
        assert 'No aggregates found.' in resp.content.decode()

    def test_sales_multi_select_union(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj, agg_level='sales',
            sales_node_ids=f'{sales_leaf.pk},{sales_leaf_b.pk}',
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' in body
        assert 'Unassigned' not in body

    def test_item_hierarchy_multi_select_union(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj, agg_level='item_hierarchy',
            taxonomy_node_ids=f'{tax_leaf.pk},{tax_leaf_b.pk}',
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Brick A' in body
        assert 'Brick B' in body
        assert 'Unassigned' not in body

    def test_item_hierarchy_multi_select_fails_closed_on_any_bad_id(
        self, draft_version, client_obj, active_item, item2, unmapped_item,
        leaf_location, second_leaf_location, unmapped_location,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(draft_version, client_obj, active_item, item2,
                   unmapped_item, leaf_location, second_leaf_location,
                   unmapped_location, sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            draft_version, client_obj, agg_level='item_hierarchy',
            taxonomy_node_ids=f'{tax_leaf.pk},999999',
        ))
        assert resp.status_code == 200
        assert 'No aggregates found.' in resp.content.decode()


# ── actuals_aggregates view ───────────────────────────────────────────────

@pytest.mark.django_db
class TestActualsAggregatesView:

    def _seed(self, client_obj, active_item, item2, unmapped_item,
              leaf_location, unmapped_location, planning_customer,
              distribution_channel_common, distribution_channel_retail,
              sales_leaf, sales_leaf_b, mapped_items):
        # Enable the Distribution Channel dimension so ActualSale keeps a
        # non-'00' channel (save() forces '00' for channel-disabled clients).
        client_obj.allowed_distribution_channels = ['00', '01']
        client_obj.save(update_fields=['allowed_distribution_channels'])

        # leaf_location: shape-c → sales_leaf, and a shape-a (dc+cust) → sales_leaf_b
        _make_link(client_obj, leaf_location, sales_leaf)
        _make_link(
            client_obj, leaf_location, sales_leaf_b,
            dc=distribution_channel_retail, cust=planning_customer,
        )
        # unmapped_location: no link at all.

        p = datetime.date(2025, 1, 1)
        # falls back to shape-c → sales_leaf
        _make_sale(client_obj, leaf_location, active_item, p, '100.000',
                   '10000.00', distribution_channel_common)
        # shape-a (retail + customer) → sales_leaf_b
        _make_sale(client_obj, leaf_location, active_item, p, '200.000',
                   '20000.00', distribution_channel_retail,
                   cust=planning_customer)
        # no link → sales Unassigned; unmapped item → taxonomy Unassigned
        _make_sale(client_obj, unmapped_location, item2, p, '50.000',
                   '5000.00', distribution_channel_common)
        _make_sale(client_obj, unmapped_location, unmapped_item, p, '30.000',
                   '3000.00', distribution_channel_common)

    def _url(self, client_obj, **params):
        base = reverse(
            'demand_ui:actuals_aggregates',
            kwargs={'client_id': client_obj.client_id},
        )
        if params:
            return f'{base}?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return base

    def test_sales_level_applies_a_to_b_to_c_precedence(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(client_obj, agg_level='sales'))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' in body
        assert 'Unassigned' in body

    def test_sales_subtree_filter_restricts_rows(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            client_obj, agg_level='sales', sales_node_id=sales_leaf.pk,
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' not in body
        assert 'Unassigned' not in body

    def test_sales_subtree_filter_fails_closed(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            client_obj, agg_level='sales', sales_node_id=999999,
        ))
        assert resp.status_code == 200
        assert 'No actuals found.' in resp.content.decode()

    def test_item_hierarchy_level_renders_taxonomy_nodes(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(client_obj, agg_level='item_hierarchy'))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Brick A' in body
        assert 'Brick B' in body
        assert 'Unassigned' in body

    def test_sales_multi_select_union(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            client_obj, agg_level='sales',
            sales_node_ids=f'{sales_leaf.pk},{sales_leaf_b.pk}',
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'REP-01 — Rep 1' in body
        assert 'REP-02 — Rep 2' in body
        assert 'Unassigned' not in body

    def test_item_hierarchy_multi_select_union(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            client_obj, agg_level='item_hierarchy',
            taxonomy_node_ids=f'{tax_leaf.pk},{tax_leaf_b.pk}',
        ))
        assert resp.status_code == 200
        body = resp.content.decode()
        assert 'Brick A' in body
        assert 'Brick B' in body
        assert 'Unassigned' not in body

    def test_item_hierarchy_multi_select_fails_closed_on_any_bad_id(
        self, client_obj, active_item, item2, unmapped_item,
        leaf_location, unmapped_location, planning_customer,
        distribution_channel_common, distribution_channel_retail,
        sales_leaf, sales_leaf_b, tax_leaf, tax_leaf_b, mapped_items,
    ):
        self._seed(client_obj, active_item, item2, unmapped_item,
                   leaf_location, unmapped_location, planning_customer,
                   distribution_channel_common, distribution_channel_retail,
                   sales_leaf, sales_leaf_b, mapped_items)
        c = _admin_client()
        resp = c.get(self._url(
            client_obj, agg_level='item_hierarchy',
            taxonomy_node_ids=f'{tax_leaf.pk},999999',
        ))
        assert resp.status_code == 200
        assert 'No actuals found.' in resp.content.decode()
