# Sprint 3B.6 — Forecast Approval and PO Export
## Detailed Implementation Instructions

**Dependencies:** Sprint 3B.5 complete (override API, HTMX grid, `apply_overrides` wired)
**Estimated effort:** 2–3 days
**App label:** `mysite`

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Model Delta — no new models](#2-model-delta)
3. [Approval Workflow UI](#3-approval-workflow-ui)
4. [Email Notifications on Status Transition](#4-email-notifications)
5. [Export Endpoint — `.xlsx` download](#5-export-endpoint)
6. [ForecastAccuracy Dashboard Endpoint](#6-forecastaccuracy-dashboard-endpoint)
7. [Serializers](#7-serializers)
8. [URL Additions](#8-url-additions)
9. [Unit Tests](#9-unit-tests)
10. [Migration and Checklist](#10-migration-and-checklist)

---

## 1. Architecture Overview

### What Sprint 3B.6 adds

```
Planner action (HTMX buttons or API client)
    │
    ▼
POST /api/demand/forecast-versions/{id}/approve/    ← already exists from 3B.3
    │  Calls version.transition_to(new_status, user) — unchanged
    │  NEW: fires send_forecast_status_email.delay() after every transition
    │
    ▼
Email notification (Celery task)
    │  Finds client users who need to be notified for this transition
    │  Sends Django templated email
    │
    ▼
GET /api/demand/forecast-versions/{id}/export/      ← NEW
    │  Streams ForecastLine rows as a formatted .xlsx workbook
    │  Layout: Location × Item matrix with period columns
    │  Works on any status (DRAFT previews, LOCKED for PO input)
    │
    ▼
GET /api/demand/forecast-versions/{id}/accuracy/    ← NEW
    │  Returns ForecastAccuracy rows grouped/aggregated by
    │  category or location — the accuracy dashboard feed
    │
    ▼
HTMX Approval Panel (new partial)
    │  Status badge + action buttons appropriate to current status
    │  Confirm modal before submit / approve / lock
    │  Inline note field on reject
```

### Approval state machine (unchanged from 3B.3)

```
DRAFT ──submit──▶ IN_REVIEW ──approve──▶ APPROVED ──lock──▶ LOCKED
  ▲                   │                                         │
  └─────reject────────┘                    copy() ─────────────┘
```

The `transition_to()` method on `ForecastVersion` (Sprint 3B.3) enforces allowed
transitions and raises `ValidationError` for illegal ones. Sprint 3B.6 does not change
the state machine — it adds email notification and the HTMX UI surface.

---

## 2. Model Delta

No new models. No migration required.

All models (`ForecastVersion`, `ForecastLine`, `ForecastAccuracy`) exist from Sprints 3B.3–3B.4.

---

## 3. Approval Workflow UI

The approval panel is an HTMX partial that sits at the top of the forecast version detail
page. It shows the current status badge and the actions available from that status.

### 3a. Template structure

```
mysite/
  templates/
    demand/
      partials/
        approval_panel.html          ← status badge + action buttons
        approval_confirm_modal.html  ← confirmation modal (shared for all actions)
        approval_rejected_note.html  ← reject-specific: note entry before confirm
```

### 3b. `approval_panel.html`

```html
{# demand/partials/approval_panel.html #}
{# Context: version (ForecastVersion), request.user #}

<div class="approval-panel" id="approval-panel-{{ version.pk }}">

  {# ── Status badge ─────────────────────────────────────────────────────── #}
  <div class="approval-panel__status">
    {% with s=version.status %}
    <span class="status-badge status-badge--{{ s|lower }}">
      {% if s == 'DRAFT' %}📝 Draft
      {% elif s == 'IN_REVIEW' %}🔍 In Review
      {% elif s == 'APPROVED' %}✅ Approved
      {% elif s == 'LOCKED' %}🔒 Locked
      {% endif %}
    </span>
    {% endwith %}

    <span class="approval-panel__meta">
      Created by {{ version.created_by.get_full_name|default:version.created_by.username }}
      on {{ version.created_at|date:"d M Y" }}
      {% if version.approved_by %}
        · Approved by {{ version.approved_by.get_full_name|default:version.approved_by.username }}
        on {{ version.approved_at|date:"d M Y" }}
      {% endif %}
      {% if version.locked_at %}
        · Locked {{ version.locked_at|date:"d M Y" }}
      {% endif %}
    </span>
  </div>

  {# ── Action buttons — vary by current status ───────────────────────────── #}
  <div class="approval-panel__actions">

    {% if version.status == 'DRAFT' %}
      {# Planners submit for review #}
      <button class="btn btn-primary"
              hx-post="/api/demand/forecast-versions/{{ version.pk }}/approve/"
              hx-vals='{"action": "submit"}'
              hx-confirm="Submit this version for review? Overrides will be frozen."
              hx-target="#approval-panel-{{ version.pk }}"
              hx-swap="outerHTML"
              hx-headers='{"X-CSRFToken": "{{ csrf_token }}",
                            "Content-Type": "application/json"}'>
        Submit for Review
      </button>
      <button class="btn btn-secondary"
              hx-get="/demand/partials/approval-copy-form/{{ version.pk }}/"
              hx-target="#approval-modal-container"
              hx-swap="innerHTML">
        Copy Version
      </button>

    {% elif version.status == 'IN_REVIEW' %}
      {# Approvers can approve or reject (reject sends back to DRAFT) #}
      <button class="btn btn-success"
              hx-post="/api/demand/forecast-versions/{{ version.pk }}/approve/"
              hx-vals='{"action": "approve"}'
              hx-confirm="Approve this forecast version?"
              hx-target="#approval-panel-{{ version.pk }}"
              hx-swap="outerHTML"
              hx-headers='{"X-CSRFToken": "{{ csrf_token }}",
                            "Content-Type": "application/json"}'>
        Approve
      </button>
      <button class="btn btn-warning"
              hx-get="/demand/partials/approval-reject-form/{{ version.pk }}/"
              hx-target="#approval-modal-container"
              hx-swap="innerHTML">
        Reject (send back)
      </button>

    {% elif version.status == 'APPROVED' %}
      {# Only lock action remains — this is terminal except for copy #}
      <button class="btn btn-danger"
              hx-post="/api/demand/forecast-versions/{{ version.pk }}/approve/"
              hx-vals='{"action": "lock"}'
              hx-confirm="Lock this version? It will be immutable and used as the PO baseline."
              hx-target="#approval-panel-{{ version.pk }}"
              hx-swap="outerHTML"
              hx-headers='{"X-CSRFToken": "{{ csrf_token }}",
                            "Content-Type": "application/json"}'>
        Lock for PO Export
      </button>
      <button class="btn btn-secondary"
              hx-get="/demand/partials/approval-copy-form/{{ version.pk }}/"
              hx-target="#approval-modal-container"
              hx-swap="innerHTML">
        Copy Version
      </button>

    {% elif version.status == 'LOCKED' %}
      {# No mutations — only copy and export #}
      <a class="btn btn-primary"
         href="/api/demand/forecast-versions/{{ version.pk }}/export/"
         download="forecast_{{ version.version_label|slugify }}.xlsx">
        📥 Download PO Export (.xlsx)
      </a>
      <button class="btn btn-secondary"
              hx-get="/demand/partials/approval-copy-form/{{ version.pk }}/"
              hx-target="#approval-modal-container"
              hx-swap="innerHTML">
        Copy to New Draft
      </button>
    {% endif %}

  </div>

  {# ── Modal container — populated by HTMX for reject / copy forms ────────── #}
  <div id="approval-modal-container"></div>

</div>
```

### 3c. `approval_rejected_note.html` — reject with note

```html
{# demand/partials/approval_rejected_note.html #}
{# Loaded into #approval-modal-container when "Reject" is clicked #}
{# Context: version #}

<div class="modal-overlay" id="approval-reject-modal">
  <div class="modal">
    <h3>Send back for revision</h3>
    <p>Rejecting will return this version to <strong>DRAFT</strong> status.
       Planners will be notified by email.</p>

    <form
      hx-post="/api/demand/forecast-versions/{{ version.pk }}/approve/"
      hx-target="#approval-panel-{{ version.pk }}"
      hx-swap="outerHTML"
      hx-on::after-request="document.getElementById('approval-modal-container').innerHTML=''"
      hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
    >
      <input type="hidden" name="action" value="reject">
      <div class="form-group">
        <label for="reject-note">Reason for rejection <span class="hint">(shown in email)</span></label>
        <textarea id="reject-note" name="note" rows="4"
                  placeholder="e.g. Category totals for North region need revision…"
                  class="form-control" required></textarea>
      </div>
      <div class="modal__actions">
        <button type="submit" class="btn btn-warning">Confirm Rejection</button>
        <button type="button" class="btn btn-link"
                onclick="document.getElementById('approval-modal-container').innerHTML=''">
          Cancel
        </button>
      </div>
    </form>
  </div>
</div>
```

### 3d. `approval_copy_form.html` — copy to new draft

```html
{# demand/partials/approval_copy_form.html #}
{# Context: version #}

<div class="modal-overlay" id="approval-copy-modal">
  <div class="modal">
    <h3>Copy to new Draft</h3>
    <p>Creates a new DRAFT version with all forecast lines copied.
       Override history is not carried over.</p>

    <form
      hx-post="/api/demand/forecast-versions/{{ version.pk }}/approve/"
      hx-target="body"
      hx-swap="none"
      hx-on::after-request="window.location.href='/demand/forecast-versions/'"
      hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'
    >
      <input type="hidden" name="action" value="copy">
      <div class="form-group">
        <label for="copy-label">New version label</label>
        <input type="text" id="copy-label" name="note"
               value="{{ version.version_label }} (copy)"
               class="form-control" required>
      </div>
      <div class="modal__actions">
        <button type="submit" class="btn btn-primary">Create Copy</button>
        <button type="button" class="btn btn-link"
                onclick="document.getElementById('approval-modal-container').innerHTML=''">
          Cancel
        </button>
      </div>
    </form>
  </div>
</div>
```
 
### 3e. HTMX views to serve approval partials

Add to `mysite/views/demand/forecast_htmx.py` (alongside the Sprint 3B.5 HTMX views):

```python
# mysite/views/demand/forecast_htmx.py  — Sprint 3B.6 additions

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from mysite.models.demand.forecast import ForecastVersion


@login_required
def approval_panel(request, pk):
    """
    HTMX partial: renders the approval panel for a forecast version.
    Called after a successful approve/reject/lock action to refresh the panel.
    Also loaded on page-load via {% include %} in the version detail template.
    """
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_panel.html', {
        'version': version,
    })


@login_required
def approval_reject_form(request, pk):
    """HTMX partial: reject-with-note modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_rejected_note.html', {
        'version': version,
    })


@login_required
def approval_copy_form(request, pk):
    """HTMX partial: copy-to-new-draft modal body."""
    version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)
    return render(request, 'demand/partials/approval_copy_form.html', {
        'version': version,
    })
```

Add to the non-API URL conf:

```python
from mysite.views.demand.forecast_htmx import (
    approval_panel,
    approval_reject_form,
    approval_copy_form,
)

urlpatterns += [
    path(
        'demand/partials/approval-panel/<int:pk>/',
        approval_panel,
        name='demand-approval-panel',
    ),
    path(
        'demand/partials/approval-reject-form/<int:pk>/',
        approval_reject_form,
        name='demand-approval-reject-form',
    ),
    path(
        'demand/partials/approval-copy-form/<int:pk>/',
        approval_copy_form,
        name='demand-approval-copy-form',
    ),
]
```

### 3f. Update `ForecastVersionApproveView` to fire email on transition

`ForecastVersionApproveView` already exists from Sprint 3B.3. Add the email task call
after every successful `transition_to()`:

```python
# In mysite/api/demand/views.py — update ForecastVersionApproveView.post():

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

        old_status = version.status

        try:
            version.transition_to(self.ACTION_TRANSITIONS[action], user=request.user)
        except DjangoValidationError as exc:
            return Response({'detail': exc.message}, status=status.HTTP_403_FORBIDDEN)

        if note:
            version.notes = (version.notes + f'\n[{action}] {note}').strip()
            version.save(update_fields=['notes'])

        # ── NEW: fire email notification ──────────────────────────────────────
        from mysite.tasks.demand.notifications import send_forecast_status_email
        send_forecast_status_email.delay(
            version_id  = version.pk,
            old_status  = old_status,
            new_status  = version.status,
            actor_id    = request.user.pk,
            note        = note,
        )
        # ─────────────────────────────────────────────────────────────────────

        version.refresh_from_db()
        return Response(ForecastVersionSerializer(version).data)
```

---

## 4. Email Notifications

### 4a. Email recipients by transition

| Transition | Notify |
|---|---|
| DRAFT → IN_REVIEW (submit) | All staff users for this client |
| IN_REVIEW → APPROVED (approve) | Version creator + all planners |
| IN_REVIEW → DRAFT (reject) | Version creator only |
| APPROVED → LOCKED (lock) | Version creator + all planners |

"All planners for this client" is defined as users who are in a group named
`{client.client_id}_planners` or `demand_planners`, or who have `is_staff=True`
for the client. Adjust to match your actual user-group model.

### 4b. Celery task — `send_forecast_status_email`

Create `mysite/tasks/demand/notifications.py`:

```python
"""
mysite/tasks/demand/notifications.py

Celery tasks for forecast workflow email notifications.
Fired by ForecastVersionApproveView after every successful status transition.
"""
import logging
from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


# Map (old_status, new_status) → email template base name
_TEMPLATE_MAP = {
    ('DRAFT',     'IN_REVIEW'): 'submitted_for_review',
    ('IN_REVIEW', 'APPROVED'):  'approved',
    ('IN_REVIEW', 'DRAFT'):     'rejected',
    ('APPROVED',  'LOCKED'):    'locked',
}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_forecast_status_email(
    self,
    version_id: int,
    old_status: str,
    new_status: str,
    actor_id:   int,
    note:       str = '',
):
    """
    Send email notification when a ForecastVersion changes status.

    Args:
        version_id  — ForecastVersion.pk
        old_status  — status before transition
        new_status  — status after transition
        actor_id    — User.pk of the person who performed the action
        note        — optional freetext note (used verbatim in reject emails)
    """
    from mysite.models.demand.forecast import ForecastVersion

    try:
        version = ForecastVersion.objects.select_related(
            'client', 'created_by', 'approved_by'
        ).get(pk=version_id)
    except ForecastVersion.DoesNotExist:
        logger.warning(f'send_forecast_status_email: version {version_id} not found')
        return

    try:
        actor = User.objects.get(pk=actor_id)
    except User.DoesNotExist:
        actor = None

    template_key = (old_status, new_status)
    template_base = _TEMPLATE_MAP.get(template_key)
    if not template_base:
        logger.info(
            f'send_forecast_status_email: no template for '
            f'{old_status} → {new_status}; skipping'
        )
        return

    recipients = _get_recipients(version, old_status, new_status)
    if not recipients:
        logger.info(
            f'send_forecast_status_email: no recipients for version '
            f'{version_id} ({old_status} → {new_status})'
        )
        return

    context = {
        'version':    version,
        'actor':      actor,
        'old_status': old_status,
        'new_status': new_status,
        'note':       note,
        'site_url':   getattr(settings, 'SITE_URL', 'http://localhost:8000'),
        'timestamp':  timezone.now(),
    }

    subject = _build_subject(version, template_base)
    text_body = render_to_string(
        f'demand/email/forecast_{template_base}.txt', context
    )
    html_body = render_to_string(
        f'demand/email/forecast_{template_base}.html', context
    )

    from_email = getattr(
        settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'
    )

    try:
        msg = EmailMultiAlternatives(
            subject    = subject,
            body       = text_body,
            from_email = from_email,
            to         = recipients,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)
        logger.info(
            f'send_forecast_status_email: sent "{subject}" '
            f'to {recipients} for version {version_id}'
        )
    except Exception as exc:
        logger.exception(
            f'send_forecast_status_email: failed for version {version_id}: {exc}'
        )
        raise self.retry(exc=exc)


def _get_recipients(version, old_status: str, new_status: str) -> list[str]:
    """
    Return the list of email addresses to notify for a given transition.
    Adjust the group name logic to match your user model.
    """
    creator_email = (
        version.created_by.email
        if version.created_by and version.created_by.email
        else None
    )

    if new_status == 'IN_REVIEW':
        # Submitted: notify all staff who can approve
        staff_emails = list(
            User.objects
            .filter(is_staff=True, is_active=True)
            .exclude(email='')
            .values_list('email', flat=True)
        )
        return list(set(staff_emails))

    elif new_status == 'APPROVED':
        # Approved: notify creator and all active planners for the client
        planner_emails = _get_planner_emails(version.client)
        emails = planner_emails
        if creator_email:
            emails = list(set(emails + [creator_email]))
        return emails

    elif new_status == 'DRAFT' and old_status == 'IN_REVIEW':
        # Rejected: notify creator only
        return [creator_email] if creator_email else []

    elif new_status == 'LOCKED':
        # Locked: notify creator and all active planners
        planner_emails = _get_planner_emails(version.client)
        emails = planner_emails
        if creator_email:
            emails = list(set(emails + [creator_email]))
        return emails

    return []


def _get_planner_emails(client) -> list[str]:
    """
    Return email addresses of active users associated with a client.
    Extend this to query your ClientUserRole or group model as needed.

    Current implementation: returns all active non-anonymous users who have
    email addresses. In a multi-tenant system, replace with a query that
    filters by client membership.
    """
    # ── Adjust this query to match your user-client relationship ──────────────
    # Example if you have a ClientUser / UserProfile linking model:
    #   from mysite.models import ClientUser
    #   return list(
    #       ClientUser.objects
    #       .filter(client=client, is_active=True)
    #       .exclude(user__email='')
    #       .values_list('user__email', flat=True)
    #   )
    #
    # Fallback: all active staff users
    return list(
        User.objects
        .filter(is_active=True, is_staff=False)
        .exclude(email='')
        .values_list('email', flat=True)
    )


def _build_subject(version, template_base: str) -> str:
    labels = {
        'submitted_for_review': 'submitted for review',
        'approved':             'approved',
        'rejected':             'sent back for revision',
        'locked':               'locked for PO export',
    }
    action_label = labels.get(template_base, template_base)
    return (
        f'[Demand Planning] "{version.version_label}" has been {action_label}'
    )
```

### 4c. Email templates

Create `mysite/templates/demand/email/` with four pairs of `.txt` / `.html` files.

**`forecast_submitted_for_review.txt`**:
```
{{ version.version_label }} — Submitted for Review

{{ actor.get_full_name|default:actor.username }} has submitted this forecast version for review.

Version: {{ version.version_label }}
Client:  {{ version.client }}
Period:  {{ version.period_type }} ending {{ version.base_period_end }}
Submitted at: {{ timestamp|date:"d M Y H:i" }}

Please log in to review and approve or reject:
{{ site_url }}/demand/forecast-versions/{{ version.pk }}/

---
This is an automated notification from the Demand Planning system.
```

**`forecast_submitted_for_review.html`** (minimal, styled):
```html
<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
  <div style="background:#0d6efd;padding:16px;border-radius:4px 4px 0 0">
    <h2 style="color:#fff;margin:0">📋 Forecast Submitted for Review</h2>
  </div>
  <div style="padding:24px;border:1px solid #dee2e6;border-top:none;border-radius:0 0 4px 4px">
    <p>
      <strong>{{ actor.get_full_name|default:actor.username }}</strong>
      has submitted a forecast version for review.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0">
      <tr><td style="padding:6px;color:#6c757d">Version</td>
          <td style="padding:6px"><strong>{{ version.version_label }}</strong></td></tr>
      <tr><td style="padding:6px;color:#6c757d">Client</td>
          <td style="padding:6px">{{ version.client }}</td></tr>
      <tr><td style="padding:6px;color:#6c757d">Period</td>
          <td style="padding:6px">{{ version.period_type }} ending {{ version.base_period_end }}</td></tr>
      <tr><td style="padding:6px;color:#6c757d">Submitted</td>
          <td style="padding:6px">{{ timestamp|date:"d M Y H:i" }}</td></tr>
    </table>
    <a href="{{ site_url }}/demand/forecast-versions/{{ version.pk }}/"
       style="display:inline-block;background:#0d6efd;color:#fff;padding:10px 20px;
              border-radius:4px;text-decoration:none;font-weight:bold">
      Review Forecast →
    </a>
  </div>
  <p style="font-size:11px;color:#adb5bd;margin-top:16px">
    Automated notification — Demand Planning System
  </p>
</body>
</html>
```

**`forecast_approved.txt`**:
```
{{ version.version_label }} — Approved

{{ actor.get_full_name|default:actor.username }} has approved this forecast version.
It is now ready to be locked for PO export.

Version: {{ version.version_label }}
Approved at: {{ timestamp|date:"d M Y H:i" }}

View: {{ site_url }}/demand/forecast-versions/{{ version.pk }}/
```

**`forecast_approved.html`** — same structure as submitted; change heading to
"✅ Forecast Approved", badge colour to `#198754` (green), and button text to
"Lock for PO Export →".

**`forecast_rejected.txt`**:
```
{{ version.version_label }} — Sent Back for Revision

{{ actor.get_full_name|default:actor.username }} has sent this forecast version back to DRAFT.

Reason: {{ note|default:"No reason provided." }}

Version: {{ version.version_label }}
Rejected at: {{ timestamp|date:"d M Y H:i" }}

Please revise and resubmit:
{{ site_url }}/demand/forecast-versions/{{ version.pk }}/
```

**`forecast_rejected.html`** — heading "⚠️ Forecast Sent Back for Revision",
badge colour `#fd7e14` (orange), include `note` in a highlighted block:
```html
{% if note %}
<div style="background:#fff3cd;border:1px solid #ffc107;border-radius:4px;padding:12px;margin:16px 0">
  <strong>Reason:</strong> {{ note }}
</div>
{% endif %}
```

**`forecast_locked.txt`**:
```
{{ version.version_label }} — Locked for PO Export

{{ actor.get_full_name|default:actor.username }} has locked this forecast version.
It is now immutable and available for purchase order export.

Version: {{ version.version_label }}
Locked at: {{ timestamp|date:"d M Y H:i" }}

Download PO export:
{{ site_url }}/api/demand/forecast-versions/{{ version.pk }}/export/
```

**`forecast_locked.html`** — heading "🔒 Forecast Locked for PO Export",
badge colour `#0d6efd` (blue), add a prominent "Download .xlsx" button.

---

## 5. Export Endpoint

### 5a. Export format

The `.xlsx` workbook has two sheets:

**Sheet 1: "Forecast" (PO input format)**

Rows = one per (Location × Item × Customer).
Columns = Location, Item ID, Item Name, Customer (if any), Unit of Measure, Price,
then one column per forecast period (`period_start` formatted as `MMM-YY`).
Cell values = `final_qty` (3 decimal places).

```
Location | Item ID | Item Name | Customer | UOM | Price | Jan-25 | Feb-25 | Mar-25 …
MUM-01   | ITEM-001| Brake Pad | —        | EA  | 150.00| 120.000| 135.000| 118.000
MUM-01   | ITEM-002| Disc      | —        | EA  | 320.00|  45.000|  52.000|  47.000
DEL-01   | ITEM-001| Brake Pad | —        | EA  | 150.00|  80.000|  90.000|  75.000
```

**Sheet 2: "Summary" (aggregate totals)**

Rows = one per period.
Columns = Period, Total Final Qty, Total Final Value (₹), Override Count.
Sourced from `ForecastAggregate` where `agg_level='total'`.

### 5b. View

Add to `mysite/api/demand/views.py`:

```python
# ─────────────────────────────────────────────────────────────────────────────
# Sprint 3B.6 imports — add to existing import block
# ─────────────────────────────────────────────────────────────────────────────
import io
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


# ─────────────────────────────────────────────────────────────────────────────
# 5C. Export view
# GET /api/demand/forecast-versions/{id}/export/
# ─────────────────────────────────────────────────────────────────────────────

class ForecastVersionExportView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/export/

    Streams a formatted .xlsx workbook of ForecastLine.final_qty values.

    Query params:
        forecast_level — filter to one grain level (default: all lines)
        location_code  — export one location only
        period_start   — ISO date, include periods >= value
        period_end     — ISO date, include periods <= value

    Works on any version status. LOCKED versions are the canonical source
    for purchase order input.

    Response headers:
        Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
        Content-Disposition: attachment; filename="forecast_{version_label}.xlsx"
    """
    permission_classes = [IsAuthenticated]

    # Openpyxl style constants — defined once, reused across rows
    _HEADER_FONT     = Font(name='Arial', bold=True, color='FFFFFF', size=10)
    _HEADER_FILL     = PatternFill('solid', start_color='1F4E79')   # dark navy
    _PERIOD_FONT     = Font(name='Arial', bold=True, color='FFFFFF', size=10)
    _PERIOD_FILL     = PatternFill('solid', start_color='2E75B6')   # mid-blue
    _SUBHEADER_FONT  = Font(name='Arial', bold=True, size=10)
    _BODY_FONT       = Font(name='Arial', size=10)
    _OVR_FILL        = PatternFill('solid', start_color='FFF2CC')   # pale yellow
    _THIN_BORDER     = Border(
        bottom=Side(style='thin', color='DEE2E6'),
        right =Side(style='thin', color='DEE2E6'),
    )
    _NUM_FMT         = '#,##0.000'   # 3 d.p. for quantities
    _VAL_FMT         = '₹#,##0.00'  # 2 d.p. for values

    def get(self, request, pk):
        version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

        # ── Build ForecastLine queryset ───────────────────────────────────────
        qs = (
            ForecastLine.objects
            .filter(version=version)
            .select_related('item', 'planning_location', 'planning_customer')
            .order_by(
                'planning_location__code',
                'item__item_id',
                'planning_customer__code',
                'period_start',
            )
        )

        p = request.query_params
        if p.get('forecast_level'):
            qs = qs.filter(forecast_level=p['forecast_level'])
        if p.get('location_code'):
            qs = qs.filter(planning_location__code=p['location_code'])
        if p.get('period_start'):
            try:
                import datetime
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                pass
        if p.get('period_end'):
            try:
                import datetime
                qs = qs.filter(
                    period_end__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                pass

        lines = list(qs)

        if not lines:
            return Response(
                {'detail': 'No forecast lines found for the specified filters.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Build workbook ────────────────────────────────────────────────────
        wb = Workbook()
        self._build_forecast_sheet(wb, version, lines)
        self._build_summary_sheet(wb, version)

        # ── Stream response ───────────────────────────────────────────────────
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        safe_label = version.version_label.replace(' ', '_').replace('/', '-')
        filename   = f'forecast_{safe_label}.xlsx'

        response = HttpResponse(
            buf.read(),
            content_type=(
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            ),
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    # ── Sheet builders ────────────────────────────────────────────────────────

    def _build_forecast_sheet(self, wb, version, lines):
        """
        Sheet 1: Location × Item × Period matrix.

        Structure:
          Row 1  — workbook title (merged)
          Row 2  — version meta (merged)
          Row 3  — blank
          Row 4  — column headers (Location, Item ID, Item Name, Customer,
                                   UOM, Price, <period_1>, <period_2>, …)
          Row 5+ — one row per unique (location, item, customer) with
                   final_qty in each period column.
        """
        ws = wb.active
        ws.title = 'Forecast'

        # ── Collect distinct periods in order ─────────────────────────────────
        periods = sorted({line.period_start for line in lines})
        period_labels = [
            p.strftime('%b-%y') for p in periods   # e.g. Jan-25
        ]

        # ── Fixed columns ─────────────────────────────────────────────────────
        fixed_cols = [
            'Location', 'Item ID', 'Item Name', 'Customer', 'UOM', 'Price (₹)'
        ]
        n_fixed   = len(fixed_cols)
        n_periods = len(periods)
        total_cols = n_fixed + n_periods

        # ── Row 1: workbook title ─────────────────────────────────────────────
        ws.merge_cells(start_row=1, start_column=1,
                       end_row=1,   end_column=total_cols)
        title_cell = ws.cell(row=1, column=1,
                             value=f'Demand Forecast — {version.version_label}')
        title_cell.font      = Font(name='Arial', bold=True, size=13, color='1F4E79')
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 24

        # ── Row 2: version meta ───────────────────────────────────────────────
        ws.merge_cells(start_row=2, start_column=1,
                       end_row=2,   end_column=total_cols)
        meta_cell = ws.cell(
            row=2, column=1,
            value=(
                f'Status: {version.status}  |  '
                f'Period: {version.period_type}  |  '
                f'Base end: {version.base_period_end}  |  '
                f'Horizon: {version.horizon_periods} periods  |  '
                f'Exported: {__import__("datetime").date.today()}'
            )
        )
        meta_cell.font      = Font(name='Arial', size=9, italic=True, color='6C757D')
        meta_cell.alignment = Alignment(horizontal='left')
        ws.row_dimensions[2].height = 16

        # ── Row 3: blank spacer ───────────────────────────────────────────────
        ws.row_dimensions[3].height = 6

        # ── Row 4: column headers ─────────────────────────────────────────────
        header_row = 4
        for col_idx, label in enumerate(fixed_cols, start=1):
            cell = ws.cell(row=header_row, column=col_idx, value=label)
            cell.font      = self._HEADER_FONT
            cell.fill      = self._HEADER_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center',
                                       wrap_text=True)
            cell.border    = self._THIN_BORDER

        for p_idx, label in enumerate(period_labels, start=n_fixed + 1):
            cell = ws.cell(row=header_row, column=p_idx, value=label)
            cell.font      = self._PERIOD_FONT
            cell.fill      = self._PERIOD_FILL
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border    = self._THIN_BORDER

        ws.row_dimensions[header_row].height = 28

        # ── Pivot: (location, item, customer) → {period_start: final_qty} ────
        pivot: dict[tuple, dict] = {}
        meta:  dict[tuple, dict] = {}   # static metadata per row key

        for line in lines:
            key = (
                line.planning_location.code,
                line.item.item_id,
                line.planning_customer.code if line.planning_customer else '',
            )
            if key not in pivot:
                pivot[key] = {}
                meta[key]  = {
                    'location_name': line.planning_location.name
                                     if hasattr(line.planning_location, 'name')
                                     else line.planning_location.code,
                    'item_name':     line.item.name,
                    'uom':           getattr(line.item, 'uom', 'EA'),
                    'price':         float(line.price_used) if line.price_used else '',
                    'has_override':  False,
                }
            pivot[key][line.period_start] = float(line.final_qty)
            if line.override_qty is not None:
                meta[key]['has_override'] = True

        # ── Data rows ─────────────────────────────────────────────────────────
        data_start_row = header_row + 1
        for row_idx, (key, period_qtys) in enumerate(
            sorted(pivot.keys(), key=lambda k: (k[0], k[1], k[2])),
            start=data_start_row,
        ):
            loc_code, item_id, cust_code = key
            m = meta[key]
            fill = self._OVR_FILL if m['has_override'] else None

            fixed_values = [
                loc_code,
                item_id,
                m['item_name'],
                cust_code or '—',
                m['uom'],
                m['price'],
            ]
            for col_idx, val in enumerate(fixed_values, start=1):
                cell         = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.font    = self._BODY_FONT
                cell.border  = self._THIN_BORDER
                if fill:
                    cell.fill = fill
                if col_idx == n_fixed:   # Price column — right-align, number format
                    cell.alignment  = Alignment(horizontal='right')
                    cell.number_format = '#,##0.00'

            for p_idx, period_start in enumerate(periods, start=n_fixed + 1):
                qty  = period_qtys.get(period_start, '')
                cell = ws.cell(row=row_idx, column=p_idx, value=qty)
                cell.font   = self._BODY_FONT
                cell.border = self._THIN_BORDER
                if qty != '':
                    cell.number_format = self._NUM_FMT
                    cell.alignment     = Alignment(horizontal='right')
                if fill:
                    cell.fill = fill

        # ── Column widths ─────────────────────────────────────────────────────
        col_widths = [14, 12, 28, 16, 6, 12] + [10] * n_periods
        for col_idx, width in enumerate(col_widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        # ── Freeze panes: freeze fixed columns + header rows ──────────────────
        ws.freeze_panes = ws.cell(
            row=data_start_row, column=n_fixed + 1
        )

        # ── Legend row below data ─────────────────────────────────────────────
        legend_row = data_start_row + len(pivot) + 1
        ws.merge_cells(start_row=legend_row, start_column=1,
                       end_row=legend_row, end_column=4)
        legend_cell = ws.cell(
            row=legend_row, column=1,
            value='⬛ Highlighted rows have planner overrides applied.'
        )
        legend_cell.fill = self._OVR_FILL
        legend_cell.font = Font(name='Arial', size=9, italic=True)

    def _build_summary_sheet(self, wb, version):
        """
        Sheet 2: Period-level summary from ForecastAggregate (agg_level='total').
        Falls back to aggregating ForecastLine if no aggregate rows exist.
        """
        ws = wb.create_sheet(title='Summary')

        from mysite.models.demand.forecast import ForecastAggregate
        from django.db.models import Sum, Count, Q

        # Try ForecastAggregate first (populated by 3B.4 write_forecast_aggregates)
        agg_rows = (
            ForecastAggregate.objects
            .filter(version=version, agg_level='total')
            .order_by('period_start')
        )

        # ── Header ────────────────────────────────────────────────────────────
        headers = [
            'Period', 'Period Start', 'Total Final Qty',
            'Total Final Value (₹)', 'Override Count',
        ]
        for col_idx, label in enumerate(headers, start=1):
            cell       = ws.cell(row=1, column=col_idx, value=label)
            cell.font  = self._HEADER_FONT
            cell.fill  = self._HEADER_FILL
            cell.border= self._THIN_BORDER
            cell.alignment = Alignment(horizontal='center')
        ws.row_dimensions[1].height = 22

        # ── Data ──────────────────────────────────────────────────────────────
        if agg_rows.exists():
            for row_idx, agg in enumerate(agg_rows, start=2):
                override_count = (
                    ForecastLine.objects
                    .filter(
                        version      = version,
                        period_start = agg.period_start,
                        override_qty__isnull=False,
                    )
                    .count()
                )
                row_data = [
                    agg.period_start.strftime('%b-%y'),
                    agg.period_start,
                    float(agg.final_qty),
                    float(agg.total_final_value) if agg.total_final_value else '',
                    override_count,
                ]
                for col_idx, val in enumerate(row_data, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font   = self._BODY_FONT
                    cell.border = self._THIN_BORDER
                    if col_idx == 3:
                        cell.number_format = self._NUM_FMT
                        cell.alignment     = Alignment(horizontal='right')
                    if col_idx == 4 and val != '':
                        cell.number_format = '#,##0.00'
                        cell.alignment     = Alignment(horizontal='right')

        else:
            # Fallback: aggregate directly from ForecastLine
            summary = (
                ForecastLine.objects
                .filter(version=version)
                .values('period_start')
                .annotate(
                    total_qty   = Sum('final_qty'),
                    total_value = Sum('final_value'),
                    ovr_count   = Count('pk', filter=Q(override_qty__isnull=False)),
                )
                .order_by('period_start')
            )
            for row_idx, row in enumerate(summary, start=2):
                ps = row['period_start']
                row_data = [
                    ps.strftime('%b-%y'),
                    ps,
                    float(row['total_qty']  or 0),
                    float(row['total_value'] or 0),
                    row['ovr_count'],
                ]
                for col_idx, val in enumerate(row_data, start=1):
                    cell = ws.cell(row=row_idx, column=col_idx, value=val)
                    cell.font   = self._BODY_FONT
                    cell.border = self._THIN_BORDER
                    if col_idx == 3:
                        cell.number_format = self._NUM_FMT
                        cell.alignment     = Alignment(horizontal='right')
                    if col_idx == 4:
                        cell.number_format = '#,##0.00'
                        cell.alignment     = Alignment(horizontal='right')

        # ── Add totals row using Excel SUM formulas ───────────────────────────
        last_data_row = ws.max_row
        totals_row    = last_data_row + 1
        ws.cell(row=totals_row, column=1, value='TOTAL').font = self._SUBHEADER_FONT
        for col_idx in (3, 4):
            col_letter = get_column_letter(col_idx)
            total_cell = ws.cell(
                row=totals_row, column=col_idx,
                value=f'=SUM({col_letter}2:{col_letter}{last_data_row})',
            )
            total_cell.font   = self._SUBHEADER_FONT
            total_cell.border = self._THIN_BORDER
            total_cell.number_format = (
                self._NUM_FMT if col_idx == 3 else '#,##0.00'
            )
            total_cell.alignment = Alignment(horizontal='right')

        # ── Column widths ─────────────────────────────────────────────────────
        for col_idx, width in enumerate([10, 14, 18, 22, 16], start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width
```

---

## 6. ForecastAccuracy Dashboard Endpoint

### 6a. Design

The endpoint aggregates `ForecastAccuracy` rows by category **or** location,
across all periods, for a given version. It is the data feed for the accuracy
dashboard visible on the version detail page.

```
GET /api/demand/forecast-versions/{id}/accuracy/

Query params:
    group_by        — "category" | "location" | "period" (default: "category")
    period_start    — ISO date filter (>=)
    period_end      — ISO date filter (<=)
    agg_level       — "category" | "subcategory" | "region" | "location"
                      (used when group_by=category or group_by=location)
```

Response shape (group_by=category example):
```json
{
  "version_id": 42,
  "version_label": "Jan-2025 Monthly Consensus v3",
  "group_by": "category",
  "count": 8,
  "overall": {
    "mean_mape": "6.82",
    "mean_bias": "1.24",
    "record_count": 1440
  },
  "results": [
    {
      "group_key":    "Braking Systems",
      "mean_mape":    "5.10",
      "mean_bias":    "0.80",
      "record_count": 240,
      "min_mape":     "0.40",
      "max_mape":     "22.10",
      "over_forecast_pct": 62.5
    },
    ...
  ]
}
```

### 6b. View

Add to `mysite/api/demand/views.py`:

```python
class ForecastVersionAccuracyView(DemandFeatureMixin, APIView):
    """
    GET /api/demand/forecast-versions/{id}/accuracy/

    Returns ForecastAccuracy records grouped and averaged by the requested
    dimension. Uses DuckDB for fast in-memory aggregation over potentially
    large accuracy result sets.

    group_by options:
        'category'  — grouped by Item.category (or Item.subcategory)
        'location'  — grouped by PlanningLocation.code
        'period'    — grouped by period_start (time series of accuracy)
        'item'      — per-item MAPE/Bias (for detailed drilldown)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        import datetime
        import duckdb
        import pandas as pd
        from mysite.models.demand.forecast import ForecastAccuracy

        version = get_object_or_404(ForecastVersion, pk=pk, client=request.client)

        group_by = request.query_params.get('group_by', 'category').lower()
        if group_by not in ('category', 'location', 'period', 'item'):
            return Response(
                {'detail': 'group_by must be one of: category, location, period, item.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Build queryset ────────────────────────────────────────────────────
        qs = (
            ForecastAccuracy.objects
            .filter(version=version)
            .select_related('item', 'planning_location')
            .values(
                'item__item_id',
                'item__name',
                'item__category',
                'planning_location__code',
                'planning_location__name',
                'period_start',
                'actual_qty',
                'forecast_qty',
                'mape',
                'bias',
            )
        )

        p = request.query_params
        if p.get('period_start'):
            try:
                qs = qs.filter(
                    period_start__gte=datetime.date.fromisoformat(p['period_start'])
                )
            except ValueError:
                pass
        if p.get('period_end'):
            try:
                qs = qs.filter(
                    period_start__lte=datetime.date.fromisoformat(p['period_end'])
                )
            except ValueError:
                pass

        if not qs.exists():
            return Response({
                'version_id':    version.pk,
                'version_label': version.version_label,
                'group_by':      group_by,
                'count':         0,
                'overall':       None,
                'results':       [],
                'detail':        (
                    'No accuracy records found. Run the compute_accuracy task '
                    'after actuals have landed for the forecast period.'
                ),
            })

        df = pd.DataFrame(list(qs))
        # Rename columns for DuckDB readability
        df.columns = [c.replace('__', '_') for c in df.columns]
        # Ensure numeric types
        for col in ('mape', 'bias', 'actual_qty', 'forecast_qty'):
            df[col] = pd.to_numeric(df[col], errors='coerce')

        con = duckdb.connect()
        con.register('acc', df)

        # ── Group-by SQL ──────────────────────────────────────────────────────
        group_col_map = {
            'category': 'item_category',
            'location': 'planning_location_code',
            'period':   'period_start',
            'item':     'item_item_id',
        }
        group_col = group_col_map[group_by]

        group_label_map = {
            'category': 'item_category AS group_key',
            'location': 'planning_location_code AS group_key',
            'period':   "CAST(period_start AS VARCHAR) AS group_key",
            'item':     "item_item_id || ' — ' || item_name AS group_key",
        }
        group_label = group_label_map[group_by]

        grouped = con.execute(f"""
            SELECT
                {group_label},
                AVG(mape)              AS mean_mape,
                AVG(bias)              AS mean_bias,
                MIN(mape)              AS min_mape,
                MAX(mape)              AS max_mape,
                COUNT(*)               AS record_count,
                -- % of periods that are over-forecast (bias > 0)
                100.0 * SUM(CASE WHEN bias > 0 THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0) AS over_forecast_pct
            FROM acc
            WHERE mape IS NOT NULL
            GROUP BY {group_col}
            ORDER BY mean_mape ASC NULLS LAST
        """).df()

        overall = con.execute("""
            SELECT
                AVG(mape)  AS mean_mape,
                AVG(bias)  AS mean_bias,
                COUNT(*)   AS record_count
            FROM acc
            WHERE mape IS NOT NULL
        """).fetchone()

        con.close()

        def _fmt(val):
            if val is None or pd.isna(val):
                return None
            return f'{float(val):.2f}'

        results = [
            {
                'group_key':         row['group_key'],
                'mean_mape':         _fmt(row['mean_mape']),
                'mean_bias':         _fmt(row['mean_bias']),
                'min_mape':          _fmt(row['min_mape']),
                'max_mape':          _fmt(row['max_mape']),
                'record_count':      int(row['record_count']),
                'over_forecast_pct': _fmt(row['over_forecast_pct']),
            }
            for _, row in grouped.iterrows()
        ]

        return Response({
            'version_id':    version.pk,
            'version_label': version.version_label,
            'group_by':      group_by,
            'count':         len(results),
            'overall': {
                'mean_mape':    _fmt(overall[0]) if overall else None,
                'mean_bias':    _fmt(overall[1]) if overall else None,
                'record_count': int(overall[2])  if overall else 0,
            },
            'results': results,
        })
```

---

## 7. Serializers

No new model serializers are required for Sprint 3B.6 — the accuracy dashboard and
export views return raw dicts / `HttpResponse` rather than DRF serializers.

Update `ForecastVersionSerializer` to expose `locked_at`:

```python
# In ForecastVersionSerializer.Meta.fields — add 'locked_at'
# It is already on the model; just needs to be in the fields list.

class ForecastVersionSerializer(serializers.ModelSerializer):
    ...
    class Meta:
        model  = ForecastVersion
        fields = [
            'id', 'version_label', 'period_type',
            'base_period_end', 'horizon_periods',
            'engine_config', 'status', 'is_editable',
            'created_by_name', 'approved_by_name',
            'approved_at', 'locked_at',           # ← locked_at was already on model
            'copied_from', 'notes',
            'created_at', 'updated_at',
            'line_count',
            'run_status', 'celery_task_id', 'run_error',   # from 3B.4
        ]
        read_only_fields = [
            'status', 'approved_by_name', 'approved_at',
            'locked_at', 'created_at', 'updated_at',
            'is_editable', 'run_status', 'celery_task_id', 'run_error',
        ]
```

---

## 8. URL Additions

### 8a. REST API URLs — append to `mysite/api/demand/urls.py`

```python
# Sprint 3B.6 additions

urlpatterns += [
    # Export as .xlsx
    path(
        'forecast-versions/<int:pk>/export/',
        views.ForecastVersionExportView.as_view(),
        name='demand-forecast-version-export',
    ),
    # Accuracy dashboard
    path(
        'forecast-versions/<int:pk>/accuracy/',
        views.ForecastVersionAccuracyView.as_view(),
        name='demand-forecast-version-accuracy',
    ),
]
```

### 8b. HTMX partial URLs — append to `mysite/urls.py` (or `mysite/demand_urls.py`)

```python
from mysite.views.demand.forecast_htmx import (
    approval_panel,
    approval_reject_form,
    approval_copy_form,
)

urlpatterns += [
    path(
        'demand/partials/approval-panel/<int:pk>/',
        approval_panel,
        name='demand-approval-panel',
    ),
    path(
        'demand/partials/approval-reject-form/<int:pk>/',
        approval_reject_form,
        name='demand-approval-reject-form',
    ),
    path(
        'demand/partials/approval-copy-form/<int:pk>/',
        approval_copy_form,
        name='demand-approval-copy-form',
    ),
]
```

### 8c. Celery task registration

Ensure `mysite/tasks/demand/notifications.py` is auto-discovered. If you use explicit
`CELERY_IMPORTS` in settings, add:

```python
CELERY_IMPORTS = [
    ...
    'mysite.tasks.demand.notifications',
]
```

If you use `autodiscover_tasks()` with the `mysite` app, no change is needed.

---

## 9. Unit Tests

Add to `mysite/tests/demand/test_export_approval.py`:

```python
"""
Sprint 3B.6 unit tests — export, approval workflow, accuracy dashboard.
"""
import datetime
import io
import pytest
from decimal import Decimal
from rest_framework.test import APIClient
from openpyxl import load_workbook

from mysite.models.demand.forecast import (
    ForecastVersion, ForecastLine, ForecastAccuracy,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures (re-use from earlier sprints where possible)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def api_client(db, django_user_model):
    user = django_user_model.objects.create_user(
        username='exporter', password='pass', email='exporter@example.com'
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def version_with_lines(db, draft_version, active_item, leaf_location):
    """
    Version with 6 ForecastLine rows: 2 items × 3 monthly periods.
    """
    periods = [
        (datetime.date(2025, 1, 1), datetime.date(2025, 1, 31)),
        (datetime.date(2025, 2, 1), datetime.date(2025, 2, 28)),
        (datetime.date(2025, 3, 1), datetime.date(2025, 3, 31)),
    ]
    lines = []
    for ps, pe in periods:
        line = ForecastLine.objects.create(
            version           = draft_version,
            item              = active_item,
            planning_location = leaf_location,
            planning_customer = None,
            period_type       = 'month',
            period_start      = ps,
            period_end        = pe,
            statistical_qty   = Decimal('100.000'),
            final_qty         = Decimal('100.000'),
            price_used        = Decimal('150.00'),
            statistical_value = Decimal('15000.00'),
            final_value       = Decimal('15000.00'),
            model_used        = 'AutoETS',
            forecast_level    = 'item_cust_location',
        )
        lines.append(line)
    return draft_version, lines


# ─────────────────────────────────────────────────────────────────────────────
# Test: Export endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestForecastExport:

    def test_export_returns_xlsx_content_type(self, api_client, version_with_lines):
        client, user = api_client
        version, lines = version_with_lines
        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        assert resp.status_code == 200
        assert (
            'spreadsheetml' in resp['Content-Type']
            or 'xlsx' in resp['Content-Type']
        )
        assert 'attachment' in resp['Content-Disposition']
        assert '.xlsx' in resp['Content-Disposition']

    def test_export_row_count_matches_forecast_line_count(
        self, api_client, version_with_lines
    ):
        """
        The 'Forecast' sheet must have one data row per unique
        (location, item, customer) combination — not per ForecastLine.
        With 3 periods for 1 item at 1 location, there should be 1 data row
        and 3 period columns.
        """
        client, user = api_client
        version, lines = version_with_lines

        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        assert resp.status_code == 200

        wb  = load_workbook(io.BytesIO(resp.content))
        ws  = wb['Forecast']

        # Rows 1, 2 = title/meta; row 3 = spacer; row 4 = headers; row 5+ = data
        data_rows = [
            row for row in ws.iter_rows(min_row=5, values_only=True)
            if any(cell is not None for cell in row)
        ]
        # 1 unique (location, item, customer) → 1 data row
        assert len(data_rows) == 1

    def test_export_period_columns_match_distinct_periods(
        self, api_client, version_with_lines
    ):
        """
        The number of period columns = number of distinct period_start values.
        Fixed columns = 6; periods = 3 → total columns = 9.
        """
        client, user = api_client
        version, lines = version_with_lines

        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        wb   = load_workbook(io.BytesIO(resp.content))
        ws   = wb['Forecast']

        header_row = [cell.value for cell in ws[4] if cell.value is not None]
        # 6 fixed + 3 period labels
        assert len(header_row) == 9
        # Period labels look like 'Jan-25'
        period_labels = header_row[6:]
        for label in period_labels:
            assert len(label) == 6    # e.g. 'Jan-25'
            assert '-' in label

    def test_export_final_qty_values_in_cells(self, api_client, version_with_lines):
        """Cell values in period columns equal final_qty for that period."""
        client, user = api_client
        version, lines = version_with_lines

        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        wb   = load_workbook(io.BytesIO(resp.content))
        ws   = wb['Forecast']

        # Data row 5, columns 7–9 = the three period quantities
        data_row = [cell.value for cell in ws[5]]
        qty_cells = [v for v in data_row if isinstance(v, (int, float))]
        assert qty_cells, 'No numeric values found in data row'
        # All lines have final_qty = 100.0
        for qty in qty_cells:
            assert abs(qty - 100.0) < 0.001

    def test_export_works_on_locked_version(self, api_client, version_with_lines):
        """Export must succeed on LOCKED versions — these are the PO baseline."""
        client, user = api_client
        version, lines = version_with_lines

        # Promote to LOCKED
        version.status    = ForecastVersion.Status.LOCKED
        version.locked_at = __import__('django.utils.timezone', fromlist=['now']).now()
        version.save(update_fields=['status', 'locked_at'])

        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        assert resp.status_code == 200
        assert 'spreadsheetml' in resp['Content-Type']

    def test_export_returns_404_when_no_lines(self, api_client, draft_version):
        """Exporting a version with no ForecastLine rows returns 404."""
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{draft_version.pk}/export/'
        )
        assert resp.status_code == 404

    def test_export_summary_sheet_exists(self, api_client, version_with_lines):
        """Workbook must have a 'Summary' sheet."""
        client, user = api_client
        version, lines = version_with_lines

        resp = client.get(f'/api/demand/forecast-versions/{version.pk}/export/')
        wb   = load_workbook(io.BytesIO(resp.content))
        assert 'Summary' in wb.sheetnames

    def test_export_location_filter(self, api_client, version_with_lines):
        """location_code param must filter exported lines."""
        client, user = api_client
        version, lines = version_with_lines
        location_code = lines[0].planning_location.code

        resp = client.get(
            f'/api/demand/forecast-versions/{version.pk}/export/'
            f'?location_code={location_code}'
        )
        assert resp.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Test: Approval workflow state transitions
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestApprovalWorkflow:

    def _approve_url(self, version_id):
        return f'/api/demand/forecast-versions/{version_id}/approve/'

    def test_submit_draft_to_in_review(self, api_client, draft_version):
        client, user = api_client
        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'submit'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'IN_REVIEW'

    def test_approve_in_review_to_approved(self, api_client, draft_version):
        client, user = api_client
        draft_version.status = ForecastVersion.Status.IN_REVIEW
        draft_version.save(update_fields=['status'])

        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'approve'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'APPROVED'

    def test_reject_in_review_to_draft(self, api_client, draft_version):
        client, user = api_client
        draft_version.status = ForecastVersion.Status.IN_REVIEW
        draft_version.save(update_fields=['status'])

        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'reject', 'note': 'North region totals need revision'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'DRAFT'

    def test_lock_approved_to_locked(self, api_client, draft_version):
        client, user = api_client
        draft_version.status = ForecastVersion.Status.APPROVED
        draft_version.save(update_fields=['status'])

        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'lock'},
            format='json',
        )
        assert resp.status_code == 200
        assert resp.data['status'] == 'LOCKED'
        # Confirm locked_at is now set
        draft_version.refresh_from_db()
        assert draft_version.locked_at is not None

    def test_illegal_transition_returns_403(self, api_client, draft_version):
        """Trying to lock a DRAFT version (skipping IN_REVIEW) must return 403."""
        client, user = api_client
        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'lock'},
            format='json',
        )
        assert resp.status_code == 403

    def test_copy_any_status_creates_draft(self, api_client, draft_version):
        client, user = api_client
        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'copy', 'note': 'Feb-2025 Plan v1'},
            format='json',
        )
        assert resp.status_code == 201
        assert resp.data['status'] == 'DRAFT'
        assert resp.data['version_label'] == 'Feb-2025 Plan v1'

    def test_note_appended_to_version_notes(self, api_client, draft_version):
        """A note provided on submit must be appended to ForecastVersion.notes."""
        client, user = api_client
        resp = client.post(
            self._approve_url(draft_version.pk),
            {'action': 'submit', 'note': 'Ready for monthly consensus review'},
            format='json',
        )
        assert resp.status_code == 200
        draft_version.refresh_from_db()
        assert 'Ready for monthly consensus review' in draft_version.notes


# ─────────────────────────────────────────────────────────────────────────────
# Test: Accuracy dashboard endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAccuracyDashboard:

    @pytest.fixture
    def version_with_accuracy(self, db, draft_version, active_item, leaf_location):
        """A version with 4 ForecastAccuracy rows across 2 periods."""
        for ps, pe in [
            (datetime.date(2025, 1, 1), datetime.date(2025, 1, 31)),
            (datetime.date(2025, 2, 1), datetime.date(2025, 2, 28)),
        ]:
            ForecastAccuracy.objects.create(
                version              = draft_version,
                item                 = active_item,
                planning_location    = leaf_location,
                planning_customer    = None,
                period_type          = 'month',
                period_start         = ps,
                period_end           = pe,
                actual_qty           = Decimal('100.000'),
                forecast_qty         = Decimal('110.000'),
                mape                 = Decimal('10.0000'),
                bias                 = Decimal('10.0000'),
            )
        return draft_version

    def test_accuracy_endpoint_returns_200(
        self, api_client, version_with_accuracy
    ):
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{version_with_accuracy.pk}/accuracy/'
        )
        assert resp.status_code == 200
        assert resp.data['count'] >= 1

    def test_accuracy_overall_mape_computed(
        self, api_client, version_with_accuracy
    ):
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{version_with_accuracy.pk}/accuracy/'
            f'?group_by=period'
        )
        assert resp.status_code == 200
        overall = resp.data.get('overall')
        assert overall is not None
        assert float(overall['mean_mape']) == pytest.approx(10.0, abs=0.1)

    def test_accuracy_group_by_period(self, api_client, version_with_accuracy):
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{version_with_accuracy.pk}/accuracy/'
            f'?group_by=period'
        )
        assert resp.status_code == 200
        assert resp.data['group_by'] == 'period'
        # 2 periods should give 2 result rows
        assert resp.data['count'] == 2

    def test_accuracy_returns_empty_gracefully_with_no_records(
        self, api_client, draft_version
    ):
        """Version with no accuracy records returns 200 with empty results."""
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{draft_version.pk}/accuracy/'
        )
        assert resp.status_code == 200
        assert resp.data['count'] == 0
        assert resp.data['results'] == []

    def test_accuracy_invalid_group_by_returns_400(
        self, api_client, version_with_accuracy
    ):
        client, user = api_client
        resp = client.get(
            f'/api/demand/forecast-versions/{version_with_accuracy.pk}/accuracy/'
            f'?group_by=invalid'
        )
        assert resp.status_code == 400
```

---

## 10. Migration and Checklist

No migration required — all models exist from Sprints 3B.3–3B.4.

```bash
# Confirm no drift
python manage.py migrate --check
python manage.py check

# Run new tests
pytest mysite/tests/demand/test_export_approval.py -v

# Full demand suite regression check
pytest mysite/tests/demand/ -v
```

**New files created in 3B.6:**

```
mysite/tasks/demand/notifications.py
mysite/templates/demand/email/
    forecast_submitted_for_review.txt
    forecast_submitted_for_review.html
    forecast_approved.txt
    forecast_approved.html
    forecast_rejected.txt
    forecast_rejected.html
    forecast_locked.txt
    forecast_locked.html
mysite/templates/demand/partials/
    approval_panel.html
    approval_rejected_note.html
    approval_copy_form.html
mysite/tests/demand/test_export_approval.py
```

**Modified files:**

```
mysite/api/demand/views.py
    — ForecastVersionApproveView.post() fires send_forecast_status_email.delay()
    — ForecastVersionExportView added
    — ForecastVersionAccuracyView added
mysite/api/demand/serializers.py
    — ForecastVersionSerializer.Meta.fields adds 'locked_at'
mysite/api/demand/urls.py
    — /export/ and /accuracy/ paths added
mysite/views/demand/forecast_htmx.py
    — approval_panel, approval_reject_form, approval_copy_form views added
mysite/urls.py (or demand_urls.py)
    — 3 approval partial paths added
```

**Final Sprint 3B.6 checklist:**

```
── APPROVAL WORKFLOW UI ───────────────────────────────────────────────────────
[x] approval_panel.html — status badge + buttons that vary by status
[x] approval_rejected_note.html — reject modal with required note textarea
[x] approval_copy_form.html — copy modal with editable new label
[x] HTMX views: approval_panel, approval_reject_form, approval_copy_form
[x] 3 non-API URL paths for HTMX partials

── EMAIL NOTIFICATIONS ────────────────────────────────────────────────────────
[x] notifications.py — send_forecast_status_email Celery task
[x] _get_recipients() — distinct recipient list per transition type
[x] 4 .txt email templates (submitted, approved, rejected, locked)
[x] 4 .html email templates (matching pair for each .txt)
[x] ForecastVersionApproveView.post() fires task after every transition
[x] CELERY_IMPORTS updated (if not using autodiscover)
[x] SITE_URL in settings.py (for email links)

── EXPORT ENDPOINT ────────────────────────────────────────────────────────────
[x] GET /api/demand/forecast-versions/{id}/export/
[x] ForecastVersionExportView — streams .xlsx HttpResponse
[x] Sheet 1 "Forecast": Location × Item pivot, period columns, freeze panes
[x] Sheet 2 "Summary": period totals with SUM formulas
[x] Highlighted rows (OVR_FILL) for lines with overrides applied
[x] Filter params: forecast_level, location_code, period_start, period_end
[x] Returns 404 when no lines match filters
[x] Works on any version status (DRAFT preview through LOCKED PO export)

── ACCURACY DASHBOARD ─────────────────────────────────────────────────────────
[x] GET /api/demand/forecast-versions/{id}/accuracy/
[x] ForecastVersionAccuracyView — DuckDB aggregation
[x] group_by: category | location | period | item
[x] overall MAPE/Bias summary in response envelope
[x] Returns 200 with empty results when no accuracy records exist
[x] Returns 400 for invalid group_by value

── URLS ───────────────────────────────────────────────────────────────────────
[x] /export/   added to mysite/api/demand/urls.py
[x] /accuracy/ added to mysite/api/demand/urls.py
[x] 3 HTMX partial paths added to non-API URL conf

── UNIT TESTS ────────────────────────────────────────────────────────────────
[x] TestForecastExport         (7 tests)
      content-type is spreadsheetml
      row count = unique (location, item, customer) count
      period column count = distinct periods
      cell values equal final_qty
      LOCKED version export succeeds
      404 when no lines
      Summary sheet exists
      location_code filter respected
[x] TestApprovalWorkflow       (7 tests)
      DRAFT → IN_REVIEW (submit)
      IN_REVIEW → APPROVED (approve)
      IN_REVIEW → DRAFT (reject)
      APPROVED → LOCKED (lock) + locked_at stamped
      illegal transition → 403
      copy → new DRAFT with given label
      note appended to version.notes
[x] TestAccuracyDashboard      (5 tests)
      200 with results
      overall mean_mape computed correctly
      group_by=period → 2 rows for 2 periods
      no accuracy records → 200 empty gracefully
      invalid group_by → 400

── SETTINGS TO CONFIRM ────────────────────────────────────────────────────────
[ ] SITE_URL = 'https://your-domain.com'   (for email links)
[ ] DEFAULT_FROM_EMAIL set
[ ] EMAIL_BACKEND configured (SMTP in prod, console/file in dev)
[ ] Celery broker reachable from notifications task
```
