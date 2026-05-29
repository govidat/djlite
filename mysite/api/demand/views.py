# `mysite/api/demand/views.py`

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
    


#3.1 `POST /api/demand/actuals/upload/`

#Accepts a multipart file upload, validates the file type, creates an
#`ActualSaleImport` record, fires the Celery task, and returns immediately
#with the import job ID. The client polls `/actuals/upload/{id}/` for status.
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