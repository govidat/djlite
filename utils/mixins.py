from django.shortcuts import render
from utils.feature_control import is_feature_disabled

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_htmx(request) -> bool:
    return request.headers.get('HX-Request') == 'true'


def feature_gate(request, feature: str):
    """
    Returns an HttpResponse (403) if the feature is disabled, else None.
    Usage in any view:
        blocked = feature_gate(request, "forecast_run")
        if blocked:
            return blocked
    """
    result = is_feature_disabled(request.client, feature)
    if result["disabled"]:
        return render(request, "partials/feature_disabled.html", {
            "message": result["message"],
        }, status=403)
    return None


def _client_url_kwargs(request) -> dict:
    return {'client_id': request.client.client_id}