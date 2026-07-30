# utils/demand/actuals_net.py
from django.db.models import Case, DecimalField, F, Value, When
from django.db.models.functions import Coalesce

from mysite.models.demand.actuals import ActualSale

""" Callers call
config = getattr(client, "forecasting_config", None)
use_net = config.forecast_uses_net_actuals if config else False
"""
def actuals_queryset_with_net(client, use_net: bool):
    """
    Returns an ActualSale queryset for `client`, annotated with net_qty / net_revenue.

    use_net is supplied by the caller from the relevant Client flag
    (client.forecast_uses_net_actuals / client.reporting_uses_net_actuals /
    client.abc_classification_uses_net_actuals). This function itself doesn't
    read any flag off `client` — keeping it flag-agnostic means all three
    call sites share one code path and one set of tests.
    """
    qs = ActualSale.objects.filter(client=client).select_related("outlier_adjustment")

    if not use_net:
        return qs.annotate(
            net_qty=F("qty"),
            net_revenue=F("revenue"),
        )

    return qs.annotate(
        net_qty=Case(
            When(
                outlier_adjustment__status="CONFIRMED",
                then=F("qty") - F("outlier_adjustment__qty_adjustment"),
            ),
            default=F("qty"),
            output_field=DecimalField(max_digits=14, decimal_places=3),
        ),
        net_revenue=Case(
            When(
                outlier_adjustment__status="CONFIRMED",
                then=F("revenue") - Coalesce(
                    F("outlier_adjustment__revenue_adjustment"),
                    Value(0),
                ),
            ),
            default=F("revenue"),
            output_field=DecimalField(max_digits=16, decimal_places=2),
        ),
    )


def resolve_net_actuals_choice(request, config_flag_name: str, feature_name: str = 'outlier_management') -> bool:
    """
    Shared toggle-precedence logic for reporting views: an explicit
    '?exclude_outliers=' query param always wins; absent that, fall back to
    the client's ForecastingConfig flag named by config_flag_name (e.g.
    'reporting_uses_net_actuals'); absent BOTH a request context and a
    config row, default to False (raw actuals) -- same "missing config ->
    raw" fallback used everywhere else in this system.

    Extracted into one place specifically because the inline version of
    this logic (as originally sketched in a reporting view) used
    `getattr(request.client, 'forecastingconfig', None)` -- missing the
    underscore in the real reverse accessor name (`forecasting_config`,
    per ForecastingConfig.client's related_name) -- which silently always
    returned None and defaulted every client to raw actuals regardless of
    their configured preference. One shared implementation means that typo
    can only exist in one place, not in every view that copies the pattern.

    Also respects the outlier_management feature flag: if the UI toggle
    itself shouldn't be shown (client_feature_control disables it), this
    returns the config default directly rather than reading a query param
    the UI never should have exposed in the first place.
    """
    from utils.feature_control import outlier_ui_visible

    client = getattr(request, 'client', None)
    if client is None:
        return False

    config = getattr(client, 'forecasting_config', None)
    config_default = bool(config and getattr(config, config_flag_name, False))

    if not outlier_ui_visible(client):
        return config_default

    param = request.GET.get('exclude_outliers')
    if param is not None:
        return param in ('1', 'true', 'True')

    return config_default