"""
Resolve scheme scope: materialize ResolvedSalesSchemePeriod for one scheme.

Called on scheme post_save when status becomes ACTIVE, and on scope/period edits.
Deletes and rebuilds the scheme's resolved rows in one transaction.
"""

from decimal import Decimal
from celery import shared_task
from django.db import transaction
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType

from mysite.models.demand.schemes import (
    SalesScheme, SalesSchemeScope, SalesSchemePeriod,
    ResolvedSalesSchemePeriod, addback_weight,
)


SPECIFICITY_MAP = {
    "OVERALL": 0,
    "TAXONOMY": 1,
    "BRAND": 2,
    "ITEM": 3,
}


def _scheme_scope_item_ids(client_id: int, node_id: int) -> tuple[int, ...]:
    """Union of item_ids mapped beneath node in ITS OWN taxonomy tree.

    Tree-aware: membership comes from ItemTaxonomyNode where the mapping node
    descends from `node` (materialized path). Deliberately NOT primary-mapping-only
    — a promo covers the item whether or not the node is its canonical planning
    grain. Used for both TAXONOMY and BRAND scope rows.
    """
    from mysite.models import ItemTaxonomyNode, Item, TaxonomyNode
    node = TaxonomyNode.objects.only("path", "taxonomy_id").get(pk=node_id)
    mapping_node_ids = TaxonomyNode.objects.filter(
        taxonomy_id=node.taxonomy_id, path__startswith=node.path,
    ).values_list("id", flat=True)
    return tuple(
        Item.objects.filter(client_id=client_id, taxonomy_mappings__node_id__in=mapping_node_ids)
        .distinct().values_list("id", flat=True)
    )


@shared_task
def resolve_scheme_scope(scheme_id: int):
    """Materialize ResolvedSalesSchemePeriod for one scheme.

    Algorithm:
    1. Load scheme; bail if status != ACTIVE.
    2. For each SalesSchemeScope, resolve the item set (tree-aware, from the scope node's
       own taxonomy).
    3. Within-scheme dedup: most-specific-wins (ITEM > BRAND > TAXONOMY > OVERALL).
    4. Cross items × periods × locations/channels/customers to build WINDOW rows.
    5. If shadow_periods > 0, build shadow rows for each WINDOW row.
    6. Delete old resolved rows and bulk_create new ones in one transaction.
    """
    scheme = SalesScheme.objects.select_related("client").prefetch_related(
        "scopes", "periods"
    ).filter(pk=scheme_id).first()
    if scheme is None:
        return {"status": "not_found"}
    if scheme.status != "ACTIVE":
        return {"status": "skipped", "reason": f"status={scheme.status}"}

    from mysite.models.demand.hierarchy import PlanningLocation
    from mysite.models.demand.actuals import DistributionChannel

    client = scheme.client
    client_id = client.pk

    # Step 2 & 3: Resolve items per scope with most-specific-wins dedup
    # {item_id: scope_type}
    item_scope_map: dict[int, str] = {}
    for scope in scheme.scopes.all():
        item_ids = _resolve_scope_items(client_id, scope)
        spec = SPECIFICITY_MAP.get(scope.scope_type, 0)
        for item_id in item_ids:
            existing_spec = SPECIFICITY_MAP.get(item_scope_map.get(item_id), 0)
            if spec > existing_spec:
                item_scope_map[item_id] = scope.scope_type

    if not item_scope_map:
        # No items resolved — delete existing and return
        ResolvedSalesSchemePeriod.objects.filter(scheme=scheme).delete()
        return {"status": "resolved", "window_rows": 0, "shadow_rows": 0}

    # Resolve locations/channels/customers from scopes
    locations, channels, customers = _resolve_scope_filters(scheme)

    # Step 4 & 5: Build WINDOW + SHADOW rows
    rows = []
    periods = list(scheme.periods.all())
    qty_factor = Decimal("1") + scheme.expected_qty_uplift_pct
    value_factor = Decimal("1") + scheme.expected_value_uplift_pct

    for item_id in item_scope_map:
        for period in periods:
            for loc in locations:
                for channel in channels:
                    for cust in customers:
                        # WINDOW row
                        rows.append(ResolvedSalesSchemePeriod(
                            scheme=scheme,
                            item_id=item_id,
                            planning_location_id=loc,
                            planning_customer_id=cust,
                            distribution_channel_id=channel,
                            period_type=period.period_type,
                            period_start=period.period_start,
                            period_end=period.period_end,
                            qty_factor=qty_factor,
                            value_factor=value_factor,
                            is_shadow=False,
                        ))

                        # Step 6: Shadow rows
                        if scheme.shadow_periods > 0:
                            _build_shadow_rows(
                                rows, scheme, item_id, loc, cust, channel,
                                period, qty_factor, value_factor,
                            )

    # Step 7: Atomic delete + bulk_create
    with transaction.atomic():
        ResolvedSalesSchemePeriod.objects.filter(scheme=scheme).delete()
        ResolvedSalesSchemePeriod.objects.bulk_create(rows, batch_size=2000)

    return {"status": "resolved", "window_rows": len([r for r in rows if not r.is_shadow]),
            "shadow_rows": len([r for r in rows if r.is_shadow])}


def _resolve_scope_items(client_id: int, scope: SalesSchemeScope) -> tuple[int, ...]:
    """Resolve item IDs for one scope row."""
    if scope.scope_type == "OVERALL":
        from mysite.models import Item
        return tuple(
            Item.objects.filter(client_id=client_id).values_list("id", flat=True)
        )
    elif scope.scope_type in ("TAXONOMY", "BRAND") and scope.taxonomy_node_id:
        return _scheme_scope_item_ids(client_id, scope.taxonomy_node_id)
    elif scope.scope_type == "ITEM" and scope.item_id:
        return (scope.item_id,)
    return ()


def _resolve_scope_filters(scheme: SalesScheme):
    """Resolve locations, channels, customers from scheme scopes.

    Returns tuples of IDs. Empty tuple means "all" for locations/channels,
    None for customers (meaning unattributed).
    """
    from mysite.models.demand.hierarchy import PlanningLocation
    from mysite.models.demand.actuals import DistributionChannel

    locations = set()
    channels = set()
    customers = set()
    has_location_filter = False
    has_channel_filter = False
    has_customer_filter = False

    for scope in scheme.scopes.all():
        if scope.planning_location_id:
            locations.add(scope.planning_location_id)
            has_location_filter = True
        if scope.distribution_channel_id:
            channels.add(scope.distribution_channel_id)
            has_channel_filter = True
        if scope.planning_customer_id:
            customers.add(scope.planning_customer_id)
            has_customer_filter = True

    # Default: all locations, default channel, unattributed customer
    if not has_location_filter:
        locations = list(
            PlanningLocation.objects.filter(client=scheme.client)
            .values_list("id", flat=True)
        )
    else:
        locations = list(locations)

    if not has_channel_filter:
        channels = list(
            DistributionChannel.objects.all().values_list("pk", flat=True)[:1]
        ) or ["00"]
    else:
        channels = list(channels)

    if not has_customer_filter:
        customers = [None]
    else:
        customers = list(customers)

    return locations, channels, customers


def _build_shadow_rows(rows, scheme, item_id, loc, cust, channel,
                       period, qty_factor, value_factor):
    """Build PRE and POST shadow rows for a WINDOW row."""
    from mysite.models.demand.schemes import (
        previous_period_start, next_period_start, addback_weight,
    )

    for side in ("PRE", "POST"):
        for j in range(1, scheme.shadow_periods + 1):
            if side == "PRE":
                shadow_start = previous_period_start(
                    period.period_start, period.period_type, j
                )
            else:
                shadow_start = next_period_start(
                    period.period_start, period.period_type, j
                )

            from mysite.models.demand.actuals import compute_period_end
            shadow_end = compute_period_end(shadow_start, period.period_type)

            aw = addback_weight(
                scheme.pull_forward_pct, side, j, scheme.shadow_periods
            )

            rows.append(ResolvedSalesSchemePeriod(
                scheme=scheme,
                item_id=item_id,
                planning_location_id=loc,
                planning_customer_id=cust,
                distribution_channel_id=channel,
                period_type=period.period_type,
                period_start=shadow_start,
                period_end=shadow_end,
                is_shadow=True,
                shadow_side=side,
                shadow_offset=j,
                anchor_period_start=period.period_start,
                anchor_qty_factor=qty_factor,
                anchor_value_factor=value_factor,
                addback_qty_weight=aw,
                addback_value_weight=aw,
            ))
