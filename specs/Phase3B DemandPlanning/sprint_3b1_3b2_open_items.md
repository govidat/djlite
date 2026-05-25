# Sprint 3B.1 & 3B.2 — Open Items: Detailed Implementation Instructions

**Scope:** REST endpoints, Celery tasks, management command, and unit tests.  
**Stack:** Django REST Framework · Celery · pandas · openpyxl · pytest-django  
**App label:** `mysite`

---

## Table of Contents

1. [Prerequisites and Package Setup](#1-prerequisites)
2. [Sprint 3B.1 — REST Endpoints: Sales & Location Hierarchy](#2-sprint-3b1-rest-endpoints)
3. [Sprint 3B.2 — REST Endpoints: Actuals Upload & Query](#3-sprint-3b2-rest-endpoints)
4. [Sprint 3B.2 — Celery Task: `process_actuals_import`](#4-celery-task-process_actuals_import)
5. [Sprint 3B.2 — Celery Task: `process_summary_actuals_import`](#5-celery-task-process_summary_actuals_import)
6. [Sprint 3B.2 — Management Command: `generate_actuals_template`](#6-management-command-generate_actuals_template)
7. [URL Registration](#7-url-registration)
8. [Unit Tests](#8-unit-tests)

---

## 1. Prerequisites

### 1.1 Confirm DRF is installed

```bash
pip show djangorestframework
```

If missing:

```bash
pip install djangorestframework --break-system-packages
```

Add to `settings.py` if not already present:

```python
INSTALLED_APPS = [
    # ...
    'rest_framework',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
}
```

### 1.2 File layout for new code

```
mysite/
    api/
        demand/
            __init__.py
            serializers.py      ← hierarchy + actuals serializers
            views.py            ← all demand API views
            urls.py             ← demand URL patterns
    tasks/
        demand/
            __init__.py
            import_actuals.py   ← Celery tasks
    management/
        commands/
            generate_actuals_template.py
    tests/
        demand/
            __init__.py
            test_hierarchy_api.py
            test_actuals_import.py
            test_unit_tests.py
```

---

## 2. Sprint 3B.1 — REST Endpoints: Sales & Location Hierarchy

Two read-only endpoints returning the full tree for the authenticated client.

### 2.1 Serializers — `mysite/api/demand/serializers.py`

The tree is recursive: each node may have children. Use a serializer that
references itself via `SerializerMethodField` rather than a direct nested
serializer, which avoids infinite recursion and allows lazy loading.

```python
# mysite/api/demand/serializers.py

from rest_framework import serializers
from mysite.models.demand.hierarchy import (
    PlanningLocation, SalesNode, CustomerSalesAssignment, PlanningCustomer,
)


# ─────────────────────────────────────────────────────────────────────────────
# Planning Location tree
# ─────────────────────────────────────────────────────────────────────────────

class PlanningLocationTreeSerializer(serializers.ModelSerializer):
    """
    Recursive serializer for PlanningLocation.
    children are populated only for root-call nodes; leaves return [].
    The full tree is built in the view by fetching all nodes in one query
    and assembling in Python (avoids N+1).
    """
    children = serializers.SerializerMethodField()

    class Meta:
        model  = PlanningLocation
        fields = [
            'id', 'code', 'name', 'level_label',
            'is_leaf', 'is_active', 'depth', 'path',
            'children',
        ]

    def get_children(self, obj):
        # Children are pre-attached by the view (see build_tree() below)
        children = getattr(obj, '_children', [])
        return PlanningLocationTreeSerializer(children, many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# Sales Node tree
# ─────────────────────────────────────────────────────────────────────────────

class CustomerSalesAssignmentSerializer(serializers.ModelSerializer):
    customer_code = serializers.CharField(
        source='planning_customer.code', read_only=True
    )
    customer_name = serializers.CharField(
        source='planning_customer.name', read_only=True
    )

    class Meta:
        model  = CustomerSalesAssignment
        fields = ['id', 'customer_code', 'customer_name', 'valid_from', 'valid_to']


class SalesNodeTreeSerializer(serializers.ModelSerializer):
    children             = serializers.SerializerMethodField()
    active_assignments   = serializers.SerializerMethodField()
    location_code        = serializers.CharField(
        source='planning_location.code', read_only=True, default=None
    )
    location_name        = serializers.CharField(
        source='planning_location.name', read_only=True, default=None
    )

    class Meta:
        model  = SalesNode
        fields = [
            'id', 'code', 'name', 'level_label', 'is_active',
            'depth', 'path',
            'location_code', 'location_name',
            'active_assignments',
            'children',
        ]

    def get_children(self, obj):
        children = getattr(obj, '_children', [])
        return SalesNodeTreeSerializer(children, many=True).data

    def get_active_assignments(self, obj):
        from django.utils import timezone
        today = timezone.now().date()
        assignments = [
            a for a in getattr(obj, '_assignments', [])
            if a.valid_from <= today and (a.valid_to is None or a.valid_to >= today)
        ]
        return CustomerSalesAssignmentSerializer(assignments, many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# Actuals serializers (used by Sprint 3B.2 endpoints)
# ─────────────────────────────────────────────────────────────────────────────

class ActualSaleImportSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        from mysite.models.demand.actuals import ActualSaleImport
        model  = ActualSaleImport
        fields = [
            'id', 'file_name', 'period_type', 'row_count',
            'status', 'error_log', 'uploaded_at', 'uploaded_by_name',
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.username
        return None


class ActualSaleSerializer(serializers.ModelSerializer):
    item_id           = serializers.CharField(source='item.item_id', read_only=True)
    item_name         = serializers.CharField(source='item.name',    read_only=True)
    location_code     = serializers.CharField(
        source='planning_location.code', read_only=True
    )
    customer_code     = serializers.CharField(
        source='planning_customer.code', read_only=True, default=None
    )

    class Meta:
        from mysite.models.demand.actuals import ActualSale
        model  = ActualSale
        fields = [
            'id',
            'item_id', 'item_name',
            'location_code', 'customer_code',
            'period_type', 'period_start', 'period_end',
            'qty', 'revenue',
        ]
```

### 2.2 Tree-building utility

Both hierarchy endpoints use the same in-Python assembly pattern.
Put this in `mysite/api/demand/views.py` at the top:

```python
def build_tree(nodes, parent_id=None):
    """
    Assemble a flat list of model instances (ordered by path) into a nested
    tree by attaching a `_children` list to each node.

    All nodes are fetched in ONE query; assembly is O(n) in Python.
    Returns the list of root nodes (parent_id=None).

    nodes must be ordered by path so parents always appear before children.
    """
    lookup = {node.pk: node for node in nodes}
    roots  = []

    for node in nodes:
        node._children = []

    for node in nodes:
        if node.parent_id is None:
            roots.append(node)
        else:
            parent = lookup.get(node.parent_id)
            if parent is not None:
                parent._children.append(node)

    return roots
```

### 2.3 Views — hierarchy endpoints

```python
# mysite/api/demand/views.py  (hierarchy section)

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils.translation import gettext_lazy as _

from mysite.models.demand.hierarchy import (
    PlanningLocation, SalesNode, CustomerSalesAssignment,
)
from mysite.api.demand.serializers import (
    PlanningLocationTreeSerializer,
    SalesNodeTreeSerializer,
)
from utils.feature_control import is_demand_feature_disabled


class DemandFeatureMixin:
    """
    Mixin for all demand API views.
    Checks the master demand_planning feature flag before processing.
    Assumes request.client is set by your ClientScopedMixin / middleware.
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
# GET /api/demand/location-hierarchy/
# ─────────────────────────────────────────────────────────────────────────────

class PlanningLocationHierarchyView(DemandFeatureMixin, APIView):
    """
    Returns the full PlanningLocation tree for the authenticated client.

    Query params:
        active_only=true   (default: true) — exclude is_active=False nodes
        leaves_only=false  — return only leaf nodes (flat list, no nesting)

    Response shape:
        [
            {
                "id": 1, "code": "NORTH", "name": "North Region",
                "level_label": "Region", "is_leaf": false,
                "is_active": true, "depth": 0, "path": "1/",
                "children": [
                    {
                        "id": 3, "code": "DEL", "name": "Delhi Branch",
                        "level_label": "Branch", "is_leaf": true,
                        "is_active": true, "depth": 1, "path": "1/3/",
                        "children": []
                    }
                ]
            },
            ...
        ]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client      = request.client
        active_only = request.query_params.get('active_only', 'true') == 'true'
        leaves_only = request.query_params.get('leaves_only', 'false') == 'true'

        qs = PlanningLocation.objects.filter(client=client).order_by('path')
        if active_only:
            qs = qs.filter(is_active=True)
        if leaves_only:
            qs = qs.filter(is_leaf=True)
            # For leaves_only, return flat list — no nesting needed
            serializer = PlanningLocationTreeSerializer(qs, many=True)
            return Response(serializer.data)

        nodes = list(qs)
        roots = build_tree(nodes)
        serializer = PlanningLocationTreeSerializer(roots, many=True)
        return Response(serializer.data)


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/demand/sales-hierarchy/
# ─────────────────────────────────────────────────────────────────────────────

class SalesHierarchyView(DemandFeatureMixin, APIView):
    """
    Returns the full SalesNode tree for the authenticated client,
    with active CustomerSalesAssignments attached to each leaf node.

    Query params:
        active_only=true  (default: true) — exclude is_active=False nodes
        with_assignments=true (default: true) — include customer assignments

    Response shape:
        [
            {
                "id": 1, "code": "NSM", "name": "National Sales Manager",
                "level_label": "National", "is_active": true,
                "depth": 0, "path": "1/",
                "location_code": null, "location_name": null,
                "active_assignments": [],
                "children": [
                    {
                        "id": 4, "code": "REP-MUM-01",
                        "name": "Mumbai Rep 1",
                        "level_label": "Sales Rep",
                        "depth": 2, "path": "1/2/4/",
                        "active_assignments": [
                            {
                                "customer_code": "CUST-001",
                                "customer_name": "Acme Pvt Ltd",
                                "valid_from": "2024-01-01",
                                "valid_to": null
                            }
                        ],
                        "children": []
                    }
                ]
            }
        ]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client           = request.client
        active_only      = request.query_params.get('active_only', 'true') == 'true'
        with_assignments = request.query_params.get('with_assignments', 'true') == 'true'

        qs = SalesNode.objects.filter(client=client).order_by('path')
        if active_only:
            qs = qs.filter(is_active=True)

        nodes = list(qs)

        # Pre-fetch all assignments in ONE query and attach to nodes
        if with_assignments:
            node_ids    = [n.pk for n in nodes]
            assignments = (
                CustomerSalesAssignment.objects
                .filter(sales_node_id__in=node_ids)
                .select_related('planning_customer')
                .order_by('planning_customer__code')
            )
            # Group assignments by sales_node_id
            assignment_map = {}
            for a in assignments:
                assignment_map.setdefault(a.sales_node_id, []).append(a)

            for node in nodes:
                node._assignments = assignment_map.get(node.pk, [])
        else:
            for node in nodes:
                node._assignments = []

        roots = build_tree(nodes)
        serializer = SalesNodeTreeSerializer(roots, many=True)
        return Response(serializer.data)
```

### 2.4 URL patterns — `mysite/api/demand/urls.py`

```python
# mysite/api/demand/urls.py

from django.urls import path
from mysite.api.demand import views

urlpatterns = [
    # ── Hierarchy ──────────────────────────────────────────────────────────
    path(
        'location-hierarchy/',
        views.PlanningLocationHierarchyView.as_view(),
        name='demand-location-hierarchy',
    ),
    path(
        'sales-hierarchy/',
        views.SalesHierarchyView.as_view(),
        name='demand-sales-hierarchy',
    ),

    # ── Actuals (Sprint 3B.2) ──────────────────────────────────────────────
    path(
        'actuals/upload/',
        views.ActualsUploadView.as_view(),
        name='demand-actuals-upload',
    ),
    path(
        'actuals/upload/<int:pk>/',
        views.ActualsUploadStatusView.as_view(),
        name='demand-actuals-upload-status',
    ),
    path(
        'actuals/',
        views.ActualsQueryView.as_view(),
        name='demand-actuals-query',
    ),
]
```

---

## 3. Sprint 3B.2 — REST Endpoints: Actuals Upload & Query

### 3.1 `POST /api/demand/actuals/upload/`

Accepts a multipart file upload, validates the file type, creates an
`ActualSaleImport` record, fires the Celery task, and returns immediately
with the import job ID. The client polls `/actuals/upload/{id}/` for status.

```python
# mysite/api/demand/views.py  (actuals section — append below hierarchy views)

import os
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from mysite.models.demand.actuals import ActualSale, ActualSaleImport
from mysite.api.demand.serializers import (
    ActualSaleImportSerializer,
    ActualSaleSerializer,
)


ALLOWED_EXTENSIONS = {'.csv', '.xlsx', '.xls'}


class ActualsUploadView(DemandFeatureMixin, APIView):
    """
    POST /api/demand/actuals/upload/

    Multipart body:
        file        required  — .csv or .xlsx
        period_type required  — one of: day/week/month/quarter/halfyear/year
        notes       optional  — free-text description of this upload

    Response 202:
        {
            "import_id": 42,
            "status": "pending",
            "poll_url": "/api/demand/actuals/upload/42/"
        }

    Response 400: validation errors (wrong file type, missing period_type)
    Response 403: feature disabled
    """
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        # ── Feature gate ──────────────────────────────────────────────────
        result = is_demand_feature_disabled(request.client, 'actuals_upload')
        if result['disabled']:
            return Response(
                {'detail': result['message']},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Validate file ─────────────────────────────────────────────────
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response(
                {'file': 'This field is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            return Response(
                {'file': f'Unsupported file type "{ext}". Allowed: {", ".join(ALLOWED_EXTENSIONS)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate period_type ──────────────────────────────────────────
        from mysite.models.demand.actuals import PERIOD_TYPE_CHOICES
        valid_period_types = [k for k, _ in PERIOD_TYPE_CHOICES]
        period_type = request.data.get('period_type', '').strip()
        if period_type not in valid_period_types:
            return Response(
                {'period_type': f'Must be one of: {", ".join(valid_period_types)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Save the file to a temp/upload location ───────────────────────
        # Use Django's default storage or a dedicated upload dir.
        # Here we use Django's default storage so the path is portable.
        from django.core.files.storage import default_storage
        save_path = default_storage.save(
            f'demand/actuals_imports/{uploaded_file.name}',
            uploaded_file,
        )

        # ── Create import job ─────────────────────────────────────────────
        import_job = ActualSaleImport.objects.create(
            client      = request.client,
            uploaded_by = request.user,
            file_name   = save_path,
            period_type = period_type,
            status      = 'pending',
        )

        # ── Fire Celery task ──────────────────────────────────────────────
        from mysite.tasks.demand.import_actuals import process_actuals_import
        process_actuals_import.delay(import_job.pk)

        return Response(
            {
                'import_id': import_job.pk,
                'status':    'pending',
                'poll_url':  f'/api/demand/actuals/upload/{import_job.pk}/',
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ActualsUploadStatusView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/actuals/upload/{id}/

    Poll the status of an import job.

    Response 200:
        {
            "id": 42,
            "file_name": "demand/actuals_imports/upload.xlsx",
            "period_type": "month",
            "row_count": 480,
            "status": "done",          // pending | processing | done | failed
            "error_log": "",
            "uploaded_at": "2025-01-15T10:30:00Z",
            "uploaded_by_name": "Govind K"
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            job = ActualSaleImport.objects.get(pk=pk, client=request.client)
        except ActualSaleImport.DoesNotExist:
            return Response(
                {'detail': 'Import job not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(ActualSaleImportSerializer(job).data)


class ActualsQueryView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/actuals/

    Query actuals for the authenticated client.

    Query params (all optional):
        item_id         — filter by Item.item_id (exact)
        location_code   — filter by PlanningLocation.code (exact)
        customer_code   — filter by PlanningCustomer.code (exact)
        period_type     — filter by period type
        period_start    — ISO date, filter period_start >= this date
        period_end      — ISO date, filter period_end <= this date
        page            — page number (default 1)
        page_size       — results per page (default 100, max 1000)

    Response 200:
        {
            "count": 480,
            "next": "/api/demand/actuals/?page=2",
            "previous": null,
            "results": [ { ...ActualSale fields... }, ... ]
        }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import datetime
        from django.core.paginator import Paginator, EmptyPage

        qs = (
            ActualSale.objects
            .filter(client=request.client)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by('period_start', 'planning_location__code', 'item__item_id')
        )

        # ── Filters ───────────────────────────────────────────────────────
        p = request.query_params

        if p.get('item_id'):
            qs = qs.filter(item__item_id=p['item_id'])

        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])

        if p.get('customer_code'):
            qs = qs.filter(planning_customer__code=p['customer_code'])

        if p.get('period_type'):
            qs = qs.filter(period_type=p['period_type'])

        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                return Response(
                    {'period_start': 'Invalid date format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                return Response(
                    {'period_end': 'Invalid date format. Use YYYY-MM-DD.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── Pagination ────────────────────────────────────────────────────
        try:
            page_size = min(int(p.get('page_size', 100)), 1000)
            page_num  = int(p.get('page', 1))
        except ValueError:
            page_size, page_num = 100, 1

        paginator = Paginator(qs, page_size)
        try:
            page = paginator.page(page_num)
        except EmptyPage:
            page = paginator.page(paginator.num_pages)

        serializer = ActualSaleSerializer(page.object_list, many=True)

        return Response({
            'count':    paginator.count,
            'next':     self._build_page_url(request, page_num + 1, paginator.num_pages),
            'previous': self._build_page_url(request, page_num - 1, paginator.num_pages),
            'results':  serializer.data,
        })

    def _build_page_url(self, request, page_num, num_pages):
        if page_num < 1 or page_num > num_pages:
            return None
        params = request.query_params.copy()
        params['page'] = page_num
        return request.build_absolute_uri(f'?{params.urlencode()}')
```

---

## 4. Celery Task: `process_actuals_import`

This is the core of Sprint 3B.2. The task:

1. Reads the uploaded file (CSV or Excel) with pandas
2. Resolves all FK columns (item_id → Item.pk, location_code → PlanningLocation.pk, etc.)
3. Validates each row, collecting errors without aborting
4. Bulk-upserts valid rows using `bulk_create(update_conflicts=True)`
5. Updates `ActualSaleImport` with final status and row counts

### 4.1 Expected column headers in the upload file

```
period_start    YYYY-MM-DD   required
item_id         string       required — must match Item.item_id for this client
location_code   string       required — must match PlanningLocation.code
customer_code   string       optional — blank = unattributed (planning_customer=NULL)
qty             decimal      required
revenue         decimal      optional
```

`period_type` is NOT a column in the file — it is specified at upload time
(as a `POST` parameter) and applies to all rows in the file.

### 4.2 Task code

```python
# mysite/tasks/demand/import_actuals.py

import logging
import datetime
import traceback
from decimal import Decimal, InvalidOperation

import pandas as pd
from celery import shared_task
from django.db import transaction

from mysite.models.demand.actuals import (
    ActualSale, ActualSaleImport,
    PERIOD_TYPE_CHOICES, PERIOD_FREQ_MAP,
    compute_period_end, validate_period_start,
)
from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer
from mysite.models import Item   # adjust import path to match your project

logger = logging.getLogger(__name__)

# ── Column spec ───────────────────────────────────────────────────────────────
REQUIRED_COLUMNS = {'period_start', 'item_id', 'location_code', 'qty'}
OPTIONAL_COLUMNS = {'customer_code', 'revenue'}
ALL_COLUMNS      = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

# ── Batch size for bulk_create ────────────────────────────────────────────────
BATCH_SIZE = 500


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_actuals_import(self, import_id: int):
    """
    Parse an uploaded actuals file and upsert rows into ActualSale.

    Called by: ActualsUploadView after creating the ActualSaleImport record.
    The file path is stored in ActualSaleImport.file_name.

    Error handling strategy:
      - Row-level errors (bad date, missing FK, invalid qty) are collected
        into ActualSaleImport.error_log. Other rows continue to be processed.
      - File-level errors (file unreadable, missing columns) abort immediately
        and set status='failed'.
      - On task exception, the import is marked failed and the exception is
        re-raised so Celery can retry per max_retries.
    """
    job = None
    try:
        job = ActualSaleImport.objects.get(pk=import_id)
    except ActualSaleImport.DoesNotExist:
        logger.error(f"process_actuals_import: import_id={import_id} not found")
        return

    job.status = 'processing'
    job.save(update_fields=['status'])

    try:
        _run_import(job)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = (job.error_log or '') + f"\n\nFATAL: {traceback.format_exc()}"
        job.save(update_fields=['status', 'error_log'])
        logger.exception(f"process_actuals_import: fatal error on import_id={import_id}")
        raise self.retry(exc=exc)


def _run_import(job: ActualSaleImport):
    """
    Core import logic, separated from the Celery task boilerplate
    so it can be called directly in tests.
    """
    from django.core.files.storage import default_storage

    client      = job.client
    period_type = job.period_type
    errors      = []

    # ── 1. Read file ──────────────────────────────────────────────────────────
    file_path = job.file_name
    try:
        with default_storage.open(file_path, 'rb') as f:
            raw = f.read()
    except FileNotFoundError:
        job.status    = 'failed'
        job.error_log = f"File not found at storage path: {file_path}"
        job.save(update_fields=['status', 'error_log'])
        return

    try:
        if file_path.endswith('.csv'):
            df = pd.read_csv(
                __import__('io').BytesIO(raw),
                dtype=str,           # read everything as string first
                keep_default_na=False,
            )
        else:
            df = pd.read_excel(
                __import__('io').BytesIO(raw),
                dtype=str,
                keep_default_na=False,
            )
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = f"Could not parse file: {exc}"
        job.save(update_fields=['status', 'error_log'])
        return

    # ── 2. Validate columns ───────────────────────────────────────────────────
    df.columns = [c.strip().lower() for c in df.columns]
    missing_cols = REQUIRED_COLUMNS - set(df.columns)
    if missing_cols:
        job.status    = 'failed'
        job.error_log = f"Missing required columns: {', '.join(sorted(missing_cols))}"
        job.save(update_fields=['status', 'error_log'])
        return

    df = df.fillna('')
    total_rows = len(df)

    # ── 3. Build FK lookup maps (one query each) ──────────────────────────────
    # Fetch all active items for this client indexed by item_id
    item_map = {
        item.item_id: item
        for item in Item.objects.filter(client=client, status='active')
    }
    # Fetch all active planning locations indexed by code
    location_map = {
        loc.code: loc
        for loc in PlanningLocation.objects.filter(client=client, is_active=True)
    }
    # Fetch all active planning customers indexed by code
    customer_map = {
        cust.code: cust
        for cust in PlanningCustomer.objects.filter(client=client, is_active=True)
    }

    # ── 4. Parse and validate each row ───────────────────────────────────────
    valid_records = []

    for row_num, row in df.iterrows():
        row_errors = []
        excel_row  = row_num + 2  # 1-based, +1 for header

        # period_start
        period_start_raw = str(row.get('period_start', '')).strip()
        period_start = None
        try:
            period_start = datetime.date.fromisoformat(period_start_raw)
            validate_period_start(period_start, period_type)
        except ValueError as exc:
            row_errors.append(f"period_start: {exc}")

        # item
        item_id_raw = str(row.get('item_id', '')).strip()
        item = item_map.get(item_id_raw)
        if not item:
            row_errors.append(f"item_id '{item_id_raw}': not found or inactive")

        # location
        location_code_raw = str(row.get('location_code', '')).strip()
        location = location_map.get(location_code_raw)
        if not location:
            row_errors.append(f"location_code '{location_code_raw}': not found or inactive")

        # customer (optional)
        customer_code_raw = str(row.get('customer_code', '')).strip()
        customer = None
        if customer_code_raw:
            customer = customer_map.get(customer_code_raw)
            if not customer:
                row_errors.append(
                    f"customer_code '{customer_code_raw}': not found or inactive"
                )

        # qty
        qty_raw = str(row.get('qty', '')).strip()
        qty = None
        try:
            qty = Decimal(qty_raw)
            if qty < 0:
                raise ValueError("qty cannot be negative")
        except (InvalidOperation, ValueError) as exc:
            row_errors.append(f"qty '{qty_raw}': {exc}")

        # revenue (optional)
        revenue_raw = str(row.get('revenue', '')).strip()
        revenue = None
        if revenue_raw:
            try:
                revenue = Decimal(revenue_raw)
            except InvalidOperation:
                row_errors.append(f"revenue '{revenue_raw}': not a valid decimal")

        if row_errors:
            errors.append(f"Row {excel_row}: {'; '.join(row_errors)}")
            continue

        # Compute period_end
        period_end = compute_period_end(period_start, period_type)

        valid_records.append(
            ActualSale(
                client            = client,
                item              = item,
                planning_location = location,
                planning_customer = customer,
                period_type       = period_type,
                period_start      = period_start,
                period_end        = period_end,
                qty               = qty,
                revenue           = revenue,
                import_batch      = job,
            )
        )

    # ── 5. Bulk upsert in batches ─────────────────────────────────────────────
    # update_conflicts=True makes this idempotent:
    # re-uploading the same file updates qty/revenue rather than failing
    # on the unique_together constraint.
    update_fields = ['qty', 'revenue', 'import_batch']
    unique_fields = [
        'client', 'planning_location', 'item',
        'planning_customer', 'period_type', 'period_start',
    ]

    inserted_count = 0
    with transaction.atomic():
        for i in range(0, len(valid_records), BATCH_SIZE):
            batch = valid_records[i : i + BATCH_SIZE]
            result = ActualSale.objects.bulk_create(
                batch,
                update_conflicts = True,
                unique_fields    = unique_fields,
                update_fields    = update_fields,
            )
            inserted_count += len(result)

    # ── 6. Finalise the import job ────────────────────────────────────────────
    job.row_count = inserted_count
    job.status    = 'done' if not errors else 'done'
    # Always mark done even with row-level errors — partial imports are valid.
    # Errors are inspectable in error_log. Use 'failed' only for fatal errors.
    job.error_log = '\n'.join(errors) if errors else ''
    job.save(update_fields=['row_count', 'status', 'error_log'])

    logger.info(
        f"process_actuals_import: import_id={job.pk} done. "
        f"total={total_rows} valid={inserted_count} errors={len(errors)}"
    )
```

> **Note on `bulk_create(update_conflicts=True)`:** This is available from
> Django 4.1+ on PostgreSQL. The `unique_fields` argument must exactly match
> the columns in the `unique_together` constraint. Since `planning_customer`
> is nullable, Postgres treats NULLs as distinct in unique constraints by
> default — you may need a partial unique index for the null case. See
> Section 4.3 below.

### 4.3 Handling NULL `planning_customer` in the upsert

PostgreSQL's standard unique constraint treats `NULL != NULL`, so two rows
with `planning_customer=NULL` for the same `(client, location, item, period)`
would both insert rather than conflict. Fix this with a partial unique index
added via `RunSQL` in the migration:

```python
# Add to your actuals migration's operations list:
migrations.RunSQL(
    sql="""
        -- Unique index for rows WITH a customer (standard behaviour)
        CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_with_customer
            ON mysite_actualsale (
                client_id, planning_location_id, item_id,
                planning_customer_id, period_type, period_start
            )
            WHERE planning_customer_id IS NOT NULL;

        -- Unique index for rows WITHOUT a customer (handles NULL)
        CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_no_customer
            ON mysite_actualsale (
                client_id, planning_location_id, item_id,
                period_type, period_start
            )
            WHERE planning_customer_id IS NULL;
    """,
    reverse_sql="""
        DROP INDEX IF EXISTS uq_actualsale_with_customer;
        DROP INDEX IF EXISTS uq_actualsale_no_customer;
    """,
)
```

Remove the Django-level `unique_together` from `ActualSale.Meta` once these
two partial indexes are in place — they replace it. Django's
`bulk_create(update_conflicts=True)` on PostgreSQL will use whichever index
matches each row's `planning_customer_id` value.

---

## 5. Celery Task: `process_summary_actuals_import`

This task handles location-level summary uploads (no customer, no item
breakdown — just total qty and revenue per location per period). It writes
to a separate `ActualSaleLocation` summary table rather than `ActualSale`.

### 5.1 `ActualSaleLocation` model

Add this to `mysite/models/demand/actuals.py` below `ActualSale`:

```python
class ActualSaleLocation(models.Model):
    """
    Location-level summary actuals. One row per (client, location, period).

    Populated either:
      a) By direct upload via process_summary_actuals_import, or
      b) By aggregating ActualSale rows (via a Celery rollup task in 3B.3).

    Used as a consistency check: if the sum of ActualSale.qty for a
    location × period does not match ActualSaleLocation.total_qty,
    the data has gaps.
    """
    client            = models.ForeignKey(
        "mysite.Client", on_delete=models.CASCADE,
        related_name="actual_sale_locations",
    )
    planning_location = models.ForeignKey(
        PlanningLocation, on_delete=models.PROTECT,
        related_name="actual_sale_locations",
        verbose_name=_("planning location"),
    )
    period_type  = models.CharField(
        _("period type"), max_length=16, choices=PERIOD_TYPE_CHOICES,
    )
    period_start = models.DateField(_("period start"))
    period_end   = models.DateField(_("period end"), editable=False)
    total_qty    = models.DecimalField(
        _("total quantity"), max_digits=16, decimal_places=3,
    )
    total_revenue = models.DecimalField(
        _("total revenue"), max_digits=18, decimal_places=2,
        null=True, blank=True,
    )
    import_batch  = models.ForeignKey(
        ActualSaleImport, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="summary_actuals",
    )

    class Meta:
        app_label     = "mysite"
        unique_together = [
            ("client", "planning_location", "period_type", "period_start"),
        ]
        ordering      = ["period_type", "period_start", "planning_location"]
        verbose_name  = _("02-06 Actual Sale Location")
        verbose_name_plural = _("02-06 Actual Sale Locations")
        indexes = [
            models.Index(
                fields=["client", "planning_location", "period_type", "period_start"],
                name="ix_actualsaleloc_period",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.period_type and self.period_start:
            self.period_end = compute_period_end(self.period_start, self.period_type)
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.period_type}:{self.period_start} | "
            f"{self.planning_location} | qty={self.total_qty}"
        )
```

### 5.2 Summary import file columns

```
period_start    YYYY-MM-DD   required
location_code   string       required
total_qty       decimal      required
total_revenue   decimal      optional
```

### 5.3 Task code

```python
# mysite/tasks/demand/import_actuals.py  (append below process_actuals_import)

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_summary_actuals_import(self, import_id: int):
    """
    Parse a location-summary actuals file and upsert into ActualSaleLocation.
    Same file-handling and error-collection pattern as process_actuals_import.
    """
    from mysite.models.demand.actuals import ActualSaleLocation

    job = None
    try:
        job = ActualSaleImport.objects.get(pk=import_id)
    except ActualSaleImport.DoesNotExist:
        logger.error(f"process_summary_actuals_import: import_id={import_id} not found")
        return

    job.status = 'processing'
    job.save(update_fields=['status'])

    try:
        _run_summary_import(job)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = (job.error_log or '') + f"\n\nFATAL: {traceback.format_exc()}"
        job.save(update_fields=['status', 'error_log'])
        raise self.retry(exc=exc)


def _run_summary_import(job: ActualSaleImport):
    from django.core.files.storage import default_storage
    from mysite.models.demand.actuals import ActualSaleLocation

    client      = job.client
    period_type = job.period_type
    errors      = []

    # Read file (identical to _run_import)
    try:
        with default_storage.open(job.file_name, 'rb') as f:
            raw = f.read()
        if job.file_name.endswith('.csv'):
            df = pd.read_csv(__import__('io').BytesIO(raw), dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(__import__('io').BytesIO(raw), dtype=str, keep_default_na=False)
    except Exception as exc:
        job.status    = 'failed'
        job.error_log = str(exc)
        job.save(update_fields=['status', 'error_log'])
        return

    df.columns = [c.strip().lower() for c in df.columns]
    required   = {'period_start', 'location_code', 'total_qty'}
    missing    = required - set(df.columns)
    if missing:
        job.status    = 'failed'
        job.error_log = f"Missing columns: {', '.join(sorted(missing))}"
        job.save(update_fields=['status', 'error_log'])
        return

    df = df.fillna('')

    location_map = {
        loc.code: loc
        for loc in PlanningLocation.objects.filter(client=client, is_active=True)
    }

    valid_records = []

    for row_num, row in df.iterrows():
        row_errors = []
        excel_row  = row_num + 2

        period_start_raw = str(row.get('period_start', '')).strip()
        period_start = None
        try:
            period_start = datetime.date.fromisoformat(period_start_raw)
            validate_period_start(period_start, period_type)
        except ValueError as exc:
            row_errors.append(f"period_start: {exc}")

        location_code_raw = str(row.get('location_code', '')).strip()
        location = location_map.get(location_code_raw)
        if not location:
            row_errors.append(f"location_code '{location_code_raw}': not found")

        total_qty_raw = str(row.get('total_qty', '')).strip()
        total_qty = None
        try:
            total_qty = Decimal(total_qty_raw)
        except InvalidOperation:
            row_errors.append(f"total_qty '{total_qty_raw}': invalid decimal")

        total_revenue_raw = str(row.get('total_revenue', '')).strip()
        total_revenue = None
        if total_revenue_raw:
            try:
                total_revenue = Decimal(total_revenue_raw)
            except InvalidOperation:
                row_errors.append(f"total_revenue '{total_revenue_raw}': invalid decimal")

        if row_errors:
            errors.append(f"Row {excel_row}: {'; '.join(row_errors)}")
            continue

        period_end = compute_period_end(period_start, period_type)

        valid_records.append(
            ActualSaleLocation(
                client            = client,
                planning_location = location,
                period_type       = period_type,
                period_start      = period_start,
                period_end        = period_end,
                total_qty         = total_qty,
                total_revenue     = total_revenue,
                import_batch      = job,
            )
        )

    with transaction.atomic():
        for i in range(0, len(valid_records), BATCH_SIZE):
            batch = valid_records[i : i + BATCH_SIZE]
            ActualSaleLocation.objects.bulk_create(
                batch,
                update_conflicts = True,
                unique_fields    = [
                    'client', 'planning_location', 'period_type', 'period_start'
                ],
                update_fields    = ['total_qty', 'total_revenue', 'import_batch'],
            )

    job.row_count = len(valid_records)
    job.status    = 'done'
    job.error_log = '\n'.join(errors)
    job.save(update_fields=['row_count', 'status', 'error_log'])
```

---

## 6. Management Command: `generate_actuals_template`

Produces a ready-to-use `.xlsx` file clients can download, fill in,
and upload via the API. Includes a column-header row, data-validation
dropdowns for `period_type` choices, and example data rows.

```python
# mysite/management/commands/generate_actuals_template.py

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from mysite.models.demand.actuals import PERIOD_TYPE_CHOICES, PERIOD_FREQ_MAP


HEADER_FILL  = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT  = Font(color="FFFFFF", bold=True, size=11)
EXAMPLE_FILL = PatternFill("solid", fgColor="EBF3FB")
LOCKED_FILL  = PatternFill("solid", fgColor="D9D9D9")


class Command(BaseCommand):
    help = (
        "Generate an .xlsx actuals upload template for a given client.\n"
        "Usage: python manage.py generate_actuals_template "
        "--client <client_id> [--type <period_type>] [--out <path>]"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--client', required=True,
            help="client_id of the client to generate the template for."
        )
        parser.add_argument(
            '--type', dest='period_type', default='month',
            choices=[k for k, _ in PERIOD_TYPE_CHOICES],
            help="Period type to pre-fill (default: month)."
        )
        parser.add_argument(
            '--out', dest='output_path', default=None,
            help="Output file path. Default: actuals_template_<client>_<type>.xlsx"
        )
        parser.add_argument(
            '--examples', type=int, default=3,
            help="Number of example rows to include (default: 3)."
        )

    def handle(self, *args, **options):
        from mysite.models import Client, Item
        from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer

        client_id   = options['client']
        period_type = options['period_type']
        output_path = options['output_path'] or (
            f"actuals_template_{client_id}_{period_type}.xlsx"
        )
        n_examples  = options['examples']

        # Resolve client
        try:
            client = Client.objects.get(client_id=client_id)
        except Client.DoesNotExist:
            raise CommandError(f"Client '{client_id}' not found.")

        # Fetch sample items, locations, customers for the example rows
        sample_items     = list(
            Item.objects.filter(client=client, status='active')
            .values_list('item_id', flat=True)[:n_examples]
        )
        sample_locations = list(
            PlanningLocation.objects.filter(client=client, is_active=True, is_leaf=True)
            .values_list('code', flat=True)[:n_examples]
        )
        sample_customers = list(
            PlanningCustomer.objects.filter(client=client, is_active=True)
            .values_list('code', flat=True)[:n_examples]
        ) + ['']   # include blank to show optional

        # ── Build workbook ────────────────────────────────────────────────────
        wb = openpyxl.Workbook()

        # ── Sheet 1: Data entry sheet ─────────────────────────────────────────
        ws = wb.active
        ws.title = "Actuals Upload"

        # Column definitions: (header, width, example_value, note)
        columns = [
            ("period_start",   18, self._example_period_start(period_type),
             "First day of the period bucket. Format: YYYY-MM-DD"),
            ("item_id",        24, sample_items[0] if sample_items else "ITEM-001",
             "Item identifier. Must be an active item for this client."),
            ("location_code",  20, sample_locations[0] if sample_locations else "LOC-001",
             "Planning location code. Must be an active leaf location."),
            ("customer_code",  20, sample_customers[0] if sample_customers else "",
             "Optional. Leave blank for unattributed demand."),
            ("qty",            14, "100",
             "Sales quantity in base UoM. Must be >= 0."),
            ("revenue",        16, "15000.00",
             "Optional. Revenue in client base currency."),
        ]

        # Write header row
        for col_idx, (col_name, width, _, _note) in enumerate(columns, start=1):
            cell               = ws.cell(row=1, column=col_idx, value=col_name)
            cell.font          = HEADER_FONT
            cell.fill          = HEADER_FILL
            cell.alignment     = Alignment(horizontal='center', vertical='center')
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        ws.row_dimensions[1].height = 22

        # Write example rows
        for ex_row in range(n_examples):
            row_idx = ex_row + 2
            row_vals = [
                self._example_period_start(period_type, offset=ex_row),
                sample_items[ex_row % len(sample_items)] if sample_items else f"ITEM-00{ex_row+1}",
                sample_locations[ex_row % len(sample_locations)] if sample_locations else f"LOC-00{ex_row+1}",
                sample_customers[ex_row % len(sample_customers)],
                str((ex_row + 1) * 100),
                str((ex_row + 1) * 15000),
            ]
            for col_idx, val in enumerate(row_vals, start=1):
                cell       = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.fill  = EXAMPLE_FILL

        # Freeze header row
        ws.freeze_panes = "A2"

        # ── Sheet 2: Notes / Instructions ─────────────────────────────────────
        ws_notes = wb.create_sheet("Instructions")
        instructions = [
            ("Actuals Upload Template", True),
            ("", False),
            (f"Client:      {client.client_id}", False),
            (f"Period Type: {period_type}", False),
            (f"Generated:   {timezone.now():%Y-%m-%d %H:%M}", False),
            ("", False),
            ("COLUMN GUIDE", True),
            ("period_start  — YYYY-MM-DD. Must be the first day of a valid bucket.", False),
        ]
        if period_type == 'month':
            instructions.append(
                ("               Example: 2024-01-01 for January 2024.", False)
            )
        elif period_type == 'quarter':
            instructions.append(
                ("               Example: 2024-01-01 (Q1), 2024-04-01 (Q2).", False)
            )
        elif period_type == 'week':
            instructions.append(
                ("               Must be a Monday. Example: 2024-01-01.", False)
            )
        instructions += [
            ("item_id       — Must match an active item for this client.", False),
            ("location_code — Must match an active leaf planning location.", False),
            ("customer_code — Optional. Leave blank for unattributed demand.", False),
            ("qty           — Decimal number >= 0. Required.", False),
            ("revenue       — Decimal number. Optional.", False),
            ("", False),
            ("RULES", True),
            ("1. Do not change column headers.", False),
            ("2. Delete example rows before uploading.", False),
            ("3. Uploading the same file twice updates (not duplicates) existing rows.", False),
            ("4. Rows with errors are skipped; other rows are still imported.", False),
            ("5. Check the import status API for row-level error details.", False),
        ]

        for row_idx, (text, is_heading) in enumerate(instructions, start=1):
            cell = ws_notes.cell(row=row_idx, column=1, value=text)
            if is_heading:
                cell.font = Font(bold=True, size=12)
        ws_notes.column_dimensions['A'].width = 75

        # ── Sheet 3: Valid reference values ───────────────────────────────────
        ws_ref = wb.create_sheet("Reference Values")

        ref_cols = [
            ("Valid Item IDs",
             list(Item.objects.filter(client=client, status='active')
                  .values_list('item_id', flat=True)[:200])),
            ("Valid Location Codes",
             list(PlanningLocation.objects.filter(client=client, is_active=True, is_leaf=True)
                  .values_list('code', flat=True)[:200])),
            ("Valid Customer Codes (optional)",
             list(PlanningCustomer.objects.filter(client=client, is_active=True)
                  .values_list('code', flat=True)[:200])),
        ]

        for col_idx, (heading, values) in enumerate(ref_cols, start=1):
            cell       = ws_ref.cell(row=1, column=col_idx, value=heading)
            cell.font  = Font(bold=True)
            cell.fill  = HEADER_FILL
            cell.font  = HEADER_FONT
            ws_ref.column_dimensions[get_column_letter(col_idx)].width = 30
            for row_idx, val in enumerate(values, start=2):
                ws_ref.cell(row=row_idx, column=col_idx, value=val)

        # ── Save ──────────────────────────────────────────────────────────────
        wb.save(output_path)
        self.stdout.write(
            self.style.SUCCESS(f"Template written to: {output_path}")
        )

    def _example_period_start(self, period_type: str, offset: int = 0) -> str:
        """Return an example period_start string for the given period_type."""
        import datetime
        from dateutil.relativedelta import relativedelta
        base = datetime.date(2025, 1, 1)  # always use a clean anchor
        if period_type == 'week':
            d = base + datetime.timedelta(weeks=offset)
        elif period_type == 'month':
            d = base + relativedelta(months=offset)
        elif period_type == 'bimonth':
            d = base + relativedelta(months=offset * 2)
        elif period_type == 'quarter':
            d = base + relativedelta(months=offset * 3)
        elif period_type == 'halfyear':
            d = base + relativedelta(months=offset * 6)
        elif period_type == 'year':
            d = base + relativedelta(years=offset)
        else:
            d = base + datetime.timedelta(days=offset)
        return d.isoformat()
```

**Usage:**

```bash
# Generate template for client 'acme' with monthly periods
python manage.py generate_actuals_template --client acme --type month

# Generate template for quarterly periods, custom output path
python manage.py generate_actuals_template --client acme --type quarter --out /tmp/acme_q.xlsx

# Include 5 example rows
python manage.py generate_actuals_template --client acme --type month --examples 5
```

---

## 7. URL Registration

### 7.1 Wire demand URLs into the project

In your main `urls.py` (or your client-scoped URL config):

```python
# urls.py

from django.urls import path, include

urlpatterns = [
    # ... existing URLs ...
    path(
        'api/demand/',
        include('mysite.api.demand.urls'),
    ),
]
```

### 7.2 Add download URL for the template

The management command writes to disk. If you want planners to download the
template via the browser rather than a manual file share, add a simple view:

```python
# mysite/api/demand/urls.py — add this entry:

path(
    'actuals/template/',
    views.ActualsTemplateDownloadView.as_view(),
    name='demand-actuals-template',
),
```

```python
# mysite/api/demand/views.py — add:

import subprocess
import tempfile
import os
from django.http import FileResponse

class ActualsTemplateDownloadView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/actuals/template/?period_type=month

    Generates and streams the .xlsx template for the authenticated client.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        period_type = request.query_params.get('period_type', 'month')
        from mysite.models.demand.actuals import PERIOD_TYPE_CHOICES
        if period_type not in [k for k, _ in PERIOD_TYPE_CHOICES]:
            return Response(
                {'period_type': 'Invalid value.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client    = request.client
        tmp_path  = tempfile.mktemp(suffix='.xlsx')

        from django.core.management import call_command
        call_command(
            'generate_actuals_template',
            client=client.client_id,
            period_type=period_type,
            output_path=tmp_path,
        )

        response = FileResponse(
            open(tmp_path, 'rb'),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="actuals_template_{client.client_id}_{period_type}.xlsx"'
        )
        return response
```

---

## 8. Unit Tests

### 8.1 Test structure and fixtures

```python
# mysite/tests/demand/conftest.py  (or in each test file's setUp)

import pytest
import datetime
from mysite.models import Client, Item
from mysite.models.demand.hierarchy import (
    PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment
)
from mysite.models.demand.actuals import ActualSale, ActualSaleImport


@pytest.fixture
def client_obj(db):
    return Client.objects.create(client_id='test-client', name='Test Client')


@pytest.fixture
def root_location(db, client_obj):
    return PlanningLocation.objects.create(
        client=client_obj, code='ROOT', name='Root', is_leaf=False
    )


@pytest.fixture
def leaf_location(db, client_obj, root_location):
    return PlanningLocation.objects.create(
        client=client_obj, code='LEAF-01', name='Leaf Branch',
        parent=root_location, is_leaf=True
    )


@pytest.fixture
def active_item(db, client_obj):
    return Item.objects.create(
        client=client_obj, item_id='ITEM-001',
        name='Test Item', status='active'
    )


@pytest.fixture
def planning_customer(db, client_obj):
    return PlanningCustomer.objects.create(
        client=client_obj, code='CUST-001', name='Test Customer'
    )
```

### 8.2 Hierarchy tree tests — `test_hierarchy_api.py`

```python
# mysite/tests/demand/test_hierarchy_api.py

import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from mysite.models.demand.hierarchy import SalesNode, CustomerSalesAssignment
import datetime


@pytest.mark.django_db
class TestPlanningLocationHierarchyAPI:

    def setup_method(self):
        self.api = APIClient()

    def test_returns_nested_tree(self, client_obj, root_location, leaf_location, django_user_model):
        user = django_user_model.objects.create_user('testuser', password='pw')
        self.api.force_authenticate(user=user)
        # Attach client to request (simulate your middleware)
        self.api.credentials(HTTP_X_CLIENT_ID=client_obj.client_id)

        url = reverse('demand-location-hierarchy')
        response = self.api.get(url)

        assert response.status_code == 200
        data = response.json()
        # Root node should appear at top level
        assert len(data) == 1
        root = data[0]
        assert root['code'] == 'ROOT'
        assert root['depth'] == 0
        # Child node nested inside
        assert len(root['children']) == 1
        child = root['children'][0]
        assert child['code'] == 'LEAF-01'
        assert child['is_leaf'] is True
        assert child['depth'] == 1

    def test_leaves_only_param_returns_flat_list(
        self, client_obj, root_location, leaf_location, django_user_model
    ):
        user = django_user_model.objects.create_user('user2', password='pw')
        self.api.force_authenticate(user=user)

        url = reverse('demand-location-hierarchy')
        response = self.api.get(url, {'leaves_only': 'true'})

        assert response.status_code == 200
        data = response.json()
        # Only leaf nodes returned, flat list
        codes = [n['code'] for n in data]
        assert 'LEAF-01' in codes
        assert 'ROOT' not in codes


@pytest.mark.django_db
class TestPathMaterialization:
    """Sprint 3B.1 unit tests: path computed correctly."""

    def test_root_node_path(self, client_obj):
        node = PlanningLocation.objects.create(
            client=client_obj, code='R', name='Root', is_leaf=False
        )
        node.refresh_from_db()
        assert node.path == f'{node.pk}/'

    def test_child_node_path(self, client_obj, root_location):
        child = PlanningLocation.objects.create(
            client=client_obj, code='C', name='Child',
            parent=root_location, is_leaf=True
        )
        child.refresh_from_db()
        assert child.path == f'{root_location.pk}/{child.pk}/'

    def test_reparent_updates_path(self, client_obj, root_location):
        """Moving a node to a new parent must recompute path."""
        other_root = PlanningLocation.objects.create(
            client=client_obj, code='R2', name='Other Root', is_leaf=False
        )
        child = PlanningLocation.objects.create(
            client=client_obj, code='C2', name='Child',
            parent=root_location, is_leaf=True
        )
        child.refresh_from_db()
        original_path = child.path

        # Reparent
        child.parent = other_root
        child.save()
        child.refresh_from_db()

        assert child.path != original_path
        assert child.path == f'{other_root.pk}/{child.pk}/'

    def test_subtree_query_via_path_startswith(self, client_obj, root_location, leaf_location):
        """path__startswith must return all descendants."""
        root_location.refresh_from_db()
        descendants = PlanningLocation.objects.filter(
            path__startswith=root_location.path
        ).exclude(pk=root_location.pk)
        assert leaf_location in descendants

    def test_grandchild_path(self, client_obj, root_location, leaf_location):
        grandchild = PlanningLocation.objects.create(
            client=client_obj, code='GC', name='Grandchild',
            parent=leaf_location, is_leaf=True
        )
        grandchild.refresh_from_db()
        assert grandchild.path == (
            f'{root_location.pk}/{leaf_location.pk}/{grandchild.pk}/'
        )


@pytest.mark.django_db
class TestCustomerSalesAssignment:

    def test_date_effectivity_no_overlap_allowed(
        self, client_obj, planning_customer
    ):
        """Two open assignments for the same customer must be rejected."""
        from django.core.exceptions import ValidationError

        sales_root = SalesNode.objects.create(
            client=client_obj, code='NSM', name='National'
        )
        sales_leaf = SalesNode.objects.create(
            client=client_obj, code='REP-01', name='Rep 1',
            parent=sales_root
        )

        # First assignment — open-ended
        a1 = CustomerSalesAssignment(
            planning_customer=planning_customer,
            sales_node=sales_leaf,
            valid_from=datetime.date(2024, 1, 1),
            valid_to=None,
        )
        a1.full_clean()
        a1.save()

        # Second overlapping assignment — should be rejected
        a2 = CustomerSalesAssignment(
            planning_customer=planning_customer,
            sales_node=sales_leaf,
            valid_from=datetime.date(2024, 6, 1),
            valid_to=None,
        )
        # Your clean() method or a DB constraint should raise here.
        # If you haven't added overlap validation to clean() yet, add it:
        #
        #   def clean(self):
        #       overlapping = CustomerSalesAssignment.objects.filter(
        #           planning_customer=self.planning_customer,
        #           valid_to__isnull=True,
        #       ).exclude(pk=self.pk)
        #       if overlapping.exists():
        #           raise ValidationError(
        #               "Customer already has an open assignment. "
        #               "Close the existing one before creating a new one."
        #           )
        with pytest.raises(ValidationError):
            a2.full_clean()
```

> **Action required:** Add the overlap check to `CustomerSalesAssignment.clean()` as shown in the comment above — the test verifies it.

### 8.3 Actuals import tests — `test_actuals_import.py`

```python
# mysite/tests/demand/test_actuals_import.py

import io
import pytest
import datetime
import pandas as pd
from mysite.models.demand.actuals import ActualSale, ActualSaleImport
from mysite.tasks.demand.import_actuals import _run_import


def make_csv(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def make_import_job(client_obj, period_type='month', tmp_file_content=None,
                    file_name='test_upload.csv', django_storage=None):
    """
    Create an ActualSaleImport record and write content to Django's default
    storage so _run_import() can open it.
    """
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile

    path = default_storage.save(
        f'demand/actuals_imports/{file_name}',
        ContentFile(tmp_file_content or b''),
    )
    return ActualSaleImport.objects.create(
        client=client_obj,
        file_name=path,
        period_type=period_type,
        status='pending',
    )


@pytest.mark.django_db(transaction=True)
class TestActualsImport:

    def test_valid_upload_creates_correct_row_count(
        self, client_obj, leaf_location, active_item, planning_customer
    ):
        """Valid upload → ActualSale row count == file row count."""
        rows = [
            {
                'period_start': '2024-01-01',
                'item_id': 'ITEM-001',
                'location_code': 'LEAF-01',
                'customer_code': 'CUST-001',
                'qty': '100',
                'revenue': '15000.00',
            },
            {
                'period_start': '2024-02-01',
                'item_id': 'ITEM-001',
                'location_code': 'LEAF-01',
                'customer_code': 'CUST-001',
                'qty': '120',
                'revenue': '18000.00',
            },
        ]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        assert job.status == 'done'
        assert job.row_count == 2
        assert ActualSale.objects.filter(client=client_obj).count() == 2

    def test_duplicate_upload_is_idempotent(
        self, client_obj, leaf_location, active_item, planning_customer
    ):
        """Uploading the same file twice: row count stays the same."""
        rows = [{
            'period_start': '2024-01-01', 'item_id': 'ITEM-001',
            'location_code': 'LEAF-01', 'customer_code': 'CUST-001',
            'qty': '100', 'revenue': '',
        }]
        csv_content = make_csv(rows)

        job1 = make_import_job(client_obj, period_type='month',
                               tmp_file_content=csv_content, file_name='dup1.csv')
        _run_import(job1)
        assert ActualSale.objects.filter(client=client_obj).count() == 1

        job2 = make_import_job(client_obj, period_type='month',
                               tmp_file_content=csv_content, file_name='dup2.csv')
        _run_import(job2)
        # Still only 1 row — upsert, not insert
        assert ActualSale.objects.filter(client=client_obj).count() == 1

        job2.refresh_from_db()
        assert job2.status == 'done'

    def test_invalid_item_fk_collected_in_error_log(
        self, client_obj, leaf_location, active_item
    ):
        """Row with unknown item_id → error in error_log; other rows imported."""
        rows = [
            {
                'period_start': '2024-01-01', 'item_id': 'ITEM-001',
                'location_code': 'LEAF-01', 'customer_code': '',
                'qty': '100', 'revenue': '',
            },
            {
                'period_start': '2024-01-01', 'item_id': 'NONEXISTENT',
                'location_code': 'LEAF-01', 'customer_code': '',
                'qty': '50', 'revenue': '',
            },
        ]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        # Valid row imported; bad row skipped
        assert ActualSale.objects.filter(client=client_obj).count() == 1
        assert job.status == 'done'
        assert 'NONEXISTENT' in job.error_log
        assert 'Row 3' in job.error_log   # excel_row = row_num+2, second data row = 3

    def test_missing_required_columns_fails_fast(self, client_obj):
        """File missing required columns → status=failed immediately."""
        bad_csv = b"location_code,qty\nLEAF-01,100\n"
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=bad_csv, file_name='bad.csv')
        _run_import(job)
        job.refresh_from_db()

        assert job.status == 'failed'
        assert 'period_start' in job.error_log
        assert 'item_id' in job.error_log

    def test_invalid_period_start_anchor_collected_as_error(
        self, client_obj, leaf_location, active_item
    ):
        """period_start=2024-01-15 for month bucket → row error, not crash."""
        rows = [{
            'period_start': '2024-01-15',    # wrong anchor — not 1st of month
            'item_id': 'ITEM-001', 'location_code': 'LEAF-01',
            'customer_code': '', 'qty': '100', 'revenue': '',
        }]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)
        job.refresh_from_db()

        assert ActualSale.objects.filter(client=client_obj).count() == 0
        assert 'period_start' in job.error_log

    def test_unattributed_demand_null_customer(
        self, client_obj, leaf_location, active_item
    ):
        """Blank customer_code → ActualSale.planning_customer is NULL."""
        rows = [{
            'period_start': '2024-01-01', 'item_id': 'ITEM-001',
            'location_code': 'LEAF-01', 'customer_code': '',
            'qty': '75', 'revenue': '',
        }]
        job = make_import_job(client_obj, period_type='month',
                              tmp_file_content=make_csv(rows))
        _run_import(job)

        sale = ActualSale.objects.get(client=client_obj)
        assert sale.planning_customer is None
        assert sale.qty == pytest.approx(75)
```

### 8.4 Running the tests

```bash
# Run all demand tests
pytest mysite/tests/demand/ -v

# Run only import tests
pytest mysite/tests/demand/test_actuals_import.py -v

# Run with coverage
pytest mysite/tests/demand/ --cov=mysite.models.demand --cov=mysite.tasks.demand --cov-report=term-missing
```

Add to `pytest.ini` or `setup.cfg` if not already configured:

```ini
[pytest]
DJANGO_SETTINGS_MODULE = mysite.settings
python_files = test_*.py
python_classes = Test*
python_functions = test_*
```

---

## Final Checklist

**Sprint 3B.1 — Open items:**
- [ ] `mysite/api/demand/` directory created with `__init__.py`, `serializers.py`, `views.py`, `urls.py`
- [ ] `build_tree()` utility in `views.py`
- [ ] `GET /api/demand/location-hierarchy/` returns nested JSON
- [ ] `GET /api/demand/sales-hierarchy/` returns nested JSON with active assignments
- [ ] URLs wired into main `urls.py`
- [ ] `CustomerSalesAssignment.clean()` overlap check added (needed for unit test)
- [ ] All Sprint 3B.1 unit tests pass

**Sprint 3B.2 — Open items:**
- [ ] `ActualSaleLocation` model added to `actuals.py` and migration run
- [ ] Partial unique indexes (`uq_actualsale_with_customer`, `uq_actualsale_no_customer`) added via `RunSQL`
- [ ] `mysite/tasks/demand/` directory created with `__init__.py`, `import_actuals.py`
- [ ] `POST /api/demand/actuals/upload/` accepts file and fires Celery task
- [ ] `GET /api/demand/actuals/upload/{id}/` returns job status
- [ ] `GET /api/demand/actuals/` returns filtered, paginated results
- [ ] `GET /api/demand/actuals/template/` streams the generated Excel template
- [ ] `generate_actuals_template` management command runs without errors
- [ ] `process_actuals_import` Celery task imports valid rows and collects errors
- [ ] `process_summary_actuals_import` Celery task imports location summary rows
- [ ] All Sprint 3B.2 unit tests pass
