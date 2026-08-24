"""
Detect scheme candidates: identify transient spikes in product-group actuals
that may indicate unplanned sales promotions.

Algorithm:
1. Aggregate raw actuals to product-group grain for the target window + lookback.
2. Run detect_candidates (MAD + persistence) per product-group series.
3. Skip candidates already covered by an ACTIVE ResolvedSalesSchemePeriod.
4. Suggest expected_qty_uplift_pct from the spike/median ratio.
5. Create DRAFT SalesScheme rows with detected_by='SYSTEM' → planner queue.
6. Record run identity on ForecastingConfig.
"""

import statistics
from decimal import Decimal

from celery import shared_task
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from mysite.models import Client, ForecastVersion
from mysite.models.demand.forecast import ForecastingConfig
from mysite.models.demand.actuals import ActualSale
from mysite.models.demand.schemes import (
    SalesScheme, SalesSchemeScope, SalesSchemePeriod,
    ResolvedSalesSchemePeriod,
)
from utils.demand.outlier_detection import detect_candidates
from utils.demand.periods import as_date, step_date


@shared_task
def detect_scheme_candidates(client_id, target_period_start, target_period_end,
                             triggered_by_user_id=None):
    """Detect transient spikes in product-group actuals that may be schemes.

    Creates DRAFT SalesScheme rows with detected_by='SYSTEM' for planner review.
    Never auto-activates.
    """
    target_period_start = as_date(target_period_start)
    target_period_end = as_date(target_period_end)

    client = Client.objects.select_related("forecasting_config").get(client_id=client_id)
    config = getattr(client, "forecasting_config", None)
    if config is None:
        return {"status": "no_config"}

    # Determine period_type from target range
    target_range_period_types = list(
        ActualSale.objects.filter(
            client=client,
            period_start__gte=target_period_start,
            period_start__lte=target_period_end,
        ).order_by().values_list("period_type", flat=True).distinct()
    )
    if not target_range_period_types:
        return {"status": "no_data"}
    if len(target_range_period_types) > 1:
        raise ValueError(f"Mixed period_type in target range: {target_range_period_types}")
    period_type = target_range_period_types[0]

    lookback_start = step_date(target_period_start, period_type, -config.min_history_periods)

    # Step 1: Aggregate raw actuals to product-group grain
    from mysite.models import TaxonomyNode, ItemTaxonomyNode
    product_group_node_ids = TaxonomyNode.objects.filter(
        taxonomy__slug=config.planning_producthierarchy,
        client_id=client_id,
    ).values_list("id", flat=True)

    # Build item → product_group mapping
    item_to_group = {}
    for node_id in product_group_node_ids:
        child_ids = TaxonomyNode.objects.filter(
            path__startswith=TaxonomyNode.objects.get(pk=node_id).path,
            taxonomy__slug=config.planning_producthierarchy,
        ).values_list("id", flat=True)
        item_ids = ItemTaxonomyNode.objects.filter(
            node_id__in=child_ids,
        ).values_list("item_id", flat=True)
        for item_id in item_ids:
            item_to_group[item_id] = node_id

    # Aggregate raw actuals by product group
    raw_rows = (
        ActualSale.objects.filter(
            client=client,
            period_start__gte=lookback_start,
            period_start__lte=target_period_end,
        )
        .values('item_id', 'period_start')
        .annotate(total_qty=Sum('qty'))
    )

    # Group by product group and period
    group_series = {}
    for row in raw_rows:
        group_id = item_to_group.get(row['item_id'])
        if group_id is None:
            continue
        group_series.setdefault(group_id, []).append({
            'period_start': row['period_start'],
            'qty': row['total_qty'],
        })

    # Step 2: Run detect_candidates per product-group series
    to_create = []
    for group_id, series_rows in group_series.items():
        series_rows.sort(key=lambda r: r['period_start'])
        values = [Decimal(str(r['qty'])) for r in series_rows]

        if len(values) < config.min_history_periods:
            continue

        candidate_indices = detect_candidates(
            [float(v) for v in values],
            mad_threshold=config.mad_threshold,
            persistence_periods=config.persistence_periods,
            min_history_periods=config.min_history_periods,
        )

        for i in candidate_indices:
            row = series_rows[i]
            if row['period_start'] < target_period_start:
                continue  # lookback-only period

            # Step 3: Skip if already covered by an ACTIVE scheme
            if ResolvedSalesSchemePeriod.objects.filter(
                scheme__status='ACTIVE',
                period_type=period_type,
                period_start=row['period_start'],
            ).filter(
                # Check if any item in this group is covered
                item_id__in=ItemTaxonomyNode.objects.filter(
                    node__in=TaxonomyNode.objects.filter(
                        path__startswith=TaxonomyNode.objects.get(pk=group_id).path,
                        taxonomy__slug=config.planning_producthierarchy,
                    )
                ).values_list("item_id", flat=True)
            ).exists():
                continue

            # Step 4: Suggest expected_qty_uplift_pct
            median_qty = statistics.median(values)
            if median_qty > 0:
                uplift_pct = (Decimal(str(row['qty'])) / median_qty) - Decimal('1')
            else:
                uplift_pct = Decimal('0')

            # Step 5: Create a DRAFT SalesScheme proposal
            to_create.append({
                'group_id': group_id,
                'period_start': row['period_start'],
                'qty': row['qty'],
                'uplift_pct': uplift_pct,
            })

    # Step 5: Create DRAFT SalesScheme rows
    created_count = 0
    with transaction.atomic():
        for proposal in to_create:
            group_node = TaxonomyNode.objects.get(pk=proposal['group_id'])
            scheme = SalesScheme(
                client=client,
                scheme_code=f"SYS-{group_node.pk}-{proposal['period_start'].strftime('%Y%m%d')}",
                name=f"System-detected spike: {group_node.name} @ {proposal['period_start']}",
                status='DRAFT',
                expected_qty_uplift_pct=proposal['uplift_pct'].quantize(Decimal('0.0001')),
                expected_value_uplift_pct=Decimal('0'),
                created_by_id=triggered_by_user_id,
            )
            scheme.full_clean()
            scheme.save()

            # Create scope (TAXONOMY)
            SalesSchemeScope.objects.create(
                scheme=scheme,
                scope_type='TAXONOMY',
                taxonomy_node=group_node,
            )

            # Create period
            SalesSchemePeriod.objects.create(
                scheme=scheme,
                period_type=period_type,
                period_start=proposal['period_start'],
            )

            created_count += 1

        # Step 6: Record run identity
        config.last_scheme_detection_run_at = timezone.now()
        config.last_scheme_detection_run_by_id = triggered_by_user_id
        config.last_scheme_detection_run_from = target_period_start
        config.last_scheme_detection_run_to = target_period_end
        config.save(update_fields=[
            "last_scheme_detection_run_at", "last_scheme_detection_run_by",
            "last_scheme_detection_run_from", "last_scheme_detection_run_to",
            "updated_at",
        ])

    return {"status": "completed", "candidates_found": created_count}
