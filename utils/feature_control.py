# utils/feature_control.py

from django.core.cache import cache
from django.utils import timezone
from django.db import models
from mysite.models import ClientFeatureControl
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.conf import settings

CACHE_TTL = 900  # 15 minutes. Anyway cache bust will take care if there is any change

# ALSO UPDATE utils > feature_control.py

_FEATURE_HIERARCHY = {
    "demand_planning": frozenset({
        "actuals_upload",
        "forecast_run",
        "consensus_override",
        "forecast_approval",
        "outlier_management",
        "scheme_management",
        "item_lifecycle",
    }),
    "inventory":  frozenset(),   # populate in Phase 2
    "ecommerce":  frozenset(),   # populate in Phase 3
    "master_data": frozenset(),  # client Master Data upload UI
}

# Reverse lookup: sub-feature → parent
_SUBFEATURE_PARENT = {
    sub: parent
    for parent, children in _FEATURE_HIERARCHY.items()
    for sub in children
}


def is_feature_disabled(client, feature: str) -> dict:
    """
    Checks feature flag, respecting parent-child hierarchy.
    If a sub-feature's parent is disabled, the sub-feature is
    implicitly disabled regardless of its own row.
    """
    parent = _SUBFEATURE_PARENT.get(feature)
    if parent:
        master = _check_feature_disabled(client, parent)
        if master["disabled"]:
            return {
                "disabled": True,
                "message": master["message"] or f"{parent.replace('_', ' ').title()} is not enabled for this account.",
            }
    return _check_feature_disabled(client, feature)

def _check_feature_disabled(client, feature: str) -> dict:
    if client is None and not settings.DEBUG:
        # No client context — fail open (don't block) but log it
        import logging
        logging.getLogger(__name__).warning(
            "is_feature_disabled called with client=None for feature=%s", feature
        )

    """Raw DB/cache lookup — no hierarchy logic."""
    client_code = client.client_code if client else "global"
    cache_key = f"feature_control:{client_code}:{feature}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    now = timezone.now()
    base_qs = ClientFeatureControl.objects.filter(
        feature=feature,
        is_disabled=True,
        from_date__lte=now,
        to_date__gte=now,
    )
    obj = base_qs.filter(client__isnull=True).first()
    if obj is None and client:
        obj = base_qs.filter(client=client).first()

    result = {"disabled": bool(obj), "message": obj.message if obj else ""}
    cache.set(cache_key, result, CACHE_TTL)
    return result


# Backward compat — remove once all call sites use is_feature_disabled()
def is_demand_feature_disabled(client, feature: str) -> dict:
    return is_feature_disabled(client, feature)


 
# ── 2. View decorator ─────────────────────────────────────────────────────────
#
# Usage:
#   @demand_feature_required("actuals_upload")
#   def upload_actuals_view(request, client_slug):
#       ...
#
# Expects the view to have `request.client` set (via your ClientScopedMixin
# or middleware). Renders demand/feature_disabled.html on block; raise
# PermissionDenied if you prefer a hard 403 instead.
#
# The template receives: {{ message }}
 
def demand_feature_required(feature, template="demand/feature_disabled.html"):
    """
    Decorator factory for class-based or function-based views.
 
    For function-based views:
        @demand_feature_required("forecast_run")
        def my_view(request): ...
 
    For class-based views, apply in urls.py:
        path("...", demand_feature_required("forecast_run")(MyView.as_view()))
    """
    from functools import wraps
    from django.shortcuts import render
 
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            client = getattr(request, "client", None)
            result = is_feature_disabled(client, feature)
            if result["disabled"]:
                return render(
                    request,
                    template,
                    {"message": result["message"] or "This feature is currently unavailable."},
                    status=403,
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
 
 
# ── 3. Celery task guard ──────────────────────────────────────────────────────
#
# Usage inside a Celery task:
#
#   from mysite.models import Client
#   from utils.feature_control import celery_demand_feature_guard
#
#   @app.task(bind=True)
#   def run_forecast_task(self, client_code):
#       client = Client.objects.get(pk=client_code)
#       skip = celery_demand_feature_guard(client, "forecast_run")
#       if skip:
#           return skip           # {"status": "skipped", "reason": "..."}
#       # ... proceed with forecast
 
def celery_demand_feature_guard(client, feature):
    """
    Returns a skip-result dict if the feature is disabled, else None.
 
    Callers treat a non-None return as an early exit:
        skip = celery_demand_feature_guard(client, "forecast_run")
        if skip:
            return skip
 
    Return shape on skip:
        {"status": "skipped", "feature": str, "reason": str}
    Return on proceed:
        None
    """
    result = is_feature_disabled(client, feature)
    if result["disabled"]:
        return {
            "status": "skipped",
            "feature": feature,
            "reason": result["message"] or f"Feature '{feature}' is currently disabled.",
        }
    return None
 

def outlier_ui_visible(client) -> bool:
    """
    True when the outlier-management UI (sidebar section, aggregates
    include/exclude toggle) should be shown for this client.
 
    ClientFeatureControl is a DISABLER, not an enabler — no row at all
    means the feature is available by default; a row only takes effect
    while is_disabled=True and now falls within [from_date, to_date].
    is_feature_disabled() already encodes that plus the parent/sub-feature
    cascade ('outlier_management' -> 'demand_planning'), so this is a thin
    wrapper rather than a second implementation of the same check — kept
    here (not duplicated inline in the context processor and the view) so
    both call sites can never drift out of sync with each other.
    """
    if client is None:
        return False
 
    result = is_feature_disabled(client, 'outlier_management')
    return not result['disabled']

def scheme_ui_visible(client) -> bool:
    """
    True when the scheme-management UI should be shown for this client.
    Same disabler logic as outlier_ui_visible.
    """
    if client is None:
        return False
    result = is_feature_disabled(client, 'scheme_management')
    return not result['disabled']

def item_lifecycle_ui_visible(client) -> bool:
    """
    True when the item-lifecycle UI (substitution / discontinuation /
    introduction sections) should be shown for this client.
    """
    if client is None:
        return False
    result = is_feature_disabled(client, 'item_lifecycle')
    return not result['disabled']

def demand_ui_visible(client) -> bool:

    if client is None:
        return False
 
    result = is_feature_disabled(client, 'demand_planning')
    return not result['disabled']

# ── 4. Cache invalidation helper ─────────────────────────────────────────────
#
# Call this from a post_save signal or admin action whenever a
# ClientFeatureControl row is saved, so the 15-minute cache doesn't
# serve stale data after an admin toggles a feature.
#
# Wire the signal in apps.py:
#
#   from django.db.models.signals import post_save
#   from mysite.models import ClientFeatureControl
#   from utils.feature_control import bust_feature_cache
#
#   class MysiteConfig(AppConfig):
#       def ready(self):
#           post_save.connect(bust_feature_cache, sender=ClientFeatureControl)
 
def bust_feature_cache(sender, instance, **kwargs):
    """
    post_save signal handler for ClientFeatureControl.
    Clears the cache key for the affected (client, feature) combination.
    Also clears the global key in case a client-specific row shadows it.
    """
    feature = instance.feature
    client_code = instance.client.client_code if instance.client else "global"
 
    keys_to_delete = [
        f"feature_control:{client_code}:{feature}",
        f"feature_control:global:{feature}",   # always clear global too
    ]
    cache.delete_many(keys_to_delete)
