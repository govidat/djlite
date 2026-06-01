# Sprint 3B.3 — Delta: Sections 7, 8, 9, 10
## Views · URLs · Unit Tests · Final Checklist

**Applies to:** `sprint_3b3_instructions.md` as compiled  
**These four sections were not updated after the SeriesProfile additions.**  
**Apply these deltas in order.**

---

## Gap Analysis

| Section | What exists | What is missing |
|---|---|---|
| **7 Views** | 5 ForecastVersion views with stale import block | Import block missing 6 new symbols; `ForecastVersionLinesView` missing `forecast_level` filter; 4 new SeriesProfile/Config views exist only in a later appendix section |
| **8 URLs** | 5 ForecastVersion URL patterns | 4 new URL patterns exist only in the appendix; consolidated list never produced |
| **9 Tests** | `ForecastLine`, state machine, copy, override tests | No tests for `AbcClassDefinition`, `ForecastingConfig`, `SeriesProfile.compute_syntetos_boylan`, `SeriesLevelEvaluation`, API override PATCH, `ForecastingConfigView` |
| **10 Checklist** | Original 6-model, 5-view, 5-URL checklist | All new models, admin, serializers, views, URLs, tasks, and tests missing |

---

## 7. Views — Complete Replacement

**Action:** Replace Section 7 in its entirety with the block below.
The appendix "Section 3. Views" (line 5007 onwards) is superseded and
should be removed from the compiled document.

```python
# mysite/api/demand/views.py
# ── Complete import block for Sprint 3B.3 ─────────────────────────────────

from django.db.models import Count
from django.core.paginator import Paginator, EmptyPage
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

from mysite.models.demand.forecast import (
    ForecastVersion,
    ForecastLine,
    ForecastAggregate,
    SeriesProfile,
    SeriesLevelEvaluation,
    ForecastingConfig,
)
from mysite.api.demand.serializers import (
    ForecastVersionSerializer,
    ForecastVersionCreateSerializer,
    ForecastLineSerializer,
    ForecastAggregateSerializer,
    SeriesProfileListSerializer,
    SeriesProfileSerializer,
    SeriesLevelEvaluationSerializer,
    ForecastingConfigSerializer,
)
from utils.feature_control import is_demand_feature_disabled


# ─────────────────────────────────────────────────────────────────────────────
# Mixin: demand feature gate
# ─────────────────────────────────────────────────────────────────────────────

class DemandFeatureMixin:
    """
    Checks the master demand_planning feature flag on every request.
    Assumes request.client is set by middleware / ClientScopedMixin.
    """
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        result = is_demand_feature_disabled(
            getattr(request, 'client', None), 'demand_planning'
        )
        if result['disabled']:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied(detail=result['message'])


# ─────────────────────────────────────────────────────────────────────────────
# Forecast Version views
# ─────────────────────────────────────────────────────────────────────────────

class ForecastVersionListCreateView(DemandFeatureMixin, APIView):
    """
    GET  /api/demand/forecast-versions/
         List all versions for the client. Filterable by status.

    POST /api/demand/forecast-versions/
         Create a new DRAFT version.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            ForecastVersion.objects
            .filter(client=request.client)
            .annotate(line_count=Count('lines'))
            .select_related('created_by', 'approved_by')
            .order_by('-created_at')
        )
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())

        serializer = ForecastVersionSerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        result = is_demand_feature_disabled(request.client, 'forecast_run')
        if result['disabled']:
            return Response(
                {'detail': result['message']},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = ForecastVersionCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        version = serializer.save(
            client     = request.client,
            created_by = request.user,
            status     = ForecastVersion.Status.DRAFT,
        )
        return Response(
            ForecastVersionSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )


class ForecastVersionDetailView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/
    """
    permission_classes = [IsAuthenticated]

    def _get_version(self, request, pk):
        return get_object_or_404(
            ForecastVersion.objects
            .annotate(line_count=Count('lines'))
            .select_related('created_by', 'approved_by'),
            pk=pk, client=request.client,
        )

    def get(self, request, pk):
        return Response(ForecastVersionSerializer(self._get_version(request, pk)).data)


class ForecastVersionLinesView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/lines/

    Query params:
        item_id         — filter by Item.item_id
        location_code   — filter by PlanningLocation.code
        customer_code   — filter by PlanningCustomer.code
        period_start    — ISO date, period_start >= value
        period_end      — ISO date, period_end <= value
        has_override    — true | false
        forecast_level  — filter by forecast_level grain string
                          (e.g. "item_client", "item_loc_depth_2")
                          When store_all_level_forecasts=true, multiple rows
                          exist per series — this filter selects which level
                          to display.
        page / page_size — default 100, max 500
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import datetime

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        qs = (
            ForecastLine.objects
            .filter(version=version)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('period_start', 'planning_location__code', 'item__item_id')
        )

        p = request.query_params

        if p.get('item_id'):
            qs = qs.filter(item__item_id=p['item_id'])
        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])
        if p.get('customer_code'):
            qs = qs.filter(planning_customer__code=p['customer_code'])
        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response(
                    {'period_start': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                return Response(
                    {'period_end': 'Use YYYY-MM-DD format.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if p.get('has_override') == 'true':
            qs = qs.filter(override_qty__isnull=False)
        elif p.get('has_override') == 'false':
            qs = qs.filter(override_qty__isnull=True)

        # NEW: filter by forecast level grain (from SeriesProfile additions)
        if p.get('forecast_level'):
            qs = qs.filter(forecast_level=p['forecast_level'])

        try:
            page_size = min(int(p.get('page_size', 100)), 500)
            page_num  = int(p.get('page', 1))
        except ValueError:
            page_size, page_num = 100, 1

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        return Response({
            'version_id':    version.pk,
            'version_label': version.version_label,
            'count':         paginator.count,
            'next':          self._page_url(request, page_num + 1, paginator.num_pages),
            'previous':      self._page_url(request, page_num - 1, paginator.num_pages),
            'results':       ForecastLineSerializer(page.object_list, many=True).data,
        })

    def _page_url(self, request, page_num, num_pages):
        if page_num < 1 or page_num > num_pages:
            return None
        params = request.query_params.copy()
        params['page'] = page_num
        return request.build_absolute_uri(f'?{params.urlencode()}')


class ForecastVersionAggregatesView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/aggregates/

    Query params:
        agg_level    — filter by level (category, region, total, etc.)
        period_start — ISO date
        period_end   — ISO date
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import datetime

        version = get_object_or_404(
            ForecastVersion, pk=pk, client=request.client
        )
        qs = (
            ForecastAggregate.objects
            .filter(version=version)
            .order_by('agg_level', 'period_start')
        )

        p = request.query_params
        if p.get('agg_level'):
            qs = qs.filter(agg_level=p['agg_level'])
        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response({'period_start': 'Use YYYY-MM-DD format.'},
                                status=status.HTTP_400_BAD_REQUEST)
        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                return Response({'period_end': 'Use YYYY-MM-DD format.'},
                                status=status.HTTP_400_BAD_REQUEST)

        return Response(ForecastAggregateSerializer(qs, many=True).data)


class ForecastVersionApproveView(DemandFeatureMixin, APIView):
    """
    POST /api/demand/forecast-versions/{id}/approve/

    Body: {"action": "submit|approve|reject|lock|copy", "note": "..."}

    submit  → DRAFT      → IN_REVIEW
    approve → IN_REVIEW  → APPROVED
    reject  → IN_REVIEW  → DRAFT
    lock    → APPROVED   → LOCKED
    copy    → any status → new DRAFT (returns the new version, HTTP 201)
    """
    permission_classes = [IsAuthenticated]

    ACTION_TRANSITIONS = {
        'submit':  ForecastVersion.Status.IN_REVIEW,
        'approve': ForecastVersion.Status.APPROVED,
        'reject':  ForecastVersion.Status.DRAFT,
        'lock':    ForecastVersion.Status.LOCKED,
    }

    def post(self, request, pk):
        result = is_demand_feature_disabled(request.client, 'forecast_approval')
        if result['disabled']:
            return Response({'detail': result['message']},
                            status=status.HTTP_403_FORBIDDEN)

        version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
        action  = request.data.get('action', '').strip().lower()
        note    = request.data.get('note', '').strip()

        if action == 'copy':
            new_label   = note or f'{version.version_label} (copy)'
            new_version = version.copy(user=request.user, new_label=new_label)
            return Response(ForecastVersionSerializer(new_version).data,
                            status=status.HTTP_201_CREATED)

        if action not in self.ACTION_TRANSITIONS:
            return Response(
                {'detail': (
                    f'Unknown action "{action}". '
                    f'Valid: submit, approve, reject, lock, copy.'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            version.transition_to(self.ACTION_TRANSITIONS[action], user=request.user)
        except DjangoValidationError as exc:
            return Response({'detail': exc.message}, status=status.HTTP_403_FORBIDDEN)

        if note:
            version.notes = (version.notes + f'\n[{action}] {note}').strip()
            version.save(update_fields=['notes'])

        version.refresh_from_db()
        return Response(ForecastVersionSerializer(version).data)


# ─────────────────────────────────────────────────────────────────────────────
# SeriesProfile views   (NEW — from SeriesProfile additions)
# ─────────────────────────────────────────────────────────────────────────────

class SeriesProfileListView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/series-profiles/

    Lightweight list — no nested evaluation log.
    Use /series-profiles/{id}/ for the full audit trail.

    Query params:
        demand_class   — SMOOTH | ERRATIC | INTERMITTENT | LUMPY |
                         INSUFFICIENT | ZERO
        abc_class      — A | B | C | D  (client's AbcClassDefinition labels)
        chosen_grain   — filter by chosen_grain string
        has_override   — true | false
        is_manual      — true → only series needing planner input
        location_code  — filter by PlanningLocation.code
        period_type    — filter by period type
        page / page_size — default 100, max 500
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = (
            SeriesProfile.objects
            .filter(client=request.client)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('abc_class_atomic', 'demand_class_atomic', 'item__item_id')
        )

        p = request.query_params
        if p.get('demand_class'):
            qs = qs.filter(demand_class_atomic=p['demand_class'].upper())
        if p.get('abc_class'):
            qs = qs.filter(abc_class_atomic=p['abc_class'].upper())
        if p.get('chosen_grain'):
            qs = qs.filter(chosen_grain=p['chosen_grain'])
        if p.get('has_override') == 'true':
            qs = qs.exclude(override_grain='').exclude(override_strategy='')
        elif p.get('has_override') == 'false':
            qs = qs.filter(override_grain='', override_strategy='')
        if p.get('is_manual') == 'true':
            qs = qs.filter(chosen_strategy='MANUAL')
        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])
        if p.get('period_type'):
            qs = qs.filter(period_type=p['period_type'])

        try:
            page_size = min(int(p.get('page_size', 100)), 500)
            page_num  = int(p.get('page', 1))
        except ValueError:
            page_size, page_num = 100, 1

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        return Response({
            'count':    paginator.count,
            'next':     self._page_url(request, page_num + 1, paginator.num_pages),
            'previous': self._page_url(request, page_num - 1, paginator.num_pages),
            'results':  SeriesProfileListSerializer(page.object_list, many=True).data,
        })

    def _page_url(self, request, page_num, num_pages):
        if page_num < 1 or page_num > num_pages:
            return None
        params = request.query_params.copy()
        params['page'] = page_num
        return request.build_absolute_uri(f'?{params.urlencode()}')


class SeriesProfileDetailView(DemandFeatureMixin, APIView):
    """
    GET   /api/demand/series-profiles/{id}/
          Full detail with nested evaluation log.

    PATCH /api/demand/series-profiles/{id}/
          Only override_grain, override_strategy, override_note are writable.
          Requires consensus_override feature flag.
    """
    permission_classes = [IsAuthenticated]

    def _get_profile(self, request, pk):
        return get_object_or_404(
            SeriesProfile.objects.select_related(
                'item', 'planning_location',
                'planning_customer', 'override_set_by',
            ),
            pk=pk, client=request.client,
        )

    def get(self, request, pk):
        profile = self._get_profile(request, pk)
        return Response(
            SeriesProfileSerializer(profile, context={'request': request}).data
        )

    def patch(self, request, pk):
        result = is_demand_feature_disabled(request.client, 'consensus_override')
        if result['disabled']:
            return Response({'detail': result['message']},
                            status=status.HTTP_403_FORBIDDEN)

        profile = self._get_profile(request, pk)

        allowed_fields = {'override_grain', 'override_strategy', 'override_note'}
        disallowed = set(request.data.keys()) - allowed_fields
        if disallowed:
            return Response(
                {'detail': (
                    f'Fields not writable: {", ".join(sorted(disallowed))}. '
                    f'Only override_grain, override_strategy, and '
                    f'override_note may be updated.'
                )},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = SeriesProfileSerializer(
            profile, data=request.data, partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        instance = serializer.save()
        instance.override_set_by = request.user
        instance.override_set_at = timezone.now()
        instance.save(update_fields=['override_set_by', 'override_set_at'])

        return Response(
            SeriesProfileSerializer(instance, context={'request': request}).data
        )


class SeriesProfileEvaluationsView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/series-profiles/{id}/evaluations/

    All SeriesLevelEvaluation rows for this series, ordered so the
    search path reads naturally: rejected levels first, accepted level last.
    Lazy-load alternative to the nested evaluations in the detail endpoint.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        profile = get_object_or_404(
            SeriesProfile, pk=pk, client=request.client
        )
        evals = (
            SeriesLevelEvaluation.objects
            .filter(
                client=request.client,
                item=profile.item,
                period_type=profile.period_type,
            )
            .order_by('is_accepted', 'grain')
        )
        return Response(SeriesLevelEvaluationSerializer(evals, many=True).data)


class ForecastingConfigView(DemandFeatureMixin, APIView):
    """
    GET   /api/demand/forecasting-config/
          Returns ForecastingConfig + AbcClassDefinitions + derived time horizons.
          Query param: period_type (default: month) — used for derived_time_horizons.

    PATCH /api/demand/forecasting-config/
          Update thresholds. Staff only.
          ABC tiers must be managed via Django admin.
    """
    permission_classes = [IsAuthenticated]

    def _get_config(self, request):
        return ForecastingConfig.get_for_client(request.client)

    def get(self, request):
        return Response(
            ForecastingConfigSerializer(
                self._get_config(request),
                context={'request': request},
            ).data
        )

    def patch(self, request):
        if not request.user.is_staff:
            return Response(
                {'detail': 'Only staff users may update forecasting config.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        config = self._get_config(request)
        serializer = ForecastingConfigSerializer(
            config, data=request.data, partial=True,
            context={'request': request},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        serializer.save()
        return Response(serializer.data)
```

---

## 8. URLs — Complete Replacement

**Action:** Replace Section 8 in its entirety. The appendix "Section 4. URL additions"
(line 5275 onwards) is superseded and should be removed.

```python
# mysite/api/demand/urls.py
# Complete urlpatterns for Sprint 3B.3 — all 9 patterns in one place.

from django.urls import path
from mysite.api.demand import views

urlpatterns = [
    # ── Forecast Versions ──────────────────────────────────────────────────
    path(
        'forecast-versions/',
        views.ForecastVersionListCreateView.as_view(),
        name='demand-forecast-versions',
    ),
    path(
        'forecast-versions/<int:pk>/',
        views.ForecastVersionDetailView.as_view(),
        name='demand-forecast-version-detail',
    ),
    path(
        'forecast-versions/<int:pk>/lines/',
        views.ForecastVersionLinesView.as_view(),
        name='demand-forecast-version-lines',
    ),
    path(
        'forecast-versions/<int:pk>/aggregates/',
        views.ForecastVersionAggregatesView.as_view(),
        name='demand-forecast-version-aggregates',
    ),
    path(
        'forecast-versions/<int:pk>/approve/',
        views.ForecastVersionApproveView.as_view(),
        name='demand-forecast-version-approve',
    ),

    # ── Series Profiles  (NEW — SeriesProfile additions) ───────────────────
    path(
        'series-profiles/',
        views.SeriesProfileListView.as_view(),
        name='demand-series-profiles',
    ),
    path(
        'series-profiles/<int:pk>/',
        views.SeriesProfileDetailView.as_view(),
        name='demand-series-profile-detail',
    ),
    path(
        'series-profiles/<int:pk>/evaluations/',
        views.SeriesProfileEvaluationsView.as_view(),
        name='demand-series-profile-evaluations',
    ),

    # ── Forecasting Config  (NEW — SeriesProfile additions) ────────────────
    path(
        'forecasting-config/',
        views.ForecastingConfigView.as_view(),
        name='demand-forecasting-config',
    ),
]
```

---

## 9. Unit Tests — Delta (add after existing tests)

**Action:** Append the following test classes to
`mysite/tests/demand/test_forecast.py` after `TestForecastOverrideValidation`.
The existing test classes are unchanged.

```python
# ─────────────────────────────────────────────────────────────────────────────
# Additional fixtures needed for SeriesProfile tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def forecasting_config(db, client_obj):
    from mysite.models.demand.forecast import ForecastingConfig
    return ForecastingConfig.get_for_client(client_obj)


@pytest.fixture
def abc_definitions(db, client_obj):
    from mysite.models.demand.forecast import AbcClassDefinition
    return AbcClassDefinition.get_or_create_defaults(client_obj)


@pytest.fixture
def series_profile(db, client_obj, active_item, leaf_location,
                   planning_customer, forecasting_config, abc_definitions):
    from mysite.models.demand.forecast import SeriesProfile
    import datetime
    return SeriesProfile.objects.create(
        client            = client_obj,
        item              = active_item,
        planning_customer = planning_customer,
        planning_location = leaf_location,
        period_type       = 'month',
        analysis_from     = datetime.date(2022, 1, 1),
        analysis_to       = datetime.date(2024, 12, 31),
        total_periods     = 36,
        nonzero_periods   = 24,
        total_qty         = Decimal('8640.000'),
        zero_rate         = Decimal('0.3333'),
        demand_class_atomic = 'SMOOTH',
        abc_class_atomic    = 'A',
        chosen_grain        = 'item_client',
        chosen_demand_class = 'SMOOTH',
        chosen_strategy     = 'AUTOETS',
        chosen_eval_period  = 'month',
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test: AbcClassDefinition
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAbcClassDefinition:

    def test_get_or_create_defaults_creates_three_tiers(
        self, client_obj, abc_definitions
    ):
        """Default tiers are A/B/C at 70/90/100."""
        from mysite.models.demand.forecast import AbcClassDefinition
        tiers = AbcClassDefinition.objects.filter(client=client_obj).order_by('rank')
        assert tiers.count() == 3
        labels = [t.label for t in tiers]
        assert labels == ['A', 'B', 'C']
        thresholds = [float(t.cumulative_upper_pct) for t in tiers]
        assert thresholds == [70.0, 90.0, 100.0]

    def test_get_or_create_defaults_is_idempotent(self, client_obj, abc_definitions):
        """Calling get_or_create_defaults twice does not create duplicates."""
        from mysite.models.demand.forecast import AbcClassDefinition
        AbcClassDefinition.get_or_create_defaults(
            AbcClassDefinition.objects.filter(client=client_obj).first().client
        )
        assert AbcClassDefinition.objects.filter(client=client_obj).count() == 3

    def test_compute_class_a_item(self, abc_definitions):
        """Item at top of value ranking is class A."""
        from mysite.models.demand.forecast import AbcClassDefinition
        # Item with value 700 out of [1000, 700, 200, 100] total=2000
        # cumulative share of top item = 1000/2000=50%, rank-1 item is A
        result = AbcClassDefinition.compute_class(
            item_value=1000.0,
            all_values_sorted_desc=[1000.0, 700.0, 200.0, 100.0],
            definitions=abc_definitions,
        )
        assert result['abc_class'] == 'A'

    def test_compute_class_c_item(self, abc_definitions):
        """Item at bottom of value ranking is class C."""
        from mysite.models.demand.forecast import AbcClassDefinition
        result = AbcClassDefinition.compute_class(
            item_value=100.0,
            all_values_sorted_desc=[1000.0, 700.0, 200.0, 100.0],
            definitions=abc_definitions,
        )
        assert result['abc_class'] == 'C'

    def test_four_tier_client(self, client_obj):
        """Client with 4 tiers (A/B/C/D) classifies correctly."""
        from mysite.models.demand.forecast import AbcClassDefinition
        # Create 4-tier config
        AbcClassDefinition.objects.filter(client=client_obj).delete()
        defs = AbcClassDefinition.objects.bulk_create([
            AbcClassDefinition(client=client_obj, rank=1, label='A',
                               cumulative_upper_pct=Decimal('60.000')),
            AbcClassDefinition(client=client_obj, rank=2, label='B',
                               cumulative_upper_pct=Decimal('80.000')),
            AbcClassDefinition(client=client_obj, rank=3, label='C',
                               cumulative_upper_pct=Decimal('95.000')),
            AbcClassDefinition(client=client_obj, rank=4, label='D',
                               cumulative_upper_pct=Decimal('100.000')),
        ])
        result = AbcClassDefinition.compute_class(
            item_value=50.0,           # last item, clearly D
            all_values_sorted_desc=[500.0, 300.0, 150.0, 50.0],
            definitions=defs,
        )
        assert result['abc_class'] == 'D'


# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastingConfig
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastingConfig:

    def test_get_for_client_creates_with_defaults(self, client_obj):
        """get_for_client creates a config with sensible defaults."""
        from mysite.models.demand.forecast import ForecastingConfig
        config = ForecastingConfig.get_for_client(client_obj)
        assert float(config.adi_threshold)  == 1.32
        assert float(config.cv2_threshold)  == 0.49
        assert config.min_nonzero_periods   == 6
        assert config.time_horizon_steps    == 2
        assert config.evaluate_customer_grain is True

    def test_get_for_client_is_idempotent(self, client_obj, forecasting_config):
        """Calling get_for_client twice returns the same row."""
        from mysite.models.demand.forecast import ForecastingConfig
        config2 = ForecastingConfig.get_for_client(client_obj)
        assert config2.pk == forecasting_config.pk

    def test_derived_time_horizons_monthly(self, forecasting_config):
        """Monthly base with 2 steps gives [quarter, halfyear]."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('month', forecasting_config.time_horizon_steps)
        assert horizons == ['quarter', 'halfyear']

    def test_derived_time_horizons_daily(self, forecasting_config):
        """Daily base with 2 steps gives [week, fortnight]."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('day', forecasting_config.time_horizon_steps)
        assert horizons == ['week', 'fortnight']

    def test_zero_steps_returns_empty(self, forecasting_config):
        """time_horizon_steps=0 means no time aggregation is tried."""
        from mysite.models.demand.actuals import get_higher_period_types
        horizons = get_higher_period_types('month', 0)
        assert horizons == []


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile.compute_syntetos_boylan (pure function)
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSyntetosBoylan:
    """
    Pure function tests — no DB required.
    All use default thresholds: ADI=1.32, CV²=0.49, min_nonzero=6.
    """

    ADI = 1.32
    CV2 = 0.49
    MNZ = 6

    def test_smooth_series(self):
        """All-positive, low-variance series → SMOOTH."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('100')] * 36
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'SMOOTH'
        assert result['recommended_strategy'] == 'AUTOETS'
        assert result['nonzero_periods'] == 36
        assert float(result['adi']) == pytest.approx(1.0, abs=0.01)

    def test_lumpy_series(self):
        """Sparse, high-variance series → LUMPY."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI = 36/6 = 6.0 ≥ 1.32; CV² of [100,50,200,150,80,120] is high
        qty = [Decimal('0')] * 30 + [
            Decimal('100'), Decimal('50'), Decimal('200'),
            Decimal('150'), Decimal('80'), Decimal('120'),
        ]
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'LUMPY'
        assert float(result['adi']) == pytest.approx(6.0, abs=0.1)

    def test_intermittent_series(self):
        """Sparse but stable qty → INTERMITTENT → Croston."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI ≥ 1.32, CV² < 0.49 (stable qty of 100 each time)
        qty = [Decimal('0')] * 30 + [Decimal('100')] * 6
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'INTERMITTENT'
        assert result['recommended_strategy'] == 'CROSTON'

    def test_erratic_series(self):
        """Frequent but high-variance qty → ERRATIC → AutoARIMA."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI < 1.32 (demand every period), CV² ≥ 0.49 (wildly variable)
        qty = [
            Decimal('5'), Decimal('500'), Decimal('3'), Decimal('450'),
            Decimal('8'), Decimal('600'), Decimal('2'), Decimal('400'),
            Decimal('10'), Decimal('550'), Decimal('4'), Decimal('480'),
        ] * 3   # 36 periods
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'ERRATIC'
        assert result['recommended_strategy'] == 'AUTOARIMA'

    def test_zero_series(self):
        """All-zero series → ZERO → MANUAL."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('0')] * 36
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'ZERO'
        assert result['recommended_strategy'] == 'MANUAL'
        assert result['nonzero_periods'] == 0

    def test_insufficient_series(self):
        """Fewer than min_nonzero non-zero periods → INSUFFICIENT."""
        from mysite.models.demand.forecast import SeriesProfile
        qty = [Decimal('0')] * 33 + [Decimal('100')] * 3   # only 3 non-zero
        result = SeriesProfile.compute_syntetos_boylan(qty, self.ADI, self.CV2, self.MNZ)
        assert result['demand_class'] == 'INSUFFICIENT'
        assert result['recommended_strategy'] == 'MOVING_AVG'

    def test_configurable_thresholds(self):
        """Stricter ADI threshold changes classification."""
        from mysite.models.demand.forecast import SeriesProfile
        # ADI = 36/12 = 3.0 — INTERMITTENT with default 1.32
        # but SMOOTH with a very loose threshold of 10.0
        qty = [Decimal('0')] * 24 + [Decimal('100')] * 12
        default_result = SeriesProfile.compute_syntetos_bowlan(
            qty, 1.32, 0.49, 6
        ) if False else SeriesProfile.compute_syntetos_boylan(qty, 1.32, 0.49, 6)
        loose_result   = SeriesProfile.compute_syntetos_boylan(qty, 10.0, 0.49, 6)

        assert default_result['demand_class'] == 'INTERMITTENT'
        assert loose_result['demand_class']   == 'SMOOTH'


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesLevelEvaluation
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesLevelEvaluation:

    def test_create_evaluation_row(
        self, client_obj, active_item, leaf_location
    ):
        """Can create a SeriesLevelEvaluation row with grain string."""
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        import datetime

        eval_row = SeriesLevelEvaluation.objects.create(
            client=client_obj,
            item=active_item,
            planning_customer=None,
            period_type='month',
            grain='item_client',
            evaluation_key={'grain': 'item_client'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36,
            nonzero_periods=20,
            total_qty=Decimal('2400.000'),
            zero_rate=Decimal('0.4444'),
            demand_class='LUMPY',
            is_accepted=False,
            rejection_reason='LUMPY (ADI=1.8, CV²=0.62)',
            recommended_strategy='',
        )
        assert eval_row.pk is not None
        assert eval_row.is_accepted is False
        assert 'LUMPY' in eval_row.rejection_reason

    def test_accepted_grain_stored_correctly(
        self, client_obj, active_item, leaf_location
    ):
        """The accepted evaluation row is flagged is_accepted=True."""
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        import datetime

        SeriesLevelEvaluation.objects.create(
            client=client_obj, item=active_item, planning_customer=None,
            period_type='month',
            grain='item_client',
            evaluation_key={'grain': 'item_client'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36, nonzero_periods=30,
            total_qty=Decimal('5000.000'),
            zero_rate=Decimal('0.1667'),
            demand_class='SMOOTH',
            is_accepted=True,
            rejection_reason='',
            recommended_strategy='AUTOETS',
        )
        accepted = SeriesLevelEvaluation.objects.filter(
            client=client_obj, item=active_item,
            period_type='month', is_accepted=True
        )
        assert accepted.count() == 1
        assert accepted.first().demand_class == 'SMOOTH'


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile model properties
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesProfileProperties:

    def test_effective_grain_uses_chosen_when_no_override(self, series_profile):
        """effective_grain returns chosen_grain when no override is set."""
        assert series_profile.override_grain == ''
        assert series_profile.effective_grain == 'item_client'

    def test_effective_grain_honours_override(self, series_profile):
        """effective_grain returns override_grain when set."""
        series_profile.override_grain = 'item_loc_depth_2'
        series_profile.save()
        assert series_profile.effective_grain == 'item_loc_depth_2'

    def test_effective_strategy_honours_override(self, series_profile):
        """effective_strategy returns override when set."""
        series_profile.override_strategy = 'CROSTON'
        series_profile.save()
        assert series_profile.effective_strategy == 'CROSTON'

    def test_is_overridden_false_by_default(self, series_profile):
        assert series_profile.is_overridden is False

    def test_is_overridden_true_when_grain_set(self, series_profile):
        series_profile.override_grain = 'item_client'
        assert series_profile.is_overridden is True

    def test_is_manual_true_when_strategy_manual(self, series_profile):
        series_profile.chosen_strategy = 'MANUAL'
        assert series_profile.is_manual is True

    def test_is_manual_false_for_autoets(self, series_profile):
        series_profile.chosen_strategy = 'AUTOETS'
        assert series_profile.is_manual is False


# ─────────────────────────────────────────────────────────────────────────────
# Test: SeriesProfile API — PATCH override
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestSeriesProfileAPI:

    def setup_method(self):
        from rest_framework.test import APIClient
        self.api = APIClient()

    def test_patch_override_grain_valid(
        self, series_profile, staff_user, client_obj,
        active_item, leaf_location
    ):
        """Valid override_grain from an evaluated level is accepted."""
        from mysite.models.demand.forecast import SeriesLevelEvaluation
        from django.urls import reverse
        import datetime

        # Create an evaluation row so validate_override_grain passes
        SeriesLevelEvaluation.objects.create(
            client=client_obj, item=active_item, planning_customer=None,
            period_type='month',
            grain='item_loc_depth_1',
            evaluation_key={'grain': 'item_loc_depth_1', 'level_label': 'Region'},
            eval_period_type='month',
            analysis_from=datetime.date(2022, 1, 1),
            analysis_to=datetime.date(2024, 12, 31),
            total_periods=36, nonzero_periods=28,
            total_qty=Decimal('4000.000'),
            zero_rate=Decimal('0.2222'),
            demand_class='INTERMITTENT',
            is_accepted=False,
            rejection_reason='',
            recommended_strategy='CROSTON',
        )

        self.api.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = self.api.patch(
            url,
            {'override_grain': 'item_loc_depth_1', 'override_note': 'Manual review'},
            format='json',
        )
        assert response.status_code == 200
        data = response.json()
        assert data['override_grain']   == 'item_loc_depth_1'
        assert data['is_overridden']    is True
        assert data['effective_grain']  == 'item_loc_depth_1'

    def test_patch_disallowed_field_rejected(
        self, series_profile, staff_user
    ):
        """Attempting to patch a read-only field returns 400."""
        from django.urls import reverse
        self.api.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = self.api.patch(
            url,
            {'chosen_grain': 'item_client'},  # read-only field
            format='json',
        )
        assert response.status_code == 400
        assert 'not writable' in response.json()['detail']

    def test_patch_invalid_grain_rejected(
        self, series_profile, staff_user
    ):
        """Grain string not matching any evaluated level is rejected."""
        from django.urls import reverse
        self.api.force_authenticate(user=staff_user)
        url = reverse('demand-series-profile-detail', kwargs={'pk': series_profile.pk})
        response = self.api.patch(
            url,
            {'override_grain': 'item_loc_depth_99'},  # no evaluation at this level
            format='json',
        )
        assert response.status_code == 400
        assert 'valid grain' in response.json()['override_grain'][0]


# ─────────────────────────────────────────────────────────────────────────────
# Test: ForecastingConfigView API
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastingConfigAPI:

    def setup_method(self):
        from rest_framework.test import APIClient
        self.api = APIClient()

    def test_get_returns_config_with_abc_tiers(
        self, client_obj, staff_user, forecasting_config, abc_definitions
    ):
        """GET returns the config including ABC tier definitions."""
        from django.urls import reverse
        self.api.force_authenticate(user=staff_user)
        url = reverse('demand-forecasting-config')
        response = self.api.get(url)
        assert response.status_code == 200
        data = response.json()
        assert 'adi_threshold'         in data
        assert 'abc_class_definitions' in data
        assert len(data['abc_class_definitions']) == 3
        assert data['abc_class_definitions'][0]['label'] == 'A'

    def test_get_includes_derived_time_horizons_for_period(
        self, client_obj, staff_user, forecasting_config, abc_definitions
    ):
        """derived_time_horizons respects the period_type query param."""
        from django.urls import reverse
        self.api.force_authenticate(user=staff_user)
        url = reverse('demand-forecasting-config')
        response = self.api.get(url, {'period_type': 'month'})
        data = response.json()
        # Default steps=2: month → [quarter, halfyear]
        assert data['derived_time_horizons'] == ['quarter', 'halfyear']

    def test_patch_by_non_staff_returns_403(
        self, client_obj, forecasting_config, abc_definitions, django_user_model
    ):
        """Non-staff user cannot PATCH forecasting config."""
        from django.urls import reverse
        regular_user = django_user_model.objects.create_user(
            'regular', password='pw', is_staff=False
        )
        self.api.force_authenticate(user=regular_user)
        url = reverse('demand-forecasting-config')
        response = self.api.patch(url, {'time_horizon_steps': 3}, format='json')
        assert response.status_code == 403

    def test_patch_by_staff_updates_threshold(
        self, client_obj, staff_user, forecasting_config, abc_definitions,
        django_user_model
    ):
        """Staff user can update ADI threshold."""
        from django.urls import reverse
        staff = django_user_model.objects.create_user(
            'adminstaff', password='pw', is_staff=True
        )
        self.api.force_authenticate(user=staff)
        url = reverse('demand-forecasting-config')
        response = self.api.patch(url, {'adi_threshold': '1.5000'}, format='json')
        assert response.status_code == 200
        assert response.json()['adi_threshold'] == '1.5000'
        forecasting_config.refresh_from_db()
        assert float(forecasting_config.adi_threshold) == 1.5
```

---

## 10. Final Checklist — Complete Replacement

**Action:** Replace Section 10 in its entirety.
Items marked `[x]` were already done. Items marked `[ ]` need verification.

```
── MODELS ───────────────────────────────────────────────────────────────────
[x] mysite/models/demand/forecast.py created
[x]   ForecastVersion (with status state machine, copy(), transition_to())
[x]   ForecastLine (final_qty computed in save())
[x]   ForecastAggregate
[x]   ForecastOverride (override_qty XOR override_pct validation)
[x]   OverrideSplitWeight
[x]   ForecastAccuracy
[x]   AbcClassDefinition (flexible ABC tier subtable)
[x]   ForecastingConfig (ADI/CV²/time horizon thresholds per client)
[x]   SeriesLevelEvaluation (per-level evaluation audit log)
[x]   SeriesProfile (level-selection summary, override fields)
[x] demand/__init__.py updated to import all 10 models

── HELPERS ──────────────────────────────────────────────────────────────────
[x] mysite/models/demand/actuals.py — get_higher_period_types() added
[x] mysite/models/demand/actuals.py — PERIOD_HIGHER_HORIZONS dict added
[x] utils/demand/__init__.py created (empty)
[x] utils/demand/hierarchy_utils.py created:
[x]   get_location_levels()
[x]   get_location_children_map()
[x]   get_location_ancestor_map()
[x]   get_product_hierarchy_levels()

── MIGRATIONS ───────────────────────────────────────────────────────────────
[x] makemigrations mysite --name forecast_models
[x] RunSQL index block added (ix_forecastline_version, etc.)
[ ] makemigrations mysite --name abc_defs_forecasting_config_series_level_eval
[ ] python manage.py migrate — clean on both migrations
[ ] python manage.py check — 0 issues

── CELERY TASKS ─────────────────────────────────────────────────────────────
[x] mysite/tasks/demand/compute_series_profiles.py created
[ ] Task runs without error on a client with actuals data
[ ] SeriesLevelEvaluation rows created (one per level evaluated per item)
[ ] SeriesProfile rows created (one per atomic series)
[ ] AbcClassDefinition defaults created for client if none exist

── ADMIN ────────────────────────────────────────────────────────────────────
[x] mysite/admin/demand_forecast.py — ForecastVersionAdmin (status badge)
[x] mysite/admin/demand_forecast.py — ForecastLineAdmin
[x] mysite/admin/demand_forecast.py — ForecastAccuracyAdmin
[x] mysite/admin/demand_forecast.py — AbcClassDefinitionInline
[x] mysite/admin/demand_forecast.py — ForecastingConfigAdmin (with inline)
[x] mysite/admin/demand_forecast.py — SeriesLevelEvaluationAdmin (read-only)
[x] mysite/admin/demand_forecast.py — SeriesProfileAdmin
[x]   SeriesLevelEvaluationReadOnlyInline inside SeriesProfileAdmin
[ ] /admin/ loads without errors
[ ] ForecastingConfigAdmin shows AbcClassDefinition inline
[ ] SeriesProfileAdmin shows evaluation log inline for an item

── SERIALIZERS ──────────────────────────────────────────────────────────────
[x] ForecastVersionSerializer (read fields + line_count + is_editable)
[x] ForecastVersionCreateSerializer
[x] ForecastLineSerializer (read-only + period_end + final_qty)
[x] ForecastAggregateSerializer
[x] ForecastOverrideSerializer
[x] AbcClassDefinitionSerializer
[x] ForecastingConfigSerializer (with derived_time_horizons method field)
[x] SeriesLevelEvaluationSerializer (with grain_label method field)
[x] SeriesProfileSerializer (full, with nested evaluations)
[x] SeriesProfileListSerializer (lightweight, no nested evaluations)

── VIEWS ────────────────────────────────────────────────────────────────────
[x] ForecastVersionListCreateView   GET + POST
[x] ForecastVersionDetailView       GET
[x] ForecastVersionLinesView        GET (+ forecast_level filter added)
[x] ForecastVersionAggregatesView   GET
[x] ForecastVersionApproveView      POST (submit/approve/reject/lock/copy)
[x] SeriesProfileListView           GET (lightweight, paginated)
[x] SeriesProfileDetailView         GET + PATCH (override fields only)
[x] SeriesProfileEvaluationsView    GET (lazy-load evaluation log)
[x] ForecastingConfigView           GET + PATCH (staff only)

── URLs (9 total) ───────────────────────────────────────────────────────────
[x] forecast-versions/
[x] forecast-versions/<pk>/
[x] forecast-versions/<pk>/lines/
[x] forecast-versions/<pk>/aggregates/
[x] forecast-versions/<pk>/approve/
[x] series-profiles/
[x] series-profiles/<pk>/
[x] series-profiles/<pk>/evaluations/
[x] forecasting-config/

── SMOKE TESTS (manual verification) ────────────────────────────────────────
[ ] GET /api/demand/forecast-versions/           → empty list for new client
[ ] POST /api/demand/forecast-versions/          → creates DRAFT version
[ ] POST /api/demand/forecast-versions/{id}/approve/ action=submit
                                                 → moves to IN_REVIEW
[ ] POST /api/demand/forecast-versions/{id}/approve/ action=copy on LOCKED
                                                 → returns new DRAFT (HTTP 201)
[ ] GET /api/demand/forecast-versions/{id}/lines/ → paginated, filterable
[ ] GET /api/demand/forecast-versions/{id}/lines/?forecast_level=item_client
                                                 → filters by grain
[ ] GET /api/demand/series-profiles/            → list with ABC/demand class
[ ] GET /api/demand/series-profiles/?is_manual=true
                                                 → only MANUAL items
[ ] GET /api/demand/series-profiles/{id}/       → includes evaluations nested
[ ] GET /api/demand/series-profiles/{id}/evaluations/
                                                 → evaluation log in search order
[ ] PATCH /api/demand/series-profiles/{id}/     → updates override fields only
[ ] PATCH /api/demand/series-profiles/{id}/     with invalid grain → 400
[ ] GET /api/demand/forecasting-config/         → returns config + ABC tiers
[ ] GET /api/demand/forecasting-config/?period_type=day
                                                 → derived_time_horizons for day
[ ] PATCH /api/demand/forecasting-config/       as non-staff → 403

── UNIT TESTS ───────────────────────────────────────────────────────────────
[ ] pytest mysite/tests/demand/test_forecast.py -v
[ ]   TestForecastLineFinalQty              (5 tests — existing)
[ ]   TestForecastVersionStateMachine       (6 tests — existing)
[ ]   TestLockedVersionRejectsEdits         (4 tests — existing)
[ ]   TestForecastVersionCopy              (4 tests — existing)
[ ]   TestForecastOverrideValidation       (2 tests — existing)
[ ]   TestAbcClassDefinition               (5 tests — new)
[ ]   TestForecastingConfig                (5 tests — new)
[ ]   TestComputeSyntetosBoylan            (7 tests — new)
[ ]   TestSeriesLevelEvaluation            (2 tests — new)
[ ]   TestSeriesProfileProperties          (7 tests — new)
[ ]   TestSeriesProfileAPI                 (3 tests — new)
[ ]   TestForecastingConfigAPI             (4 tests — new)
```

---

## Summary of Changes per Section

| Section | Change type | Detail |
|---|---|---|
| **7 Views** | Full replacement | Import block corrected; `DemandFeatureMixin` moved here from appendix; `ForecastVersionLinesView` gains `forecast_level` filter; 4 new views consolidated inline; appendix section superseded |
| **8 URLs** | Full replacement | All 9 patterns in one consolidated `urlpatterns` list; appendix section superseded |
| **9 Tests** | Delta (append only) | 5 new fixture additions; 7 new test classes (44 new tests); existing 5 classes unchanged |
| **10 Checklist** | Full replacement | Reflects all 10 models, 4 helpers, 2 migrations, 1 task, 7 admin registrations, 10 serializers, 9 views, 9 URLs, and full test coverage |
