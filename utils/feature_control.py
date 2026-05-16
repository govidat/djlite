# utils/feature_control.py

from django.core.cache import cache
from django.utils import timezone
from django.db import models
from mysite.models import ClientFeatureControl



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