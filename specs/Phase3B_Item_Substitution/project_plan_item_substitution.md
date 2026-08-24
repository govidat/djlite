# Item Lifecycle Management — Substitution / Discontinuation / Introduction — Project Plan

**Sprint:** 3B.2d (Item Lifecycle — Predecessor History Reuse, Discontinuation, New-Item Introduction)
**Depends on:** Sprint 3B.2c (Scheme Management) — shares the composed baseline-netting helper, the
feature-flag pattern, and the admin/HTMX scaffolding. No code from 3B.2c is required at runtime, but
this sprint is sequenced after it so both land on the same netting single-source-of-truth.

---

## Business Requirement

Items go through lifecycle events that a naive "one item, one series" forecast model cannot
represent. Three events are supported. They share **one admin/UI, one config flag, and one consumer
pipeline**, but each lands in a different layer:

1. **Substitution (replacement code — Scenario 3).** An item with past sales is superseded in the
   future by a **new item code** (repack, reformulation, supersession). The retired code's historical
   actuals must be **reused to forecast the new code** from its launch date onward, with a **quantity
   conversion** when unit sizes change — e.g. `2 units of the old code = 1 unit of the new code`.
   This is the **baseline re-key layer** (history → successor).

2. **Discontinuation (Scenario 1).** An item is discontinued with an **effective date**. Even though
   past actuals exist, **post effective date the forecast is nil** — there is no successor, the
   product is simply withdrawn. This is a **forecast-output filter layer** (horizon → nil).

3. **Introduction (Scenario 2).** A **new item** is introduced from an effective date and has **no
   history** of its own. The client may name **another item code whose forecast is copied onto the
   new item**, scaled by a **ratio**, and bounded by an optional **from-date / to-date** window, so the
   new item is covered **until enough historical data gets available** for it to be forecast on its
   own. This is a **forecast-output copy layer** (horizon ← reference).

### Scenario 1 — Discontinuation (key properties)

1. The item keeps its full history; nothing is re-keyed, netted, or moved (no successor owns it).
2. Forecast is **nil on/after `effective_from`** — the engine emits no `ForecastLine` for horizon
   periods `>= effective_from`. Periods **before** it forecast normally from the item's own history
   (covers in-flight months before the withdrawal).
3. `effective_from` NULL → the item produces no forecast from the current run onward (immediate).
4. The item's history still feeds **reporting, ABC classification, and accuracy** for the past —
   discontinuation is a forecast-output rule, **not** a data mutation and **not** an `Item`
   master-data status change.

### Scenario 2 — Introduction (key properties)

1. The new item has **no (or insufficient) history** at launch, so it cannot be statistically
   forecast on its own.
2. The client names a **reference item** whose **statistical forecast is copied** onto the new item,
   scaled by `ratio` (`new = reference × ratio`).
3. Copying is bounded by the **earlier** of:
   - an optional client-given window `[copy_from, copy_to]` (`copy_from` NULL = borrow from the new
     item's launch; `copy_to` NULL = no explicit stop), and
   - the item's own-history accrual: once the new item has **`>= min_history_periods`** own periods
     (`ForecastingConfig.min_history_periods`), its own statistical forecast takes over.
4. The reference item is **not retired** — it keeps its own identity, series, and forecast. The copy
   is a **horizon-level** operation (output), not a baseline re-key.
5. The copy is transparent: borrowed lines carry the **reference item and ratio**
   (`borrowed_from_item`, `borrowed_ratio` on `ForecastLine`). `qty` and `value` scale by the same
   `ratio`, so the per-unit price is preserved from the reference.
6. The copy happens at the **leaf grain** (item × planning_location × distribution_channel ×
   planning_customer) where the reference has forecast lines; a grain with no reference line simply
   gets no borrowed line (planner can override).

### Scenario 3 — Substitution (key properties, unchanged)

1. The new code's forecast must be built from the old code's history (the new code has no useful
   history of its own at launch).
2. Conversion can be non-1:1 (`2 old = 1 new`, pack-size changes, etc.).
3. The conversion applies to the **baseline** — the old history is still scheme-netted and
   outlier-adjusted before it feeds the new series (a promo spike in the old code must not leak into
   the successor's baseline).
4. The unit economics are preserved: `qty` **and** `revenue` scale by the same factor, so the
   per-unit price is unchanged by the substitution.
5. Only history **before the launch date** (`effective_from`) of the new code converts; the new
   code's own actuals (after launch) are used as-is and never double-counted with converted history.
6. **The retired old item's own forecast is nil on/after `effective_from`** — the successor owns the
   demand from the handover date (same nil rule as Scenario 1, applied via the substitution row).

---

## All Design Decisions — Confirmed

1. **Three models, one umbrella.** `ItemSubstitution`, `ItemDiscontinuation`, and `ItemIntroduction`
   all live in `mysite/models/demand/lifecycle.py`, all keyed to `(client, ...)`, and are maintained
   from one admin/HTMX section under a single feature flag:
   - `ItemSubstitution(client, old_item, new_item, conversion_factor, effective_from, notes)` —
     `unique (client, old_item)`; one predecessor maps to exactly one successor; a `new_item` may
     aggregate **many** `old_item` rows (several retired variants merged into one successor).
   - `ItemDiscontinuation(client, item, effective_from, notes)` — `unique (client, item)`;
     `effective_from` NULL = nil forecast immediately.
   - `ItemIntroduction(client, new_item, reference_item, ratio, copy_from, copy_to, notes)` —
     `unique (client, new_item)`; `ratio > 0`; window optional.
2. **One lifecycle directive per item.** The event-**subject** roles are pairwise exclusive: an item
   may be the `old_item` of a substitution, the `new_item` of a substitution, a discontinued item, or
   the `new_item` of an introduction — never more than one. The `reference_item` of an introduction is
   **not** an event subject (it is an ordinary forecasted item) and may overlap freely, **except** that
   an introduction's `new_item` may not itself be another introduction's `reference_item` (no chains).
   Enforced in `clean()` and mirrored by `post_save`/`post_delete` validation receivers.
3. **Direct mapping only (MVP)** — no chains (A→B→C) and no cycles for **any** event type; killed by
   construction (no transitive resolution needed). Chains are explicitly out of scope.
4. **Substitution conversion semantics** — `new_qty = old_qty × conversion_factor` and
   `new_revenue = old_revenue × conversion_factor` (same factor for both, preserving per-unit price).
   Guard: `conversion_factor > 0`.
5. **`effective_from` cutoff (substitution)** — an old-item row converts to the new item **only when**
   `period_start < effective_from` (`effective_from` NULL → convert the entire old history). Old-item
   rows on/after the launch date stay keyed to the old item, unconverted, so no transition data is
   lost and the retired item's reporting remains intact. The new item's own actuals are never scaled
   and never summed with converted history (the cutoff makes the sets disjoint). The retired old
   item's own **forecast** is nil on/after `effective_from`.
6. **Discontinuation semantics** — horizon periods with `period_start >= effective_from` produce no
   `ForecastLine` (nil); periods before forecast normally. `effective_from` NULL → nil from the
   current run. History untouched.
7. **Introduction semantics** — a horizon period of the new item is borrowed **only when** the new
   item has `< min_history_periods` own actual periods **and** the period is inside the copy window
   (`copy_from` NULL = borrow from launch; `copy_to` NULL = borrow until enough own history). The
   borrowed line = reference item's statistical line × `ratio`, tagged `borrowed_from_item` /
   `borrowed_ratio`. The copy stops at the **earlier** of the window end and "enough own history".
8. **Layers** — substitution is a **re-key layer on the netted baseline** applied *after* scheme
   netting and outlier netting inside the shared composed helper `actuals_queryset_with_net()`.
   Discontinuation and introduction are **forecast-output layers** applied when writing `ForecastLine`
   rows, *after* the statistical run. Each layer is inert unless its event rows exist, so the flag is
   a clean opt-in/opt-out.
9. **Consumers** — one `ForecastingConfig.use_item_lifecycle` flag (default `True`) gates **all three**
   layers for: the forecast baseline matrix (`build_actuals_dataframe`), price update
   (`update_weighted_avg_prices`), series classification (`compute_series_profiles`), outlier detection
   (`run_outlier_detection`), forecast-line write (`write_forecast_lines`), and reporting/ABC.
   Detection additionally **skips** any item that is the `old_item` of a substitution row (the retired
   code's history is owned by the successor) but does **not** skip a discontinued item (its history is
   its own and still feeds reporting/ABC/accuracy).
10. **Feature flag** — `item_lifecycle` key in `ClientFeatureControl` (parent `demand_planning`,
    mirrors `scheme_management`); `item_lifecycle_ui_visible()` wrapper in `utils/feature_control.py`.
11. **Admin/UI** — `ItemSubstitutionAdmin`, `ItemDiscontinuationAdmin`, `ItemIntroductionAdmin` (all
    `ClientScopedMixin`) in a new `mysite/admin/demand_lifecycle.py` (registered in
    `mysite/admin/__init__.py`); small HTMX list/create/edit sections for the three event types under
    the demand-planning UI, gated on the feature key. No DRF endpoints.
12. **Authorization** — all three models registered in the Guardian `ADMIN_ONLY_MODELS` permission
    sync in `mysite/signals.py` (admin-role CRUD after migrate; viewer/staff get none) — same wiring
    as the scheme cluster.

---

## Documented Simplifications (in scope but bounded)

- **Direct mapping only** for all three event types — chains (A→B→C) and reference chains are
  rejected by validation; a planner consolidating three variants into one successor adds three rows
  (old₁→new, old₂→new, old₃→new), which is the supported shape. Transitive history follow-through is
  not supported in the MVP.
- **One directive per item** — subject roles are pairwise exclusive; an item cannot be both
  substituted and discontinued, etc. (a discontinued item's history belongs to nobody; if a successor
  exists, use substitution).
- **Uniform factor for qty and value** on substitution and introduction — separate qty/value
  conversion is not offered; a launch-time repricing is expressed by letting the new item's own (net)
  weighted price take over after launch.
- **Effective-from cutoff is exclusive** — old rows `>= effective_from` never convert. If the old item
  genuinely kept selling after launch, that volume stays with the retired code and is excluded from
  the successor's series (the planner should set `effective_from` to the true handover date).
- **Discontinuation is forecast-output only** — no `Item` master-data archive/status change, no
  actuals mutation, no successor; history stays in reporting/ABC/accuracy.
- **Introduction borrows the reference item's statistical forecast at matching leaf grains** — no
  re-forecast of reference history; a grain with no reference line simply gets no borrowed line
  (planner can override); the borrow uses the current run's reference output, not a historical blend.
- **No per-(grain, period) prefer-new-else-old rule** — the substitution cutoff keeps converted and
  own actuals disjoint in time; introduction stop conditions (window / own-history) are evaluated per
  period, so no per-period preference logic is needed.
- **No lifecycle-event analytics UI** — mappings are maintained in admin + the HTMX forms.
- **Validation is structural, not signal-driven** — exclusivity and direct-mapping rules are checked
  in `clean()` and mirrored by `post_save`/`post_delete` receivers that materialize nothing (the
  substitution layer is a live JOIN; the output layers read the models at write time).

---

## Phase 1 — Models, Config & Wiring
**Depends on:** 3B.2c patterns only.
**Delivers:** `ItemSubstitution`, `ItemDiscontinuation`, `ItemIntroduction` in
`mysite/models/demand/lifecycle.py` (validation: factor/ratio > 0, same client, subject roles pairwise
exclusive, direct-mapping-only, structural checks); `ForecastingConfig.use_item_lifecycle` (default
True); `item_lifecycle` `ClientFeatureControl` key + `item_lifecycle_ui_visible()`; the three
ModelAdmins in `mysite/admin/demand_lifecycle.py` registered in `mysite/admin/__init__.py`; all three
models registered in `ADMIN_ONLY_MODELS` (signals.py).
**Exit criteria:** A non-superuser admin-role user can CRUD all three event types in Django admin
after migrate while viewer/staff see none; each `clean()` rejects: cross-client items, old==new /
new==reference, `conversion_factor`/`ratio <= 0`, inverted `copy_to < copy_from`, a duplicated
`(client, subject)` row, direct-mapping violations, and mixed subject roles (an item already used in
another event type); the feature key disables the HTMX sections when set.

## Phase 2 — Baseline Re-key Layer (Substitution — Scenario 3)
**Depends on:** Phase 1.
**Delivers:** `actuals_queryset_with_net(client, use_net, use_substitution=False)` gains a substitution
layer — a correlated `Subquery` on `ItemSubstitution` (unique per row) that annotates `eff_item_id` /
`eff_item_code` and multiplies `net_qty` / `net_revenue` by `conversion_factor` when
`(effective_from IS NULL OR period_start < effective_from)`; consumers re-keyed to the effective item:
`build_actuals_dataframe` (forecast matrix), `update_weighted_avg_prices` (new item's weighted price
derives from merged history), `compute_series_profiles._load_actuals` (new item's series decisions on
merged history).
**Exit criteria:** A fixture with old=A (12 periods, `conversion_factor=0.5`, `effective_from` = launch
of B) produces B's forecast matrix rows = B's own actuals + A's netted actuals × 0.5 for periods before
the launch and B's own actuals only on/after it; B's weighted-avg price equals the merged
`sum(revenue)/sum(qty)`; A's post-launch rows (if any) remain keyed to A; A produces no forecast
on/after `effective_from`; with `use_item_lifecycle` off, everything behaves exactly as before
(identity).

## Phase 3 — Forecast-Output Layers (Discontinuation + Introduction — Scenarios 1 & 2)
**Depends on:** Phase 2.
**Delivers:** `ForecastLine` gains nullable `borrowed_from_item` / `borrowed_ratio` columns;
`write_forecast_lines` (and the forecast pipeline) apply the two output layers when
`use_item_lifecycle` is True:
- **Discontinuation:** items with an `ItemDiscontinuation` row emit no `ForecastLine` for
  `period_start >= effective_from` (nil); pre-cutoff periods forecast normally.
- **Introduction:** for periods inside the borrow window where the new item has
  `< min_history_periods` own periods, the new item's line is set to the reference item's statistical
  line × `ratio`, tagged `borrowed_from_item` / `borrowed_ratio`. `ForecastAggregate` roll-ups include
  borrowed qty/value; the reference item's lines are untouched.
**Exit criteria:** A discontinued item's horizon on/after its date is empty (nil) while periods before
it forecast normally; a new item fixture (reference B, `ratio=0.5`, `copy_from` = launch) receives
B×0.5 lines per period until it accumulates `min_history_periods` own periods, then its own statistical
forecast takes over; borrowed lines carry the reference attribution; `use_item_lifecycle=False`
disables both layers.

## Phase 4 — Detection & Reporting
**Depends on:** Phase 2 (Phase 3 for the output layers).
**Delivers:** `run_outlier_detection` skips items that are the `old_item` of a substitution row (their
history is owned by the successor and already carries its confirmed adjustments) and **keeps**
discontinued items in detection (their history is their own and still feeds reporting/ABC/accuracy);
reporting and ABC classification read the same helper with `use_item_lifecycle` (default True).
**Exit criteria:** A spike in A's converted history is never proposed as a B candidate when it was
already netted; no candidate is proposed for the retired A; a spike in a discontinued item's own
history is still proposed; the actuals dashboard honours the flag.

## Phase 5 — HTMX UI + Hardening
**Depends on:** Phase 1.
**Delivers:** `item_substitution_list/create/edit`, `item_discontinuation_list/create/edit`,
`item_introduction_list/create/edit` HTMX views under `/planning/`, gated on
`item_lifecycle_ui_visible`; nav link; full unit-test suite (models, helper, output layers, detection
rules, feature gate).
**Exit criteria:** A planner creates all three event types from the UI and a subsequent forecast run
of the new code visibly uses converted predecessor history (substitution), the withdrawn item's horizon
is nil (discontinuation), and the introduced item shows borrowed reference lines (introduction); all
tests pass.

---

## Non-Goals (this sprint)

- No chained/multi-hop substitution or introduction resolution.
- No auto-detection of lifecycle events (planner-entered only; no suggestion engine).
- No `Item` master-data archive/status mutation — lifecycle events are forecast-layer only.
- No separate qty/value conversion factors.
- No per-period prefer-new-else-old logic (cutoff/window stop conditions are exclusive).
- No substitution-aware detection *for the retired item* beyond skipping it; no detection changes for
  discontinued items beyond leaving them alone.
- No changes to the statistical model families or reconciliation — lifecycle only feeds the baseline
  and the output lines.

---

## Effort

| Sprint | Effort (solo dev) |
|--------|------------------|
| 3B.2d Item Lifecycle (substitution + discontinuation + introduction) | 6–9 days |

(Dependency: 3B.2c first. 3B.2d is small because it rides the composed helper and the established
admin/feature-flag patterns; the two output layers are additive at the ForecastLine write boundary.)
