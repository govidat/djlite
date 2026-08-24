# utils/demand/actuals_net.py
"""
Composed baseline netting: SCHEME FIRST, THEN OUTLIER.

baseline_qty     = scheme_net_qty    − outlier_qty_adjustment
baseline_revenue = scheme_net_revenue − outlier_revenue_adjustment

Callers:
  config = getattr(client, "forecasting_config", None)
  use_net = config.forecast_uses_net_actuals if config else False
"""

from django.db.models import Case, CharField, DecimalField, F, IntegerField, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce

from mysite.models.demand.actuals import ActualSale


def _window_factors():
    """Per-row window factors via correlated Subquery (is_shadow=False).

    Overlap (Phase 6) resolves most-specific-wins by ordering on scheme_code;
    deterministic pick of the first row. NULL when the grain+period is not a
    window for any ACTIVE scheme.
    """
    from mysite.models.demand.schemes import ResolvedSalesSchemePeriod
    qs = ResolvedSalesSchemePeriod.objects.filter(
        item=OuterRef("item"), planning_location=OuterRef("planning_location"),
        planning_customer=OuterRef("planning_customer"),
        distribution_channel=OuterRef("distribution_channel"),
        period_type=OuterRef("period_type"), period_start=OuterRef("period_start"),
        is_shadow=False,
    )
    return {
        "qty_factor": Subquery(qs.order_by("scheme__scheme_code").values("qty_factor")[:1]),
        "value_factor": Subquery(qs.order_by("scheme__scheme_code").values("value_factor")[:1]),
    }


def _shadow_addbacks(client_pk: int):
    """Per-row shadow add-backs via a grouped correlated Subquery (is_shadow=True).

    For each matching shadow row:
        addback_qty     = window_qty     × (1 − 1/anchor_qty_factor)    × addback_qty_weight
        addback_revenue = window_revenue × (1 − 1/anchor_value_factor) × addback_value_weight
    where window_qty / window_revenue are the ANCHOR WINDOW period's raw
    actuals at the same grain. Summed across schemes (shadow overlap is
    additive). NULL when the grain+period is not a shadow for any scheme.
    """
    from mysite.models.demand.schemes import ResolvedSalesSchemePeriod
    shadow = ResolvedSalesSchemePeriod.objects.filter(
        item=OuterRef("item"), planning_location=OuterRef("planning_location"),
        planning_customer=OuterRef("planning_customer"),
        distribution_channel=OuterRef("distribution_channel"),
        period_type=OuterRef("period_type"), period_start=OuterRef("period_start"),
        is_shadow=True,
    ).annotate(
        window_qty=Subquery(
            ActualSale.objects.filter(
                client_id=client_pk, item=OuterRef("item"),
                planning_location=OuterRef("planning_location"),
                planning_customer=OuterRef("planning_customer"),
                distribution_channel=OuterRef("distribution_channel"),
                period_start=OuterRef("anchor_period_start"),
            ).values("qty")[:1]
        ),
        window_revenue=Subquery(
            ActualSale.objects.filter(
                client_id=client_pk, item=OuterRef("item"),
                planning_location=OuterRef("planning_location"),
                planning_customer=OuterRef("planning_customer"),
                distribution_channel=OuterRef("distribution_channel"),
                period_start=OuterRef("anchor_period_start"),
            ).values("revenue")[:1]
        ),
        addback_qty=F("window_qty") * (1 - 1 / F("anchor_qty_factor")) * F("addback_qty_weight"),
        addback_revenue=F("window_revenue") * (1 - 1 / F("anchor_value_factor")) * F("addback_value_weight"),
    )
    return {
        "shadow_addback_qty": Subquery(
            shadow.values("item").annotate(total=Sum("addback_qty")).values("total")[:1]),
        "shadow_addback_revenue": Subquery(
            shadow.values("item").annotate(total=Sum("addback_revenue")).values("total")[:1]),
    }


def scheme_netted_queryset(client, use_scheme_net: bool):
    """Annotate scheme_net_qty / scheme_net_revenue on ActualSale rows.

    Window rows DIVIDE (multiplicative, uplift scales with demand level);
    shadow rows ADD BACK a share of the anchor window's uplift. A row that is
    a window for one scheme and a shadow for another gets both branches
    composed. Outlier netting runs AFTER this (subtractive).
    """
    qs = ActualSale.objects.filter(client=client)
    if not use_scheme_net:
        return qs.annotate(scheme_net_qty=F("qty"), scheme_net_revenue=F("revenue"))

    qs = qs.annotate(**_window_factors()).annotate(**_shadow_addbacks(client.pk))
    return qs.annotate(
        # Division branch only when a window matches (qty_factor non-NULL);
        # COALESCE keeps non-window rows at raw qty.
        scheme_net_qty=Coalesce(
            F("qty") / F("qty_factor"), F("qty")
        ) + Coalesce(F("shadow_addback_qty"), Value(0), output_field=DecimalField()),
        scheme_net_revenue=Coalesce(
            F("revenue") / F("value_factor"), F("revenue")
        ) + Coalesce(F("shadow_addback_revenue"), Value(0), output_field=DecimalField()),
    )


def actuals_queryset_with_net(client, use_net: bool, use_scheme_net: bool = None,
                              use_substitution: bool = False):
    """
    Returns an ActualSale queryset for `client`, annotated with net_qty / net_revenue.

    Composed baseline netting: SCHEME FIRST, THEN OUTLIER.
    baseline_qty     = scheme_net_qty    − outlier_qty_adjustment
    baseline_revenue = scheme_net_revenue − outlier_revenue_adjustment

    use_net is supplied by the caller from the relevant Client flag
    (client.forecast_uses_net_actuals / client.reporting_uses_net_actuals /
    client.abc_classification_uses_net_actuals). This function itself doesn't
    read any flag off `client` — keeping it flag-agnostic means all three
    call sites share one code path and one set of tests.

    use_scheme_net defaults to config.scheme_net_actuals when not provided.

    When use_substitution is True each row additionally carries:
      eff_item_id / eff_item_code  — the item the row should be keyed to
        (successor when the row converts, the row's own item otherwise)
      net_qty / net_revenue        — already scaled by conversion_factor when
        the row converts (effective/effective values)
    The effective-from rule is exclusive: a row converts only when
    period_start < effective_from (or effective_from is NULL). Rows on/after
    the launch date stay with the old item, unconverted.
    """
    if use_scheme_net is None:
        use_scheme_net = getattr(
            getattr(client, "forecasting_config", None),
            "scheme_net_actuals", False,
        )
    qs = scheme_netted_queryset(client, use_scheme_net).select_related("outlier_adjustment")

    if not use_net:
        qs = qs.annotate(
            net_qty=F("scheme_net_qty"),
            net_revenue=F("scheme_net_revenue"),
        )
    else:
        qs = qs.annotate(
            net_qty=Case(
                When(
                    outlier_adjustment__status="CONFIRMED",
                    then=F("scheme_net_qty") - F("outlier_adjustment__qty_adjustment"),
                ),
                default=F("scheme_net_qty"),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            ),
            net_revenue=Case(
                When(
                    outlier_adjustment__status="CONFIRMED",
                    then=F("scheme_net_revenue") - Coalesce(
                        F("outlier_adjustment__revenue_adjustment"),
                        Value(0),
                    ),
                ),
                default=F("scheme_net_revenue"),
                output_field=DecimalField(max_digits=16, decimal_places=2),
            ),
        )

    if use_substitution:
        from mysite.models.demand.lifecycle import ItemSubstitution
        sub = (ItemSubstitution.objects
               .filter(client_id=OuterRef("client_id"),
                       old_item_id=OuterRef("item_id"))
               .values("new_item_id", "conversion_factor", "effective_from"))
        converts = (Q(sub_new_id__isnull=False)
                    & (Q(sub_eff_from__isnull=True)
                       | Q(period_start__lt=F("sub_eff_from"))))
        qs = (qs.annotate(
            sub_new_id=Subquery(sub.values("new_item_id")[:1]),
            sub_factor=Subquery(sub.values("conversion_factor")[:1]),
            sub_eff_from=Subquery(sub.values("effective_from")[:1]),
        ).annotate(
            eff_item_id=Coalesce(
                Case(When(converts, then=F("sub_new_id")),
                     default=None, output_field=IntegerField()),
                F("item_id")),
            net_qty=F("net_qty") * Coalesce(
                Case(When(converts, then=F("sub_factor")),
                     default=None, output_field=DecimalField(max_digits=14, decimal_places=6)),
                Value(1), output_field=DecimalField(max_digits=14, decimal_places=6)),
            net_revenue=F("net_revenue") * Coalesce(
                Case(When(converts, then=F("sub_factor")),
                     default=None, output_field=DecimalField(max_digits=14, decimal_places=6)),
                Value(1), output_field=DecimalField(max_digits=16, decimal_places=2)),
        ))

    return qs


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
