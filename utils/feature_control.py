# utils/feature_control.py

from django.core.cache import cache
from django.utils import timezone
from django.db import models
from mysite.models import ClientFeatureControl
from functools import wraps
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


CACHE_TTL = 900  # 15 minutes. Anyway cache bust will take care if there is any change


def is_feature_disabled(client, feature):
    """
    Returns:
        {
            "disabled": bool,
            "message": str,
        }

    Priority:
        1. Global rule (client=None)
        2. Client-specific rule
    """

    client_id = client.client_id if client else "global"

    cache_key = f"feature_control:{client_id}:{feature}"

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

    # ── GLOBAL override has precedence ─────────────────────
    obj = base_qs.filter(
        client__isnull=True
    ).first()

    # ── client-specific rule ───────────────────────────────
    if obj is None and client:
        obj = base_qs.filter(
            client=client
        ).first()

    result = {
        "disabled": bool(obj),
        "message": (
            obj.message
            if obj else ""
        )
    }

    cache.set(cache_key, result, CACHE_TTL)

    return result

# ─────────────────────────────────────────────────────────────────────────────
# DELTA ADDITIONS to utils/feature_control.py
# Paste these below your existing is_feature_disabled() function.
# No changes needed to the existing function.
# ─────────────────────────────────────────────────────────────────────────────
 
# Add this import at the top of the file (with your existing imports):
#   from functools import wraps
#   from django.core.exceptions import PermissionDenied
#   from django.shortcuts import render
 
 
# ── 1. Demand Planning sub-feature hierarchy ──────────────────────────────────
#
# The five demand planning features have a parent-child relationship:
# if "demand_planning" (master switch) is disabled, all sub-features
# are implicitly disabled regardless of their own rows.
#
# Sub-features that require the master switch to be on first:
_DEMAND_SUBFEATURES = frozenset({
    "actuals_upload",
    "forecast_run",
    "consensus_override",
    "forecast_approval",
})
 
 
def is_demand_feature_disabled(client, feature):
    """
    Like is_feature_disabled(), but also checks the master "demand_planning"
    switch before checking the sub-feature.
 
    Returns the same dict shape as is_feature_disabled():
        {"disabled": bool, "message": str}
 
    Usage (views):
        result = is_demand_feature_disabled(request.client, "actuals_upload")
        if result["disabled"]:
            return render(request, "demand/feature_disabled.html",
                          {"message": result["message"]}, status=403)
 
    Usage (Celery tasks):
        result = is_demand_feature_disabled(client, "forecast_run")
        if result["disabled"]:
            return {"status": "skipped", "reason": result["message"]}
    """
    # Check master switch first (only for sub-features)
    if feature in _DEMAND_SUBFEATURES:
        master = is_feature_disabled(client, "demand_planning")
        if master["disabled"]:
            return {
                "disabled": True,
                "message": master["message"] or "Demand Planning is not enabled for this account.",
            }
 
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
            result = is_demand_feature_disabled(client, feature)
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
#   def run_forecast_task(self, client_id):
#       client = Client.objects.get(pk=client_id)
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
    result = is_demand_feature_disabled(client, feature)
    if result["disabled"]:
        return {
            "status": "skipped",
            "feature": feature,
            "reason": result["message"] or f"Feature '{feature}' is currently disabled.",
        }
    return None
 
 
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
    client_id = instance.client.client_id if instance.client else "global"
 
    keys_to_delete = [
        f"feature_control:{client_id}:{feature}",
        f"feature_control:global:{feature}",   # always clear global too
    ]
    cache.delete_many(keys_to_delete)
