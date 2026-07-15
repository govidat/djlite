# mysite/views/demand/forecast_grid.py

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, EmptyPage
from django.shortcuts import get_object_or_404, render

from mysite.models.demand.forecast import ForecastVersion, ForecastLine, ForecastOverride


@login_required
def forecast_grid(request, pk):
    """
    Main forecast grid page.
    Pivots ForecastLine rows into grid_rows — one entry per
    (location, item, customer) with a list of per-period cells.
    """
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

    # All periods for this version, in order
    periods = sorted(
        ForecastLine.objects
        .filter(version=version)
        .values_list('period_start', flat=True)
        .distinct()
    )
    period_labels = [p.strftime('%b-%y') for p in periods]

    # Active overrides keyed by (item_id, location_code, period_start)
    # Used to attach the override object to each cell
    applied_overrides = {
        (o.override_key.get('item_id'), o.period_start): o
        for o in ForecastOverride.objects.filter(
            version=version,
            override_level='sku',
        ).select_related('created_by')
    }

    # Paginated lines — page by unique (location, item, customer) key
    # Build a list of unique row keys first, then fetch lines for that page
    row_keys = list(
        ForecastLine.objects
        .filter(version=version)
        .order_by('planning_location__code', 'item__item_id')
        .values_list(
            'planning_location__code',
            'item__item_id',
            'planning_customer__code',
        )
        .distinct()
    )

    page_size = int(request.GET.get('page_size', 50))
    page_num  = int(request.GET.get('page', 1))
    paginator = Paginator(row_keys, page_size)
    try:
        page = paginator.page(page_num)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    page_keys = list(page.object_list)

    # Fetch all lines for the current page keys in one query
    from django.db.models import Q
    key_filter = Q()
    for loc_code, item_id, cust_code in page_keys:
        key_filter |= Q(
            planning_location__code=loc_code,
            item__item_id=item_id,
            planning_customer__code=cust_code,
        )

    page_lines = (
        ForecastLine.objects
        .filter(version=version)
        .filter(key_filter)
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('planning_location__code', 'item__item_id', 'period_start')
    )

    # Pivot into grid_rows
    line_index: dict[tuple, dict] = {}
    for line in page_lines:
        row_key = (
            line.planning_location.code,
            line.item.item_id,
            line.planning_customer.code if line.planning_customer else '',
        )
        if row_key not in line_index:
            line_index[row_key] = {
                'key':           '-'.join(row_key),
                'location_code': line.planning_location.code,
                'item_id':       line.item.item_id,
                'item_name':     line.item.name,
                'customer_code': line.planning_customer.code
                                 if line.planning_customer else '',
                'cells':         [],
            }
        ovr = applied_overrides.get((line.item.item_id, line.period_start))
        line_index[row_key]['cells'].append({
            'line':         line,
            'period_label': line.period_start.strftime('%b-%y'),
            'override':     ovr,
        })

    grid_rows = [line_index[k] for k in page_keys if k in line_index]

    from mysite.models import PlanningLocation
    locations = (
        PlanningLocation.objects
        .filter(client=request.client)
        .order_by('code')
    )

    overrides = (
        ForecastOverride.objects
        .filter(version=version)
        .select_related('created_by')
        .order_by('-created_at')
    )

    return render(request, 'demand/forecast_grid.html', {
        'version':       version,
        'lines':         page,           # Page object for pagination controls
        'periods':       periods,
        'period_labels': period_labels,
        'grid_rows':     grid_rows,
        'overrides':     overrides,
        'locations':     locations,
    })
