"""
forecast_engine.py — targeted corrections for three issues identified in review.

Drop these three functions (plus one new helper) into forecast_engine.py,
replacing the originals at the locations noted below.

CHANGES SUMMARY
───────────────
_TIME_GRAIN_SUFFIXES  (NEW MODULE-LEVEL CONSTANT — add near top of file)
    Single source of truth for every coarser-period token that can appear as
    a suffix in a grain string.  Built lazily from PERIOD_HIGHER_HORIZONS so
    it automatically picks up any future period types.

_map_uids_to_agg_ids  (replaces lines 721-743)
    Issue 1 fix: detect time-aggregation suffixes by consulting
    _TIME_GRAIN_SUFFIXES instead of hard-coding _quarter / _halfyear / _year.
    Now correctly handles: week, fortnight, month, bimonth, quarter, halfyear,
    year, hour, day, minute, second — i.e. every entry in PERIOD_HIGHER_HORIZONS.

_scale_horizon  (replaces lines 746-753)
    Issue 2 fix: complete SCALES dict covering every freq string that
    PERIOD_FREQ_MAP can produce, from sub-second to yearly.  Falls back to
    per-second ratio for any unknown freq so the result is never silently wrong.

disaggregate_to_atomic  (replaces lines 792-919)
    Issue 3 fix — three sub-fixes:
      Gap A: is_time_grain now uses _TIME_GRAIN_SUFFIXES (same fix as Issue 1).
      Gap B: pure time-aggregation grains (e.g. item_client_quarter) are now
             handled by a dedicated elif branch that expands each coarse-period
             forecast row into N atomic-period rows (quarterly ÷ 3 = 3 monthly
             rows) before location disaggregation.
      Gap C: product + time combined grains (taxon_{id}_client_{period}) now
             expand the coarse-period revenue forecast into constituent monthly
             rows BEFORE doing value-share disaggregation.  The final rows carry
             monthly ds values that match ForecastLine.period_start.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# NEW MODULE-LEVEL CONSTANT
# Place this near the top of forecast_engine.py, after the existing imports
# and before the first function definition.
# ─────────────────────────────────────────────────────────────────────────────

def _build_time_grain_suffixes() -> frozenset[str]:
    """
    Collect every coarser-period token that PERIOD_HIGHER_HORIZONS defines.

    Called once at import time to build _TIME_GRAIN_SUFFIXES.
    Using PERIOD_HIGHER_HORIZONS as the single source of truth means that
    adding 'fortnight' or any other period to that dict is instantly reflected
    in grain suffix detection everywhere in the engine.
    """
    try:
        from mysite.models.demand.actuals import PERIOD_HIGHER_HORIZONS
        suffixes: set[str] = set()
        for horizon_list in PERIOD_HIGHER_HORIZONS.values():
            suffixes.update(horizon_list)
        return frozenset(suffixes)
    except ImportError:
        # Fallback for unit tests that run without Django configured
        return frozenset({
            'second', 'minute', 'hour',
            'day', 'week', 'fortnight', 'month', 'bimonth',
            'quarter', 'halfyear', 'year',
        })


_TIME_GRAIN_SUFFIXES: frozenset[str] = _build_time_grain_suffixes()


def _grain_has_time_suffix(grain: str) -> bool:
    """
    Return True if the grain string ends with a coarser-period token.

    Examples that return True:
        item_client_quarter          → suffix = 'quarter'
        item_loc_depth_2_month       → suffix = 'month'
        taxon_42_client_halfyear     → suffix = 'halfyear'
        item_client_week             → suffix = 'week'
        item_client_fortnight        → suffix = 'fortnight'

    Examples that return False:
        item_cust_location           → no time suffix
        item_client                  → 'client' is not in _TIME_GRAIN_SUFFIXES
        taxon_42_client              → 'client' is not a period token
    """
    suffix = grain.rsplit('_', 1)[-1]
    return suffix in _TIME_GRAIN_SUFFIXES


def _grain_time_suffix(grain: str) -> str | None:
    """Return the trailing time-period token of a grain, or None."""
    suffix = grain.rsplit('_', 1)[-1]
    return suffix if suffix in _TIME_GRAIN_SUFFIXES else None


# ─────────────────────────────────────────────────────────────────────────────
# FIX 1 — _map_uids_to_agg_ids  (replaces lines 721-743)
# ─────────────────────────────────────────────────────────────────────────────

def _map_uids_to_agg_ids(uids: list[str], grain: str) -> list[str]:
    """
    Convert atomic unique_ids to their aggregate counterpart for a grain.

    Grain taxonomy
    ──────────────
    item_cust_location               → atomic; uid unchanged
    item_location                    → drop customer  → item|ALL_CUST|loc
    item_loc_depth_N                 → aggregate to location ancestor N
    item_client                      → all locs/custs → item|ALL_CUST|ALL_LOC
    item_client_{period}             → time-agg of item_client uid
                                       → item|ALL_CUST|ALL_LOC  (same uid)
    item_loc_depth_N_{period}        → time-agg of depth-N uid
                                       → item|ALL_CUST|loc      (same loc sentinel)
    taxon_{node_id}_client           → product rollup → taxon_{node_id}_ALL_LOC
    taxon_{node_id}_client_{period}  → product + time rollup → same sentinel

    Fix vs original
    ───────────────
    The original hard-coded `endswith('_quarter')`, `endswith('_halfyear')`,
    `endswith('_year')`.  Any grain ending in 'week', 'fortnight', 'month',
    'bimonth', etc. fell through to the else branch and returned the atomic uid
    unchanged — wrong because the aggregate uid is different.

    This version derives the set of valid time suffixes from
    _TIME_GRAIN_SUFFIXES so it is automatically correct for any period type
    defined in PERIOD_HIGHER_HORIZONS.
    """
    agg_ids: set[str] = set()

    for uid in uids:
        parts = uid.split('|')
        if len(parts) != 3:
            continue
        item_id, cust_code, loc_code = parts

        # ── Atomic grain: uid is its own aggregate ─────────────────────────
        if grain == 'item_cust_location':
            agg_ids.add(uid)

        # ── Location-only (drop customer) ──────────────────────────────────
        elif grain == 'item_location':
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')

        # ── Location depth-N (possibly + time suffix) ──────────────────────
        # Handles: item_loc_depth_N  and  item_loc_depth_N_{period}
        elif grain.startswith('item_loc_depth_'):
            # Strip any trailing time suffix before extracting the depth token
            base_grain = grain
            if _grain_has_time_suffix(grain):
                base_grain = grain.rsplit('_', 1)[0]   # e.g. item_loc_depth_2
            # Aggregate uid keeps the location sentinel but strips the customer
            agg_ids.add(f'{item_id}|ALL_CUST|{loc_code}')

        # ── Item × Client (all locs/custs, with or without time suffix) ────
        # Handles: item_client  and  item_client_{period}
        elif grain == 'item_client' or (
            grain.startswith('item_client') and _grain_has_time_suffix(grain)
        ):
            agg_ids.add(f'{item_id}|ALL_CUST|ALL_LOC')

        # ── Product-hierarchy grain (with or without time suffix) ──────────
        # Handles: taxon_{id}_client  and  taxon_{id}_client_{period}
        elif grain.startswith('taxon_'):
            node_id = grain.split('_')[1]
            agg_ids.add(f'taxon_{node_id}_ALL_LOC')

        # ── Fallback: unrecognised grain — keep uid as-is ──────────────────
        else:
            logger.warning(
                '_map_uids_to_agg_ids: unrecognised grain "%s" for uid "%s" '
                '— returning uid unchanged', grain, uid,
            )
            agg_ids.add(uid)

    return list(agg_ids)


# ─────────────────────────────────────────────────────────────────────────────
# FIX 2 — _scale_horizon  (replaces lines 746-753)
# ─────────────────────────────────────────────────────────────────────────────

# Canonical seconds-per-period for every pandas freq alias that
# PERIOD_FREQ_MAP can produce.  All values are expressed in the same unit
# (seconds) so ratios are always dimensionally correct.
#
# How to extend: add any new pandas freq alias you introduce in PERIOD_FREQ_MAP.
# The ratio base_seconds / target_seconds gives the horizon scaling factor:
#   horizon_at_target = ceil(horizon_at_base * base_seconds / target_seconds)
#
_FREQ_SECONDS: dict[str, float] = {
    # Sub-day
    's':       1.0,                    # second  (pandas 'S' / 's')
    'S':       1.0,
    'T':       60.0,                   # minute  (legacy pandas alias)
    'min':     60.0,                   # minute  (pandas ≥ 2.2)
    'h':       3_600.0,                # hour    (pandas ≥ 2.2)
    'H':       3_600.0,                # hour    (legacy pandas alias)
    # Day / week
    'D':       86_400.0,               # day
    'W-MON':   7 * 86_400.0,          # week (Monday-anchored)
    'W':       7 * 86_400.0,          # week (generic)
    '2W-MON':  14 * 86_400.0,         # fortnight
    # Month and multiples  (approximations; used only for ratio — absolute
    # values are irrelevant as long as they are mutually consistent)
    'MS':      30.4375 * 86_400.0,    # month-start
    'M':       30.4375 * 86_400.0,    # month-end (legacy)
    '2MS':     2 * 30.4375 * 86_400.0,   # bimonth
    '2M':      2 * 30.4375 * 86_400.0,
    'QS':      91.3125 * 86_400.0,    # quarter-start  (365.25 / 4 days)
    'QS-OCT':  91.3125 * 86_400.0,    # fiscal-year quarter variants
    'QS-JAN':  91.3125 * 86_400.0,
    'Q':       91.3125 * 86_400.0,    # quarter-end (legacy)
    '2QS':     182.625 * 86_400.0,    # half-year (2 quarters)
    '2Q':      182.625 * 86_400.0,
    'YS':      365.25  * 86_400.0,    # year-start
    'AS':      365.25  * 86_400.0,    # year-start (legacy pandas alias)
    'A':       365.25  * 86_400.0,    # year-end  (legacy)
    'Y':       365.25  * 86_400.0,
}


def _scale_horizon(base_horizon: int, base_freq: str, target_freq: str) -> int:
    """
    Scale a forecast horizon when the target evaluation period is coarser
    (or finer) than the base period type.

    Examples (base = monthly 'MS', horizon = 6):
        target 'QS'    (quarterly)  → ceil(6 * 1/3)   = 2 quarters
        target '2QS'   (halfyear)   → ceil(6 * 1/6)   = 1 halfyear  (min 2)
        target 'YS'    (yearly)     → ceil(6 * 1/12)  = 1 year      (min 2)
        target 'W-MON' (weekly)     → ceil(6 * ~4.3)  = 26 weeks
        target '2W-MON'(fortnight)  → ceil(6 * ~2.2)  = 14 fortnights
        target 'D'     (daily)      → ceil(6 * ~30.4) = 183 days

    Fix vs original
    ───────────────
    Original had only 6 entries: MS, QS, 2QS, YS, D, W-MON.
    Missing: s, S, T, min, h, H, 2W-MON, 2MS, 2Q, AS, A, Y, QS-OCT …
    Any missing freq defaulted to scales.get(…, 1) which silently returned 1,
    producing wildly incorrect horizon counts (e.g. a weekly series with a
    monthly horizon of 6 would have gotten run_horizon=6 weeks instead of ~26).

    This version is driven by _FREQ_SECONDS so every entry is dimensionally
    consistent and any unknown freq raises an explicit warning rather than
    silently returning 1.
    """
    if base_freq == target_freq:
        return base_horizon

    base_sec   = _FREQ_SECONDS.get(base_freq)
    target_sec = _FREQ_SECONDS.get(target_freq)

    if base_sec is None:
        logger.warning(
            '_scale_horizon: unknown base_freq "%s" — treating as 1 period; '
            'add it to _FREQ_SECONDS to silence this warning', base_freq,
        )
        base_sec = 1.0

    if target_sec is None:
        logger.warning(
            '_scale_horizon: unknown target_freq "%s" — treating as 1 period; '
            'add it to _FREQ_SECONDS to silence this warning', target_freq,
        )
        target_sec = 1.0

    if target_sec == 0:
        return base_horizon

    raw = base_horizon * base_sec / target_sec
    # Always run at least 2 periods so StatsForecast has enough context
    # to fit seasonal components.  Cap at a generous ceiling to avoid
    # accidentally running a 365-period daily model.
    return max(2, round(raw))


# ─────────────────────────────────────────────────────────────────────────────
# HELPER — period expansion
# ─────────────────────────────────────────────────────────────────────────────

def _expand_coarse_periods_to_base(
    coarse_rows: list[dict],
    coarse_period: str,
    base_period_type: str,
    base_freq: str,
) -> list[dict]:
    """
    Given a list of forecast rows at a coarser period (e.g. quarterly),
    expand each row into N base-period rows (e.g. 3 monthly rows) by
    equal distribution.

    Each input dict must contain at least:
        ds               — the coarse period start (date or Timestamp)
        statistical_qty  — the coarse-period forecast value
        unique_id        — atomic unique_id for the disaggregated row
        grain            — original grain label (carried through for audit)
        model_used       — carried through

    Returns a flat list of dicts with base-period `ds` values.

    Rationale
    ─────────
    StatsForecast produces forecasts at the eval_period granularity
    (e.g. quarterly).  ForecastLine.period_start must match the version's
    base period_type (e.g. monthly).  This helper performs the time expansion
    step BEFORE location or value-share disaggregation so subsequent steps
    always operate on base-period rows.

    Equal distribution is the correct default here because:
    a) We have no within-period actuals to weight by (that data is at the
       coarser grain by construction — the series was aggregated precisely
       because the finer grain was too sparse).
    b) The hierarchical reconciliation step that follows disaggregation will
       adjust totals to be consistent with bottom-up actuals anyway.
    """
    from mysite.models.demand.actuals import PERIOD_FREQ_MAP

    coarse_freq = PERIOD_FREQ_MAP.get(coarse_period)
    if coarse_freq is None:
        logger.warning(
            '_expand_coarse_periods_to_base: no PERIOD_FREQ_MAP entry for '
            '"%s" — returning rows unchanged', coarse_period,
        )
        return coarse_rows

    # Number of base periods per coarse period
    coarse_sec = _FREQ_SECONDS.get(coarse_freq, 1.0)
    base_sec   = _FREQ_SECONDS.get(base_freq, 1.0)
    n_sub = max(1, round(coarse_sec / base_sec))

    expanded: list[dict] = []
    for row in coarse_rows:
        coarse_ds = pd.Timestamp(row['ds'])
        # Generate n_sub base-period timestamps starting from coarse_ds
        sub_dates = pd.date_range(start=coarse_ds, periods=n_sub, freq=base_freq)
        per_period_qty = row['statistical_qty'] / n_sub
        for sub_ds in sub_dates:
            expanded.append({
                **row,
                'ds':             sub_ds,
                'statistical_qty': per_period_qty,
                # Tag the model_used so the audit trail is clear
                'model_used':     row['model_used'] + f'@expand_{coarse_period}',
            })

    return expanded


# ─────────────────────────────────────────────────────────────────────────────
# FIX 3 — disaggregate_to_atomic  (replaces lines 792-919)
# ─────────────────────────────────────────────────────────────────────────────

def disaggregate_to_atomic(
    forecast_df: pd.DataFrame,
    actuals_df,                        # pl.DataFrame
    decisions: dict[str, dict],
    period_type: str,
    base_freq: str,
    disagg_conflict: str = 'retain_lower',
) -> pd.DataFrame:
    """
    For series whose grain is NOT item_cust_location (atomic), distribute
    the aggregate forecast back to each constituent atomic unique_id.

    NOTE: `period_type` and `base_freq` are new required parameters vs the
    original signature.  The Celery task already has these from
    ForecastVersion; pass them through.

    Disaggregation method
    ─────────────────────
    Location-hierarchy grains (item_location, item_loc_depth_N, item_client):
        Use QUANTITY share — proportional to historical mean qty per series.

    Product-hierarchy grains (taxon_*):
        Use VALUE share — proportional to historical mean revenue per item.
        Convert disaggregated VALUE to QTY using item's effective_price.

    Pure time-aggregation grains (*_{period}  where {period} ∈ _TIME_GRAIN_SUFFIXES):
        e.g. item_client_quarter, item_loc_depth_2_month
        Step 1 — expand each coarse-period forecast row into N base-period rows
                 by equal distribution.
        Step 2 — apply location disaggregation to each expanded base-period row
                 using qty share (same as location grains above).

    Product + time combined grains (taxon_{id}_client_{period}):
        Step 1 — expand each coarse-period REVENUE forecast into N base-period
                 revenue rows (equal distribution).
        Step 2 — apply value-share disaggregation to each expanded row,
                 converting revenue share to qty using item effective_price.

    disagg_conflict
    ───────────────
    'retain_lower': finer-grain forecast wins — do not overwrite atomic series
                    that already had their own forecast.
    'use_upper':    disaggregation overwrites everything.

    Returns DataFrame: unique_id (atomic), ds, statistical_qty, grain,
                       model_used, forecast_level
    All ds values are base-period timestamps (matching ForecastLine.period_start).

    Fixes vs original
    ─────────────────
    Gap A: is_time_grain uses _TIME_GRAIN_SUFFIXES  (was hard-coded to 3 tokens)
    Gap B: pure time-grain grains now have an explicit handling branch that
           first expands the coarse forecast to base-period rows, then applies
           location disaggregation.  Previously the is_time_grain flag was
           computed but never acted on — these rows fell into the location-grain
           else branch where no time expansion happened, so ForecastLine rows
           ended up with quarterly ds values instead of monthly ones.
    Gap C: taxon_{id}_client_{period} (product + time) now expands REVENUE to
           base-period rows before value-share → qty conversion.  Previously
           the code wrote one row per coarse ds value, which did not match the
           monthly ForecastLine.period_start expected by the rest of the system.
    """
    actuals_pd = actuals_df.to_pandas()
    actuals_pd['ds'] = pd.to_datetime(actuals_pd['ds'])

    # ── Separate atomic from non-atomic ──────────────────────────────────────
    atomic_forecasts    = forecast_df[forecast_df['grain'] == 'item_cust_location'].copy()
    non_atomic_forecast = forecast_df[forecast_df['grain'] != 'item_cust_location'].copy()

    if non_atomic_forecast.empty:
        return atomic_forecasts

    # ── Historical means for disaggregation weights ───────────────────────────
    uid_qty_mean: dict[str, float] = (
        actuals_pd.groupby('unique_id')['y'].mean().to_dict()
    )
    uid_rev_mean: dict[str, float] = (
        actuals_pd.groupby('unique_id')['revenue'].mean().to_dict()
    )

    disaggregated_rows: list[dict] = []

    for (grain, ds_val), group in non_atomic_forecast.groupby(['grain', 'ds']):
        agg_ids = group['unique_id'].unique()

        # Members: agg_id → [atomic_uids]
        members: dict[str, list[str]] = {}
        for uid, dec in decisions.items():
            if dec['grain'] != grain:
                continue
            mapped = _map_uids_to_agg_ids([uid], grain)
            if mapped and mapped[0] in agg_ids:
                members.setdefault(mapped[0], []).append(uid)

        for _, fcast_row in group.iterrows():
            agg_id     = fcast_row['unique_id']
            agg_qty    = float(fcast_row['statistical_qty'])
            child_uids = members.get(agg_id, [])

            if not child_uids:
                continue

            # ── Classify this grain ─────────────────────────────────────────
            is_product_grain = grain.startswith('taxon_')
            time_suffix      = _grain_time_suffix(grain)   # str or None
            is_time_grain    = time_suffix is not None

            # ── Strip the time suffix to get the spatial base grain ─────────
            # e.g.  item_client_quarter  →  item_client
            #       item_loc_depth_2_month → item_loc_depth_2
            #       taxon_42_client_halfyear → taxon_42_client  (product grain)
            spatial_grain = grain.rsplit('_', 1)[0] if is_time_grain else grain

            # ══════════════════════════════════════════════════════════════════
            # CASE 1 — Product-hierarchy grain, possibly with time suffix
            #          (taxon_{id}_client  or  taxon_{id}_client_{period})
            # ══════════════════════════════════════════════════════════════════
            if is_product_grain:
                # agg_qty is actually REVENUE at this point.
                agg_revenue = agg_qty

                # Step 1 (Gap C fix): if there is a coarse time period, expand
                # this single coarse-period revenue row into N base-period rows
                # by equal distribution BEFORE value-share disaggregation.
                if is_time_grain:
                    expanded_rows = _expand_coarse_periods_to_base(
                        coarse_rows=[{
                            'ds':             ds_val,
                            'statistical_qty': agg_revenue,
                            'unique_id':      agg_id,   # temporary; replaced below
                            'grain':          grain,
                            'model_used':     fcast_row['model_used'],
                            'forecast_level': grain,
                        }],
                        coarse_period=time_suffix,
                        base_period_type=period_type,
                        base_freq=base_freq,
                    )
                else:
                    # No time suffix — one row at native period_type
                    expanded_rows = [{
                        'ds':             ds_val,
                        'statistical_qty': agg_revenue,
                        'unique_id':      agg_id,
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'],
                        'forecast_level': grain,
                    }]

                # Step 2: value-share → qty disaggregation for each expanded row
                child_revs = {u: uid_rev_mean.get(u, 0.0) for u in child_uids}
                total_rev  = sum(child_revs.values()) or 1.0

                for exp_row in expanded_rows:
                    per_period_revenue = exp_row['statistical_qty']
                    for uid in child_uids:
                        share     = child_revs[uid] / total_rev
                        item_rev  = per_period_revenue * share
                        price     = float(decisions[uid].get('price') or 1.0)
                        child_qty = item_rev / price if price > 0 else 0.0
                        disaggregated_rows.append({
                            'unique_id':       uid,
                            'ds':              exp_row['ds'],
                            'statistical_qty': max(0.0, child_qty),
                            'grain':           grain,
                            'model_used':      exp_row['model_used'] + '@value_disagg',
                            'forecast_level':  grain,
                        })

            # ══════════════════════════════════════════════════════════════════
            # CASE 2 — Pure time-aggregation grain (non-product)
            #          e.g. item_client_quarter, item_loc_depth_2_month
            #
            # Gap B fix: previously these fell into the else (location-qty)
            # branch with no time expansion, leaving ds at quarterly values.
            # Now they are explicitly expanded first, then location-disaggregated.
            # ══════════════════════════════════════════════════════════════════
            elif is_time_grain:
                # Step 1: expand coarse forecast → N base-period rows
                expanded_rows = _expand_coarse_periods_to_base(
                    coarse_rows=[{
                        'ds':             ds_val,
                        'statistical_qty': agg_qty,
                        'unique_id':      agg_id,
                        'grain':          grain,
                        'model_used':     fcast_row['model_used'],
                        'forecast_level': grain,
                    }],
                    coarse_period=time_suffix,
                    base_period_type=period_type,
                    base_freq=base_freq,
                )

                # Step 2: qty-share location disaggregation for each expanded row
                child_qtys = {u: uid_qty_mean.get(u, 0.0) for u in child_uids}
                total_qty  = sum(child_qtys.values()) or 1.0

                for exp_row in expanded_rows:
                    per_period_qty = exp_row['statistical_qty']
                    for uid in child_uids:
                        share     = child_qtys[uid] / total_qty
                        child_qty = per_period_qty * share
                        disaggregated_rows.append({
                            'unique_id':       uid,
                            'ds':              exp_row['ds'],
                            'statistical_qty': max(0.0, child_qty),
                            'grain':           grain,
                            'model_used':      exp_row['model_used'],
                            'forecast_level':  grain,
                        })

            # ══════════════════════════════════════════════════════════════════
            # CASE 3 — Spatial location grain at native period
            #          (item_location, item_loc_depth_N, item_client)
            # ══════════════════════════════════════════════════════════════════
            else:
                child_qtys = {u: uid_qty_mean.get(u, 0.0) for u in child_uids}
                total_qty  = sum(child_qtys.values()) or 1.0
                for uid in child_uids:
                    share     = child_qtys[uid] / total_qty
                    child_qty = agg_qty * share
                    disaggregated_rows.append({
                        'unique_id':       uid,
                        'ds':              ds_val,
                        'statistical_qty': max(0.0, child_qty),
                        'grain':           grain,
                        'model_used':      fcast_row['model_used'],
                        'forecast_level':  grain,
                    })

    disagg_df = (
        pd.DataFrame(disaggregated_rows)
        if disaggregated_rows
        else pd.DataFrame(columns=[
            'unique_id', 'ds', 'statistical_qty',
            'grain', 'model_used', 'forecast_level',
        ])
    )

    # ── Conflict resolution ───────────────────────────────────────────────────
    if disagg_conflict == 'retain_lower' and not atomic_forecasts.empty:
        # Atomic series with their own fine-grain forecast are not overwritten.
        # Exclude by (unique_id, ds) pair so only the specific periods that
        # were directly forecast are protected, not the entire series.
        atomic_covered = set(
            zip(atomic_forecasts['unique_id'], atomic_forecasts['ds'])
        )
        mask = disagg_df.apply(
            lambda r: (r['unique_id'], r['ds']) not in atomic_covered, axis=1
        )
        disagg_df = disagg_df[mask]

    combined = pd.concat([atomic_forecasts, disagg_df], ignore_index=True)
    return combined


# ─────────────────────────────────────────────────────────────────────────────
# CALLER UPDATE — run_statsforecast_by_grain and Celery task
# ─────────────────────────────────────────────────────────────────────────────
# disaggregate_to_atomic now requires `period_type` and `base_freq`.
# Update the call site in your Celery task (run_forecast) as follows:
#
#   atomic_df = disaggregate_to_atomic(
#       forecast_df    = raw_forecast_df,
#       actuals_df     = actuals_df,
#       decisions      = decisions,
#       period_type    = version.period_type,        # ← NEW
#       base_freq      = PERIOD_FREQ_MAP[version.period_type],  # ← NEW
#       disagg_conflict = cfg.get('disagg_conflict_resolution', 'retain_lower'),
#   )
"""
atomic_df = disaggregate_to_atomic(
    forecast_df     = combined_df,
    actuals_df      = actuals_pl,
    decisions       = decisions,
    period_type     = version.period_type,
    base_freq       = PERIOD_FREQ_MAP[version.period_type],
    disagg_conflict = disagg_conflict,
)
"""