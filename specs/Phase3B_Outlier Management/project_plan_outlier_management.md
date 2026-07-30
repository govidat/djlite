# Project Plan — Actuals Outlier Management (FINAL)

**Scope:** Add a hybrid system/planner outlier-detection and net-actuals layer between actuals
ingestion (`ActualSale`) and the forecast/reporting/ABC-classification consumers. Delivered as Sprint
3B.2b, between existing Sprint 3B.2 (Actuals Import) and 3B.3 (Forecast Models). The review UI is
Django Template + HTMX, absorbed into 3B.2b rather than scheduled as a separate frontend sprint.

**Positioning rationale unchanged:** this must land before 3B.3/3B.4, since the forecast engine's
actuals-loading step needs to know whether to net from day one.

---

## All Design Decisions — Confirmed

1. **Adjustment model** — single mutable record, `OneToOneField` to `ActualSale`. Clean fit given
   `ActualSale`'s own unique constraint guarantees one row per grain — no separate grain-keyed
   uniqueness needed on the adjustment table.
2. **Netting mechanism** — query-time, not materialized. No `ActualSaleNet` table, no refresh task.
   `actuals_queryset_with_net()` annotates `net_qty`/`net_revenue` via a `Case`/`When` (Django ORM) or
   equivalent `LEFT JOIN` (DuckDB) at read time. Confirming/rejecting an adjustment only updates its
   own row.
3. **Detection sensitivity + net-actuals flags** — six plain fields directly on the `Client` model
   (`mad_threshold`, `persistence_periods`, `min_history_periods`, `forecast_uses_net_actuals`,
   `reporting_uses_net_actuals`, `abc_classification_uses_net_actuals`), not a separate config model.
   No lazy-default-creation logic needed — every `Client` row has these values from the migration
   forward.
4. **Reporting/ABC default posture** — `reporting_uses_net_actuals` and
   `abc_classification_uses_net_actuals` both default `True`, same as `forecast_uses_net_actuals`. Net
   actuals are the default position everywhere unless a Client opts a specific module back to raw.
5. **Review UI** — Django Template + HTMX, consistent with the existing `demand_ui/` app. No React SPA
   build for this feature; the queue view, confirm/reject actions, and raise-exception form are all
   HTMX-driven partial swaps against server-rendered templates.

---

## Phase 1 — Data Model & Query-Time Netting Helper
**Depends on:** Sprint 3B.2 (Actuals Import).
**Delivers:** `ActualSaleOutlierAdjustment` model, six new `ForecastingConfig` fields (migration on the existing
model), `outlier_management` `ClientFeatureControl` key, `actuals_queryset_with_net()` helper.
**Exit criteria:** A confirmed adjustment's net qty/revenue is correctly computed for its row via the
helper; an over-limit adjustment is rejected by `clean()`; the helper returns raw values when a
Client's relevant flag is `False`.

## Phase 2 — Detection Engine
**Depends on:** Phase 1.
**Delivers:** `detect_outlier_candidates` Celery task wired to the import-completion signal, reading
`mad_threshold` / `persistence_periods` / `min_history_periods` straight off `ForecastingConfig`.
**Exit criteria:** Detection runs automatically after every actuals import; a synthetic sustained
increase lasting `persistence_periods` periods is not flagged; a synthetic single-period spike is
flagged; two Clients with different field values produce different candidate sets on identical
fixture data.

## Phase 3 — Planner Review Views & Admin
**Depends on:** Phase 1; can run in parallel with Phase 2.
**Delivers:** Django Template + HTMX views (queue page, confirm/reject partials, raise-exception form),
`flag_stale_forecast_versions` Celery task, Django Admin (`ActualSaleOutlierAdjustmentAdmin`, six new
fields added to `ForecastingConfigAdmin`).
**Exit criteria:** A planner can browse the queue, confirm/reject a candidate, and raise a new
exception, all through server-rendered HTMX partials; confirming/rejecting flags any affected `DRAFT`
forecast version.

## Phase 4 — Forecast & Override Engine Integration
**Depends on:** Phase 1 only (read-path change).
**Delivers:** `build_actuals_dataframe` and `compute_proportional_shares` updated to call
`actuals_queryset_with_net()` (or the DuckDB-side equivalent) gated by `forecastingconfig.forecast_uses_net_actuals`.
**Exit criteria:** A forecast run against a Client with a confirmed outlier adjustment measurably
differs from the same run with the adjustment rejected.

## Phase 5 — Reporting & ABC Classification Integration
**Depends on:** Phase 1 only (read-path change); can run in parallel with Phase 4.
**Delivers:** Reporting queries and ABC classification updated to call the same helper, gated by
`forecastingconfig.reporting_uses_net_actuals` and `forecastingconfig.abc_classification_uses_net_actuals` respectively.
**Exit criteria:** A Client with `reporting_uses_net_actuals=False` still shows raw revenue in reports
even when a forecast-facing query on the same Client shows the net figure.

## Phase 6 — Hardening & Regression
**Depends on:** All prior phases.
**Delivers:** Full test suite (detection accuracy fixtures, netting annotation correctness, flag
fallback paths, view/form validation edge cases), load check on detection running across a full
monthly import batch, cross-browser QA pass on the HTMX confirm/reject/raise-exception dialogs
(the project has hit Firefox-specific dialog issues before — worth covering here explicitly).
**Exit criteria:** End-to-end test passes: import → candidates detected → planner confirms one via the
HTMX queue → forecast run reflects the exclusion → a Client with `reporting_uses_net_actuals=False`
still shows raw revenue in its reports.

---

## Sequencing Summary

```
Phase 1 (Data Model + Netting Helper)
  ├─▶ Phase 2 (Detection Engine)         ─┐
  ├─▶ Phase 3 (Review Views/Admin)        ├─▶ Phase 6 (Hardening & Regression)
  ├─▶ Phase 4 (Forecast Integration)      │
  └─▶ Phase 5 (Reporting/ABC Integration) ┘
```

Phases 2–5 can all proceed in parallel once Phase 1 lands, since each is a self-contained read-path or
task addition against the same underlying model and helper.

---

Task-level Sprint 3B.2b checklist (models, migrations, detection engine, stale-flagging, HTMX
views/templates, admin) is now in the roadmap delta doc — ready to execute against.
