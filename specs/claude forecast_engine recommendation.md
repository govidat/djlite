4. Residual disaggregation (requirement 4) — forecast_engine.py
```
def disaggregate_with_residual(
    parent_forecast: dict[tuple[str, pd.Timestamp], float],   # {(parent_uid, ds): qty}
    children_own_forecasts: dict[tuple[str, pd.Timestamp], float],  # forecastable peers' own atomic forecasts
    lumpy_children_hist_qty: dict[str, float],   # {child_uid: total historical qty}
    child_to_parent: dict[str, str],             # child_uid -> parent_uid
    periods: list[pd.Timestamp],
) -> dict[tuple[str, pd.Timestamp], float]:
    """
    For each (parent, ds):
        remaining = parent_forecast[parent, ds] - sum(children_own_forecasts for that parent's
                                                        forecastable children, that ds)
        remaining = max(remaining, 0.0)   # floor — flag if this trips, see note below
        for each lumpy child under that parent:
            share = hist_qty[child] / sum(hist_qty[lumpy siblings under same parent])
            result[child, ds] = remaining * share
    """
    from collections import defaultdict

    # own-forecast totals per (parent, ds), summed across only the forecastable children
    own_sum: dict[tuple[str, pd.Timestamp], float] = defaultdict(float)
    for (child_uid, ds), qty in children_own_forecasts.items():
        parent_uid = child_to_parent.get(child_uid)
        if parent_uid:
            own_sum[(parent_uid, ds)] += qty

    # group lumpy children by parent, precompute share weights
    lumpy_by_parent: dict[str, list[str]] = defaultdict(list)
    for child_uid, parent_uid in child_to_parent.items():
        if child_uid in lumpy_children_hist_qty:
            lumpy_by_parent[parent_uid].append(child_uid)

    shares: dict[str, float] = {}
    for parent_uid, kids in lumpy_by_parent.items():
        total_hist = sum(lumpy_children_hist_qty[k] for k in kids) or 1.0
        for k in kids:
            shares[k] = lumpy_children_hist_qty[k] / total_hist

    result: dict[tuple[str, pd.Timestamp], float] = {}
    for (parent_uid, ds), parent_qty in parent_forecast.items():
        already_covered = own_sum.get((parent_uid, ds), 0.0)
        remaining = parent_qty - already_covered

        if remaining < 0:
            logger.warning(
                f'disaggregate_with_residual: remaining < 0 for parent={parent_uid} ds={ds} '
                f'(parent_forecast={parent_qty:.2f}, own_children_sum={already_covered:.2f}). '
                f'Flooring to 0 — forecastable peers are collectively forecasting MORE than '
                f'the parent-level model, meaning the parent aggregate itself may need review.'
            )
            remaining = 0.0

        for child_uid in lumpy_by_parent.get(parent_uid, []):
            result[(child_uid, ds)] = remaining * shares.get(child_uid, 0.0)

    return result
```

This is the general fix — and it's exactly what would have prevented the Y/Z/DC1 double-count from earlier: instead of excluding forecastable children from the parent-level split (leaving the parent's history bias uncorrected), it subtracts their own forecasts from the parent total first, then shares only the remainder among the lumpy children.

Then in disaggregate_to_atomic(), wherever the old code built a flat members list per aggregate grain and split by qty-share across all members: split members into two groups first —

children whose own decisions[uid]['grain'] is at a finer level than the parent grain (i.e. they have their own independently-modeled forecast) → these are children_own_forecasts inputs, fed straight through unchanged (already handled by atomic_forecasts/earlier disaggregation passes at their own level).
children whose decisions[uid]['grain'] == this parent grain (the true "unforecastable, rolled up to here" group) → these are the lumpy_children_hist_qty targets for disaggregate_with_residual.

Applied to your worked example: Location Y is in the first group (own forecast, item_leaf or item_leaf_dc_cust), Location Z is in the second (item_saleshier_... pointing at DC1). remaining at DC1 = DC1's own forecast minus Y's forecast — so Z now only receives the part of DC1's predicted demand that isn't already accounted for by Y's own model. No more implicit double-count, and it works recursively level-by-level (n vs n-1) exactly as you specified, for both the Sales Hierarchy axis and the item hierarchy axis.

This also replaces the need for the reconciliation step for this specific bias — worth revisiting whether MinTrace/BottomUp still earns its keep once residual disaggregation is in, or whether it becomes purely a smoothing/coherence pass on top of an already-unbiased split.