# Sprint 3B.5 — Consensus Override UI
## Detailed Implementation Instructions

**Dependencies:** Sprint 3B.4 complete (forecast engine running, ForecastLine rows populated,
ForecastAggregate rows with `weighted_avg_price` populated, `apply_overrides` Celery task defined)
**Estimated effort:** 3–4 days
**App label:** `mysite`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Model Delta — no new models](#2-model-delta)
3. [Serializers — OverrideSplitWeight + updated ForecastOverride](#3-serializers)
4. [REST API — override CRUD endpoints](#4-rest-api)
5. [Celery — wire apply_overrides to the POST endpoint](#5-celery)
6. [URL additions](#6-url-additions)
7. [HTMX Override Form](#7-htmx-override-form)
8. [Override Propagation UI](#8-override-propagation-ui)
9. [OverrideSplitWeight Management UI](#9-overridesplitweight-management-ui)
10. [Unit Tests](#10-unit-tests)
11. [Migration and Checklist](#11-migration-and-checklist)

---

## 1. Architecture Overview

### What Sprint 3B.5 adds

Sprint 3B.4 implemented `apply_overrides` as a Celery task but provided no UI or API surface
for planners to create, inspect, or delete overrides. Sprint 3B.5 closes that gap.

```
Planner action (HTMX form or API client)
    │
    ▼
POST /api/demand/forecast-versions/{id}/overrides/
    │  Creates ForecastOverride row (validated: version must be DRAFT)
    │  Fires apply_overrides.delay(version_id)
    ▼
apply_overrides Celery task (Sprint 3B.4 — unchanged)
    │  Reads all unapplied ForecastOverride rows for the version
    │  Pushes override_qty to ForecastLine rows
    │  Calls write_forecast_aggregates() to refresh rollups
    ▼
GET /api/demand/forecast-versions/{id}/overrides/
    │  Returns list of ForecastOverride rows with is_applied status
    │  Used by the forecast grid to show pending / applied badges
    ▼
GET /api/demand/forecast-versions/{id}/overrides/{override_id}/affected-lines/
    │  Returns ForecastLine rows that were modified by one override
    │  Powers the "propagation view" — shows planner which SKUs changed
    ▼
DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/
    │  Only allowed when is_applied=False and version is DRAFT
    │  Reverts ForecastLine.override_qty to NULL (statistical only)
    │  Calls write_forecast_aggregates() to refresh rollups
    ▼
PUT /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/
    │  Replaces OverrideSplitWeight rows for a CUSTOM override
    │  Marks override as is_applied=False to trigger re-disaggregation
    │  Fires apply_overrides.delay(version_id)
```

### Data flow for override revert (DELETE)

When a planner deletes an unapplied override, the override row is deleted and nothing else
needs to happen — it was never applied to `ForecastLine` rows.

When a planner deletes an **applied** override, the endpoint must:
1. Identify which `ForecastLine` rows were touched by this override (using `override_level`
   + `override_key` + `period_start`).
2. Set `override_qty = NULL` on those lines (this sets `final_qty = statistical_qty`
   via the `ForecastLine.save()` signal).
3. Delete the `ForecastOverride` row.
4. Call `write_forecast_aggregates(version_id)` to refresh rollups.

The endpoint blocks deletion if the version is not DRAFT.

---

## 2. Model Delta

No new models in Sprint 3B.5. All models (`ForecastOverride`, `OverrideSplitWeight`,
`ForecastLine`) already exist from Sprint 3B.3.

**No migration required.**

---

## 3. Serializers

Add to `mysite/api/demand/serializers.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Sprint 3B.5 serializer additions
# ─────────────────────────────────────────────────────────────────────────────

from mysite.models.demand.forecast import ForecastOverride, OverrideSplitWeight


class OverrideSplitWeightSerializer(serializers.ModelSerializer):
    """
    Serializer for a single child weight in a CUSTOM override.
    Used nested inside ForecastOverrideDetailSerializer and standalone
    in the PUT /split-weights/ endpoint.
    """

    class Meta:
        model  = OverrideSplitWeight
        fields = ['id', 'child_key', 'weight']

    def validate_weight(self, value):
        if value < 0 or value > 1:
            raise serializers.ValidationError(
                'Weight must be between 0 and 1.'
            )
        return value


class ForecastOverrideSerializer(serializers.ModelSerializer):
    """
    List serializer — used for GET /overrides/ (list view).
    Lightweight: no nested split_weights to keep the list fast.
    is_applied is read-only — owned by the Celery task.
    """
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = ForecastOverride
        fields = [
            'id',
            'override_level', 'override_key',
            'period_type', 'period_start', 'period_end',
            'override_qty', 'override_pct', 'override_value',
            'disagg_method', 'override_note',
            'is_applied', 'created_by_name', 'created_at',
        ]
        read_only_fields = ['id', 'is_applied', 'created_at', 'created_by_name', 'period_end']

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None


class ForecastOverrideDetailSerializer(ForecastOverrideSerializer):
    """
    Detail serializer — used for GET /overrides/{id}/ and POST response.
    Includes nested split_weights for CUSTOM overrides.
    """
    split_weights = OverrideSplitWeightSerializer(many=True, read_only=True)

    class Meta(ForecastOverrideSerializer.Meta):
        fields = ForecastOverrideSerializer.Meta.fields + ['split_weights']


class ForecastOverrideCreateSerializer(serializers.ModelSerializer):
    """
    Write serializer — used for POST /overrides/.
    Enforces the mutual exclusivity of override_qty / override_pct / override_value
    and validates that override_value is not used at SKU level.
    The version and created_by are injected in the view's perform_create().
    """

    class Meta:
        model  = ForecastOverride
        fields = [
            'override_level', 'override_key',
            'period_type', 'period_start',
            'override_qty', 'override_pct', 'override_value',
            'disagg_method', 'override_note',
        ]

    def validate(self, data):
        has_qty   = data.get('override_qty')   is not None
        has_pct   = data.get('override_pct')   is not None
        has_value = data.get('override_value') is not None
        set_count = sum([has_qty, has_pct, has_value])

        if set_count == 0:
            raise serializers.ValidationError(
                'Provide exactly one of: override_qty, override_pct, or override_value.'
            )
        if set_count > 1:
            raise serializers.ValidationError(
                'Only one of override_qty, override_pct, or override_value may be set.'
            )
        if has_value and data.get('override_level') == 'sku':
            raise serializers.ValidationError(
                'override_value cannot be used at SKU level. '
                'Use override_qty for an absolute quantity or override_pct for a % adjustment.'
            )
        return data


class OverrideSplitWeightBulkSerializer(serializers.Serializer):
    """
    Bulk payload for PUT /overrides/{id}/split-weights/.
    Accepts a list of {child_key, weight} pairs.
    Validates that weights sum to 1.0 (within floating-point tolerance).
    """
    weights = OverrideSplitWeightSerializer(many=True)

    def validate_weights(self, value):
        if not value:
            raise serializers.ValidationError(
                'Provide at least one split weight.'
            )
        total = sum(float(w['weight']) for w in value)
        if abs(total - 1.0) > 0.001:
            raise serializers.ValidationError(
                f'Weights must sum to 1.0. Current sum: {total:.4f}.'
            )
        return value


class AffectedLineSerializer(serializers.ModelSerializer):
    """
    Lightweight read-only serializer for the affected-lines view.
    Shows before/after quantities so planners can see the override impact.
    """
    item_id       = serializers.CharField(source='item.item_id',          read_only=True)
    item_name     = serializers.CharField(source='item.name',             read_only=True)
    location_code = serializers.CharField(source='planning_location.code', read_only=True)
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )

    class Meta:
        model  = ForecastLine
        fields = [
            'id',
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_start',
            'statistical_qty',   # original statistical forecast
            'override_qty',      # what the override set it to
            'final_qty',         # = override_qty if set, else statistical_qty
            'price_used',
            'final_value',
        ]
        read_only_fields = fields
```

---

## 4. REST API

Add to `mysite/api/demand/views.py`:
 
```python
# ─────────────────────────────────────────────────────────────────────────────
# Sprint 3B.5 imports — add to existing import block
# ─────────────────────────────────────────────────────────────────────────────

from mysite.models.demand.forecast import ForecastOverride, OverrideSplitWeight
from mysite.api.demand.serializers import (
    ForecastOverrideSerializer,
    ForecastOverrideDetailSerializer,
    ForecastOverrideCreateSerializer,
    OverrideSplitWeightBulkSerializer,
    AffectedLineSerializer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_draft_version(request, pk):
    """
    Shared helper used by all override views.
    Returns the ForecastVersion for the authenticated client.
    Does NOT enforce DRAFT status here — each endpoint does its own check
    so error messages are context-specific.
    """
    return get_object_or_404(ForecastVersion, pk=pk, client=request.client)


# ─────────────────────────────────────────────────────────────────────────────
# 4A. Override list + create
# GET  /api/demand/forecast-versions/{id}/overrides/
# POST /api/demand/forecast-versions/{id}/overrides/
# ─────────────────────────────────────────────────────────────────────────────

class ForecastOverrideListCreateView(DemandFeatureMixin, APIView):
    """
    GET  — list all ForecastOverride rows for a version.
           Returns is_applied status so the frontend can badge pending vs applied.
           Supports filtering by override_level, period_start, is_applied.

    POST — create one ForecastOverride and immediately fire apply_overrides.
           Validates that the version is DRAFT.
           Returns HTTP 202 (Accepted) because the Celery task applies
           the override asynchronously.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        version = _get_draft_version(request, pk)
        qs = (
            ForecastOverride.objects
            .filter(version=version)
            .select_related('created_by')
            .order_by('-created_at')
        )

        # Optional filters
        p = request.query_params
        if p.get('override_level'):
            qs = qs.filter(override_level=p['override_level'])
        if p.get('period_start'):
            try:
                import datetime
                qs = qs.filter(
                    period_start=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response(
                    {'period_start': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('is_applied') in ('true', 'false'):
            qs = qs.filter(is_applied=(p['is_applied'] == 'true'))

        serializer = ForecastOverrideSerializer(qs, many=True)
        return Response({
            'version_id':    version.pk,
            'version_label': version.version_label,
            'version_status': version.status,
            'count':         qs.count(),
            'results':       serializer.data,
        })

    def post(self, request, pk):
        version = _get_draft_version(request, pk)

        # Enforce DRAFT-only
        if not version.is_editable:
            return Response(
                {
                    'detail': (
                        f'Version "{version.version_label}" is {version.status}. '
                        'Overrides can only be added to DRAFT versions.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ForecastOverrideCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Save — period_end is computed in ForecastOverride.save()
        override = serializer.save(
            version    = version,
            created_by = request.user,
        )

        # Fire async task to disaggregate this (and any other pending) overrides
        from mysite.tasks.demand.run_forecast import apply_overrides
        apply_overrides.delay(version.pk)

        return Response(
            ForecastOverrideDetailSerializer(override).data,
            status=status.HTTP_202_ACCEPTED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4B. Override detail + delete
# GET    /api/demand/forecast-versions/{id}/overrides/{override_id}/
# DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/
# ─────────────────────────────────────────────────────────────────────────────

class ForecastOverrideDetailView(DemandFeatureMixin, APIView):
    """
    GET    — return one override with its split_weights (if CUSTOM).
    DELETE — remove the override. Rules:
               • Version must be DRAFT.
               • If is_applied=False: delete row only (was never written to lines).
               • If is_applied=True:  revert ForecastLine.override_qty for the
                                      affected lines, then delete the row, then
                                      refresh ForecastAggregate rollups.
    """
    permission_classes = [IsAuthenticated]

    def _get_override(self, request, pk, override_id):
        version  = _get_draft_version(request, pk)
        override = get_object_or_404(ForecastOverride, pk=override_id, version=version)
        return version, override

    def get(self, request, pk, override_id):
        _, override = self._get_override(request, pk, override_id)
        return Response(ForecastOverrideDetailSerializer(override).data)

    def delete(self, request, pk, override_id):
        version, override = self._get_override(request, pk, override_id)

        # Gate: version must be DRAFT
        if not version.is_editable:
            return Response(
                {
                    'detail': (
                        f'Version "{version.version_label}" is {version.status}. '
                        'Overrides on non-DRAFT versions cannot be deleted.'
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # Revert ForecastLine rows if the override was already applied
        if override.is_applied:
            _revert_override_lines(override, version)

        override.delete()

        # Refresh aggregate rollups so the UI reflects the reverted state
        if override.is_applied:
            from utils.demand.forecast_engine import write_forecast_aggregates
            write_forecast_aggregates(version.pk)

        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# 4C. Affected-lines view (propagation UI)
# GET /api/demand/forecast-versions/{id}/overrides/{override_id}/affected-lines/
# ─────────────────────────────────────────────────────────────────────────────

class ForecastOverrideAffectedLinesView(DemandFeatureMixin, APIView):
    """
    Returns the ForecastLine rows that were (or will be) modified by one override.

    For applied overrides: returns lines where override_qty IS NOT NULL and
    the line matches the override's level + key + period_start.

    For pending overrides: returns lines that WOULD be matched — same filter
    but without the override_qty IS NOT NULL condition — so the planner can
    preview impact before apply_overrides runs.

    Query params:
        page / page_size  — default 50, max 200
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, override_id):
        version  = _get_draft_version(request, pk)
        override = get_object_or_404(ForecastOverride, pk=override_id, version=version)

        qs = _build_affected_lines_qs(override, version)

        try:
            page_size = min(int(request.query_params.get('page_size', 50)), 200)
            page_num  = int(request.query_params.get('page', 1))
        except ValueError:
            page_size, page_num = 50, 1

        from django.core.paginator import Paginator, EmptyPage
        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        return Response({
            'override_id':    override.pk,
            'override_level': override.override_level,
            'override_key':   override.override_key,
            'is_applied':     override.is_applied,
            'count':          paginator.count,
            'results':        AffectedLineSerializer(page.object_list, many=True).data,
        })


# ─────────────────────────────────────────────────────────────────────────────
# 4D. Split-weight management
# GET /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/
# PUT /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/
# ─────────────────────────────────────────────────────────────────────────────

class ForecastOverrideSplitWeightView(DemandFeatureMixin, APIView):
    """
    GET — list current OverrideSplitWeight rows for a CUSTOM override.
    PUT — replace all split weights atomically.
          Validates that the override's disagg_method is CUSTOM.
          Validates that weights sum to 1.0.
          Marks override as is_applied=False so apply_overrides re-runs.
          Fires apply_overrides.delay(version_id).
    """
    permission_classes = [IsAuthenticated]

    def _get_custom_override(self, request, pk, override_id):
        version  = _get_draft_version(request, pk)
        override = get_object_or_404(ForecastOverride, pk=override_id, version=version)
        if override.disagg_method != ForecastOverride.DisaggMethod.CUSTOM:
            return version, override, Response(
                {
                    'detail': (
                        f'Override {override_id} uses disagg_method='
                        f'{override.disagg_method}. '
                        'Split weights are only valid for CUSTOM overrides.'
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return version, override, None

    def get(self, request, pk, override_id):
        version, override, err = self._get_custom_override(request, pk, override_id)
        if err:
            return err
        from mysite.api.demand.serializers import OverrideSplitWeightSerializer
        weights = override.split_weights.order_by('id')
        return Response(OverrideSplitWeightSerializer(weights, many=True).data)

    def put(self, request, pk, override_id):
        version, override, err = self._get_custom_override(request, pk, override_id)
        if err:
            return err

        if not version.is_editable:
            return Response(
                {'detail': 'Split weights can only be edited on DRAFT versions.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = OverrideSplitWeightBulkSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated_weights = serializer.validated_data['weights']

        # Atomically replace all weights for this override
        with transaction.atomic():
            override.split_weights.all().delete()
            OverrideSplitWeight.objects.bulk_create([
                OverrideSplitWeight(
                    override  = override,
                    child_key = w['child_key'],
                    weight    = w['weight'],
                )
                for w in validated_weights
            ])
            # Reset is_applied so the task re-disaggregates with new weights
            override.is_applied = False
            override.save(update_fields=['is_applied'])

        # Re-fire disaggregation
        from mysite.tasks.demand.run_forecast import apply_overrides
        apply_overrides.delay(version.pk)

        from mysite.api.demand.serializers import OverrideSplitWeightSerializer
        weights = override.split_weights.order_by('id')
        return Response(
            {
                'detail':   'Split weights updated. Disaggregation queued.',
                'override': ForecastOverrideDetailSerializer(override).data,
                'weights':  OverrideSplitWeightSerializer(weights, many=True).data,
            },
            status=status.HTTP_202_ACCEPTED,
        )
# mysite/api/demand/views.py

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

```

Add these imports at the top of `views.py` alongside the existing ones:

```python
from django.db import transaction
```

---

### Private helpers (add to `views.py` outside any class)

```python

# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers — place ABOVE ForecastOverrideDetailView and
# ForecastOverrideAffectedLinesView in the file so both views can call them.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 3B.5 helper functions (module-level, not part of any view class)
# ─────────────────────────────────────────────────────────────────────────────

def _build_affected_lines_qs(override, version):
    """
    Build the ForecastLine queryset that matches an override's level + key.

    This mirrors the filtering logic in _apply_single_override() (Sprint 3B.4)
    so the affected-lines view shows exactly what apply_overrides touched.
    Called by both the affected-lines view and the delete revert path.
    """
    qs = (
        ForecastLine.objects
        .filter(
            version      = version,
            period_type  = override.period_type,
            period_start = override.period_start,
        )
        .select_related('item', 'planning_location', 'planning_customer')
        .order_by('planning_location__code', 'item__item_id')
    )

    key   = override.override_key
    level = override.override_level

    if level == 'sku':
        item_id_str = key.get('item_id')
        if item_id_str:
            qs = qs.filter(item__item_id=item_id_str)

    elif level == 'location':
        loc_code = key.get('location_code')
        if loc_code:
            qs = qs.filter(planning_location__code=loc_code)

    elif level == 'customer':
        cust_code = key.get('customer_code')
        if cust_code:
            qs = qs.filter(planning_customer__code=cust_code)

    elif level in ('subcategory', 'category'):
        # Category-level key: {"category": "Braking Systems"} or {"taxon_id": "42"}
        # Filter by items belonging to the taxonomy node
        taxon_id = key.get('taxon_id')
        category_name = key.get('category')
        if taxon_id:
            from mysite.models import ItemTaxonomyMapping
            item_pks = list(
                ItemTaxonomyMapping.objects
                .filter(node_id=taxon_id)
                .values_list('item_id', flat=True)
                .distinct()
            )
            qs = qs.filter(item_id__in=item_pks)
        elif category_name:
            qs = qs.filter(item__category=category_name)

    elif level == 'region':
        region_code = key.get('region_code')
        if region_code:
            qs = qs.filter(planning_location__parent__code=region_code)

    elif level == 'channel':
        channel_code = key.get('channel_code')
        if channel_code:
            qs = qs.filter(planning_customer__channel=channel_code)

    # 'total' level: no extra filtering — all lines for this period

    return qs


def _revert_override_lines(override, version):
    """
    Set override_qty = NULL on lines that were modified by this override.
    Called by ForecastOverrideDetailView.delete() when is_applied=True.

    ForecastLine.save() recomputes final_qty, override_value, final_value
    whenever override_qty changes, so we call save() not update() here.
    """
    qs = _build_affected_lines_qs(override, version).filter(
        override_qty__isnull=False
    )
    for line in qs:
        line.override_qty = None
        line.save(update_fields=['override_qty', 'final_qty', 'override_value', 'final_value'])
```

---

## 5. Celery

No new Celery tasks in Sprint 3B.5. The `apply_overrides` task from Sprint 3B.4 is already
correct. The only wiring needed is calling `.delay()` from the POST and PUT views above.

Confirm `apply_overrides` is importable from:
```python
from mysite.tasks.demand.run_forecast import apply_overrides
```

If your task file is at a different path, adjust the import in views accordingly.

---

## 6. URL Additions

Append to `mysite/api/demand/urls.py`:

```python
# ── Sprint 3B.5 — Override CRUD and split-weight management ──────────────────

from mysite.api.demand import views   # already imported
from mysite.api.demand.views import forecast_grid
urlpatterns += [
    # Override list + create
    path(
        'forecast-versions/<int:pk>/overrides/',
        views.ForecastOverrideListCreateView.as_view(),
        name='demand-forecast-overrides',
    ),
    # Override detail + delete
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/',
        views.ForecastOverrideDetailView.as_view(),
        name='demand-forecast-override-detail',
    ),
    # Propagation view — which lines did this override touch?
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/affected-lines/',
        views.ForecastOverrideAffectedLinesView.as_view(),
        name='demand-forecast-override-affected-lines',
    ),
    # Custom split-weight management
    path(
        'forecast-versions/<int:pk>/overrides/<int:override_id>/split-weights/',
        views.ForecastOverrideSplitWeightView.as_view(),
        name='demand-forecast-override-split-weights',
    ),
    path(
        'demand/forecast-versions/<int:pk>/grid/',
        forecast_grid,
        name='demand-forecast-grid',
    ),       
]
```

---

## 7. HTMX Override Form

The HTMX form lives inside the forecast grid template. It allows planners to click on a
forecast value, enter an override inline, and have the row update without a full page reload.

### 7a. Template structure

```
mysite/
  templates/
    demand/
      forecast_grid.html                ← main grid page (already exists or will exist)
      partials/
        override_form.html              ← HTMX partial: the inline edit form
        override_badge.html             ← HTMX partial: the applied/pending badge
        override_list_row.html          ← HTMX partial: one row in the override list table
        override_propagation.html       ← HTMX partial: affected-lines table
        split_weight_form.html          ← HTMX partial: CUSTOM weight editor
```

### 7b. `override_form.html` — inline override entry

This partial is loaded into a `<td>` or modal when the planner clicks a forecast cell.

```html
{# demand/partials/override_form.html #}
{# Context vars: version, line (ForecastLine), period_label #}

<form
  hx-post="/api/demand/forecast-versions/{{ version.pk }}/overrides/"
  hx-target="#override-list-{{ version.pk }}"
  hx-swap="outerHTML"
  hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
  class="override-form"
  id="override-form-{{ line.pk }}"
>
  {# Hidden fields: period and target identification #}
  <input type="hidden" name="period_type"  value="{{ version.period_type }}">
  <input type="hidden" name="period_start" value="{{ line.period_start|date:'Y-m-d' }}">

  {# Override level and key — determine what gets overridden #}
  <div class="override-form__level">
    <label for="override_level">Level</label>
    <select name="override_level" id="override_level" required
            hx-trigger="change"
            hx-get="/demand/partials/override-key-field/"
            hx-target="#override-key-container"
            hx-include="[name='override_level']">
      <option value="sku"         {% if default_level == 'sku' %}selected{% endif %}>SKU</option>
      <option value="location">Location</option>
      <option value="region">Region</option>
      <option value="category">Category</option>
      <option value="customer">Customer</option>
      <option value="total">Grand Total</option>
    </select>
  </div>

  {# override_key is rendered dynamically based on level selection #}
  <div id="override-key-container">
    {# Default: SKU — pre-populate from the clicked line #}
    <input type="hidden" name="override_key"
           value='{"item_id": "{{ line.item.item_id }}"}'>
  </div>

  {# Override value — exactly one must be filled in #}
  <fieldset class="override-form__value">
    <legend>Override value</legend>

    <div class="override-form__mode" id="override-mode-tabs">
      <label class="tab {% if True %}active{% endif %}">
        <input type="radio" name="_mode" value="qty" checked
               hx-trigger="change" hx-target="#override-value-inputs"
               hx-get="/demand/partials/override-value-inputs/?mode=qty">
        Absolute Qty
      </label>
      <label class="tab">
        <input type="radio" name="_mode" value="pct"
               hx-trigger="change" hx-target="#override-value-inputs"
               hx-get="/demand/partials/override-value-inputs/?mode=pct">
        % Adjustment
      </label>
      <label class="tab {% if default_level == 'sku' %}disabled{% endif %}">
        <input type="radio" name="_mode" value="value"
               {% if default_level == 'sku' %}disabled{% endif %}
               hx-trigger="change" hx-target="#override-value-inputs"
               hx-get="/demand/partials/override-value-inputs/?mode=value">
        ₹ Target
      </label>
    </div>

    <div id="override-value-inputs">
      {# Default: qty input #}
      <label>
        Quantity
        <input type="number" name="override_qty" min="0" step="0.001"
               value="{{ line.final_qty }}" required>
      </label>
      <small class="hint">
        Statistical: {{ line.statistical_qty }} | Current: {{ line.final_qty }}
      </small>
    </div>
  </fieldset>

  {# Disaggregation method (shown for non-SKU levels) #}
  <div class="override-form__disagg"
       {% if default_level == 'sku' %}style="display:none"{% endif %}>
    <label for="disagg_method">Split method</label>
    <select name="disagg_method" id="disagg_method">
      <option value="PROPORTIONAL" selected>Proportional (historical share)</option>
      <option value="EQUAL">Equal split</option>
      <option value="CUSTOM"
              hx-trigger="change"
              hx-get="/demand/partials/split-weight-form/?version={{ version.pk }}&override_level={{ default_level|default:'sku' }}&period_start={{ line.period_start|date:'Y-m-d' }}"
              hx-target="#split-weight-container">
        Custom weights
      </option>
    </select>
    <div id="split-weight-container"></div>
  </div>

  {# Note #}
  <div class="override-form__note">
    <label for="override_note">Note (optional)</label>
    <textarea name="override_note" id="override_note" rows="2"
              placeholder="Reason for override…"></textarea>
  </div>

  <div class="override-form__actions">
    <button type="submit" class="btn btn-primary">Apply Override</button>
    <button type="button" class="btn btn-secondary"
            onclick="document.getElementById('override-form-{{ line.pk }}').remove()">
      Cancel
    </button>
  </div>
</form>
```

### 7c. `override_badge.html` — applied/pending badge

Returned by `hx-swap` after a successful POST, replacing the cell value.

```html
{# demand/partials/override_badge.html #}
{# Context: line (ForecastLine), override (ForecastOverride) #}

<td class="forecast-cell forecast-cell--overridden"
    data-line-id="{{ line.pk }}"
    data-override-id="{{ override.pk }}">

  {# Main value #}
  <span class="forecast-value">
    {% if override.is_applied %}
      {{ line.final_qty|floatformat:0 }}
    {% else %}
      {{ line.statistical_qty|floatformat:0 }}
      <span class="badge badge--pending" title="Override pending disaggregation">⏳</span>
    {% endif %}
  </span>

  {# Override chip — shows the override type and value #}
  <span class="override-chip">
    {% if override.override_qty is not None %}
      <span class="override-chip__label">Qty</span>
      <span class="override-chip__value">{{ override.override_qty|floatformat:0 }}</span>
    {% elif override.override_pct is not None %}
      <span class="override-chip__label">
        {% if override.override_pct >= 0 %}+{% endif %}{{ override.override_pct }}%
      </span>
    {% elif override.override_value is not None %}
      <span class="override-chip__label">₹{{ override.override_value|floatformat:0 }}</span>
    {% endif %}

    {# Links: propagation view and delete #}
    <a class="override-chip__link"
       hx-get="/demand/partials/override-propagation/{{ override.pk }}/"
       hx-target="#propagation-panel"
       hx-swap="innerHTML"
       title="View affected lines">🔍</a>

    <button class="override-chip__delete"
            hx-delete="/api/demand/forecast-versions/{{ version.pk }}/overrides/{{ override.pk }}/"
            hx-confirm="Revert this override? The line will return to its statistical forecast."
            hx-target="#override-list-{{ version.pk }}"
            hx-swap="outerHTML"
            hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
      ✕
    </button>
  </span>
</td>
```


### 7d. Supporting HTMX view — `override-key-field` partial

Add to the Django view layer (a simple template view, not an API view):

```python

# In mysite/views/demand/forecast_htmx.py
from django.shortcuts import render
from django.contrib.auth.decorators import login_required


@login_required
def override_key_field(request):
    """
    HTMX partial: renders the appropriate override_key input widget
    based on the selected override_level.
    Called when the level <select> changes in the override form.
    """
    level = request.GET.get('override_level', 'sku')
    return render(request, f'demand/partials/override_key_{level}.html', {
        'level': level,
    })


@login_required
def override_value_inputs(request):
    """
    HTMX partial: renders the active override value input (qty / pct / value)
    based on the selected mode tab.
    """
    mode = request.GET.get('mode', 'qty')
    return render(request, f'demand/partials/override_value_{mode}.html', {
        'mode': mode,
    })
```

Create the per-level key templates:

```html
{# demand/partials/override_key_sku.html #}
<label>Item ID
  <input type="text" name="override_key_item_id" required
         placeholder="e.g. ITEM-001"
         hx-trigger="blur"
         hx-post="/demand/partials/encode-override-key/"
         hx-target="#override-key-hidden"
         hx-include="[name^='override_key_']">
</label>
<input type="hidden" id="override-key-hidden" name="override_key" value="{}">
```

```html
{# demand/partials/override_key_location.html #}
<label>Location code
  <input type="text" name="override_key_location_code" required
         placeholder="e.g. MUM-01">
</label>
<input type="hidden" id="override-key-hidden" name="override_key" value="{}">
```

```html
{# demand/partials/override_key_total.html #}
{# Grand total has no key — empty JSON object is correct #}
<input type="hidden" name="override_key" value='{"level": "total"}'>
<p class="hint">This override applies to all lines in the period.</p>
```

Add a small Django view to encode the key as JSON for the hidden input:

```python
@login_required
def encode_override_key(request):
    """
    Receives form fields named override_key_{field} and returns a hidden input
    containing the JSON-encoded override_key.  Called via HTMX on blur.
    """
    import json
    from django.http import HttpResponse

    key = {}
    for k, v in request.POST.items():
        if k.startswith('override_key_') and v:
            field = k[len('override_key_'):]
            key[field] = v

    encoded = json.dumps(key)
    return HttpResponse(
        f'<input type="hidden" id="override-key-hidden" '
        f'name="override_key" value=\'{encoded}\'>',
        content_type='text/html',
    )
```

---

### 7e. `override_list_row.html` — one row in the override list table

This partial renders a single <tr> inside the override history table on the forecast grid page. It is used in two ways:

On initial page load, the table is built by looping over overrides in the Django view context.
After a POST creates a new override, HTMX prepends a fresh row via hx-swap="afterbegin" on the <tbody>.

```html
{# demand/partials/override_list_row.html #}
{# Context: override (ForecastOverride), version (ForecastVersion) #}

<tr class="override-list-row
           {% if override.is_applied %}override-list-row--applied
           {% else %}override-list-row--pending{% endif %}"
    id="override-row-{{ override.pk }}"
    data-override-id="{{ override.pk }}">

  {# ── Level + Key ──────────────────────────────────────────────────────── #}
  <td class="override-list-row__level">
    <span class="level-badge level-badge--{{ override.override_level }}">
      {{ override.get_override_level_display }}
    </span>
  </td>
  <td class="override-list-row__key">
    {% with key=override.override_key %}
      {% if override.override_level == 'sku' %}
        {{ key.item_id|default:"—" }}
      {% elif override.override_level == 'location' %}
        {{ key.location_code|default:"—" }}
      {% elif override.override_level == 'customer' %}
        {{ key.customer_code|default:"—" }}
      {% elif override.override_level == 'category' %}
        {{ key.category|default:key.taxon_id|default:"—" }}
      {% elif override.override_level == 'region' %}
        {{ key.region_code|default:"—" }}
      {% elif override.override_level == 'channel' %}
        {{ key.channel_code|default:"—" }}
      {% else %}
        Grand Total
      {% endif %}
    {% endwith %}
  </td>

  {# ── Period ───────────────────────────────────────────────────────────── #}
  <td class="override-list-row__period">
    {{ override.period_start|date:"M Y" }}
  </td>

  {# ── Override value — show whichever of the three is set ─────────────── #}
  <td class="override-list-row__value">
    {% if override.override_qty is not None %}
      <span class="override-type-tag override-type-tag--qty">Qty</span>
      <strong>{{ override.override_qty|floatformat:0 }}</strong>
    {% elif override.override_pct is not None %}
      <span class="override-type-tag override-type-tag--pct">%</span>
      <strong>
        {% if override.override_pct >= 0 %}+{% endif %}{{ override.override_pct }}%
      </strong>
    {% elif override.override_value is not None %}
      <span class="override-type-tag override-type-tag--value">₹</span>
      <strong>₹{{ override.override_value|floatformat:0 }}</strong>
    {% else %}
      —
    {% endif %}
  </td>

  {# ── Disagg method ────────────────────────────────────────────────────── #}
  <td class="override-list-row__disagg">
    {{ override.get_disagg_method_display }}
    {% if override.disagg_method == 'CUSTOM' %}
      <a class="link-sm"
         hx-get="/api/demand/forecast-versions/{{ version.pk }}/overrides/{{ override.pk }}/split-weights/"
         hx-target="#split-weight-editor-container"
         hx-swap="innerHTML"
         title="Edit custom weights">
        ✏️
      </a>
    {% endif %}
  </td>

  {# ── Status badge ─────────────────────────────────────────────────────── #}
  <td class="override-list-row__status">
    {% if override.is_applied %}
      <span class="badge badge--applied" title="Override disaggregated to line level">
        ✓ Applied
      </span>
    {% else %}
      <span class="badge badge--pending" title="Waiting for apply_overrides task">
        ⏳ Pending
      </span>
    {% endif %}
  </td>

  {# ── Created by / when ────────────────────────────────────────────────── #}
  <td class="override-list-row__meta">
    <span class="meta-user">
      {{ override.created_by.get_full_name|default:override.created_by.username }}
    </span>
    <span class="meta-time">{{ override.created_at|date:"d M H:i" }}</span>
  </td>

  {# ── Note (collapsed, shown on hover / expand) ─────────────────────────── #}
  <td class="override-list-row__note">
    {% if override.override_note %}
      <span class="note-preview" title="{{ override.override_note }}">
        {{ override.override_note|truncatechars:40 }}
      </span>
    {% else %}
      <span class="note-empty">—</span>
    {% endif %}
  </td>

  {# ── Actions ──────────────────────────────────────────────────────────── #}
  <td class="override-list-row__actions">

    {# Propagation view — which lines were touched? #}
    <button class="btn-icon"
            title="View affected lines"
            hx-get="/demand/partials/override-propagation/{{ override.pk }}/"
            hx-target="#propagation-panel"
            hx-swap="innerHTML">
      🔍
    </button>

    {# Delete — with confirmation; only shown on DRAFT versions #}
    {% if version.is_editable %}
    <button class="btn-icon btn-icon--danger"
            title="{% if override.is_applied %}Revert and delete{% else %}Delete{% endif %}"
            hx-delete="/api/demand/forecast-versions/{{ version.pk }}/overrides/{{ override.pk }}/"
            hx-confirm="{% if override.is_applied %}This override has been applied to forecast lines. Deleting it will revert those lines to their statistical forecast. Continue?{% else %}Delete this pending override?{% endif %}"
            hx-target="#override-row-{{ override.pk }}"
            hx-swap="outerHTML swap:300ms"
            hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
      🗑
    </button>
    {% endif %}

  </td>
</tr>
```

### 7f. `forecast_grid.html` —  main grid page scaffold

This was referenced throughout the sprint but never fully written. It is the host page for all the partials.

```html
{# demand/forecast_grid.html #}
{# Context: version (ForecastVersion), lines (Page), periods (list[date]),
            overrides (QuerySet[ForecastOverride]),
            period_labels (list[str]) #}

{% extends "base.html" %}
{% load humanize %}

{% block title %}Forecast Grid — {{ version.version_label }}{% endblock %}

{% block content %}
<div class="forecast-grid-page" data-version-id="{{ version.pk }}">

  {# ════════════════════════════════════════════════════════════════════════ #}
  {# Header: version meta + approval panel                                   #}
  {# ════════════════════════════════════════════════════════════════════════ #}
  <div class="forecast-grid-page__header">
    <div class="version-meta">
      <h1 class="version-meta__title">{{ version.version_label }}</h1>
      <dl class="version-meta__details">
        <dt>Period</dt>
        <dd>{{ version.period_type|capfirst }} · {{ version.horizon_periods }} periods</dd>
        <dt>Base end</dt>
        <dd>{{ version.base_period_end|date:"d M Y" }}</dd>
        <dt>Lines</dt>
        <dd>{{ version.lines.count|intcomma }}</dd>
      </dl>
    </div>

    {# Approval panel — HTMX-refreshed after every status transition #}
    <div id="approval-panel-{{ version.pk }}">
      {% include "demand/partials/approval_panel.html" with version=version %}
    </div>
  </div>

  {# ════════════════════════════════════════════════════════════════════════ #}
  {# Two-column layout: grid (left) + side panels (right)                    #}
  {# ════════════════════════════════════════════════════════════════════════ #}
  <div class="forecast-grid-page__body">

    {# ── LEFT: forecast grid table ──────────────────────────────────────── #}
    <div class="forecast-grid-page__grid">

      {# Filter bar #}
      <div class="grid-filter-bar">
        <input type="text" id="grid-search" placeholder="Filter by item or location…"
               hx-get="/demand/partials/forecast-grid-rows/?version={{ version.pk }}"
               hx-trigger="keyup changed delay:400ms"
               hx-target="#forecast-grid-tbody"
               hx-swap="innerHTML"
               hx-include="#grid-filter-bar"
               name="q"
               class="grid-filter-bar__search">

        <select name="location_code"
                hx-get="/demand/partials/forecast-grid-rows/?version={{ version.pk }}"
                hx-trigger="change"
                hx-target="#forecast-grid-tbody"
                hx-swap="innerHTML"
                hx-include="#grid-filter-bar"
                class="grid-filter-bar__select">
          <option value="">All locations</option>
          {% for loc in locations %}
            <option value="{{ loc.code }}">{{ loc.code }} — {{ loc.name }}</option>
          {% endfor %}
        </select>

        <a href="/api/demand/forecast-versions/{{ version.pk }}/export/"
           class="btn btn-secondary btn-sm"
           download>
          📥 Export .xlsx
        </a>
      </div>
      <div id="grid-filter-bar" style="display:none">
        {# Hidden container used by hx-include to pick up filter values #}
      </div>

      {# Forecast grid table — scrollable horizontally #}
      <div class="grid-scroll-wrapper">
        <table class="forecast-grid-table" id="forecast-grid-table">

          <thead class="forecast-grid-table__head">
            <tr>
              <th class="col-location">Location</th>
              <th class="col-item-id">Item ID</th>
              <th class="col-item-name">Item</th>
              <th class="col-customer">Customer</th>
              {# One <th> per forecast period #}
              {% for label in period_labels %}
                <th class="col-period">{{ label }}</th>
              {% endfor %}
            </tr>
          </thead>

          <tbody id="forecast-grid-tbody">
            {#
              Each <tr> groups all periods for one (location, item, customer).
              Each period <td> is either:
                • a plain qty cell  →  click to open override_form.html inline
                • an overridden cell → shows override_badge.html
            #}
            {% for row in grid_rows %}
            <tr class="forecast-row" id="forecast-row-{{ row.key }}">

              <td class="col-location">{{ row.location_code }}</td>
              <td class="col-item-id">{{ row.item_id }}</td>
              <td class="col-item-name">{{ row.item_name }}</td>
              <td class="col-customer">{{ row.customer_code|default:"—" }}</td>

              {% for cell in row.cells %}
              <td class="forecast-cell
                         {% if cell.line.override_qty is not None %}forecast-cell--overridden{% endif %}"
                  id="cell-{{ cell.line.pk }}"
                  data-line-id="{{ cell.line.pk }}"
                  data-period="{{ cell.period_label }}">

                {% if cell.line.override_qty is not None %}
                  {# Cell has an applied or pending override → show badge #}
                  {% include "demand/partials/override_badge.html"
                     with line=cell.line override=cell.override version=version %}
                {% else %}
                  {# Plain statistical cell → click opens the inline form #}
                  <span class="forecast-cell__value"
                        hx-get="/demand/partials/override-form/?line={{ cell.line.pk }}&version={{ version.pk }}"
                        hx-target="#cell-{{ cell.line.pk }}"
                        hx-swap="innerHTML"
                        title="Click to add override">
                    {{ cell.line.final_qty|floatformat:0 }}
                  </span>
                {% endif %}

              </td>
              {% endfor %}

            </tr>
            {% empty %}
              <tr>
                <td colspan="{{ periods|length|add:4 }}" class="grid-empty">
                  No forecast lines found.
                </td>
              </tr>
            {% endfor %}
          </tbody>

        </table>
      </div>{# /grid-scroll-wrapper #}

      {# Pagination #}
      <div class="grid-pagination">
        {% if lines.has_previous %}
          <a href="?page={{ lines.previous_page_number }}"
             class="btn btn-sm btn-secondary">← Previous</a>
        {% endif %}
        <span>Page {{ lines.number }} of {{ lines.paginator.num_pages }}</span>
        {% if lines.has_next %}
          <a href="?page={{ lines.next_page_number }}"
             class="btn btn-sm btn-secondary">Next →</a>
        {% endif %}
      </div>

    </div>{# /forecast-grid-page__grid #}

    {# ── RIGHT: side panels ─────────────────────────────────────────────── #}
    <div class="forecast-grid-page__sidebar">

      {# Override history table #}
      <section class="sidebar-section" id="override-history-section">
        <h2 class="sidebar-section__title">
          Overrides
          <span class="badge">{{ overrides.count }}</span>
        </h2>

        <div class="override-list-wrapper">
          <table class="override-list-table">
            <thead>
              <tr>
                <th>Level</th>
                <th>Key</th>
                <th>Period</th>
                <th>Value</th>
                <th>Split</th>
                <th>Status</th>
                <th>By</th>
                <th>Note</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="override-list-{{ version.pk }}">
              {% for override in overrides %}
                {% include "demand/partials/override_list_row.html"
                   with override=override version=version %}
              {% empty %}
                <tr>
                  <td colspan="9" class="override-list--empty">
                    No overrides yet. Click a forecast cell to add one.
                  </td>
                </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>

        {# CUSTOM weight editor — loaded here when ✏️ is clicked #}
        <div id="split-weight-editor-container"></div>
      </section>

      {# Propagation panel — loaded when 🔍 is clicked on any override row #}
      <section class="sidebar-section" id="propagation-panel">
        <p class="propagation-panel--placeholder">
          Click 🔍 on an override to see which lines were affected.
        </p>
      </section>

    </div>{# /forecast-grid-page__sidebar #}

  </div>{# /forecast-grid-page__body #}

</div>{# /forecast-grid-page #}

{# ── Global: approval modal container (for reject / copy modals) ─────────── #}
<div id="approval-modal-container"></div>
{% endblock %}
```

## 8. Override Propagation UI

The propagation panel shows which child lines were affected by a non-SKU override.
It is loaded as an HTMX swap into `#propagation-panel` when the planner clicks 🔍.

### 8a. `override_propagation.html`

```html
{# demand/partials/override_propagation.html #}
{# Context: override, page (Page object), count #}

<div class="propagation-panel" id="propagation-panel">

  <div class="propagation-panel__header">
    <h3>Lines affected by override</h3>
    <dl class="override-meta">
      <dt>Level</dt>  <dd>{{ override.get_override_level_display }}</dd>
      <dt>Key</dt>    <dd>{{ override.override_key }}</dd>
      <dt>Period</dt> <dd>{{ override.period_start }}</dd>
      <dt>Status</dt>
      <dd>
        {% if override.is_applied %}
          <span class="badge badge--applied">✓ Applied</span>
        {% else %}
          <span class="badge badge--pending">⏳ Pending</span>
        {% endif %}
      </dd>
    </dl>
  </div>

  <table class="propagation-table">
    <thead>
      <tr>
        <th>Item</th>
        <th>Location</th>
        <th>Customer</th>
        <th>Statistical Qty</th>
        <th>Override Qty</th>
        <th>Final Qty</th>
        <th>₹ Value</th>
      </tr>
    </thead>
    <tbody>
      {% for line in page.object_list %}
      <tr class="{% if line.override_qty %}propagation-table__row--overridden{% endif %}">
        <td>{{ line.item.item_id }} — {{ line.item.name }}</td>
        <td>{{ line.planning_location.code }}</td>
        <td>{{ line.planning_customer.code|default:"—" }}</td>
        <td class="num">{{ line.statistical_qty|floatformat:0 }}</td>
        <td class="num {% if line.override_qty %}overridden{% endif %}">
          {{ line.override_qty|floatformat:0|default:"—" }}
        </td>
        <td class="num">{{ line.final_qty|floatformat:0 }}</td>
        <td class="num">
          {% if line.final_value %}₹{{ line.final_value|floatformat:0 }}{% else %}—{% endif %}
        </td>
      </tr>
      {% empty %}
        <tr><td colspan="7" class="empty">No lines matched this override.</td></tr>
      {% endfor %}
    </tbody>
  </table>

  {# Pagination #}
  {% if page.has_previous or page.has_next %}
  <div class="propagation-panel__pagination">
    {% if page.has_previous %}
    <button hx-get="/demand/partials/override-propagation/{{ override.pk }}/?page={{ page.previous_page_number }}"
            hx-target="#propagation-panel" hx-swap="outerHTML">
      ← Previous
    </button>
    {% endif %}
    <span>Page {{ page.number }} of {{ page.paginator.num_pages }} — {{ count }} total lines</span>
    {% if page.has_next %}
    <button hx-get="/demand/partials/override-propagation/{{ override.pk }}/?page={{ page.next_page_number }}"
            hx-target="#propagation-panel" hx-swap="outerHTML">
      Next →
    </button>
    {% endif %}
  </div>
  {% endif %}

  <button class="btn btn-link" onclick="document.getElementById('propagation-panel').innerHTML = ''">
    Close
  </button>
</div>
```

### 8b. HTMX view to serve the propagation partial

```python

# In mysite/views/demand/forecast_htmx.py
from django.core.paginator import Paginator, EmptyPage
from mysite.models.demand.forecast import ForecastOverride, ForecastVersion
from mysite.api.demand.views import _build_affected_lines_qs   # reuse the helper


@login_required
def override_propagation(request, override_id):
    """
    HTMX partial: renders the propagation panel for one override.
    Loaded when the planner clicks 🔍 on an override badge.
    """
    override = get_object_or_404(
        ForecastOverride,
        pk=override_id,
        version__client=request.client,
    )
    version = override.version

    qs      = _build_affected_lines_qs(override, version)
    page_size = 50
    page_num  = int(request.GET.get('page', 1))
    paginator = Paginator(qs, page_size)
    try:
        page = paginator.page(page_num)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    return render(request, 'demand/partials/override_propagation.html', {
        'override': override,
        'version':  version,
        'page':     page,
        'count':    paginator.count,
    })
```

Add to the non-API URL conf (e.g. `mysite/urls.py` or `mysite/demand_urls.py`):

```python
from mysite.views.demand.forecast_htmx import (
    override_key_field,
    override_value_inputs,
    encode_override_key,
    override_propagation,
)

urlpatterns += [
    path(
        'demand/partials/override-key-field/',
        override_key_field,
        name='demand-override-key-field',
    ),
    path(
        'demand/partials/override-value-inputs/',
        override_value_inputs,
        name='demand-override-value-inputs',
    ),
    path(
        'demand/partials/encode-override-key/',
        encode_override_key,
        name='demand-encode-override-key',
    ),
    path(
        'demand/partials/override-propagation/<int:override_id>/',
        override_propagation,
        name='demand-override-propagation',
    ),
]
```

---

## 9. OverrideSplitWeight Management UI

The CUSTOM weight editor is loaded into `#split-weight-container` inside the override form
when the planner selects "Custom weights" in the disagg_method select.

### 9a. `split_weight_form.html` — initial load (before override is saved)

```html
{# demand/partials/split_weight_form.html #}
{# Context: version, override_level, period_start #}
{# Shown during override creation — weights entered before the override is saved. #}
{# The form JS collects these into a JSON array and includes them in the POST body. #}

<div class="split-weight-form" id="split-weight-form">
  <h4>Custom split weights</h4>
  <p class="hint">
    Weights must sum to 1.0. Add one row per child node.
    Example: 0.5 = 50% of the override goes to this child.
  </p>

  <table class="split-weight-table" id="split-weight-table">
    <thead>
      <tr>
        <th>Child key (JSON)</th>
        <th>Weight</th>
        <th></th>
      </tr>
    </thead>
    <tbody id="split-weight-rows">
      {# Rows are added by JS below #}
    </tbody>
  </table>

  <div class="split-weight-form__total">
    Total: <strong id="split-weight-total">0.000</strong>
    <span id="split-weight-warning" style="color:red;display:none">
      ⚠ Must sum to 1.0
    </span>
  </div>

  <button type="button" class="btn btn-secondary btn-sm" id="add-weight-row">
    + Add child
  </button>

  {#
    On form submit, the JS below serialises the split_weights table to a hidden
    field called "split_weights_json" which the view decodes.
    The POST endpoint for create (Section 4A) should accept an optional
    "split_weights_json" field and create OverrideSplitWeight rows atomically
    with the ForecastOverride. See Section 9c for the view update.
  #}
</div>

<script>
(function () {
  const tbody   = document.getElementById('split-weight-rows');
  const totalEl = document.getElementById('split-weight-total');
  const warnEl  = document.getElementById('split-weight-warning');

  function addRow(key = '', weight = '') {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class="sw-key"    type="text"   placeholder='{"item_id": "SKU-001"}' value="${key}" required></td>
      <td><input class="sw-weight" type="number"  step="0.001" min="0" max="1"         value="${weight}" required></td>
      <td><button type="button" class="sw-remove">✕</button></td>
    `;
    tr.querySelector('.sw-remove').addEventListener('click', () => {
      tr.remove(); updateTotal();
    });
    tr.querySelector('.sw-weight').addEventListener('input', updateTotal);
    tbody.appendChild(tr);
    updateTotal();
  }

  function updateTotal() {
    const weights = [...document.querySelectorAll('.sw-weight')]
      .map(el => parseFloat(el.value) || 0);
    const total = weights.reduce((a, b) => a + b, 0);
    totalEl.textContent = total.toFixed(3);
    warnEl.style.display = Math.abs(total - 1.0) > 0.001 ? 'inline' : 'none';
    serialise();
  }

  function serialise() {
    const rows = [...tbody.querySelectorAll('tr')];
    const data = rows.map(tr => ({
      child_key: tr.querySelector('.sw-key').value,
      weight:    parseFloat(tr.querySelector('.sw-weight').value) || 0,
    }));
    const hidden = document.getElementById('split-weights-json-field');
    if (hidden) hidden.value = JSON.stringify(data);
  }

  document.getElementById('add-weight-row').addEventListener('click', () => addRow());

  // Inject a hidden field into the parent form for serialisation
  const form = document.querySelector('.override-form');
  if (form && !document.getElementById('split-weights-json-field')) {
    const hidden = document.createElement('input');
    hidden.type  = 'hidden';
    hidden.name  = 'split_weights_json';
    hidden.id    = 'split-weights-json-field';
    form.appendChild(hidden);
  }

  // Seed one empty row
  addRow();
})();
</script>
```

### 9b. `split_weight_editor.html` — editor for an existing override (PUT endpoint)

Used when the planner opens an already-created override and edits its CUSTOM weights.
Loaded from the override detail page via HTMX GET on the split-weights endpoint.

```html
{# demand/partials/split_weight_editor.html #}
{# Context: override, weights (list of OverrideSplitWeight) #}

<div class="split-weight-editor" id="split-weight-editor">
  <h4>Edit custom weights for override {{ override.pk }}</h4>
  <p class="hint">
    Changing weights will reset is_applied and re-queue disaggregation.
  </p>

  <form
    hx-put="/api/demand/forecast-versions/{{ override.version_id }}/overrides/{{ override.pk }}/split-weights/"
    hx-target="#split-weight-editor"
    hx-swap="outerHTML"
    hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
    hx-encoding="application/json"
    id="split-weight-edit-form"
  >
    <table class="split-weight-table">
      <thead>
        <tr>
          <th>Child key (JSON)</th>
          <th>Weight</th>
          <th></th>
        </tr>
      </thead>
      <tbody id="edit-weight-rows">
        {% for sw in weights %}
        <tr>
          <td><input class="sw-key"    type="text"   value="{{ sw.child_key }}" required></td>
          <td><input class="sw-weight" type="number"  step="0.001" min="0" max="1"
                     value="{{ sw.weight }}" required></td>
          <td><button type="button" class="sw-remove">✕</button></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>

    <div class="split-weight-form__total">
      Total: <strong id="edit-weight-total">—</strong>
      <span id="edit-weight-warning" style="color:red;display:none">⚠ Must sum to 1.0</span>
    </div>

    <button type="button" id="add-edit-row" class="btn btn-secondary btn-sm">+ Add child</button>
    <button type="submit" class="btn btn-primary">Save weights</button>
    <button type="button" class="btn btn-link"
            onclick="document.getElementById('split-weight-editor').innerHTML=''">
      Cancel
    </button>
  </form>
</div>

<script>
(function() {
  /* Same totalUpdate / serialise logic as above — could be extracted to a shared JS file */
  function updateTotal() {
    const ws = [...document.querySelectorAll('#edit-weight-rows .sw-weight')]
      .map(el => parseFloat(el.value)||0);
    const total = ws.reduce((a,b)=>a+b,0);
    document.getElementById('edit-weight-total').textContent = total.toFixed(3);
    document.getElementById('edit-weight-warning').style.display =
      Math.abs(total-1.0)>0.001?'inline':'none';
  }

  document.querySelectorAll('#edit-weight-rows .sw-remove').forEach(btn => {
    btn.addEventListener('click', () => { btn.closest('tr').remove(); updateTotal(); });
  });
  document.querySelectorAll('#edit-weight-rows .sw-weight').forEach(el => {
    el.addEventListener('input', updateTotal);
  });
  document.getElementById('add-edit-row').addEventListener('click', () => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input class="sw-key"    type="text"   required></td>
      <td><input class="sw-weight" type="number"  step="0.001" min="0" max="1" required></td>
      <td><button type="button" class="sw-remove">✕</button></td>`;
    tr.querySelector('.sw-remove').addEventListener('click', () => { tr.remove(); updateTotal(); });
    tr.querySelector('.sw-weight').addEventListener('input', updateTotal);
    document.getElementById('edit-weight-rows').appendChild(tr);
    updateTotal();
  });

  // Serialise to JSON for the PUT request
  document.getElementById('split-weight-edit-form').addEventListener('htmx:configRequest', e => {
    const rows = [...document.querySelectorAll('#edit-weight-rows tr')];
    e.detail.parameters = {
      weights: rows.map(tr => ({
        child_key: tr.querySelector('.sw-key').value,
        weight: parseFloat(tr.querySelector('.sw-weight').value)||0,
      }))
    };
  });

  updateTotal();
})();
</script>
```

### 9c. View update — accept `split_weights_json` on override create

Update `ForecastOverrideListCreateView.post()` to create `OverrideSplitWeight` rows
atomically when the planner selects CUSTOM and provides weights in the same POST:

```python
# In ForecastOverrideListCreateView.post(), after serializer.save():

import json as _json
from django.db import transaction as _transaction

split_weights_json = request.data.get('split_weights_json')
if split_weights_json and override.disagg_method == ForecastOverride.DisaggMethod.CUSTOM:
    try:
        raw_weights = _json.loads(split_weights_json)
    except (ValueError, TypeError):
        raw_weights = []

    if raw_weights:
        with _transaction.atomic():
            OverrideSplitWeight.objects.bulk_create([
                OverrideSplitWeight(
                    override  = override,
                    child_key = w.get('child_key', {}),
                    weight    = w.get('weight', 0),
                )
                for w in raw_weights
                if w.get('weight', 0) > 0
            ])
```

---

## 10. Unit Tests

Add to `mysite/tests/demand/test_overrides.py`:

```python
# mysite/tests/demand/test_overrides.py

"""
Sprint 3B.5 unit tests — override API, disaggregation, revert.

Fixtures re-use the pytest fixtures from test_forecast.py where possible.
"""
import pytest
from decimal import Decimal
from django.urls import reverse
from rest_framework.test import APIClient

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastOverride, OverrideSplitWeight,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client(db, django_user_model):
    user = django_user_model.objects.create_user(username='planner', password='pass')
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def draft_version_with_lines(db, draft_version, active_item, leaf_location):
    """
    A DRAFT version with two ForecastLine rows for January 2025.
    line_a: ITEM-001 | NULL | LEAF-01 | statistical_qty=100
    line_b: ITEM-002 | NULL | LEAF-01 | statistical_qty=200
    """
    from mysite.models.demand.forecast import ForecastLine
    import datetime

    line_a = ForecastLine.objects.create(
        version              = draft_version,
        item                 = active_item,
        planning_location    = leaf_location,
        planning_customer    = None,
        period_type          = 'month',
        period_start         = datetime.date(2025, 1, 1),
        period_end           = datetime.date(2025, 1, 31),
        statistical_qty      = Decimal('100.000'),
        final_qty            = Decimal('100.000'),
        price_used           = Decimal('150.00'),
        statistical_value    = Decimal('15000.00'),
        final_value          = Decimal('15000.00'),
        model_used           = 'AutoETS',
        forecast_level       = 'item_cust_location',
    )
    # Second item (assume you have a second active_item fixture; adapt as needed)
    line_b = ForecastLine.objects.create(
        version              = draft_version,
        item                 = active_item,   # same item — different location in real test
        planning_location    = leaf_location,
        planning_customer    = None,
        period_type          = 'month',
        period_start         = datetime.date(2025, 2, 1),
        period_end           = datetime.date(2025, 2, 28),
        statistical_qty      = Decimal('200.000'),
        final_qty            = Decimal('200.000'),
        price_used           = Decimal('150.00'),
        statistical_value    = Decimal('30000.00'),
        final_value          = Decimal('30000.00'),
        model_used           = 'AutoETS',
        forecast_level       = 'item_cust_location',
    )
    return draft_version, line_a, line_b


# ─────────────────────────────────────────────────────────────────────────────
# Test class: POST /overrides/ — create
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestCreateOverride:

    def _url(self, version_id):
        return f'/api/demand/forecast-versions/{version_id}/overrides/'

    def test_create_qty_override_returns_202(self, api_client, draft_version_with_lines):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   120,
            'disagg_method':  'PROPORTIONAL',
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 202
        assert ForecastOverride.objects.filter(version=version).count() == 1
        override = ForecastOverride.objects.get(version=version)
        assert override.override_qty == Decimal('120')
        assert override.is_applied is False   # Celery task is async in tests

    def test_create_pct_override(self, api_client, draft_version_with_lines):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_pct':   10.0,
            'disagg_method':  'PROPORTIONAL',
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 202
        override = ForecastOverride.objects.get(version=version)
        assert override.override_pct == Decimal('10.000')
        assert override.override_qty is None

    def test_rejects_dual_override_type(self, api_client, draft_version_with_lines):
        """Providing both override_qty and override_pct must return 400."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   100,
            'override_pct':   10.0,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 400

    def test_rejects_override_value_at_sku_level(self, api_client, draft_version_with_lines):
        """override_value at SKU level must return 400."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_value': 50000,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 400

    def test_rejects_create_on_non_draft_version(self, api_client, draft_version_with_lines):
        """Creating an override on an IN_REVIEW or LOCKED version must return 403."""
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        version.status = ForecastVersion.Status.IN_REVIEW
        version.save(update_fields=['status'])

        payload = {
            'override_level': 'sku',
            'override_key':   {'item_id': line_a.item.item_id},
            'period_type':    'month',
            'period_start':   '2025-01-01',
            'override_qty':   100,
        }
        resp = client.post(self._url(version.pk), payload, format='json')
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Test class: GET /overrides/ — list
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestListOverrides:

    def test_list_returns_all_overrides_for_version(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        ForecastOverride.objects.create(
            version        = version,
            override_level = 'sku',
            override_key   = {'item_id': line_a.item.item_id},
            period_type    = 'month',
            period_start   = line_a.period_start,
            period_end     = line_a.period_end,
            override_qty   = Decimal('120'),
            disagg_method  = 'PROPORTIONAL',
            created_by     = user,
        )
        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/overrides/')
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['override_qty'] == '120.000'

    def test_list_filters_by_is_applied(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('120'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=True,
        )
        ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('130'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=False,
        )
        resp = client.get(
            f'/api/demand/forecast-versions/{version.pk}/overrides/?is_applied=true'
        )
        assert resp.status_code == 200
        assert resp.data['count'] == 1
        assert resp.data['results'][0]['is_applied'] is True


# ─────────────────────────────────────────────────────────────────────────────
# Test class: DELETE — applied override reverts ForecastLine
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestDeleteOverride:

    def test_delete_unapplied_override_removes_row(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('999'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=False,
        )
        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 204
        assert not ForecastOverride.objects.filter(pk=override.pk).exists()
        # ForecastLine.override_qty should still be None (was never applied)
        line_a.refresh_from_db()
        assert line_a.override_qty is None

    def test_delete_applied_override_reverts_forecast_line(
        self, api_client, draft_version_with_lines, django_user_model
    ):
        """
        After an applied override is deleted, ForecastLine.override_qty must be NULL
        and final_qty must equal statistical_qty.
        """
        client, user = api_client
        version, line_a, _ = draft_version_with_lines

        # Simulate an applied override: set override_qty on the line
        line_a.override_qty = Decimal('999.000')
        line_a.final_qty    = Decimal('999.000')
        line_a.save(update_fields=['override_qty', 'final_qty'])

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('999'),
            disagg_method='PROPORTIONAL', created_by=user,
            is_applied=True,   # already applied
        )

        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 204

        line_a.refresh_from_db()
        # Revert: override_qty cleared
        assert line_a.override_qty is None
        # final_qty reverts to statistical_qty
        assert line_a.final_qty == Decimal('100.000')

    def test_delete_blocked_on_non_draft_version(self, api_client, draft_version_with_lines, django_user_model):
        client, user = api_client
        version, line_a, _ = draft_version_with_lines
        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('100'),
            disagg_method='PROPORTIONAL', created_by=user,
        )
        version.status = ForecastVersion.Status.LOCKED
        version.save(update_fields=['status'])

        resp = client.delete(
            f'/api/demand/forecast-versions/{version.pk}/overrides/{override.pk}/'
        )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# Test class: apply_overrides Celery task (unit, no Celery worker)
# ─────────────────────────────────────────────────────────────────────────────
# In test_overrides.py — update TestApplyOverridesTask fixtures

@pytest.mark.django_db
class TestApplyOverridesTask:

    def test_qty_override_updates_forecast_line_final_qty(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('150'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('150.000')
        assert line_a.final_qty    == Decimal('150.000')

    def test_pct_override_multiplies_statistical_qty(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_pct=Decimal('10'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('110.000')
        assert line_a.final_qty    == Decimal('110.000')

    def test_delete_override_reverts_to_statistical(
        self, draft_version_with_lines, planner_user      # ← add planner_user
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override
        from mysite.api.demand.views import _revert_override_lines

        version, line_a, _ = draft_version_with_lines

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('200'),
            disagg_method='PROPORTIONAL', created_by=planner_user,  # ← use fixture
        )
        _apply_single_override(override, version)
        override.is_applied = True
        override.save(update_fields=['is_applied'])

        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('200.000')

        _revert_override_lines(override, version)
        line_a.refresh_from_db()
        assert line_a.override_qty is None
        assert line_a.final_qty    == Decimal('100.000')
"""
@pytest.mark.django_db
class TestApplyOverridesTask:

    def test_qty_override_updates_forecast_line_final_qty(
        self, draft_version_with_lines, django_user_model
    ):

        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('150'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        _apply_single_override(override, version)
        line_a.refresh_from_db()

        assert line_a.override_qty == Decimal('150.000')
        assert line_a.final_qty    == Decimal('150.000')

    def test_pct_override_multiplies_statistical_qty(
        self, draft_version_with_lines, django_user_model
    ):
        from mysite.tasks.demand.run_forecast import _apply_single_override

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_pct=Decimal('10'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        _apply_single_override(override, version)
        line_a.refresh_from_db()

        # 100 * 1.1 = 110
        assert line_a.override_qty == Decimal('110.000')
        assert line_a.final_qty    == Decimal('110.000')

    def test_delete_override_reverts_to_statistical(
        self, draft_version_with_lines, django_user_model
    ):

        from mysite.tasks.demand.run_forecast import _apply_single_override
        from mysite.api.demand.views import _revert_override_lines

        version, line_a, _ = draft_version_with_lines
        user = django_user_model.objects.get(username='planner')

        override = ForecastOverride.objects.create(
            version=version, override_level='sku',
            override_key={'item_id': line_a.item.item_id},
            period_type='month', period_start=line_a.period_start,
            period_end=line_a.period_end, override_qty=Decimal('200'),
            disagg_method='PROPORTIONAL', created_by=user,
        )

        # Apply it
        _apply_single_override(override, version)
        override.is_applied = True
        override.save(update_fields=['is_applied'])

        line_a.refresh_from_db()
        assert line_a.override_qty == Decimal('200.000')

        # Revert it
        _revert_override_lines(override, version)
        line_a.refresh_from_db()

        assert line_a.override_qty is None
        assert line_a.final_qty    == Decimal('100.000')   # back to statistical
"""        
```

---

## 11. Migration and Checklist

No migration required — all models exist from Sprint 3B.3.

```bash
# Verify no schema drift
python manage.py migrate --check

# Run new tests
pytest --co -q mysite/tests/demand/test_overrides.py  ## first run
pytest mysite/tests/demand/test_overrides.py -v --tb=short ## main run

pytest mysite/tests/demand/test_overrides.py -v

# Run full demand test suite to confirm no regressions
pytest mysite/tests/demand/ -v
```

**New files created in 3B.5:**

```
mysite/tests/demand/test_overrides.py
mysite/views/demand/forecast_htmx.py
mysite/templates/demand/partials/
    override_form.html
    override_badge.html
    override_propagation.html
    split_weight_form.html
    split_weight_editor.html
    override_key_sku.html
    override_key_location.html
    override_key_total.html
    override_value_qty.html        (trivial: renders the qty <input>)
    override_value_pct.html        (trivial: renders the pct <input>)
    override_value_value.html      (trivial: renders the ₹ <input>)
```

**Final Sprint 3B.5 checklist:**

```
── REST API ─────────────────────────────────────────────────────────────────
[x] POST   /api/demand/forecast-versions/{id}/overrides/
         → creates ForecastOverride, returns 202, fires apply_overrides.delay()
[x] GET    /api/demand/forecast-versions/{id}/overrides/
         → lists overrides with is_applied badge, supports level/period/is_applied filters
[x] GET    /api/demand/forecast-versions/{id}/overrides/{oid}/
         → detail with split_weights nested
[x] DELETE /api/demand/forecast-versions/{id}/overrides/{oid}/
         → blocks non-DRAFT; reverts lines if is_applied=True; 204
[x] GET    /api/demand/forecast-versions/{id}/overrides/{oid}/affected-lines/
         → paginated list of ForecastLine rows matching the override
[x] GET    /api/demand/forecast-versions/{id}/overrides/{oid}/split-weights/
         → lists OverrideSplitWeight rows for CUSTOM overrides
[x] PUT    /api/demand/forecast-versions/{id}/overrides/{oid}/split-weights/
         → atomically replaces weights; validates sum=1.0; marks is_applied=False; 202

── SERIALIZERS ───────────────────────────────────────────────────────────────
[x] OverrideSplitWeightSerializer
[x] ForecastOverrideSerializer (list)
[x] ForecastOverrideDetailSerializer (with nested split_weights)
[x] ForecastOverrideCreateSerializer (write; mutually exclusive validation)
[x] OverrideSplitWeightBulkSerializer (PUT body; sum-to-1 validation)
[x] AffectedLineSerializer (read-only; statistical_qty + override_qty + final_qty)

── URLS ──────────────────────────────────────────────────────────────────────
[x] 4 REST API paths added to mysite/api/demand/urls.py
[x] 4 HTMX partial paths added to mysite/urls.py

── HTMX UI ──────────────────────────────────────────────────────────────────
[x] override_form.html — inline edit in forecast grid
[x] override_badge.html — applied/pending cell badge with 🔍 and ✕ controls
[x] override_propagation.html — paginated affected-lines panel
[x] split_weight_form.html — CUSTOM weight entry during override creation
[x] split_weight_editor.html — CUSTOM weight editor for existing overrides
[x] override_key_*.html — per-level key input partials (sku / location / total)
[x] HTMX views: override_key_field, override_value_inputs, encode_override_key,
               override_propagation

── UNIT TESTS ────────────────────────────────────────────────────────────────
[x] TestCreateOverride         (5 tests)
      qty override → 202
      pct override → 202
      dual type → 400
      override_value at SKU → 400
      non-DRAFT create → 403
[x] TestListOverrides          (2 tests)
      list all; filter by is_applied
[x] TestDeleteOverride         (3 tests)
      unapplied delete → row gone, line unchanged
      applied delete → row gone, line reverted to statistical
      non-DRAFT delete → 403
[x] TestApplyOverridesTask     (3 tests)
      qty override applied → final_qty updated
      pct override applied → final_qty = statistical * multiplier
      delete applied override → final_qty = statistical_qty

── SMOKE CHECKS ─────────────────────────────────────────────────────────────
[ ] POST override on DRAFT → override row created, apply_overrides queued
[ ] GET /overrides/ → lists override with is_applied=False until task runs
[ ] After task: GET /overrides/ → is_applied=True; GET /lines/ → final_qty updated
[ ] GET /affected-lines/ → shows which ForecastLine rows changed
[ ] DELETE applied override → ForecastLine.override_qty=NULL, final_qty=statistical_qty
[ ] PUT /split-weights/ with sum ≠ 1.0 → 400 validation error
[ ] PUT /split-weights/ with valid weights → is_applied reset, task re-queued
[ ] Forecast grid: click cell → override_form.html loads inline
[ ] Propagation panel: click 🔍 → propagation partial loads, shows affected lines
[ ] CUSTOM disagg: enter weights, submit → weights saved, disaggregation fires
```
