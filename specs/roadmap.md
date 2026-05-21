# Roadmap

## Phasing Philosophy

Each phase delivers a fully working, deployable product. No phase depends on unbuilt scaffolding from a future phase. The current codebase represents Phase 1 in an advanced state — the roadmap reflects what is done, what remains, and what comes next.

---

## Phase 1 — Multi-Tenant CMS with Page Builder & Auth

**Goal**: A deployed SaaS where multiple SME clients can each publish multilingual, multi-page websites. Client staff manage content. Customers can register and log in.

### Milestone 1.1 — Project Foundation ✅ Done
- [x] Django 5.2.4 project scaffold (`mydj/` project root)
- [x] `requirements.txt` with pinned versions
- [x] SQLite for dev wired up
- [x] `django-tailwind` (`theme` app) installed and configured
- [x] `django-cotton` installed with correct loader chain (`APP_DIRS=False`, `cached.Loader`)
- [x] `django-debug-toolbar` installed with conditional loading (`not TESTING` guard)
- [x] `honcho` + `cookiecutter` for Tailwind dev workflow
- [x] Split `settings.py` into `base.py` / `development.py` / `production.py`
- [x] Move `SECRET_KEY` to environment variable
- [ ] `whitenoise` for static files
- [ ] PostgreSQL wiring via `DATABASE_URL` env var
- [ ] Deploy skeleton app to Railway/Render (establish pipeline early)

### Milestone 1.2 — Multi-Tenancy Core ✅ Done
- [x] `Client` model: `client_id` (LowercaseCharField), `parent` (self-FK for hierarchy), `language_list` (JSONField), `theme_list` (JSONField), translatable `name` / `nb_title`
- [x] `CustomerProfileMiddleware`: resolves `/{client_id}/` → `request.client`; URL kwargs → session fallback
- [x] `client_context` context processor: consumes `request.client`, calls `fetch_clientstatic()`, delivers `client`, `theme`, `page_dict` to all templates
- [x] `ClientLocation` model: `location_id`, `location_type` (store/branch/warehouse/office), FK to `Client`
- [x] `LowercaseCharField` custom field for all natural-key IDs
- [x] Explicit `AppConfig` for `mysite` (verify app label matches in all migrations)
- [x] URL namespace: confirm `/{client_id}/` prefix routes are fully wired in `urls.py`
- [x] `NavItem` model: `name` (translatable), `location` (header/footer/sidebar),
      `nav_type` (page/url/anchor/label), optional FK to `Page`, `url`,
      `order`, `open_in_new_tab`, `parent` self-FK for one level of nesting.
      Decouples navbar from page tree. `get_url()` resolves full path for
      `page` nav_type. `header_nav` and `footer_nav` added to
      `fetch_clientstatic` payload.
- [x] `navbar_v001_l1recur.html` cotton component: recursive, handles all
      four `nav_type` values, active-state highlighting via `item.url` vs
      `current_page`, `item.href` for resolved anchor href.

### Milestone 1.3 — User Model & Auth ✅ Done
- [x] Django's built-in `User` used directly (no custom AbstractBaseUser)
- [x] `ClientUserProfile`: `OneToOneField(User)`, FK to `Client`, `mobile`, `is_active`
- [x] `CustomerProfile`: `ForeignKey(User)`, FK to `Client`, `preferred_language`, `preferred_theme`, `default_address`, `unique_together (user, client)`
- [x] `CustomerAddress`: FK to `CustomerProfile`, `is_default` logic with auto-clear on save
- [x] `ClientGroup`: `role` (admin/staff/viewer), M2M to `ClientLocation`, FK to `Client`
- [x] `ClientGroupPermission`: module + action level permissions per group
- [x] `ClientUserMembership`: user → group assignment with cross-client `clean()` validation
- [x] `django-allauth` configured with `ClientAwareAccountAdapter`
- [x] `django-allauth-ui` with `widget_tweaks` + `slippers` dependencies
- [x] `django-guardian` installed with `ObjectPermissionBackend`; custom permissions on `Client` model
- [x] `CustomerProfileMiddleware` sets `request.active_role` (`staff` / `customer` / `None`)
- [x] Auth entry points: `client_login`, `client_signup`, `client_logout` views
- [x] Customer onboarding flow (`customer_onboarding` view + forms)
- [x] Customer profile view (`customer_profile`)
- [x] Customer address views (`customer_addresses`, `add_address`, `set_default_address`, `delete_address`)
- [ ] `ACCOUNT_EMAIL_VERIFICATION` set to `"mandatory"` in production settings
- [ ] Wire `django-guardian` permissions to actual view/admin enforcement (currently installed, not fully enforced)
- [ ] Staff login flow (currently only customer flow is wired end-to-end)

### Milestone 1.4 — Language System ✅ Done
- [x] `settings.LANGUAGES` defined: `en`, `hi`, `fr`, `ta`
- [x] `LANGUAGE_CODE = 'en'` as system default
- [x] `TIME_ZONE = 'Asia/Kolkata'`, `USE_I18N = True`, `USE_L10N = True`, `USE_TZ = True`
- [x] `LocaleMiddleware` in middleware stack
- [x] `LOCALE_PATHS` configured
- [x] `django-modeltranslation` installed before `django.contrib.admin` (required)
- [x] `Client.language_list` JSONField for per-client active languages
- [x] `GlobalVal` / `GlobalValCat` key-value store for UI strings; `get_globalval()` utility
- [x] `globalval` context processor delivering `gv` (resolved) and `gvt` (raw) to all templates
- [x] `SvgtextbadgeValue.language_code` CharField as per-component translation mechanism
- [x] `django-modeltranslation` translation classes registered in `translation.py` for `Client`, `Page`, `Theme`, `GlobalVal` — confirm registrations are complete and migrations generated
- [x] Language switcher UI wired end-to-end (session-based language preference per customer per client)

### Milestone 1.5 — Page Builder Models ✅ Done
- [x] `Page`: `page_id`, `parent` (self-FK), `order`, `hidden`, translatable `name`; `unique_together (client, page_id)`
- [x] `Layout`: single self-referential model with `level` (10/20/30/40), `parent`, `slug`, `order`, `css_class`, `style`, `hidden`; `unique_together (page, level, slug)`; `clean()` validates parent-level integrity
- [x] `Component`: `OneToOneField(Layout)`, `comp_id` (hero/card/accordion/carousel), styling fields per component type, `config` JSONField; `level=40` only
- [x] `ComponentSlot`: FK to `Component`, `slot_type` (figure/text), `order`; figure fields (`image_url`, `alt`); `comptextblocks` GenericRelation
- [x] `ComptextBlock`: GenericForeignKey parent, `block_id` (title/content/actbut), `order`, `css_class`, `href_page`; `textstbitems` GenericRelation
- [x] `TextstbItem`: GenericForeignKey parent, `item_id` (text/svg/badge), `order`, `css_class`, `svg_text`
- [x] `SvgtextbadgeValue`: FK to `TextstbItem`, `language_code`, `stext`, `ltext`
- [x] `ThemePreset`: full design token model (colours, typography, spacing, radius, shadow)
- [x] `Theme`: FK to `Client` + `ThemePreset`, `overrides` JSONField, `is_default`
- [x] `django-admin-sortable2` on `Layout.order`, `ComponentSlot.order`, `Page.order`
- [x] `django-nested-admin` for nested inline hierarchy in Django Admin
- [x] `no_html_tags` + `no_double_quotes` validators on all user-facing text fields
- [x] `GentextBlock` is present but currently unused in `build_client_payload` (commented out) — decide: keep for future use or remove
- [ ] `django-admin-sortable2` fully wired into admin classes for all sortable models

### Milestone 1.5b — Hybrid Page Authoring (Track A: Raw HTML) ✅ Done
- [x] `PageContent` model: FK to `Page`, `language_code`, `html` (TextField)
- [x] `unique_together ('page', 'language_code')` — one blob per language per page
- [x] `ClientPageView` checks `PageContent` before falling through to component tree
- [x] Language fallback: active lang → `en` → first available `PageContent` row
- [x] `PageContentInline` in Django Admin under `Page`
- [x] Signal: `post_save` / `post_delete` on `PageContent` invalidates `clientstatic` cache
- [x] `|safe` filter in template — developer-authored HTML only; sanitiser deferred to Phase 2
- [ ] Document the HTML authoring workflow in README (which tools work, how to paste)
- [x] `fetch_clientstatic(client_id, use_cache, timeout)` — single deeply-prefetched query + cache
- [x] `build_client_payload()` — builds full client dict (languages, themes, pages, page_tree)
- [x] `build_page()` / `build_layout()` / `build_component()` / `build_slot()` — recursive tree builders
- [x] `build_blocks()` / `build_stb_item()` / `build_values()` — text content serialisers
- [x] `build_page_tree()` — builds nested page hierarchy dict for navigation bar
- [x] `serialize_model()` — generic model → dict with modeltranslation grouping
- [x] `resolve_theme()` — merges ThemePreset base tokens with Theme.overrides
- [x] `THEME_PRESET_FIELDS` cached at import time
- [x] `LocMemCache` configured (`translations-cache`)
- [x] **Cache invalidation signals** — `post_save` on `Client`, `Page`, `Layout`, `Component`, `ComponentSlot`, `Theme` must call `cache.delete(f"clientstatic:{client_id}")`. Not yet implemented. Without this, content edits don't reflect until cache expires or server restarts.
- [ ] Switch to Redis cache in production (config is commented in settings — uncomment and wire to env var)
- [ ] `use_cache=True` — currently hardcoded `False` in some call sites for debugging; restore before production

### Milestone 1.7 — Page Rendering ✅ Done (partially)
- [x] `ClientPageView(TemplateView)` — renders `base.html` with client/page/theme from context processor
- [x] `client_context` processor resolves `page_dict` from URL kwargs (`page` kwarg → match in `client.pages`)
- [x] `set_theme` view — POST handler, stores `active_theme_id` in session
- [x] `landing_page` view — root URL with no client context
- [x] `django-cotton` component templates wired for component types
- [ ] Cotton component templates for all `comp_id` types: `hero`, `card`, `accordion`, `carousel` — confirm all are implemented
- [ ] 404 handling for unknown `client_id` slugs (currently raises `Client.DoesNotExist`, not a clean 404)
- [ ] 404 handling for unpublished / hidden pages
- [ ] Homepage routing: `/{client_id}/` → first published page or configurable homepage
- [x] Split `models.py` into `models/` package:
      base.py, global_config.py, client.py, nav.py,
      page.py, component.py, users.py
      Zero migrations generated — app_label unchanged.
### Milestone 1.8 — Interactive Forms (Pending decision)
- [ ] **HTMX vs Datastar decision** — Datastar was dropped. Evaluate HTMX for: theme switcher, language switcher, inline content editing. Spike and decide.
- [ ] Theme switcher wired with HTMX partial response (currently full-page POST redirect)
- [ ] Language switcher UI component

### Milestone 1.9 — Production Hardening
- [x] Split `settings.py` into `base` / `development` / `production`
- [ ] `SECRET_KEY` moved to env var; `DEBUG=False` in production config
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` set via env vars
- [ ] `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` in production
- [ ] `whitenoise` static files verified on PaaS
- [ ] `DATABASE_URL` env var driving PostgreSQL
- [ ] Redis cache wired in production
- [ ] Cache invalidation signals implemented
- [ ] `manage.py check --deploy` passes with no warnings
- [ ] Basic smoke tests: tenant resolution, page render, auth flows
- [x] README with local dev setup and deploy instructions

---

## Open Decisions

| Decision | Status | Notes |
|----------|--------|-------|
| DONE - HTMX Added in Phase 2 - HTMX vs Datastar | Datastar dropped. HTMX not yet added. | Spike HTMX for theme/language switcher and inline editing |
| NOT Used `GentextBlock` retention | Present but unused | Decide: keep for future use or remove to reduce model complexity |
| DONE`models.py` split | Single file, growing large | Split into `models/` package before Phase 2 |
| WIP Staff admin UI | Django Admin (current) | Re-evaluate custom dashboard after Phase 1 with real client feedback |
| DONE Cache invalidation | Not implemented | Required before production — `post_save` signals on all content models |
| DONE Navbar architecture | ~~Coupled to page_tree~~ → **Resolved**: dedicated `NavItem` model,
|    decoupled from pages, supports external links and footer nav independently | Done |
---

## Phase 2 — Product Catalogue

**Goal**: Each client can manage a product catalogue. Customers can browse products per client.

### Key Deliverables
- [ ] `Category` model: hierarchical (adjacency list or MPTT), tenant-scoped, translatable
- [ ] `Product` model: `name`, `description`, `SKU`, images, `price`, `stock_status` — translatable
- [ ] `ProductVariant`: size, colour, or custom attribute variants
- [ ] Product list and detail pages (as new `comp_id` types in the component system, or dedicated URL patterns)
- [ ] Client admin: product CRUD with image upload
- [ ] Media file migration: PaaS volume → S3 / Cloudflare R2
- [ ] Celery + Redis: background jobs for bulk product import (CSV)
- [ ] Split `models.py` into `models/` package (required before this phase)


## Phase 2 — Item Catalogue (Implementation Plan)
 
### Sprint 2.1 — Models and Migration
- [ ] Create `mysite/models/catalogue.py` with `Taxonomy`, `TaxonomyNode`,
      `Item`, `ItemTaxonomyNode`, `ItemImage`, `ItemVariant`
- [ ] Add to `mysite/models/__init__.py`
- [ ] Register translatable fields in `translation.py`:
      `Taxonomy.name`, `TaxonomyNode.name`, `Item.name`, `Item.description`
- [ ] `python manage.py makemigrations`
- [ ] Add PostgreSQL GIN index and path index via `RunSQL` in migration
- [ ] `python manage.py migrate`
- [ ] `python manage.py check` — 0 issues
### Sprint 2.2 — Admin
- [ ] Create `mysite/admin/catalogue.py`:
      `TaxonomyAdmin` (with `TaxonomyNodeInline`),
      `ItemAdmin` (with `ItemTaxonomyNodeInline`, `ItemImageInline`, `ItemVariantInline`)
- [ ] Register in `mysite/admin/__init__.py`
- [ ] Verify admin renders correctly for all models
### Sprint 2.3 — Query Layer
- [ ] Create `utils/catalogue_queries.py`:
      `get_resolved_taxonomies()`, `get_taxonomy_tree()`,
      `get_item_queryset()`, `build_catalogue_payload()`,
      `get_facet_counts()`, `paginate_items()`
- [ ] Unit test: global item overridden by client item of same `item_id`
- [ ] Unit test: subtree filter includes descendants
- [ ] Unit test: JSONB attribute filter
### Sprint 2.4 — Views and URLs
- [ ] Create `mysite/views/catalogue.py`:
      `catalogue_page`, `catalogue_filter`, `item_detail`
- [ ] Add to `mysite/views/__init__.py`
- [ ] Wire URLs in `mydj/urls.py` BEFORE `<str:client_id>/<str:page>/` catch-all
- [ ] Add `django-htmx` to `requirements.txt` and `MIDDLEWARE`
### Sprint 2.5 — Templates
- [ ] `templates/catalogue/page_catalogue.html` (Track B full page)
- [ ] `templates/catalogue/page_catalogue_html.html` (Track A wrapper)
- [ ] `templates/catalogue/partials/filter_sidebar.html`
- [ ] `templates/catalogue/partials/filter_node.html` (recursive)
- [ ] `templates/catalogue/partials/items_list.html` (HTMX target)
- [ ] `templates/catalogue/partials/item_card.html`
- [ ] `templates/catalogue/partials/pagination.html`
- [ ] `templates/catalogue/item_detail.html`
- [ ] Add `dict_filters.get_item` to templatetags if not already present
### Sprint 2.6 — Cache and Signals
- [ ] Add `Taxonomy`, `TaxonomyNode` to signal invalidation
- [ ] Add `invalidate_taxonomy_cache()` handler using `delete_pattern`
      (Redis) or manual key loop (LocMemCache dev)
- [ ] Verify taxonomy tree cache invalidates on node save
### Sprint 2.7 — Sample Data and Testing
- [ ] Create `management/commands/load_sample_products.py`
- [ ] Run: `python manage.py load_sample_products bahushira`
- [ ] End-to-end test: visit `/{client_id}/catalogue/`
- [ ] Test HTMX filter: click category checkbox → items update without reload
- [ ] Test pagination: next/prev updates items without reload
- [ ] Test item detail: `/{client_id}/catalogue/tshirt-001/`
- [ ] Test language switch: item names render in active language
- [ ] Test global/client override: global item suppressed by client item
### Sprint 2.8 — Production Hardening
- [ ] Deploy to PaaS with PostgreSQL
- [ ] Verify GIN index is active: `EXPLAIN ANALYZE` on attributes filter
- [ ] Verify path index is active: `EXPLAIN ANALYZE` on subtree query
- [ ] Load test: 20k items, 50 concurrent filter requests

### Sprint 2.9 (Authorization) added:
- [ ] Superuser-only GlobalItem admin
- [ ] ClientAdmin can select from GlobalItems but not create them
- [ ] TaxonomyNode (client=None) admin restricted to superuser
---
 
## Open Decisions (Phase 2)
 
| Decision | Options | Target |
|----------|---------|--------|
| HTMX adoption | Confirmed for catalogue filters + pagination | Sprint 2.4 |
| Media file storage | PaaS volume (Phase 2) → S3/Cloudflare R2 (Phase 2.8) | Sprint 2.8 |
| Bulk import | CSV management command | Sprint 2.7 |
| Search | `icontains` (Phase 2) → PostgreSQL full-text (Phase 3) | Phase 3 |


---

## Phase 3 — eCommerce

**Goal**: Customers can purchase products. Clients can manage orders.
Phase 3 commerce models are Beckn schema-aligned. Full Beckn network participation (BPP role, async callbacks, digital signatures, ONDC registry) is Phase 4.

### Key Deliverables
- [ ] `Cart` and `CartItem`: session-based for anonymous, DB-persisted for logged-in customers
- [ ] `Order` and `OrderItem`: full lifecycle (pending → confirmed → shipped → delivered → cancelled)
- [ ] Payment gateway integration (Stripe or Razorpay for INR — TBD)
- [ ] Order confirmation emails (Celery task)
- [ ] Client dashboard: order management, basic revenue reporting
- [ ] REST API layer (`djangorestframework`) for future mobile app consumption
- [ ] Customer order history view
- [ ] `ClientGroupPermission` modules `cart`, `order`, `delivery`, `shipment`, `billing` activated (model stubs already present)

---

## Deferred / Future Consideration

| Feature | Rationale |
|---------|-----------|
| Native mobile app | Needs REST API (Phase 3) and separate build pipeline. `fetch_clientstatic` dict is pre-adapted for API use. |
| Subdomain / custom domain routing | Increases infrastructure complexity; path-prefix sufficient through Phase 2 |
| Drag-and-drop visual page editor | High frontend complexity; validate Django Admin approach with real clients first |
| Elasticsearch / full-text search | Premature until catalogue size justifies it |
| Multi-currency | Deferred until eCommerce validated |
| Redis cache (dev) | LocMemCache sufficient for development; Redis config is already written — just needs uncommenting |

## Phase 3B — Demand Planning
*(Recommended sequencing: build Phase 3B before Phase 3A eCommerce so that
approved forecasts can feed into Order creation as suggested quantities.)*
 
**Goal:** Client staff can upload monthly actuals (SKU × Customer × Location),
trigger statistical forecast runs, make consensus overrides at any hierarchy
level, approve a final forecast, and track accuracy against actuals.
 
Phase 3B uses the existing `Item`, `CustomerProfile`, and `ClientLocation` models
from Phases 1 and 2 as foreign keys. It adds a new `demand/` model package and a
React SPA frontend served under `/{client_id}/planning/`.
 
---
 
### Sprint 3B.0 — Foundation and Prerequisites
- [ ] Add `statsforecast`, `hierarchicalforecast`, `polars`, `duckdb`, `prophet`, `openpyxl`, `pandas` to `requirements.txt`
- [ ] Add `ClientFeatureControl` keys: `demand_planning`, `actuals_upload`, `forecast_run`, `consensus_override`, `forecast_approval`
- [ ] Add `ClientLocation.parent` self-FK (nullable) + `path` CharField for materialized path
- [ ] Add `ClientLocation.path` index (`text_pattern_ops`)
- [ ] `python manage.py makemigrations && migrate`
- [ ] `python manage.py check` — 0 issues
---
 
### Sprint 3B.1 — Sales Hierarchy Models
- [ ] Create `mysite/models/demand/hierarchy.py`:
  - `SalesNode(client, name, level_label, parent→self, location FK nullable, path CharField)`
  - `CustomerSalesAssignment(customer, sales_node, valid_from, valid_to)`
- [ ] `SalesNode` materialized path: `pre_save` signal computes path from parent chain
- [ ] Add `ix_salesnode_path` index via `RunSQL` in migration
- [ ] Admin: `SalesNodeAdmin` (tree display with indent), `CustomerSalesAssignmentInline`
- [ ] REST endpoint: `GET /api/demand/sales-hierarchy/` → full tree JSON
- [ ] REST endpoint: `GET /api/demand/location-hierarchy/` → ClientLocation tree JSON
- [ ] Unit tests: path computed correctly on create/reparent; subtree query returns all descendants; CustomerSalesAssignment date effectivity
---
 
### Sprint 3B.2 — Actuals Models and Import Pipeline
- [ ] Create `mysite/models/demand/actuals.py`:
  - `ActualSale(client, item, variant nullable, customer, location, year, month, qty, revenue MoneyField)`
  - Unique constraint: `(client, item, customer, location, year, month)`
  - `ActualSaleLocation(client, location, year, month, total_qty, total_revenue MoneyField)`
  - `ActualSaleImport(client, import_date, source_file, row_count, status, errors JSONField)`
- [ ] Add DB indexes: `ix_actualsale_client_period`, `ix_actualsale_item_customer`
- [ ] Django Admin: `ActualSaleImport` admin with status display
- [ ] REST endpoint: `POST /api/demand/actuals/upload/` — multipart file, creates import job
- [ ] REST endpoint: `GET /api/demand/actuals/upload/{id}/` — poll import status
- [ ] REST endpoint: `GET /api/demand/actuals/` — filtered query (item, customer, location, period range)
- [ ] Celery task `process_actuals_import(import_id)`:
  - Parse CSV / Excel with `pandas`
  - Validate all FKs exist; collect errors per row into `ActualSaleImport.errors`
  - `bulk_create` with `update_conflicts=True` (idempotent re-upload)
  - Update `ActualSaleImport.status` → `COMPLETE` / `FAILED`
- [ ] Celery task `process_summary_actuals_import` for `ActualSaleLocation`
- [ ] Excel template: `management/commands/generate_actuals_template.py` — produces a `.xlsx` with correct column headers for client download
- [ ] Unit tests: duplicate upload → idempotent; invalid item FK → error row; valid upload → `ActualSale` row count correct
---
 
### Sprint 3B.3 — Forecast Models and Version Management
- [ ] Create `mysite/models/demand/forecast.py`:
  - `ForecastVersion(client, version_label, base_period_end, horizon_months, engine_config JSONField, status, created_by, approved_by nullable, approved_at nullable)`
  - `ForecastLine(version, item, customer, location, year, month, statistical_qty, override_qty nullable, final_qty)` — `final_qty` = `override_qty or statistical_qty` (computed on save)
  - `ForecastAggregate(version, agg_level, agg_key JSONField, year, month, statistical_qty, override_qty, final_qty)`
  - `ForecastOverride(version, override_level, override_key JSONField, year, month, override_qty nullable, override_pct nullable, disagg_method, override_note, created_by)`
  - `OverrideSplitWeight(override, child_key JSONField, weight)` — for CUSTOM disaggregation
  - `ForecastAccuracy(version, item, customer, location, year, month, actual_qty, forecast_qty, mape, bias)`
- [ ] Add DB indexes: `ix_forecastline_version`, `ix_forecastaggregate_version_level`
- [ ] `ForecastVersion.status` state machine: `DRAFT → IN_REVIEW → APPROVED → LOCKED`
- [ ] REST endpoints:
  - `GET/POST /api/demand/forecast-versions/`
  - `GET /api/demand/forecast-versions/{id}/`
  - `GET /api/demand/forecast-versions/{id}/lines/` (paginated, filterable)
  - `GET /api/demand/forecast-versions/{id}/aggregates/`
  - `POST /api/demand/forecast-versions/{id}/approve/`
- [ ] Admin: `ForecastVersionAdmin` with status display; read-only `ForecastLineInline` (paginated)
- [ ] Unit tests: `final_qty` computation; status transition guard (LOCKED → no edits); version copy
---
 
### Sprint 3B.4 — Statistical Forecast Engine
- [ ] Create `utils/demand/forecast_engine.py`:
  - `build_actuals_dataframe(client_id, period_start, period_end)` → Polars DataFrame via DuckDB
  - `build_summing_matrix(client_id)` → numpy array `S` + `tags` dict for three hierarchy dimensions
  - `run_statsforecast(actuals_df, horizon_months)` → forecasts DataFrame
  - `run_hierarchical_reconciliation(forecasts_df, actuals_df, S, tags, method)` → reconciled DataFrame
  - `write_forecast_lines(version_id, reconciled_df)` → bulk_create ForecastLine (batched 5000)
  - `write_forecast_aggregates(version_id)` → roll-up ForecastAggregate for all agg_levels
- [ ] Celery task `run_forecast(version_id)`:
  - Orchestrates the above pipeline steps
  - Updates `ForecastVersion.status` → `READY` on success, `FAILED` on error
  - Notifies requesting user
- [ ] Engine config JSONField controls: model list (ETS / ARIMA / Theta / CrostonSBA), reconciliation method, intermittent threshold (series with zero rate > X% use CrostonSBA automatically)
- [ ] REST endpoint: `POST /api/demand/forecast-versions/` with `engine_config` → triggers `run_forecast` Celery task; returns version_id for polling
- [ ] REST endpoint: `GET /api/demand/forecast-versions/{id}/` includes `celery_task_id` for progress polling
- [ ] Unit tests:
  - `build_summing_matrix` produces correct `S` shape for known hierarchy
  - Reconciled totals at top level equal sum of bottom-up actuals (within float tolerance)
  - CrostonSBA selected for intermittent series (> 50% zero months)
  - `write_forecast_lines` bulk_create produces correct row count
---
 
### Sprint 3B.5 — Consensus Override Engine
- [ ] Create `utils/demand/override_engine.py`:
  - `resolve_leaf_lines(version_id, override_key, override_level)` → list of leaf `ForecastLine` PKs in subtree
  - `compute_proportional_shares(leaf_lines, base_year, base_month_range)` → dict of leaf_pk → share
  - `apply_override(override_id)` → updates `ForecastLine.override_qty` for each leaf
  - `recompute_aggregates(version_id, affected_agg_keys)` → updates `ForecastAggregate` records
- [ ] Routing logic: subtree < 500 leaves → synchronous; ≥ 500 → Celery task `propagate_override(override_id)`
- [ ] REST endpoints:
  - `GET/POST /api/demand/forecast-versions/{id}/overrides/`
  - `DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/` (reverts leaf lines to statistical)
- [ ] Unit tests:
  - Proportional disaggregation sums to override total (within rounding tolerance)
  - Override revert restores statistical_qty values
  - LOCKED version rejects override POST
---
 
### Sprint 3B.6 — Accuracy Tracking
- [ ] Celery task `compute_forecast_accuracy(version_id, year, month)`:
  - Joins `ForecastLine` (approved version, given period) with `ActualSale`
  - Computes per-leaf: `mape = abs(actual - forecast) / actual`, `bias = (forecast - actual) / actual`
  - Writes `ForecastAccuracy` records (bulk_create, update_conflicts=True)
  - Computes `WMAPE = sum(abs(actual - forecast)) / sum(actual)` at aggregate levels
- [ ] Scheduled: monthly Celery beat task triggers for all Clients with `demand_planning` feature enabled
- [ ] REST endpoint: `GET /api/demand/forecast-versions/{id}/accuracy/`
- [ ] Unit tests: MAPE formula; WMAPE aggregate; division-by-zero guard (actual = 0)
---
 
### Sprint 3B.7 — React SPA Frontend
- [ ] Scaffold React app under `frontend/planning/` (Vite + TypeScript)
- [ ] Served under `/{client_id}/planning/` via a Django catch-all view that returns `planning.html` shell
- [ ] Auth: shares Django session cookie; DRF SessionAuthentication on all demand API endpoints
- [ ] **View 1 — Actuals Dashboard:**
  - Upload widget (drag-and-drop CSV/Excel) → polls import job status
  - Location × Month heatmap (ECharts) showing total revenue
  - SKU drill-down table (AG Grid): item × customer × location × month
- [ ] **View 2 — Forecast Run:**
  - Select base period, horizon, reconciliation method
  - Submit → polls `ForecastVersion.status`; shows progress bar
  - On complete: navigate to Consensus Grid
- [ ] **View 3 — Consensus Override Grid (AG Grid):**
  - Rows: item groups / locations / sales nodes (switchable grouping)
  - Columns: months (horizon)
  - Cell values: `final_qty`; editable at any aggregate level
  - On cell edit: POST `ForecastOverride`; optimistic UI update; background propagation
  - Colour coding: statistical (white), overridden (yellow), locked (grey)
- [ ] **View 4 — Version Comparison:**
  - Select two versions; ECharts line chart overlay at chosen aggregate level
- [ ] **View 5 — Accuracy Report:**
  - MAPE / Bias / WMAPE by product group, by location, by sales node
  - Sortable AG Grid; ECharts bar chart for top N worst-performing SKUs
- [ ] Unit tests (Vitest): AG Grid cell edit triggers correct API call; polling interval logic; share computation display
---
 
### Sprint 3B.8 — Phase 3A Integration
- [ ] `OrderLine` gains `forecast_line` nullable FK → `ForecastLine`
- [ ] When staff creates `Quotation` or `Order` for a Customer × Item combination, approved `ForecastVersion` is queried for a suggested quantity; shown as a hint on the line form
- [ ] `ForecastAccuracy` extended: `actual_order_qty` column populated from `OrderLine` quantities (in addition to `ActualSale` uploads)
- [ ] Unit tests: suggested quantity shown when approved version exists; `forecast_line` FK set on OrderLine on acceptance
---
 
### Sprint 3B.9 — Production Hardening
- [ ] Deploy with Celery worker (forecasting jobs can run 5–15 min for full matrix; configure `CELERYD_TASK_SOFT_TIME_LIMIT = 1800`)
- [ ] DuckDB installed in production container (pure Python wheel; no native install needed)
- [ ] `EXPLAIN ANALYZE` on actuals matrix pull; verify indexes used
- [ ] Load test: 10K SKU × 200 customer × 36 month forecast run completes < 15 minutes
- [ ] Load test: actuals upload of 50K rows completes < 60 seconds
- [ ] End-to-end test: upload → run → override → approve → order suggestion visible
---
 
## Phase 3B Dependency Map
 
```
3B.0 (Foundation)
  └─▶ 3B.1 (Sales Hierarchy)
        └─▶ 3B.2 (Actuals Import)
              └─▶ 3B.3 (Forecast Models)
                    ├─▶ 3B.4 (Statistical Engine)  ─┐
                    └─▶ 3B.5 (Override Engine)      ├─▶ 3B.6 (Accuracy)
                                                     │         │
                    3B.4 + 3B.5 + 3B.6 ─────────────┴─▶ 3B.7 (React SPA)
                                                               │
                    3B.7 + Phase 3A Sprint 3.3 ───────────────▶ 3B.8 (3A Integration)
                                                               │
                    All ──────────────────────────────────────▶ 3B.9 (Hardening)
```
 
---
 
## Phase 3B Effort Estimates
 
| Sprint | Effort (solo dev) |
|--------|------------------|
| 3B.0 Foundation | 1–2 days |
| 3B.1 Sales Hierarchy | 2–3 days |
| 3B.2 Actuals Import | 3–4 days |
| 3B.3 Forecast Models | 3–4 days |
| 3B.4 Statistical Engine | 5–7 days |
| 3B.5 Override Engine | 4–5 days |
| 3B.6 Accuracy Tracking | 2–3 days |
| 3B.7 React SPA | 7–10 days |
| 3B.8 Phase 3A Integration | 2–3 days |
| 3B.9 Production Hardening | 2–3 days |
| **Total** | **31–44 days** |
 
Sprints 3B.4 and 3B.5 can run in parallel once 3B.3 is complete.
Sprint 3B.7 (React SPA) can begin in parallel with 3B.4/3B.5 once 3B.3 REST endpoints are stubbed.
 
---
 
## Recommended Overall Sequencing
 
```
Phase 2 (Complete)
    ↓
Phase 3B.0–3B.6  (Actuals + Forecast engine, no UI yet)   ← ~20 days
    ↓  [parallel with 3B.7]
Phase 3A.0–3A.3  (Foundation, Pricing, Inquiry, Order)    ← ~20 days
    ↓
Phase 3B.7–3B.8  (React SPA + Order integration)          ← ~12 days
    ↓
Phase 3A.4–3A.12 (Delivery through Production Hardening)  ← ~27 days
    ↓
Phase 4 (Beckn BPP, probabilistic forecasting, ML models)
```
 
This ordering means:
- The forecast engine is validated against real actuals before anyone tries to use it in an order flow.
- The Order model exists (3A.3) before the forecast-to-order integration sprint (3B.8).
- No phase blocks another; each delivers standalone value.
---
 
## Key Risks and Mitigations (Phase 3B)
 
| Risk | Mitigation |
|------|-----------|
| Nixtla library API changes | Pin `statsforecast` and `hierarchicalforecast` versions; isolate in `utils/demand/forecast_engine.py` so a library swap affects one file |
| Summing matrix construction complexity | Unit-test `S` matrix shape and column ordering independently before integrating with `HierarchicalForecast` |
| Forecast job timeout for large clients | `CELERYD_TASK_SOFT_TIME_LIMIT=1800`; design job to checkpoint progress into `ForecastVersion` so it can resume |
| Actuals data quality (missing FKs, wrong item codes) | Row-level error collection in `ActualSaleImport.errors`; never fail the whole batch for a bad row |
| React SPA auth complexity | Use Django session cookie (same domain); no JWT needed in Phase 3B |
| DuckDB + PostgreSQL dual-engine confusion | DuckDB is used **only inside Celery tasks** for fast aggregation; all writes go to PostgreSQL only; document this boundary clearly |
| AG Grid Community licence limits | Community licence is sufficient for Phase 3B; Enterprise (pivot, server-side row model) deferred to Phase 4 if needed |
 
---
 
## Definition of Done (Phase 3B)
 
- [ ] Client staff can upload monthly actuals (CSV/Excel) for SKU × Customer × Location
- [ ] Upload is idempotent (re-upload same file produces no duplicates)
- [ ] Forecast run completes for 10K SKU × 200 customer × 36 month history in < 15 minutes
- [ ] Hierarchical reconciliation: top-level total of reconciled forecast equals sum of bottom-up
- [ ] Consensus override at Location level disaggregates correctly to SKU leaf lines
- [ ] LOCKED version rejects all edits
- [ ] Accuracy report shows MAPE / Bias / WMAPE after actuals close for an approved version period
- [ ] Approved forecast version shows suggested quantity on Quotation / Order line form
- [ ] All demand API endpoints enforce `ClientGroupPermission` (demand_planning module)
- [ ] `manage.py check` clean; 0 migration errors
- [ ] Production load test passed



## Phase 3 — eCommerce

**Goal:** Customers can initiate and track orders across the full commerce lifecycle (Inquiry → Quotation → Order → Delivery → Billing). Clients manage the end-to-end process. Pricing is rule-based, auditable, and extensible. Multi-currency is supported. Partial and split deliveries are handled.

Phase 3 commerce models are Beckn v2.0 schema-aligned. Full Beckn network participation (BPP role, async callbacks, digital signatures, ONDC registry) is Phase 4.

---

### Sprint 3.0 — Foundation and Prerequisites

- [ ] Switch production cache to Redis (`CACHES` env var; Celery broker same Redis instance)
- [ ] Add `djangorestframework`, `django-filter`, `celery`, `djmoney`, `babel` to `requirements.txt`
- [ ] Extend `ClientLocation` with Phase 3 boolean flags: `allow_delivery_split`, `allow_partial_shipment`, `is_dispatch_location`, `enable_picking`, `enable_packing`, `enable_transportation`, `enable_billing_consolidation`
- [ ] Extend `Client` with: `allowed_currencies` (JSONField), `base_currency` (CharField), `allow_delivery_split`, `allow_partial_shipment`, `multi_location_dispatch`
- [ ] Add `ClientCurrencyRule(client, client_country, customer_country, currency)` model + admin
- [ ] Extend `CustomerAddress.address_type` to enum `BILL_TO / SHIP_TO / BOTH`; add Beckn fields: `gps`, `area_code`, `state`, `landmark`
- [ ] Add Phase 3 feature keys to `ClientFeatureControl`: `inquiry`, `quotation`, `picking`, `packing`, `transportation`, `billing_consolidation`, `multi_currency`, `partial_shipment`
- [ ] `python manage.py makemigrations && migrate`
- [ ] `python manage.py check` — 0 issues

---

### Sprint 3.1 — Pricing Engine

- [ ] Create `mysite/models/commerce/pricing.py`:
  - `PricingConditionType` (name, calc_type: ABSOLUTE/PERCENT, category: DISCOUNT/SURCHARGE/TAX)
  - `ConditionAccessSequence` (name, ordered access keys as JSONField)
  - `ConditionRecord` (condition_type, key_combination JSONField, valid_from, valid_to, amount MoneyField, scale FK)
  - `ConditionScale` (condition_record, scale_type VALUE/QTY, breaks JSONField)
  - `PricingProcedure` (client FK, name, is_default)
  - `PricingStep` (procedure FK, step_number, condition_type FK, access_sequence FK, apply_at LINE/HEADER, is_statistical, group_key, requirement, from_step)
  - `PricingResultLine` (GenericFK to Order/Quotation, line_ref, step_number, condition_type, base_amount, condition_value, result_amount, is_statistical)
- [ ] Signal: on Client create, copy system default `PricingProcedure`
- [ ] Create `utils/pricing_engine.py`:
  - `build_pricing_context(document)` — assembles customer, items, quantities, currency
  - `resolve_condition_record(step, context)` — walks access sequence, returns ConditionRecord or None
  - `evaluate_scale(condition_record, context_value)` — returns step rate/amount from ConditionScale
  - `execute_pricing_procedure(document)` — runs all steps sequentially, writes PricingResultLine records, updates document totals
- [ ] Cache: `pricing_procedure:{client_id}` (1hr), `condition_records:{client_id}:{type}` (15min)
- [ ] Admin: `PricingProcedureAdmin` with inline `PricingStepInline`; `ConditionRecordAdmin` with inline `ConditionScaleInline`
- [ ] Unit tests: % condition on derived base; slab step function; header condition apportionment; statistical condition exclusion from total; access sequence fallthrough

---

### Sprint 3.2 — Inquiry and Quotation

- [ ] Create `mysite/models/commerce/inquiry.py`: `Inquiry`, `InquiryLine`
  - `Inquiry` fields: `client`, `customer`, `status` (DRAFT/SUBMITTED/CONVERTED/CANCELLED), `currency`, `bill_to_address`, `ship_to_address`, `source_doc_type`, `source_doc_id`, `valid_until`, timestamps
  - `InquiryLine` fields: `inquiry`, `item`, `variant`, `qty`, `unit_price` (MoneyField), `ship_to_address` (override, nullable)
- [ ] Create `mysite/models/commerce/quotation.py`: `Quotation`, `QuotationLine`
  - `Quotation` fields: same header pattern as Inquiry + `pricing_result_total` (MoneyField)
  - `QuotationLine` fields: same as InquiryLine + `discount_amount`, `tax_amount`, `line_total` (all MoneyField)
- [ ] Create `utils/document_promotion.py`: `promote_document(source, target_model)` service function
  - Validates source status
  - Deep-copies header; sets `source_doc_type` + `source_doc_id`
  - Creates target lines from source lines
  - If target is Quotation or Order: runs `execute_pricing_procedure()`
  - Returns target in DRAFT status
- [ ] Views: `inquiry_create`, `inquiry_detail`, `inquiry_to_quotation`; `quotation_create`, `quotation_detail`, `quotation_to_order`
- [ ] Templates: `commerce/inquiry_form.html`, `commerce/quotation_form.html` (DaisyUI, HTMX inline line editing)
- [ ] Currency dropdown on Inquiry / Quotation header (populated from `Client.allowed_currencies`)
- [ ] Admin: `InquiryAdmin`, `QuotationAdmin` with line inlines; read-only `PricingResultLine` inline on Quotation
- [ ] Unit tests: Inquiry → Quotation promotion copies lines; pricing applied on Quotation creation

---

### Sprint 3.3 — Order

- [ ] Create `mysite/models/commerce/order.py`: `Order`, `OrderLine`
  - `Order` fields: `client`, `customer`, `status` (DRAFT/CONFIRMED/PROCESSING/COMPLETED/CANCELLED), `currency`, `bill_to_address`, `ship_to_address`, `allow_delivery_split` (nullable — customer override), `source_doc_type`, `source_doc_id`, pricing total fields (MoneyField)
  - `OrderLine` fields: `order`, `item`, `variant`, `qty`, `open_qty`, `closed_qty`, `unit_price`, `line_total` (MoneyField), `ship_to_address` (override), `bill_to_address` (override)
- [ ] `promote_document` extended for Quotation → Order path
- [ ] `Order` direct creation (no source doc) supported
- [ ] Cart model: `Cart`, `CartItem` — session-based for anonymous; DB-persisted for logged-in; `Cart.promote_to_order()` method
- [ ] Views: `cart_view`, `add_to_cart`, `update_cart`, `checkout`, `order_create`, `order_detail`, `order_list`
- [ ] Customer-facing order history view
- [ ] `open_qty` tracking: on DeliveryLine save, `OrderLine.open_qty` is decremented; short-close sets `open_qty=0` and `OrderLine.status=SHORT_CLOSED`
- [ ] Admin: `OrderAdmin` with `OrderLineInline`; status transition buttons
- [ ] Unit tests: Quotation → Order promotion; direct Order creation; open_qty tracking; short-close flag behaviour

---

### Sprint 3.4 — Delivery

- [ ] Create `mysite/models/commerce/delivery.py`: `Delivery`, `DeliveryLine`
  - `Delivery` fields: `order`, `dispatch_location` (FK → ClientLocation), `status` (DRAFT/CONFIRMED/DISPATCHED/DELIVERED/CANCELLED), `scheduled_date`, `actual_date`, `ship_to_address`
  - `DeliveryLine` fields: `delivery`, `order_line`, `delivered_qty`
- [ ] Delivery split service `utils/delivery_service.py`:
  - `plan_deliveries(order)` — reads split rules (Customer override → ClientLocation → Client) and groups OrderLines by `ship_to_address` and dispatch location
  - `create_delivery_from_plan(order, lines, dispatch_location)` — creates Delivery + DeliveryLines
- [ ] Part-shipment service: `create_backorder(delivery)` — creates new Delivery for remaining `open_qty` per flag
- [ ] Admin: `DeliveryAdmin` with `DeliveryLineInline`; dispatch location filter
- [ ] Unit tests: split allowed → multiple Deliveries; split disallowed → error; partial shipment → backorder created; partial shipment disallowed → short-close

---

### Sprint 3.5 — Picking and Packing (Optional)

- [ ] Create `mysite/models/commerce/picking.py`, `packing.py`
- [ ] `Picking(delivery, warehouse_user, status, lines)`, `PickingLine(picking, delivery_line, picked_qty)`
- [ ] `Packing(picking_or_delivery, status, lines)`, `PackingLine`
- [ ] Feature-gated by `ClientFeatureControl('picking')` and `ClientFeatureControl('packing')` — if disabled, Delivery goes directly to Transportation / Billing
- [ ] Admin + basic views for warehouse staff
- [ ] Unit tests: feature disabled → Picking skipped in status flow

---

### Sprint 3.6 — Transportation (Optional)

- [ ] Create `mysite/models/commerce/transportation.py`
- [ ] `Transportation(client, carrier, status, vehicle_ref, dispatch_date)` + `TransportationDelivery(transportation, delivery)` M2M through table
- [ ] Constraint: one Delivery → at most one Transportation
- [ ] Feature-gated by `ClientFeatureControl('transportation')`
- [ ] Admin: select multiple Deliveries → create Transportation (action)
- [ ] Beckn: `Transportation.to_beckn()` → `BecknFulfillment`
- [ ] Unit tests: Delivery already on Transportation → error on second assignment

---

### Sprint 3.7 — Billing / Invoice

- [ ] Create `mysite/models/commerce/billing.py`
- [ ] `Invoice(client, customer, status DRAFT/ISSUED/PAID/CANCELLED, currency, payment_terms, due_date)` + `InvoiceLine` + `InvoiceDelivery` (M2M through)
- [ ] Constraint: one Delivery → at most one Invoice
- [ ] `InvoiceDelivery` consolidation: client staff selects one or more Deliveries → Invoice auto-populated from DeliveryLines
- [ ] Feature-gated by `ClientFeatureControl('billing_consolidation')` (when disabled: 1 Invoice per Delivery)
- [ ] PDF generation Celery task (`generate_invoice_pdf`)
- [ ] Beckn: `Invoice.to_beckn()` → `BecknBilling`
- [ ] Unit tests: multi-Delivery invoice; single-Delivery fallback; PDF task queued on ISSUED

---

### Sprint 3.8 — Payment

- [ ] Create `mysite/models/commerce/payment.py`
- [ ] `Payment(invoice, method, status, amount MoneyField, gateway_ref, paid_at)` + `PaymentAllocation(payment, invoice, allocated_amount MoneyField)`
- [ ] Payment gateway integration: **Razorpay** (INR primary) + **Stripe** (multi-currency fallback)
- [ ] Webhook handlers: `razorpay_webhook`, `stripe_webhook` → update Payment status → trigger `send_order_confirmation` Celery task
- [ ] Order confirmation email template (Celery: `send_order_confirmation`)
- [ ] Quotation email with PDF attachment (Celery: `send_quotation_email`)
- [ ] Unit tests: payment allocation; over-payment; partial payment

---

### Sprint 3.9 — Returns and Refunds

- [ ] Create `mysite/models/commerce/returns.py`
- [ ] `Return(order, delivery, status, reason, lines)` + `ReturnLine(return_doc, order_line, return_qty)`
- [ ] `Refund(return_doc, payment, amount MoneyField, status, gateway_ref)`
- [ ] Return → open_qty restoration or write-off depending on condition
- [ ] Admin + customer-facing return request flow
- [ ] Unit tests: return restores open_qty; refund allocated against original payment

---

### Sprint 3.10 — REST API Layer

- [ ] Add DRF router under `mysite/api/`
- [ ] ViewSets: `InquiryViewSet`, `QuotationViewSet`, `OrderViewSet`, `DeliveryViewSet`, `InvoiceViewSet`
- [ ] Token authentication for API (DRF Token Auth; JWT deferred to Phase 4)
- [ ] `?format=beckn` query param on detail endpoints → serialiser calls `to_beckn()`
- [ ] OpenAPI schema generation (`drf-spectacular`)

---

### Sprint 3.11 — Client Dashboard and Reporting

- [ ] Order management view (client staff): filter by status, date, customer, location
- [ ] Basic revenue report: orders confirmed + paid per period
- [ ] Delivery performance: on-time vs delayed
- [ ] `ClientGroupPermission` modules activated: `inquiry`, `quotation`, `cart`, `order`, `delivery`, `shipment`, `billing`, `payment`

---

### Sprint 3.12 — Production Hardening

- [ ] Deploy with PostgreSQL + Redis on Railway / Render
- [ ] Celery worker process added to `Procfile`
- [ ] `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` in production settings
- [ ] End-to-end test: Inquiry → Quotation → Order → Delivery → Invoice → Payment
- [ ] End-to-end test: Order → split Delivery → consolidated Invoice
- [ ] End-to-end test: partial shipment → back-order Delivery
- [ ] Load test: 500 concurrent checkout sessions
- [ ] Wire `django-guardian` permissions to all commerce views and API endpoints

---

## Open Decisions (Phase 3)

| Decision | Options | Target Sprint |
|----------|---------|---------------|
| Payment gateway | Razorpay (INR) primary, Stripe fallback | 3.8 |
| API auth | DRF Token (Phase 3) → JWT (Phase 4) | 3.10 |
| PDF engine | `weasyprint` or `reportlab` for invoice PDF | 3.7 |
| Full-text search | PostgreSQL FTS on Item (deferred from Phase 2) | 3.11 |
| Currency conversion rates | Static `ClientCurrencyRule` (Phase 3) → live FX feed (Phase 4) | 3.0 |
| Drag-and-drop order line reorder | Deferred | Phase 4 |

---

## CHANGE 2 — Update Deferred / Future Consideration table

Replace the `Multi-currency` row with:

| Feature | Rationale |
|---------|-----------|
| Native mobile app | REST API now exists (Phase 3); separate build pipeline still needed |
| Subdomain / custom domain routing | Path-prefix sufficient through Phase 3 |
| Drag-and-drop visual page editor | Deferred pending client validation |
| Elasticsearch / full-text search | PostgreSQL FTS added in Phase 3.11; Elasticsearch if scale demands |
| Live FX rates | Static ClientCurrencyRule in Phase 3; live feed in Phase 4 |
| Beckn BPP network participation | ONDC registry, async callbacks, digital signatures — Phase 4 |
| Redis cache (dev) | LocMemCache dev; Redis production — production switch in Sprint 3.0 |