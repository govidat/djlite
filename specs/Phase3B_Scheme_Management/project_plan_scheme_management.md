# Project Plan — Sales Promotion Scheme Management (FINAL)

**Scope:** Add a sales-promotion scheme layer that (1) nets scheme impact out of historical actuals to
produce a clean statistical baseline, and (2) re-applies expected uplift to the forecast horizon for
planned schemes. The scheme layer sits **upstream** of the existing outlier layer:
`baseline = Actuals − scheme impact − outlier`. Delivered as Sprint 3B.2c, after Sprint 3B.2b (Outlier
Management) and before 3B.3 (Forecast Models). The review/registration UI is Django Template + HTMX,
consistent with the existing `demand_ui/` app.

**Positioning rationale:** this must land before any forecast run consumes scheme-aware actuals, because
`build_actuals_dataframe` and the series-profile / price-update paths need to know whether to net from
day one. It also **changes the basis** of outlier detection — detection must run on scheme-netted series,
so it cannot be safely retrofitted after 3B.3 ships.

---

## Business Problem

Sales promotion schemes (1-for-1, buy-2-get-1-free, %-off, dealer free-goods, etc.) run from time to time
in consumer products and auto components. Their observable pattern:

- **During the scheme:** demand (qty) spikes well above baseline; revenue behaviour is independent — a
  1-for-1 scheme doubles qty while revenue stays flat.
- **Pre/post scheme:** demand dips (pull-forward / wait-for-scheme effect).

Without a scheme layer, these distortions leak into the model three ways:

1. **Value distortion at product-group grain.** `taxon_*` grains forecast **revenue** (`y = revenue`),
   not qty. A deep-discount scheme can show *low* revenue in a high-qty period, biasing the revenue level
   and seasonality the value model learns.
2. **Price bias.** `update_weighted_avg_prices` computes `sum(revenue)/sum(qty)` over all history;
   scheme periods depress the weighted-average price and distort every future qty conversion during
   disaggregation.
3. **Inconsistent outlier treatment.** Single-period scheme spikes are currently flagged by outlier
   detection as noise (and netted out, losing the planned/repeatable nature of the event); multi-period
   schemes are swallowed by the sustained-run "level shift" exclusion. Either way the baseline is wrong
   and the uplift is not preserved for future planning.

A scheme is a **planned, repeatable event** — unlike an outlier (one-off noise) it must be removed from
history *and* re-applied to the horizon.

---

## All Design Decisions — Confirmed

1. **Timing model** — schemes can be both **historical** (tagged against past actuals to net them out)
   and **planned** (registered against future horizon periods to re-add uplift). A single `SalesScheme`
   with a set of `SalesSchemePeriod` rows covers both: a period in the past nets history, a period in the
   future re-adds uplift. No separate "future vs historical" flag is needed.
2. **Scope** — schemes are defined at **product-group (TaxonomyNode subtree)**, **brand (Brand node in the
   item taxonomy — the "vendor" of the scheme)**, **item-list**, or **OVERALL** level, with optional
   `planning_location` / `planning_customer` / `distribution_channel` filters, via a `SalesSchemeScope`
   child table (mirrors the `VendorSchemeScope` pattern from 3C). A scheme carries one or more scope rows,
   so "a vendor scheme covering multiple product groups" is one `SalesScheme` with several rows — e.g. two
   `BRAND` rows (two brands), three `TAXONOMY` rows (three planning groups), plus any `ITEM` rows. Scope
   resolution is **tree-aware**: each row resolves membership from its own node's taxonomy subtree via
   `ItemTaxonomyNode` (union of all item mappings), so a `BRAND` row covers every item mapped beneath the
   brand node regardless of planning-group placement. Within a single scheme, rows overlapping the same
   (item, location, customer, channel, period) are deduplicated most-specific-wins:
   `ITEM > BRAND > TAXONOMY > OVERALL` (no double factor application).
3. **Uplift source** — **planner-entered** `expected_qty_uplift_pct` and **independent**
   `expected_value_uplift_pct`, optionally data-checked. `discount_pct` is **metadata only** (may
   pre-fill a default `expected_value_uplift_pct`, never authoritative). Rationale: schemes like 1-for-1
   (qty ×2, revenue flat → `value_uplift = 0%`) break the assumption that value is derivable from
   qty-uplift × discount. The planner states the revenue effect directly.
4. **Sequencing with outliers** — `net_qty = (qty / (1 + qty_uplift)) − outlier_qty_adj` and
   `net_revenue = (revenue / (1 + value_uplift)) − revenue_adj`. Scheme first, outlier second. **Outlier
   detection runs on scheme-netted series**, so its median/MAD baseline is already scheme-free and a
   scheme spike can never be flagged as an outlier. One shared baseline-netting helper is the single
   source of truth for both detection and forecasting.
5. **Value netting** — independent `expected_value_uplift_pct` (see decision 3). Guards:
   `value_uplift ≤ −100%` is invalid (division by zero / negative revenue — floor at > −100%); a scheme
   with zero qty uplift but non-zero value uplift (pure price promo) must still net revenue.
6. **Output shape** — `ForecastLine` stores the clean baseline (`pre_scheme_statistical_qty`), the
   scheme uplift delta (`scheme_qty`), and the scheme-adjusted statistical value (`statistical_qty`):
   `statistical_qty = pre_scheme_statistical_qty + (scheme_qty or 0)`. For horizon periods covered by
   an ACTIVE scheme: `scheme_qty = pre_scheme_statistical_qty × uplift_pct` (the delta); for periods
   without a scheme: `scheme_qty = NULL` and `statistical_qty = pre_scheme_statistical_qty`. The
   override system continues to work on `statistical_qty` (unchanged). `ForecastAggregate` carries
   `pre_scheme_statistical_qty` / `pre_scheme_statistical_value` for both-column display, alongside
   the existing `statistical_qty` / `total_statistical_value`.
7. **Membership resolution** — scheme→actuals coverage is **materialized** (`ResolvedSalesSchemePeriod`),
   rebuilt on scheme save/approval by a Celery task, reusing the "resolve on change, materialize for
   reads" pattern already established by `ResolvedVendorScheme` / `ResolvedSupplySource` in Phase 3C.
   The query-time netting helper then LEFT JOINs the resolved table — no per-row taxonomy-subtree
   computation at read time. MVP assumes a (item, location, customer, channel, period) is covered by at
   most **one** ACTIVE scheme; overlap resolution (most-specific-wins + planner warning) is a Phase 6
   hardening item.
8. **Review UI** — Django Template + HTMX (registration form, candidate review queue, detection
   trigger, occurrence data-check), consistent with the outlier feature. No React SPA, no DRF endpoints
   for scheme interactions.
9. **Feature flag** — `scheme_management` `ClientFeatureControl` key (mirrors `outlier_management`);
   `ForecastingConfig.scheme_net_actuals` and `scheme_apply_forecast_uplift` default True.
10. **Pre/post shadow (pull-forward)** — IN SCOPE for 3B.2c, on BOTH the baseline and the horizon.
    A fraction of a scheme's netted-out uplift is *pulled forward* from neighbouring periods rather
    than being incremental. Model parameters: `SalesScheme.pull_forward_pct` (default 0.50 = half the
    uplift is pulled from neighbours, half is incremental) and `SalesScheme.shadow_periods` (default
    0 → shadow off per scheme; ≥1 enables it, pre/post symmetric). Mechanics — **anchor-based and
    symmetric on both sides** so `baseline = Actuals − scheme impact − outlier` and the horizon
    overlay stay self-consistent:
    - The add-back (history) and the dip (horizon) both anchor to the **window** period's uplift,
      `U = window_qty × (1 − 1/qty_factor)`.
    - Pre/post shadow buckets re-add (history) or depress (horizon) `U × pull_forward_pct ×
      side_share × decay_weight(j)`, with a 50/50 pre/post split and an exponential decay
      (`1/2^j`) normalized per side.
    - Value shadow anchors to the window's `expected_value_uplift_pct` — a 1-for-1 (value uplift 0)
      has no value add-back; the residual pre/post revenue dip is treated as baseline noise.
    Documented simplifications: a shadow whose anchor window falls outside the forecast horizon is
    skipped with a warning; shadow rows from different schemes on the same (grain, period) add
    additively; the ≤1-ACTIVE-scheme-per-window assumption in decision 7 is unchanged (a period may
    be a window for one scheme and a shadow for another). `pull_forward_pct` is calibrated
     empirically from closed schemes in Phase 5.
11. **Brand scope + prerequisite** — "vendor-specific scheme" == **Brand-specific scheme** in this
    domain: the vendor is the Brand, and the brand→item link lives in the **item taxonomy**, NOT the
    planning product hierarchy (which is category-based and brand-agnostic — its groups span brands).
    Brand-level coverage therefore requires an item taxonomy that contains a Brand level with items
    mapped beneath it. `scope_type = 'BRAND'` targets a brand `TaxonomyNode`, and membership is the
    **union** of all `ItemTaxonomyNode` mappings under that node (not primary-mapping-only, since a
    promo covers the item regardless of where its canonical planning grain sits). **Prerequisite:**
    a new `ForecastingConfig.brand_taxonomy` slug (nullable, mirrors `planning_producthierarchy`)
    names the taxonomy that carries the Brand level; BRAND scoping is only offered/valid once that
    taxonomy exists with nodes and item mappings. Documented simplifications: brand coverage is
    union-only (no negative/exclude brand scope — "brand X except SKU Y" is not expressible, mirror
    the planning-group limit); brand taxonomy is client-maintained master data (a setup gap surfaces
    as a UI gate + validation error, not a silent zero-item scheme); within-scheme overlap between
    BRAND/TAXONOMY/ITEM rows is resolved most-specific-wins (decision 2), cross-scheme overlap stays
    the Phase 6 hardening item (decision 7).
12. **Override base = scheme-adjusted statistical** — `ForecastLine` stores `pre_scheme_statistical_qty`
    (clean baseline), `scheme_qty` (uplift delta, NULL when no scheme), and `statistical_qty`
    (= `pre_scheme_statistical_qty + (scheme_qty or 0)`). The override system continues to work on
    `statistical_qty` — no changes to override disaggregation, `ForecastLine.save()`, aggregate rollup,
    or revert logic. When a scheme is modified after overrides exist, the version is flagged as stale and
    the planner must re-apply overrides manually (warn, not auto-re-apply). Both `pre_scheme_statistical_qty`
    and `statistical_qty` are exposed in the UI for transparency. `ForecastAggregate` carries
    `pre_scheme_statistical_qty` / `pre_scheme_statistical_value` for both-column display.

---

## Phase 1 — Data Model, Scope Resolution & Config
**Depends on:** Sprint 3B.2b (Outlier Management).
**Delivers:** `SalesScheme` (incl. `shadow_periods`, `pull_forward_pct`), `SalesSchemeScope` (incl.
`scope_type = 'BRAND'` targeting a Brand node in the item taxonomy), `SalesSchemePeriod`,
`SalesSchemeOccurrence`, `ResolvedSalesSchemePeriod` (window rows + shadow rows with anchor fields);
`ForecastingConfig` gains `brand_taxonomy` (nullable slug naming the taxonomy carrying the Brand level) +
two scheme flags + scheme-detection run-tracking fields; `scheme_management`
`ClientFeatureControl` key; `ForecastLine` gains `pre_scheme_statistical_qty`,
`pre_scheme_statistical_value`, `scheme_qty`, `scheme_value` (uplift deltas); `statistical_qty` is the
scheme-adjusted value (`pre_scheme_statistical_qty + scheme_qty`); `ForecastAggregate` gains
`pre_scheme_statistical_qty` / `pre_scheme_statistical_value`; `resolve_scheme_scope`
Celery task (tree-aware membership + within-scheme most-specific-wins dedup); **authorization + signals
wiring** — the five scheme models registered in the Guardian
`ADMIN_ONLY_MODELS` permission sync in `mysite/signals.py` (admin-role CRUD on migrate) and the
`scheme_changed` post_save receiver (resolve + stale-flag + re-trigger detection).
**Exit criteria:** A scheme scoped to a TaxonomyNode subtree with an item-list scope and an OVERALL scope
each materialize correct `ResolvedSalesSchemePeriod` rows; **a `BRAND`-scoped scheme materializes the
union of items mapped beneath the brand node even though those items spread across multiple planning
product groups, and a scheme with both a BRAND and a TAXONOMY row covering the same item resolves the
item once (most-specific-wins, no double factor application)**; a scheme with a future period produces a
row whose `period_start` lands in the horizon; a scheme whose period overlaps actuals produces a row
keyed to those actuals' grain; a scheme with `shadow_periods = 2` additionally materializes 2 PRE + 2
POST shadow rows per window row, each with correct side/offset, anchor period, factor copies, and decay
weights that normalize to `pull_forward_pct` per side; disabling a scheme drops its resolved rows; **a
BRAND scope on a client whose `brand_taxonomy` is unconfigured or empty fails validation (and the
registration UI hides/explains brand scoping)**; **`ForecastLine` has `pre_scheme_statistical_qty`,
`pre_scheme_statistical_value`, `scheme_qty`, `scheme_value` fields; `statistical_qty` is the
scheme-adjusted value (`pre_scheme_statistical_qty + scheme_qty`); `ForecastAggregate` has
`pre_scheme_statistical_qty` and `pre_scheme_statistical_value` fields**; **a non-superuser
admin-role user sees all five scheme models in Django admin after migrate while viewer/staff users see
none (Step 1.5 auth checkpoint)**.

## Phase 2 — Scheme-Netted Baseline + Outlier Sequencing
**Depends on:** Phase 1.
**Delivers:** Extend `actuals_queryset_with_net()` into a composed baseline helper
(`scheme-net → outlier-net`, order hardcoded) that ALSO applies the shadow add-back: a window row divides
by its factor; a shadow row **adds back** `window_qty × (1 − 1/anchor_qty_factor) × addback_weight`
(resolved per-row via a correlated Subquery on the anchor window's actuals); switch
`run_outlier_detection` to read scheme-netted series; re-bind `_suggest_adjustment_qty/_revenue` and
`ActualSaleOutlierAdjustment.clean()` bounds to scheme-netted values; wire `build_actuals_dataframe`,
`compute_series_profiles`, and `update_weighted_avg_prices` to the composed helper.
**Exit criteria:** The 1-for-1 fixture nets to `net_qty = qty/2`, `net_revenue = revenue`; with
`shadow_periods = 1` and `pull_forward_pct = 0.5`, each pre/post period nets to
`qty + 0.25 × window_netted_uplift` and no scheme-period spike **or** pre/post dip is proposed as an
outlier candidate by detection; an outlier adjustment cannot exceed the scheme-netted qty; a forecast run
with `scheme_net_actuals=True` differs materially from the same run with it `False`.

## Phase 3 — Forecast-Horizon Uplift (Output)
**Depends on:** Phase 1 only (read-path change on write side).
**Delivers:** `build_scheme_forecast_factors()` (resolved scheme × horizon → per-(uid, ds) factors,
including **shadow dip** overlays); merge inside `write_forecast_lines`: write `pre_scheme_statistical_qty`
from engine output, compute `scheme_qty` from factors, compute `statistical_qty = pre_scheme_statistical_qty
+ (scheme_qty or 0)`, set `scheme_id` FK; extend `write_forecast_aggregates` DuckDB roll-up with
`pre_scheme_statistical_qty` / `pre_scheme_statistical_value` sums alongside existing statistical sums.
**Exit criteria:** A horizon period inside an ACTIVE scheme's window gets `scheme_qty = pre_scheme_statistical_qty × uplift_pct` (delta) and `scheme_value = pre_scheme_statistical_value × value_uplift_pct`, with `statistical_qty = pre_scheme_statistical_qty + scheme_qty`; a horizon pre/post shadow period gets `scheme_qty = −window_pre_scheme_statistical_qty × (1 − 1/anchor_qty_factor) × addback_weight` (dip), with `statistical_qty = pre_scheme_statistical_qty + scheme_qty`; the 1-for-1 case yields `scheme_qty = pre_scheme_statistical_qty` (doubled qty delta) with `scheme_value = NULL` (flat revenue); a period outside any scheme has `scheme_qty = NULL` and `statistical_qty = pre_scheme_statistical_qty`; override system works on `statistical_qty` (unchanged); aggregate rows carry both `pre_scheme_statistical_qty` and `statistical_qty`.

## Phase 4 — Scheme Detection & Planner Review Queue
**Depends on:** Phase 1; can run in parallel with Phases 2–3.
**Delivers:** `detect_scheme_candidates` Celery task (raw-actuals product-group spike detection, implied
qty uplift = period/median-of-neighbors − 1), scheme registration form (scope lines incl. a **brand
picker** populated from `ForecastingConfig.brand_taxonomy`, gated off with a "set up brand taxonomy"
message when unconfigured), candidate review queue and
approve/activate actions (HTMX), `scheme_management` visibility gating, Django Admin in a new
`mysite/admin/demand_schemes.py` module (`SalesSchemeAdmin` with scope/period/occurrence inlines,
read-only `ResolvedSalesSchemePeriodAdmin`, scheme fields added to `ForecastingConfigAdmin` /
`ForecastLineAdmin` / `ForecastAggregateAdmin`, registered in `mysite/admin/__init__.py`).
**Exit criteria:** A single-period spike at product-group level not covered by an ACTIVE scheme becomes a
candidate; a scheme-tagged period is never re-proposed; approving a scheme materializes its resolved
rows and re-triggers outlier detection on the affected range.

## Phase 5 — Occurrence Data-Checking & Uplift Estimation ✅ IMPLEMENTED
**Depends on:** Phase 1; runs after real schemes close.
**Delivers:** `record_scheme_occurrence` (period-close cadence) writing `actual_qty_uplift_pct` /
`actual_value_uplift_pct` measured independently from actuals, plus **`actual_pull_forward_pct`**
estimated from the closed window vs its neighbouring periods (conservation check: pulled volume +
incremental volume ≈ netted-out uplift); actual-vs-expected comparison surfaced to planners;
`suggest_uplift_for_scheme` defaulting future `expected_*_uplift_pct` AND `pull_forward_pct` to the median
of the last few occurrences (mirrors the 3C vendor-rebate accrual estimation pattern).
- `suggest_uplift_for_scheme()` — `record_scheme_occurrence.py:166` — median pre-fill + IQR/MAD variance warnings
- API endpoint — `demand_ui:scheme_suggest` — `GET /{client_id}/demand/schemes/suggest/?code=CODE`
- Admin form integration — `demand_schemes.py:SalesSchemeAdmin` — JS on blur → fetch → pre-fill + warning banners
**Exit criteria:** For a closed scheme, actual uplift is measured independently for qty and value and
actual pull-forward is measured against neighbours; a re-registered scheme pre-fills uplift and
`pull_forward_pct` from the median of past occurrences; a scheme that wildly missed expectation surfaces a
variance warning.

## Phase 6 — Hardening & Regression
**Depends on:** All prior phases.
**Delivers:** Full test suite (1-for-1 netting, scheme-then-outlier ordering, detection-on-netted basis,
horizon uplift incl. shadow dip, stale-flagging on scheme change, scope resolution, config fallbacks);
overlap-resolution warning path for items covered by >1 ACTIVE scheme in the same period; load check on
`resolve_scheme_scope` across a full monthly import batch.
**Exit criteria:** End-to-end: import → planner registers scheme (with shadow) → resolved rows materialize
→ outlier detection ignores the scheme period and pre/post dips → forecast baseline is scheme-free with
shadow re-added → `pre_scheme_statistical_qty` written, `scheme_qty` computed, `statistical_qty` =
scheme-adjusted → horizon uplift + shadow dip applied → override system works on `statistical_qty`
(unchanged) → both `pre_scheme_statistical_qty` and `statistical_qty` visible in UI → scheme closes
→ occurrence records actual pull-forward → next registration pre-fills uplift and `pull_forward_pct`.
When a scheme is modified after overrides exist, planner is warned and must re-apply manually.
`makemigrations --check` clean.

> **Documented shadow simplifications (in-scope but bounded):** value add-back anchors only to the
> window's `expected_value_uplift_pct` (a 1-for-1 has no value shadow — its residual pre/post revenue dip
> is baseline noise); a shadow whose anchor window falls outside the forecast horizon is skipped with a
> warning; shadow rows from different schemes on the same (grain, period) add additively. These keep the
> baseline pipeline unambiguous without pulling in attribution/causal modeling.

---

## Sequencing Summary

```
Phase 1 (Models + Scope Resolution)
  ├─▶ Phase 2 (Scheme-Netted Baseline + Outlier Sequencing)
  │     ├─▶ Phase 3 (Horizon Uplift)
  │     └─▶ Phase 4 (Detection + Review Queue) ─▶ Phase 5 (Occurrences/Estimation)
  └─▶ Phase 6 (Hardening & Regression)
```

Phases 3 and 4 can proceed in parallel once Phase 1 lands; Phase 2 is the critical path for correctness
of the outlier ordering and must precede any production forecast run.

Task-level Sprint 3B.2c checklist (models, migrations, resolver task, netting composition, detection,
HTMX views/templates, admin, stale-flagging wiring, tests) is in the execution-instructions companion
doc — ready to execute against.
