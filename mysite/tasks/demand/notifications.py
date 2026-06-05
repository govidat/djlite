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