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
- [x] `Client` model: `client_code` (LowercaseCharField), `parent` (self-FK for hierarchy), `language_list` (JSONField), `theme_list` (JSONField), translatable `name` / `nb_title`
- [x] `CustomerProfileMiddleware`: resolves `/{client_code}/` → `request.client`; URL kwargs → session fallback
- [x] `client_context` context processor: consumes `request.client`, calls `fetch_clientstatic()`, delivers `client`, `theme`, `page_dict` to all templates
- [x] `ClientLocation` model: `location_code`, `location_type` (store/branch/warehouse/office), FK to `Client`
- [x] `LowercaseCharField` custom field for all natural-key IDs
- [x] Explicit `AppConfig` for `mysite` (verify app label matches in all migrations)
- [x] URL namespace: confirm `/{client_code}/` prefix routes are fully wired in `urls.py`
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
- [x] `Page`: `page_code`, `parent` (self-FK), `order`, `hidden`, translatable `name`; `unique_together (client, page_code)`
- [x] `Layout`: single self-referential model with `level` (10/20/30/40), `parent`, `slug`, `order`, `css_class`, `style`, `hidden`; `unique_together (page, level, slug)`; `clean()` validates parent-level integrity
- [x] `Component`: `OneToOneField(Layout)`, `component_type` (hero/card/accordion/carousel), styling fields per component type, `config` JSONField; `level=40` only
- [x] `ComponentSlot`: FK to `Component`, `slot_type` (figure/text), `order`; figure fields (`image_url`, `alt`); `comptextblocks` GenericRelation
- [x] `ComptextBlock`: GenericForeignKey parent, `block_type` (title/content/actbut), `order`, `css_class`, `href_page`; `textstbitems` GenericRelation
- [x] `TextstbItem`: GenericForeignKey parent, `item_type` (text/svg/badge), `order`, `css_class`, `svg_text`
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
- [x] `fetch_clientstatic(client_code, use_cache, timeout)` — single deeply-prefetched query + cache
- [x] `build_client_payload()` — builds full client dict (languages, themes, pages, page_tree)
- [x] `build_page()` / `build_layout()` / `build_component()` / `build_slot()` — recursive tree builders
- [x] `build_blocks()` / `build_stb_item()` / `build_values()` — text content serialisers
- [x] `build_page_tree()` — builds nested page hierarchy dict for navigation bar
- [x] `serialize_model()` — generic model → dict with modeltranslation grouping
- [x] `resolve_theme()` — merges ThemePreset base tokens with Theme.overrides
- [x] `THEME_PRESET_FIELDS` cached at import time
- [x] `LocMemCache` configured (`translations-cache`)
- [x] **Cache invalidation signals** — `post_save` on `Client`, `Page`, `Layout`, `Component`, `ComponentSlot`, `Theme` must call `cache.delete(f"clientstatic:{client_code}")`. Not yet implemented. Without this, content edits don't reflect until cache expires or server restarts.
- [ ] Switch to Redis cache in production (config is commented in settings — uncomment and wire to env var)
- [ ] `use_cache=True` — currently hardcoded `False` in some call sites for debugging; restore before production

### Milestone 1.7 — Page Rendering ✅ Done (partially)
- [x] `ClientPageView(TemplateView)` — renders `base.html` with client/page/theme from context processor
- [x] `client_context` processor resolves `page_dict` from URL kwargs (`page` kwarg → match in `client.pages`)
- [x] `set_theme` view — POST handler, stores `active_theme_id` in session
- [x] `landing_page` view — root URL with no client context
- [x] `django-cotton` component templates wired for component types
- [ ] Cotton component templates for all `component_type` types: `hero`, `card`, `accordion`, `carousel` — confirm all are implemented
- [ ] 404 handling for unknown `client_code` slugs (currently raises `Client.DoesNotExist`, not a clean 404)
- [ ] 404 handling for unpublished / hidden pages
- [ ] Homepage routing: `/{client_code}/` → first published page or configurable homepage
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
- [ ] Product list and detail pages (as new `component_type` types in the component system, or dedicated URL patterns)
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
- [ ] Unit test: global item overridden by client item of same `item_code`
- [ ] Unit test: subtree filter includes descendants
- [ ] Unit test: JSONB attribute filter
### Sprint 2.4 — Views and URLs
- [ ] Create `mysite/views/catalogue.py`:
      `catalogue_page`, `catalogue_filter`, `item_detail`
- [ ] Add to `mysite/views/__init__.py`
- [ ] Wire URLs in `mydj/urls.py` BEFORE `<str:client_code>/<str:page>/` catch-all
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
- [ ] End-to-end test: visit `/{client_code}/catalogue/`
- [ ] Test HTMX filter: click category checkbox → items update without reload
- [ ] Test pagination: next/prev updates items without reload
- [ ] Test item detail: `/{client_code}/catalogue/tshirt-001/`
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

### Sprint 2.10 — Client Sector Classification & DB-Owned Template Defaults ✅ Done
Client sites are classified by industry using a dedicated global taxonomy
(`sector`: Industrial > Automotive > AutoComponents), reusing the existing
`Taxonomy`/`TaxonomyNode` machinery. Template defaults (navbar, footer,
demand sidebar nav, etc.) moved from filesystem fallbacks into the database.
- [x] `'sector'` added to `TAXONOMY_TYPES`; global `Taxonomy` + node tree seeded via data migration (`0082_seed_sector_taxonomy`)
- [x] `Client.sector` FK → `TaxonomyNode` (`null=True`, `SET_NULL`, limited to the sector taxonomy)
- [x] `SectorTemplate` model: `(template_key, htmlblob*)`, nullable `sector_node`
      (**NULL row = active global default**), `is_active` flag; conditional unique
      constraint guarantees exactly one active default per key
- [x] Uniform resolution for ALL template keys (incl. `navbar`, `footer`,
      `demand_sidebar_nav`): ClientTemplate → SectorTemplate @ deepest→root
      sector chain → SectorTemplate @ NULL global default; no filesystem fallback
- [x] `'demand_sidebar_nav'` added to `TEMPLATE_CHOICES`
- [x] Data migration `0083_seed_global_default_templates` seeds all 8 keys as
      global rows (navbar wrapped as `{% include 'cotton/navbar_v001.html' %}` —
      cotton tags only compile through the loader chain)
- [x] `render_client_template` templatetag rewritten around DB resolution;
      `_resolve_client_templates()` / `template_info` payload removed from `utils/catalogue_queries.py`
- [x] Cache: `client_template:{client_code}:{key}`, `sector_chain:{client_code}`;
      invalidated on SectorTemplate save/delete, TaxonomyNode moves, Client saves
- [x] Admin: standalone `SectorTemplateAdmin`; `sector` field on Client admin;
      SectorTemplate is superuser-only (`ADMIN_ONLY_MODELS`)
- [x] Accuracy-report taxonomy lookups scoped by taxonomy id (materialized paths are only unique within a taxonomy)
- [x] Tests: `mysite/tests/test_sector_templates.py` (12 tests incl. seed-completeness guard)

> **Ops note**: template defaults are DB-owned since migration 0083. Editing a
> default is done in Django admin (SectorTemplate), not by editing files — code
> deploys no longer change rendered chrome.

### Country Dimension (§8b) ✅ Done
- [x] `Country` model: PK = ISO alpha-2 code, `name` (translatable), `flag_emoji`, `order`, `is_active`. Verbose name `00-00B Country`. Superuser-only.
- [x] Seed migration (`0086_*`): IN (India, default), US (USA), FR (France), DE (Germany), MY (Malaysia)
- [x] `Client.allowed_countries` JSONField (null = disabled, list = enabled) + `Client.default_country_code` CharField (default `IN`)
- [x] `Client.is_country_enabled()` / `Client.get_allowed_country_codes()` helper methods
- [x] `CountryAdmin` in Django admin (`00-00B Country` under Global Config)
- [x] `ClientForm` country_choices checkbox widget (DB-backed, populated from active Countries)
- [x] `set_country` POST view — validates against allowed list, sets `request.session['active_country_code']`
- [x] `CustomerProfileMiddleware`: resolves `active_country_code` from session, validates, auto-sets default
- [x] Geo-detection: `django-geoip2` + `django-ipware` detect country from IP on first authenticated visit
- [x] `Country` FK on `SectorTemplate` + `ClientTemplate` — nullable, NULL = all countries
- [x] Resolution chain extended: client+country → client+NULL → sector+country → sector+NULL → global+country → global+NULL
- [x] Cache key includes country: `client_template:{id}:{key}:{country}`
- [x] `select_country.html` cotton component — dropdown with flag emoji + country name
- [x] Navbar: country selector shown when `show_country_selector` and >1 allowed country
- [x] Footer: displays active country flag + name
- [x] Context processor: `active_country_code`, `show_country_selector`, `allowed_countries_list`
- [x] `build_client_payload`: `show_country_selector`, `allowed_countries_list` computed fields
- [x] Tests: `mysite/tests/test_country.py` (20 tests: model, client fields, set_country view, template resolution)
- [x] Migrations: `0085_country_model`, `0086_seed_countries`, `0087_client_country_fields`, `0088_sectortemplate_country_dim`, `0089_clienttemplate_country_dim`

### Sprint 2.11 — Reusable Attribute Definitions ✅ Done
Attribute definitions were decoupled from the taxonomy tree so a type or value is
authored once and reused across many nodes (and clients) via explicit joins.
- [x] `AttributeType` (`01-03 Attribute Type`) & `AttributeValue` (`01-04 Attribute Value`): standalone, `client` NULL = global, `slug` + translated `name` + `gpc_code`; node/order/flags removed
- [x] Uniqueness: `UniqueConstraint(client, slug, nulls_distinct=False)` and `UniqueConstraint(client, gpc_code, nulls_distinct=False, condition=~Q(gpc_code=''))` on both (empty `gpc_code` allowed; PG 17 required for `nulls_distinct`)
- [x] `TaxonomyNodeAttribute`: node ↔ type join carrying node-scoped `is_required` / `is_filterable` / `order`; `unique_together (node, attribute_type)`
- [x] `TaxonomyNodeAttributeValue`: node+type ↔ value join carrying `order`; `unique_together (node_attribute, attribute_value)` — value rows reusable across pairings
- [x] `GlobalItemAttributeValue` / `ItemAttributeValue` repointed to `AttributeType` / `AttributeValue`
- [x] Consumers updated: `utils/catalogue_queries.py`, admin inlines/admins, `translation.py`, `signals.py` cache lists
- [x] Loaders split definition/association: `load_08Aattributetype` / `load_09Aattributevalue` (standalone definitions) and `load_08Btaxonomynodeattribute` / `load_09Btaxonomynodeattributevalue` (node joins, scope-enforced); `load_11A` / `load_11B` global-only; `load_21B` enforces `{global, item.client}`
- [x] Migrations squashed into `0001_initial` (old empty tables dropped/recreated, no data migration)
- [x] Tests: `mysite/tests/test_catalogue_lhs_facets.py`; full suite 318 passed; `check` clean; catalogue + filter render 200

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
 
**Goal:** Client staff can upload periodic actuals, trigger statistical forecast
runs, make consensus overrides at any hierarchy level, approve a final forecast,
and track accuracy against actuals.
 
Phase 3B builds standalone demand-planning master data (`PlanningLocation`,
`PlanningCustomer`, `SalesNode`, `SalesForecastLink`, `DistributionChannel`) on
top of the existing `Item` catalogue, and adds a `demand/` model package. The
frontend is the existing **Django Template + HTMX** stack (`mysite/demand_ui/`)
served under `/{client_code}/planning/`, alongside a DRF JSON API
(`mysite/api/demand/`).
 
---
 
### Sprint 3B.0 — Foundation and Prerequisites
- [x] Add `statsforecast`, `hierarchicalforecast`, `polars`, `duckdb`, `prophet`, `openpyxl`, `pandas` to `requirements.txt`
- [x] Add `ClientFeatureControl` keys: `demand_planning`, `actuals_upload`, `outlier_management`, `forecast_run`, `consensus_override`, `forecast_approval`
- [x] Add `ClientLocation.parent` self-FK (nullable) + `path` CharField for materialized path
- [x] Add `ClientLocation.path` index (`text_pattern_ops`)
- [x] `python manage.py makemigrations && migrate`
- [x] `python manage.py check` — 0 issues
---
 
### Sprint 3B.1 — Demand-Planning Hierarchy Models
- [x] Create `mysite/models/demand/hierarchy.py`:
  - `PlanningLocation(client, name, parent→self, path)` and `PlanningCustomer(client, name, parent→self, path)` — standalone demand-planning hierarchies via `MaterializedPathMixin`
  - `SalesNode(client, name, level_label, parent→self, path)` — sales org tree
  - `SalesForecastLink(client, planning_location, distribution_channel, planning_customer, sales_node, valid_from, valid_to)` — 3 shapes: loc+channel+customer / loc+channel / loc-only
  - `ZZCustomerSalesAssignment` retained but deprecated (not used by the workflow)
- [x] `DistributionChannel` model (code PK, label, is_active) in `mysite/models/global_config.py`; `Client.allowed_distribution_channels` JSONField + helpers `is_distribution_channel_enabled()` / `get_allowed_distribution_channel_codes()`
- [x] Materialized path via `MaterializedPathMixin` (Phase 2 `TaxonomyNode` pattern)
- [x] Indexes: `ix_sfl_client_loc` (client, planning_location), `ix_sfl_loc_from` (client, planning_location, valid_from)
- [x] Admin: `PlanningLocationAdmin`, `PlanningCustomerAdmin`, `SalesNodeAdmin` (tree display), `SalesForecastLinkAdmin`
- [x] REST endpoints: `GET /api/demand/location-hierarchy/` (PlanningLocation tree), `GET /api/demand/sales-hierarchy/` (SalesNode tree), `GET/POST/DELETE /api/demand/sales-forecast-links/`
- [x] Unit tests: path computation, subtree queries, link CRUD (`test_hierarchy_api.py`)
---
 
### Sprint 3B.2 — Actuals Models and Import Pipeline
- [x] Create `mysite/models/demand/actuals.py`:
  - `ActualSale(client, planning_location, item→Item, planning_customer nullable, distribution_channel default '00', period_type, period_start, qty, revenue Decimal nullable)` — `period_end` auto-computed; `import_batch` FK to the upload job
  - Unique constraint: `(client, planning_location, item, planning_customer, distribution_channel, period_type, period_start)`
  - `ActualSaleLocation(client, planning_location, period_type, period_start, total_qty, total_revenue)`
  - `ActualSaleImport(client, uploaded_by, uploaded_at, file_name, period_type, row_count, status pending/processing/done/failed, error_log)`
- [x] Add DB indexes: `ix_actualsale_loc_period`, `ix_actualsale_item_period`, `ix_actualsale_cust_period`, `ix_actualsale_period_range`, `ix_actualsale_grain_lookup`, `ix_actualsaleloc_period`
- [x] Django Admin: `ActualSaleImport` admin with status display
- [x] Upload via HTMX form (`actuals_upload`) + REST `POST /api/demand/actuals/upload/` — multipart file, creates import job
- [x] REST endpoint: `GET /api/demand/actuals/upload/{id}/` — poll import status
- [x] REST endpoint: `GET /api/demand/actuals/` — filtered query (item, planning_location, planning_customer, distribution_channel, period range)
- [x] REST endpoint: `GET /api/demand/actuals/template/` — xlsx template download
- [x] Celery task `process_actuals_import(import_id)`:
  - Parse CSV / Excel with `pandas`
  - Validate all FKs exist; collect per-row errors into `ActualSaleImport.error_log`
  - Bulk upsert on the natural grain (`bulk_create` + `update_conflicts`, idempotent re-upload)
  - Update `ActualSaleImport.status` → `done` / `failed`
- [x] Celery task `process_summary_actuals_import` for `ActualSaleLocation`
- [x] Upload overlap guard: re-uploading periods with CONFIRMED adjustments requires explicit confirmation (partial-overlap UX)
- [x] Unit tests: duplicate upload → idempotent; invalid FK → error; row count correct (`test_actuals_import.py`, `test_actuals_upload_outlier_guard.py`)

### Sprint 3B.2b — Outlier Management (Detection + Planner Review)
*Shipped in full. `ActualSaleOutlierAdjustment` lives inside `actuals.py` (not a separate `outliers.py`);
detection is planner-triggered by period range, never auto-run on import completion.*

Models & migrations
- [x] `ActualSaleOutlierAdjustment` in `mysite/models/demand/actuals.py`:
  `actual_sale` OneToOne → `ActualSale`; `qty_adjustment` (Decimal 14,3); `revenue_adjustment` (Decimal 16,2, nullable); `detected_by` (SYSTEM/USER); `status` (CANDIDATE/CONFIRMED/REJECTED, default CANDIDATE); `reason`; `created_by`/`confirmed_by`/`confirmed_at`; `clean()` guards `qty_adjustment > actual_sale.qty` and `revenue_adjustment > actual_sale.revenue`
- [x] `ForecastingConfig` in `mysite/models/demand/forecast.py` (a dedicated per-client config row, **not** six fields on `Client`): `mad_threshold`, `persistence_periods`, `min_history_periods`, `forecast_uses_net_actuals` / `reporting_uses_net_actuals` / `abc_classification_uses_net_actuals` (all default True), `last_outlier_detection_run_at/by/range_start/range_end`
- [x] Migration adding `ix_outlieradj_status` index (status column on `ActualSaleOutlierAdjustment`)
- [x] Add `outlier_management` key to `ClientFeatureControl`
- [x] Register model exports in `mysite/models/demand/__init__.py`

Query-time netting helper
- [x] Create `utils/demand/actuals_net.py`:
  `actuals_queryset_with_net(qs, use_net)` — `select_related('outlier_adjustment')` + annotate `net_qty`/`net_revenue`; `use_net=True` subtracts `qty_adjustment` / `Coalesce(revenue_adjustment, 0)` only when `status='CONFIRMED'`; `use_net=False` passes raw qty/revenue through
- [x] Unit tests: no adjustment / CANDIDATE / REJECTED → net == raw; CONFIRMED → net correctly subtracted; `use_net=False` → raw regardless (`test_actuals_net.py`)

Detection engine
- [x] Celery task `run_outlier_detection(client_code, target_period_start, target_period_end, triggered_by_user_id=None)` in `mysite/tasks/demand/detect_outliers.py`:
  Reads thresholds from `ForecastingConfig` (lazily created with system defaults if absent); pulls `ActualSale` rows in `[target_period_start, target_period_end]`; groups series by (planning_location, item, distribution_channel, planning_customer); skips series with fewer than `min_history_periods`; runs residual MAD detection on `mad_threshold`; persistence check via `persistence_periods` (sustained elevation = level shift, not flagged); proposes **CANDIDATE only** (never auto-confirms); one `ActualSaleOutlierAdjustment` per flagged row, skipping rows that already have an adjustment (1:1 — a row is never re-proposed, so re-runs are idempotent); notifies planners of the candidate count; records run identity/range on `ForecastingConfig`
- [x] Trigger: planner submission of the Outlier Detection range form (HTMX) — **not** the import-completion path
- [x] Unit tests: single-period spike → flagged; sustained increase of `persistence_periods` → not flagged; different `mad_threshold` per Client → different candidate sets; short history → skipped (`test_outlier_detection.py`)

Stale-forecast flagging
- [x] Celery task `flag_stale_forecast_versions(actual_sale_id)` in the same task module: marks DRAFT `ForecastVersion` rows whose horizon window covers the row's `period_start` with `stale_actuals=True` (no auto-rerun)
- [x] Wire trigger: post-save on `ActualSaleOutlierAdjustment` when status transitions to/from CONFIRMED
- [x] Unit tests: confirming inside a DRAFT version's horizon flags only that version; rejecting a previously-confirmed adjustment re-flags it (`test_flag_stale_forecast_versions.py`)

Views / endpoints (Django Template + HTMX — `mysite/demand_ui/views.py`)
- [x] `outlier_queue` — full-page queue filterable by status tabs (CANDIDATE / CONFIRMED / REJECTED), paginated
- [x] `outlier_confirm` (POST, HTMX) — sets CONFIRMED + confirmed_by/confirmed_at; returns the re-rendered row fragment (`partials/_row.html` / `_decision_row.html`)
- [x] `outlier_reject` (POST, HTMX) — sets REJECTED
- [x] `outlier_revise` (POST, HTMX) — planner edits qty/revenue adjustment before/after decision
- [x] `outlier_undo_decision` (POST, HTMX) — restores a decided row to CANDIDATE
- [x] `outlier_bulk_delete` (POST, HTMX) — bulk-discard of selected candidates or the whole filtered set
- [x] `raise_exception_form` — planner raises a `detected_by='USER'` adjustment directly against an ActualSale row (validated via `clean()`)
- [x] `outlier_detection_form` / `trigger_outlier_detection` — range-picker form + trigger, showing `_detection_triggered.html`
- [x] `outlier_decisions_report` — decisions report view
- [x] Nav badge (open candidate count) in `demand_planning_nav` context processor + `partials/sidebar_nav.html`, updated out-of-band
- [x] No DRF outlier endpoints — interactions are HTMX-only

Templates
- [x] `templates/demand/outliers/queue.html` — full-page queue extending `_base_demand.html`
- [x] `templates/demand/outliers/partials/_row.html`, `_decision_row.html` — HTMX swap targets for confirm/reject/revise/undo
- [x] `templates/demand/outliers/partials/_detection_form.html`, `_detection_triggered.html`, `_raise_exception_form.html`
- [x] `templates/demand/outliers/decisions_report.html`
- [x] `stale_actuals` badge on affected DRAFT versions in the version list
- [x] Overlap-guard templates `partials/actuals_upload_overlap.html` / `actuals_upload_overlap_confirm.html`

Admin
- [x] Outlier adjustments surfaced inside `ActualSaleAdmin` (read-only display of the linked adjustment); `_warn_if_outlier_adjustments` delete guard on ActualSale
- [x] `ForecastingConfigAdmin` for threshold tuning; settings surfaced via `GET /api/demand/forecasting-config/`

Wrap-up
- [x] Migration notes updated; `makemigrations --check` clean
- [x] Tests: `test_outlier_detection.py`, `test_outlier_bulk_discard.py`, `test_actuals_upload_outlier_guard.py`, `test_actuals_net.py`, `test_flag_stale_forecast_versions.py`

---

### Sprint 3B.2c — Sales Promotion Scheme Management
*Sprint 3B.2c — planned promo uplift + scheme-netted baseline, incl. pre/post pull-forward shadow.
Ordering invariant: `baseline = Actuals − scheme impact − outlier`; scheme netting is multiplicative on
window rows and additive on shadow rows, outlier netting stays subtractive, and outlier detection runs on
scheme-netted (shadow-boosted) series.*

Models & migrations (`mysite/models/demand/schemes.py`, registered in `demand/__init__.py`)
- [ ] `SalesScheme(client, scheme_code, name, status DRAFT/ACTIVE/ARCHIVED, expected_qty_uplift_pct,
      expected_value_uplift_pct [independent — 1-for-1 = qty +100%, value 0%], discount_pct [metadata
      only, may pre-fill a default value uplift], shadow_periods [default 0 = off], pull_forward_pct
      [default 0.5, in [0,1]])` — `clean()` rejects negative qty uplift, `value_uplift ≤ −100%`,
      and `pull_forward_pct ∉ [0,1]`
- [ ] `SalesSchemeScope(scheme, scope_type OVERALL/TAXONOMY/BRAND/ITEM, taxonomy_node, item,
      planning_location / planning_customer / distribution_channel nullable)` — unique on the full dim
      set. BRAND = Brand node in the item taxonomy (the scheme's "vendor"); `clean()` enforces the
      `brand_taxonomy` prerequisite and that the node has item mappings
- [ ] `SalesSchemePeriod(scheme, period_type, period_start, period_end auto-computed)` — unique
      `(scheme, period_type, period_start)`; past buckets net history, future buckets re-add uplift
- [ ] `ResolvedSalesSchemePeriod(scheme, item, planning_location, planning_customer,
      distribution_channel, period_type, period_start, period_end,
      WINDOW: qty_factor/value_factor = 1+uplift;
      SHADOW: is_shadow, shadow_side, shadow_offset, anchor_period_start, anchor_qty_factor/
      anchor_value_factor (copies), addback_qty_weight/addback_value_weight)` — materialized coverage
      keyed to the ActualSale grain; unique `(scheme, item, loc, cust, dc, period_type, period_start,
      is_shadow, shadow_side, anchor_period_start)`;
      `ix_resolvedschemepen_grain` / `ix_resolvedschemepen_scheme` / `ix_resolvedschemepen_shadow`
- [ ] `SalesSchemeOccurrence(scheme, period_type, period_start, period_end, actual_qty_uplift_pct,
      actual_value_uplift_pct, actual_pull_forward_pct, qty/value/pull-forward variance, closed_at)` —
      closed-scheme data-check + shadow calibration
- [ ] `ForecastingConfig`: `scheme_net_actuals` / `scheme_apply_forecast_uplift` (default True),
      `brand_taxonomy` (nullable slug naming the taxonomy carrying the Brand level — the brand→item
      mapping prerequisite for BRAND scope),
      `last_scheme_detection_run_at/by/range_start/range_end`
- [ ] `ForecastLine`: `pre_scheme_statistical_qty`, `pre_scheme_statistical_value` (clean baseline),
      `scheme_id` FK (nullable, SET_NULL), `scheme_qty`, `scheme_value` (uplift deltas); `statistical_qty`
      now computed as `pre_scheme_statistical_qty + (scheme_qty or 0)`; override system unchanged
- [ ] `ForecastAggregate`: `pre_scheme_statistical_qty`, `pre_scheme_statistical_value` (both-column display)
- [ ] Add `scheme_management` key to `ClientFeatureControl`; `scheme_ui_visible()` helper in
      `utils/feature_control.py` (mirrors `outlier_ui_visible`); update `_FEATURE_HIERARCHY`
- [ ] Register the five scheme models in `ADMIN_ONLY_MODELS` (Guardian permission sync) + add
      `scheme_changed` post_save receiver in `mysite/signals.py` (resolve_scheme_scope +
      range-mode stale-flag + re-trigger outlier detection; extend
      `flag_stale_forecast_versions` with the `(client_id, period_type, period_start)` mode)
- [ ] Admin: `SalesSchemeAdmin` (inline scopes/periods/occurrences), `ResolvedSalesSchemePeriodAdmin`
      (read-only) in a new `mysite/admin/demand_schemes.py` registered in `mysite/admin/__init__.py`;
      scheme flags in `ForecastingConfigAdmin`; scheme columns in `ForecastLineAdmin`/
      `ForecastAggregateAdmin`

Scope resolution
- [ ] Celery task `resolve_scheme_scope(scheme_id)` — materializes `ResolvedSalesSchemePeriod` on
      ACTIVE status / scope / period edits: resolve item set per scope — tree-aware from the node's OWN
      taxonomy (OVERALL → all client items; TAXONOMY → `_scheme_scope_item_ids` union of
      `ItemTaxonomyNode` mappings beneath the node; BRAND → same union resolver on the brand node,
      validated against `ForecastingConfig.brand_taxonomy`; ITEM → single item) — cross with periods and
      dims, WINDOW rows with `qty_factor = 1 + qty_uplift`, `value_factor = 1 + value_uplift`;
      within-scheme dedup most-specific-wins (ITEM > BRAND > TAXONOMY > OVERALL); cross-scheme overlap
      warning (same order)
- [ ] Shadow rows: when `shadow_periods > 0`, per WINDOW row build 2 × shadow_periods SHADOW rows
      (PRE/POST buckets via `previous_period_start` / `next_period_start`, anchor fields copying the
      window's factors, addback weight = `pull_forward_pct × side_share × decay^j` normalized per side,
      decay `1/2^j`); NULL `qty_factor` on shadow rows; delete + bulk_create atomically
- [ ] Unit tests: TAXONOMY / ITEM / OVERALL scopes materialize correct rows; BRAND scope resolves the
      union of items beneath the brand node across multiple planning product groups; BRAND + TAXONOMY
      overlap dedupes to one factor (most-specific-wins); unconfigured `brand_taxonomy` / node not in
      brand taxonomy / no item mappings → `SalesSchemeScope.clean()` raises; future period lands in
      horizon; deactivating a scheme drops resolved rows; `shadow_periods=2` → 2 PRE + 2 POST shadow
      rows with per-side weights (4/6, 2/6) (`test_scheme_scope.py`)

Composed baseline netting + outlier sequencing
- [ ] Extend `utils/demand/actuals_net.py`: `scheme_netted_queryset()` via correlated `Subquery` +
      `Sum` annotations — WINDOW rows DIVIDE (`qty / qty_factor`), SHADOW rows ADD BACK
      `anchor_window_qty × (1 − 1/anchor_qty_factor) × addback_qty_weight` (window qty resolved by a
      nested subquery at the anchor grain); `actuals_queryset_with_net(client, use_net, use_scheme_net)`
      composes **scheme first, then outlier** — `net_qty = scheme_net_qty − outlier_adj`, same for
      revenue
- [ ] Switch consumers to the composed helper: `build_actuals_dataframe` (rename
      `net_qty→qty` stays the single injection point), `update_weighted_avg_prices` (price now on
      scheme-free revenue), `compute_series_profiles`
- [ ] `run_outlier_detection` reads SCHEME-NETTED series via the same helper (`r.scheme_net_qty` — no
      local factor loading), so window spikes AND pre/post dips are absent from detection; suggested
      adjustments computed on scheme-netted values; `ActualSaleOutlierAdjustment.clean()` bound to the
      scheme-netted qty/revenue
- [ ] Stale-flagging: `SalesScheme` post-save activates `flag_stale_forecast_versions` for covered
      periods (window + shadow) + re-triggers `run_outlier_detection` on the range; scheme modification
      after overrides exist flags version as stale (planner must re-apply overrides manually)
- [ ] Unit tests: 1-for-1 fixture → `net_qty = qty/2`, `net_revenue = revenue`; shadow fixture
      (`shadow_periods=1`, `pull_forward_pct=0.5`) → pre/post net to `qty + 0.5 × (window_qty ×
      (1 − 1/qty_factor))`; scheme spike AND pre/post dip NOT proposed as outliers; adjustment beyond
      scheme-netted qty rejected; forecast with `scheme_net_actuals=True` differs from `False`
      (`test_scheme_netting.py`, `test_actuals_net.py`)

Forecast-horizon uplift (output)
- [ ] `build_scheme_forecast_factors(client_id, period_type, horizon)` — reads resolved rows in the
      horizon → per-(uid, ds) overlay: WINDOW `{scheme_id, qty_factor, value_factor}` (multiplicative)
      or SHADOW `{scheme_id, anchor_period_start, anchor_qty_factor, anchor_value_factor,
      addback_qty_weight, addback_value_weight}` (subtractive dip)
- [ ] `write_forecast_lines` merges scheme factors inside the write path: write `pre_scheme_statistical_qty`
      from engine output; look up scheme factors → compute `scheme_qty` (delta); compute
      `statistical_qty = pre_scheme_statistical_qty + (scheme_qty or 0)`; set `scheme_id` FK; override
      system continues to work on `statistical_qty` (unchanged)
- [ ] `write_forecast_aggregates` DuckDB roll-up adds `SUM(pre_scheme_statistical_qty)` /
      `SUM(pre_scheme_statistical_value)` alongside existing statistical sums
- [ ] Unit tests: horizon window uplift delta correct (1-for-1 → `scheme_qty = pre_scheme_statistical_qty`,
      `statistical_qty = 2 × pre_scheme_statistical_qty`, flat `scheme_value`);
      horizon shadow dip delta; `statistical_qty = pre_scheme + scheme_qty`; anchor-outside-horizon
      skip + warning; outside-scheme → NULL `scheme_qty`; aggregate roll-up with
      `pre_scheme_statistical_qty` (`test_scheme_forecast_uplift.py`)

Detection + review queue (Django Template + HTMX, `mysite/demand_ui/`)
- [ ] Celery task `detect_scheme_candidates(client_code, target_period_start, target_period_end,
      triggered_by_user_id=None)` — RAW product-group aggregates, MAD + persistence spike detection,
      skip periods covered by an ACTIVE scheme (window OR shadow), implied
      `qty_uplift = period/median(neighbours) − 1`, DRAFT candidates only; records run identity on
      `ForecastingConfig`
- [ ] Views: `scheme_list`, `scheme_create`/`scheme_edit` (scope lines incl. a **BRAND picker**
      populated from `ForecastingConfig.brand_taxonomy`, gated with a "set up the brand taxonomy"
      message when unconfigured + periods + uplift inputs +
      shadow inputs `shadow_periods` / `pull_forward_pct`, pre-fill value uplift from discount),
      `scheme_review_queue`, `scheme_activate` (→ ACTIVE + `resolve_scheme_scope` + stale-flag +
      re-trigger outlier detection), `scheme_occurrences` report
- [ ] Templates under `templates/demand/schemes/` extending `_base_demand.html`; nav link +
      candidate-count badge gated on `scheme_ui_visible`
- [ ] URLs under `/schemes/`; no DRF endpoints
- [ ] Unit tests: spike not covered → candidate with sensible implied uplift; tagged period (window or
      shadow) never re-proposed; activation re-triggers detection (`test_scheme_detection.py`)

Occurrence data-checking & estimation
- [ ] `record_scheme_occurrence(scheme_id, period_type, period_start)` at period-close — measures
      actual qty/value uplift independently from actuals vs neighbouring baseline AND estimates
      `actual_pull_forward_pct` (missing volume in shadow buckets vs window uplift, clamped to [0,1],
      conservation check pulled+incremental ≈ netted-out uplift); writes `SalesSchemeOccurrence` with
      variance
- [ ] Re-registration pre-fills `expected_*_uplift_pct` AND `pull_forward_pct` from the **median** of
      the last few occurrences; variance warning surfaced when a scheme missed expectation
- [ ] Unit tests: independent actual uplift measurement; pull-forward estimation; median pre-fill incl.
      `pull_forward_pct`; variance flag (`test_scheme_occurrences.py`)

Hardening & regression
- [ ] Overlap resolution warning path (WINDOW-vs-WINDOW; window-vs-shadow on the same period composes
      additively and is covered by a test); edge guards (value_uplift floor, `pull_forward_pct ∈ [0,1]`,
      NULL-revenue rows, zero-qty-uplift scheme still nets revenue, shadow with no anchor actuals adds
      nothing)
- [ ] Load check: `resolve_scheme_scope` across a full monthly import batch within run budget (shadow
      rows multiply resolved count by `1 + 2 × shadow_periods`)
- [ ] End-to-end: import → register scheme (with shadow) → resolved rows → outlier detection ignores
      scheme window and pre/post dips → forecast baseline scheme-free with shadow re-added →
      `pre_scheme_statistical_qty` written, `scheme_qty` computed, `statistical_qty` = scheme-adjusted
      → horizon uplift + shadow dip applied → override system works on `statistical_qty` (unchanged) →
      both `pre_scheme_statistical_qty` and `statistical_qty` visible in UI → scheme closes → occurrence
      records actual pull-forward → next registration pre-fills uplift and `pull_forward_pct`
- [ ] `makemigrations --check` clean; `manage.py check` 0 issues

---

### Sprint 3B.2d — Item Lifecycle (Substitution / Discontinuation / Introduction)
*Sprint 3B.2d — three lifecycle events, three layers, one flag. Substitution (retired code's netted
history feeds the successor with qty conversion — a re-key layer in the composed helper after scheme +
outlier netting); Discontinuation (forecast nil on/after an effective date — an output filter);
Introduction (a new item with no history borrows a reference item's forecast × ratio until it has
enough own history — an output copy).*

Models & config (`mysite/models/demand/lifecycle.py`, registered in `demand/__init__.py`)
- [x] `ItemSubstitution(client, old_item, new_item, conversion_factor, effective_from, notes)`
      `unique (client, old_item)`; `conversion_factor > 0`; same-client; **direct mapping only** —
      `clean()` rejects an item appearing as both predecessor and successor (no chains, no cycles);
      indexes `(client, old_item)` / `(client, new_item)`
- [x] `ItemDiscontinuation(client, item, effective_from, notes)` — `unique (client, item)`;
      forecast NIL on/after `effective_from` (NULL = nil immediately); history kept for
      reporting/ABC/accuracy; index `(client, item)`
- [x] `ItemIntroduction(client, new_item, reference_item, ratio, copy_from, copy_to, notes)` —
      `unique (client, new_item)`; `ratio > 0`; `copy_to >= copy_from`; new_item ≠ reference_item;
      same-client; no reference chains; indexes `(client, new_item)` / `(client, reference_item)`
- [x] **One lifecycle directive per item** — subject roles (substitution old_item/new_item,
      discontinued item, introduction new_item) pairwise exclusive in `clean()` (+ optional `pre_save`
      validation receiver); an introduction's `reference_item` may overlap (ordinary forecasted item)
- [x] `ForecastingConfig.use_item_lifecycle` (default True) — one flag for all three layers;
      `ForecastLine` gains nullable `borrowed_from_item` / `borrowed_ratio` (introduction-copied lines)
- [x] `item_lifecycle` key in `ClientFeatureControl` (`demand_planning` parent) +
      `item_lifecycle_ui_visible()` in `utils/feature_control.py`
- [x] Register all three models in `ADMIN_ONLY_MODELS` (signals.py, Guardian permission sync)
- [x] Admin: `ItemSubstitutionAdmin`, `ItemDiscontinuationAdmin`, `ItemIntroductionAdmin`
      (`ClientScopedMixin`) in `mysite/admin/demand_lifecycle.py` registered in
      `mysite/admin/__init__.py`; `use_item_lifecycle` in `ForecastingConfigAdmin`

Shared-helper substitution layer (Scenario 3 — baseline re-key)
- [x] `actuals_queryset_with_net(client, use_net, use_substitution=False)` gains the re-key layer:
      correlated `Subquery` on `ItemSubstitution` annotates `eff_item_id` / `eff_item_code` and scales
      `net_qty`/`net_revenue` by `conversion_factor` when `(effective_from IS NULL OR
      period_start < effective_from)` — exclusive cutoff, converted history and successor own-actuals
      are disjoint in time; identity when flag off; the retired old item's own forecast is nil on/after
      `effective_from`
- [x] Re-key consumers to the effective item (grain keys → `eff_item_id`/`eff_item_code`):
      `build_actuals_dataframe` (forecast matrix), `update_weighted_avg_prices` (successor price over
      merged history), `compute_series_profiles._load_actuals`

Forecast-output layers (Scenarios 1 & 2 — applied at `write_forecast_lines`, gated by the same flag)
- [x] **Discontinuation** — items with an `ItemDiscontinuation` row emit no `ForecastLine` for
      `period_start >= effective_from` (nil); pre-cutoff periods forecast normally; NULL = nil from the
      current run
- [x] **Introduction** — for periods inside `[copy_from, copy_to]` (NULL bounds) where the new item has
      `< min_history_periods` own periods, the new item's line = reference statistical line × `ratio`,
      tagged `borrowed_from_item` / `borrowed_ratio`; copy stops at the earlier of `copy_to` and enough
      own history; reference lines untouched; `ForecastAggregate` roll-ups include borrowed qty/value

Detection & reporting (Scenario 3 + 1)
- [x] `run_outlier_detection`: successor series read via the composed helper (merged history); retired
      items (old_item of a substitution) SKIPPED from candidate generation; **discontinued items are
      NOT skipped** (their history is their own); reporting/ABC share the helper with the same flag

HTMX UI + tests
- [x] `item_substitution_list/create/edit`, `item_discontinuation_list/create/edit`,
      `item_introduction_list/create/edit` HTMX views under `/planning/`, gated on
      `item_lifecycle_ui_visible`
- [x] Unit tests (`test_item_lifecycle.py`): model validation (factor/ratio ≤ 0, cross-client,
      old==new / new==reference, inverted `copy_to < copy_from`, duplicate subject, direct-mapping +
      mixed-role violations); helper (2-old=1-new fixture, effective_from cutoff, null = whole history,
      identity when off, composes with scheme+outlier netting); consumers (B's matrix/price = merged
      series, A's post-launch rows stay A, A's forecast nil after launch); output layers
      (discontinuation nil on/after date; introduction borrow with window + own-history stop +
      borrowed attribution; aggregate roll-up); detection skips retired A but keeps discontinued D;
      feature gate

---

### Sprint 3B.3 — Forecast Models and Version Management
- [x] Create `mysite/models/demand/forecast.py`:
  - `ForecastVersion(client, version_label, period_type, base_period_end, horizon_periods, engine_config JSONField, status, run_status QUEUED→COMPLETE/FAILED, stale_actuals, created_by, approved_by nullable, approved_at nullable, copied_from, notes, celery_task_id)`
  - `ForecastLine(version, item, planning_customer nullable, planning_location, distribution_channel default '00', period_type, period_start, period_end, statistical_qty, override_qty nullable, final_qty, forecast_level, model_used, price_used, statistical_value/override_value/final_value)` — `final_qty` = `override_qty or statistical_qty` (computed on save)
  - `ForecastAggregate(version, agg_level, agg_key JSONField, period_start, statistical_qty, override_qty, final_qty)`
  - `ForecastOverride(version, override_level, override_key JSONField, period_start, override_qty nullable, override_pct nullable, disagg_method, override_note, created_by)`
  - `OverrideSplitWeight(override, child_key JSONField, weight)` — for CUSTOM disaggregation
  - `ForecastAccuracy(version, item, planning_customer nullable, planning_location, distribution_channel, period_start, actual_qty, forecast_qty, mape, bias)`
  - Plus `AbcClassDefinition`, `ForecastingConfig`, `SeriesLevelEvaluation`, `SeriesProfile`
- [x] `ForecastVersion.status` state machine: `DRAFT → IN_REVIEW → APPROVED → LOCKED` (`ALLOWED_TRANSITIONS` guard)
- [x] REST endpoints:
  - `GET/POST /api/demand/forecast-versions/`
  - `GET /api/demand/forecast-versions/{id}/`
  - `GET /api/demand/forecast-versions/{id}/lines/` (paginated, filterable)
  - `GET /api/demand/forecast-versions/{id}/aggregates/`
  - `POST /api/demand/forecast-versions/{id}/run/` + `GET /run-status/`
  - `POST /api/demand/forecast-versions/{id}/approve/`
  - `GET/POST/DELETE .../overrides/`, `.../overrides/{id}/affected-lines/`, `.../split-weights/`
  - `GET /api/demand/series-profiles/`, `.../{id}/`, `.../{id}/evaluations/`, `GET /api/demand/forecasting-config/`
- [x] Admin: `ForecastVersionAdmin` with status/run-status display; read-only lines handling
- [x] Unit tests: `final_qty` computation; status transition guard (LOCKED → no edits); version copy; run-status lifecycle
---
 
### Sprint 3B.4 — Statistical Forecast Engine
- [x] Create `utils/demand/forecast_engine.py`:
  Statistical Forecast Engine: `build_actuals_dataframe` consumes the net/raw join gated by `ForecastingConfig.forecast_uses_net_actuals` (via `actuals_queryset_with_net`). Unit test proves a confirmed outlier adjustment produces a materially different forecast than the same run with the adjustment rejected — regression guard that the net path is actually consumed.
  - `build_actuals_dataframe(client_id, ...)` → Polars DataFrame (net-or-raw actuals)
  - `build_aggregated_actuals(...)` → roll-ups per grain (via DuckDB)
  - `run_statsforecast_by_grain(...)` → forecasts per series, model chosen by cross-validation MAPE
  - `run_hierarchical_reconciliation(...)` → reconciled DataFrame
  - `disaggregate_to_atomic(...)` → residual-based disaggregation to leaf lines
  - `write_forecast_lines(version_id, ...)` → bulk_create ForecastLine (batched 5000), tagged `forecast_level` + `model_used`
  - `write_forecast_aggregates(version_id)` → roll-up ForecastAggregate for all agg_levels
  - `update_weighted_avg_prices(...)` → prices stored on lines for value roll-ups
- [x] `utils/demand/compute_series_profiles.py` + Celery task `compute_series_profiles(client_id, period_type)`: grain decision engine (encodings `item_loc_dc_cust`, `item_loc_dc`, `item_loc`, `item_salesnode_{node_id}`, `taxon_{node_id}_*`, `manual`) writing `SeriesProfile` records
- [x] Celery task `run_forecast(version_id)` in `mysite/tasks/demand/run_forecast.py`:
  - Orchestrates the pipeline (profiling → forecast → reconcile → disaggregate → aggregate)
  - Updates `ForecastVersion.run_status` → COMPLETE on success, FAILED with `run_error` traceback on error (workflow `status` unchanged — stays DRAFT)
  - Notifies requesting user via `notifications.send_forecast_status_email`
- [x] Engine config JSONField controls: `models` (AutoETS / AutoARIMA + CrostonSBA for intermittent), `season_length`, `reconciliation` (BottomUp / MinTrace_ols / MinTrace_wls_struct), `disagg_conflict_resolution` (retain_lower/use_upper), `store_all_level_forecasts`, `force_grain`, `min_nonzero_override`, `accuracy_lookback_periods`
- [x] REST endpoints: `POST /api/demand/forecast-versions/{id}/run/` triggers `run_forecast`; `GET /run-status/` polls progress; `GET /api/demand/series-profiles/` exposes grain decisions
- [x] Unit tests: summing-matrix shape for known hierarchy; reconciliation conserves totals; CrostonSBA for intermittent series; line row counts (`test_forecast_engine.py`)
---
 
### Sprint 3B.5 — Consensus Override Engine
- [x] Override engine lives in `mysite/tasks/demand/run_forecast.py` (not a separate `utils/demand/override_engine.py`):
  - `_resolve_override_queryset(version_id, override, client_id, as_of)` → leaf `ForecastLine` rows in the override subtree
  - `compute_proportional_shares` uses the same net-or-raw actuals query helper for same-period-last-year share calculation, gated by `ForecastingConfig.forecast_uses_net_actuals`
  - `_apply_single_override(override, version)` → updates `ForecastLine.override_qty` (+ final_qty) for each leaf
  - `apply_overrides(version_id)` → applies all pending overrides for a version and recomputes affected `ForecastAggregate` rows
  - Custom weights from `OverrideSplitWeight` for `disagg_method=CUSTOM`
- [x] Routing logic: subtree < 500 leaves → synchronous; ≥ 500 → Celery task
- [x] REST endpoints:
  - `GET/POST /api/demand/forecast-versions/{id}/overrides/`
  - `GET/DELETE /api/demand/forecast-versions/{id}/overrides/{override_id}/` (delete reverts leaf lines to statistical)
  - `GET /api/demand/forecast-versions/{id}/overrides/{override_id}/affected-lines/`
  - `GET/POST /api/demand/forecast-versions/{id}/overrides/{override_id}/split-weights/`
- [x] HTMX UI: `override_list`, override create/edit with value/qty/% editors, drill-down override form + preview, propagation status partials
- [x] Unit tests:
  - Proportional disaggregation sums to override total (within rounding tolerance); shares use the net/raw helper
  - Override revert restores statistical_qty values
  - LOCKED version rejects override POST
---
 
### Sprint 3B.6 — Accuracy Tracking
- [x] Celery task `compute_accuracy(client_id)` (in `mysite/tasks/demand/run_forecast.py`):
  - Loads APPROVED/LOCKED `ForecastVersion` rows for the client
  - Joins net `ActualSale` (via `actuals_queryset_with_net`) against the version's `ForecastLine` rows across the horizon window
  - Computes per-leaf: `mape = abs(actual - forecast) / actual`, `bias = (forecast - actual) / actual` (division-by-zero guard)
  - Writes `ForecastAccuracy` records (bulk_create, update_conflicts)
  - Computes WMAPE / weighted metrics at aggregate levels (DuckDB roll-ups)
- [ ] Scheduled: monthly Celery beat trigger for all Clients with `demand_planning` enabled — task exists, beat schedule not yet configured
- [x] REST endpoint: `GET /api/demand/forecast-versions/{id}/accuracy/` (group_by category/location/period/item)
- [x] Accuracy also computed within a run via `engine_config.accuracy_lookback_periods`
- [x] Unit tests: MAPE formula; WMAPE aggregate; division-by-zero guard (actual = 0)
---

### Sprint 3B.7a — Demand Planning UI (Django Template + HTMX):
the Outlier Review Queue was delivered as part of Sprint 3B.2b itself (see task list above) — the existing
`mysite/demand_ui/` app already uses Django Template + HTMX, so there was no separate SPA build to schedule.
All demand planning views (actuals dashboard, upload, outlier queue, forecast run, version list/detail,
override grid, accuracy, series profiles) are shipped under this stack.

- [x] Link the Outlier Review Queue into the main demand_ui navigation
- [x] Confirm the `stale_actuals` badge renders correctly alongside other Forecast Version statuses in the existing dashboard views
- [x] Cross-browser check consistent with the existing demand_ui QA pass

### Sprint 3B.7b — React SPA Frontend — **NOT BUILT — superseded by 3B.7a**
The React SPA was never scaffolded. All planned SPA functionality (views 1–5 below) was delivered in the
HTMX `demand_ui` stack instead:
- Actuals Dashboard → `actuals_list` / `actuals_aggregates` with HTMX filter bar (`exclude_outliers` net toggle), `actuals_upload`
- Forecast Run → `version_create`, `version_list`, `run_status` polling partials
- Consensus Override Grid → `forecast_grid`, `override_list`, override value/qty/% editors, `split_weight_editor`, affected-lines + propagation partials
- Version Comparison → `version_detail` / `version_export` (xlsx)
- Accuracy Report → `version_accuracy` (group_by category/location/period/item)

The outlier-queue SPA items below were all delivered via HTMX in Sprint 3B.2b (queue with system-suggested
qty/revenue adjustment, inline confirm/reject/revise, undo, bulk discard, "raise exception" from the
actuals drill-down, nav candidate-count badge, `stale_actuals` badge, `ForecastingConfig` sensitivity panel):
- [x] Candidate list: item × planning_location × distribution_channel × planning_customer × period, system-suggested qty/revenue adjustment
- [x] Inline confirm/reject actions; confirm/revise lets the planner adjust the suggested qty/revenue split
- [x] "Raise exception" action from within the Actuals Dashboard drill-down table
- [x] Badge/count on nav showing open candidate count
- [x] `stale_actuals` badge shown against affected DRAFT forecast versions
- [x] Detection sensitivity settings panel (client admin only) — edits `ForecastingConfig`
- [x] Outlier tests (Django test runner): confirm/revise/undo/bulk-discard actions, raise-exception validation (cannot exceed the row's qty/revenue)
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

### Sprint 3B.10 — Client Master Data Upload UI ✅ Done
A client-facing **Master Data** tool that routes uploaded CSV/Excel files (per-client
`03*`-and-later and, for a bahushira superuser, global `00*`–`02*` + `10*`–`12*`)
through the existing `scripts/load_*.py` loaders, with an Actuals-style overlap workflow.
- [x] Loader `data_dir` API: `load_*()` and `run(*args, data_dir=None)` accept an explicit data dir across all `scripts/load_*.py`; `scripts/helpers.py` gains `to_datetime`
- [x] Orphan loaders `load_00Aclientblock` / `load_00Bclientfeaturecontrol` + normalised CSVs (`1` → `bahushira`); `data/10Bglobalitemattributevalue.csv` stays unexposed; `30*`–`34*` excluded
- [x] Dataset registry `mysite/masterdata/datasets.py`: 32 `Dataset` dataclasses (key, title, script, scope, files, columns, group, order, model_label, natural_key, client_columns, multi_file, description) + `coerce()` / `get_dataset` / `grouped_for_scope` / `dependent_datasets(dependent FK introspection)`
- [x] `MasterDataImport` job model (`mysite/models/masterdata.py`, registered in `mysite/models/__init__.py`; migration `0005_masterdataimport`) + `master_data` top-level `ClientFeatureControl` key (migration `0006_alter_clientfeaturecontrol_feature`)
- [x] Celery task `run_masterdata_import` (`mysite/tasks/masterdata/run_loader.py`): `_read_uploads`, `_normalise` (XLSX→CSV), `_validate_columns`, `_validate_scope` (lowercased vs `client.client_code`), `build_lookups`, `count_overlaps`, `_delete_overlaps`; delete + loader run in one `transaction.atomic()`
- [x] UI app `mysite/masterdata_ui/` (`""`, `upload/`, `upload/<id>/status/`, `history/`, `template/`) mounted at `/{client_code}/masterdata/`; HTMX overlap partials (Override default / Delete-&-reload with `confirmed=1` when dependents exist / Cancel); `ALLOWED_EXT = (".csv", ".xlsx", ".xls")`
- [x] Gating: client scope for CMS admin roles via `_user_has_admin_role(client, user)`; global `00*`–`02*` + `10*`–`12*` section only when `client_code == 'bahushira'` and superuser; only superuser writes `client = NULL`; media datasets (`24itemmedia`, `12globalitemmedia`) dual file inputs (A+B), media URLs are URLField strings (binaries out of scope)
- [x] Navbar link (mobile + desktop) via `master_data_nav` context processor (`mysite/context_processors.py`) registered in the active `TEMPLATES` block
- [x] Tests: `mysite/tests/masterdata/` (26 tests); full suite 344 passed; `manage.py check` clean; `makemigrations --check --dry-run` → no changes

---

## Phase 3B Dependency Map
 
```
3B.0 (Foundation)
  └─▶ 3B.1 (Planning Hierarchy + Distribution Channel)
        └─▶ 3B.2 (Actuals Import)
              ├─▶ 3B.2b (Outlier Management)
              │     └─▶ 3B.2c (Scheme Management)   ← scheme netting is upstream of outlier;
              │                                       baseline = Actuals − scheme − outlier
              │           └─▶ 3B.2d (Item Lifecycle)  ← substitution re-key on the netted
              │                                           baseline (composed helper) +
              │                                           discontinuation/introduction
              │                                           output layers at line-write
              └─▶ 3B.3 (Forecast Models)              (3B.3/3B.4 consume the composed baseline)
                    ├─▶ 3B.4 (Statistical Engine)  ─┐
                    └─▶ 3B.5 (Override Engine)      ├─▶ 3B.6 (Accuracy)
                                                     │         │
                    3B.4 + 3B.5 + 3B.6 ─────────────┴─▶ 3B.7 (HTMX demand_ui)
                                                                │
                    3B.7 + Phase 3A Sprint 3.3 ───────────────▶ 3B.8 (3A Integration)
                                                                │
                    All ──────────────────────────────────────▶ 3B.9 (Hardening)
```

Sprint 3B.7b (React SPA) was superseded by 3B.7a — the entire UI shipped in the HTMX `demand_ui` stack.

---
 
## Phase 3B Effort Estimates
 
| Sprint | Effort (solo dev) |
|--------|------------------|
| 3B.0 Foundation | 1–2 days |
| 3B.1 Planning Hierarchy + DC | 2–3 days |
| 3B.2 Actuals Import | 3–4 days |
| 3B.2b Outlier Management | 4–6 days |
| 3B.2c Scheme Management (incl. pull-forward shadow + brand/vendor scope) | 10–14 days |
| 3B.2d Item Lifecycle (substitution + discontinuation + introduction) | 6–9 days |
| 3B.3 Forecast Models | 3–4 days |
| 3B.4 Statistical Engine | 5–7 days |
| 3B.5 Override Engine | 4–5 days |
| 3B.6 Accuracy Tracking | 2–3 days |
| 3B.7 HTMX demand_ui (incl. outlier queue) | 4–6 days |
| 3B.8 Phase 3A Integration | 2–3 days |
| 3B.9 Production Hardening | 2–3 days |
| 3B.10 Master Data Upload UI | 3–4 days |
| **Total** | **51–73 days** |

Sprints 3B.4 and 3B.5 can run in parallel once 3B.3 is complete.
Sprint 3B.7 (HTMX demand_ui) can begin in parallel with 3B.4/3B.5 once 3B.3 endpoints are stubbed.
Sprint 3B.2c (Scheme Management) ships its scheme registration + review queue views itself (HTMX, mirroring the outlier queue) as part of the sprint.
Sprint 3B.2d (Item Lifecycle) rides the composed netting helper, the ForecastLine write boundary, and the established admin/feature-flag patterns; it must land after 3B.2c and before it makes sense to harden 3B.9.
Sprint 3B.7b (React SPA) is dropped — no longer in the estimate.
 
## Phase 3C — Inventory Decision Engine (IDE)

**Goal:** Convert inventory position, demand classification, `OPERATING_PLAN` forecasts, and supply-
network data into ranked, explainable replenishment / transfer / stocking / centralization
recommendations. Planners work exception workbenches instead of reviewing individual SKUs.

Phase 3C consumes `Item`, `ClientLocation`, `Taxonomy`/`TaxonomyNode` (Phase 2) and `ForecastVersion`/
`ForecastLine`/`AbcClassDefinition`/SEIL classification (Phase 3B) as foreign keys and reused logic. It
does **not** depend on Phase 3A (eCommerce) — the two are independent consumers of the same master
data. It adds a new `ide/` model package and a Django-template + HTMX frontend (not a React SPA).

**Recommended sequencing relative to 3A:** Phase 3C can run in parallel with Phase 3A once Phase 3B's
`OPERATING_PLAN`-capable forecast infrastructure exists (3C.2 depends on 3B.3/3B.4, not on any 3A
sprint). A later integration sprint (3C.12, optional) wires an approved `ReplenishmentRecommendation`
into a 3A `Order` — that is the only point of contact between the two phases.

---

### Sprint 3C.0 — Foundation and Prerequisites

- [ ] Add `darts` to `requirements.txt` (TSB model, alongside 3B's Croston/SBA in `statsforecast`)
- [ ] Add `ClientFeatureControl` keys: `inventory_decision_engine`, `supply_network_rules`, `ddmrp`,
      `vendor_schemes`, `planner_workbenches`
- [ ] Create `mysite/models/ide/` package (empty `__init__.py` + module stubs per tech-stack layout)
- [ ] Create `ItemPlanningProfile(client, item, is_active_for_ide, lead_time_days, shelf_life_days)` —
      filters which item×node combinations the engine plans for at all
- [ ] `python manage.py makemigrations && migrate`
- [ ] `python manage.py check` — 0 issues
- [ ] Confirm `AbcClassDefinition` and SEIL classifier from 3B are importable/reusable without
      modification — do **not** create a parallel classification model

---

### Sprint 3C.1 — Policy Framework and Policy Matrix

- [ ] Create `mysite/models/ide/policy.py`:
  - `ReviewPolicy(client, name, review_type CONTINUOUS/TIME_BASED, frequency_minutes)` — frequency
    choices span 15 min through Quarterly per spec
  - `ReplenishmentPolicy(client, name, policy_type ROP/MIN_MAX/DDMRP/ORDER_UP_TO/BUY_TO_ORDER/
    TRANSFER_FIRST/CENTRALIZED/EMERGENCY/MANUAL, hybrid_config JSONField)`
  - `CoveragePolicy(client, name, coverage_days)` — 1–180 configurable
  - `StockingPolicy(client, name, strategy LOCAL/CENTRALIZED/DC/VENDOR_DIRECT/TRANSFER_FIRST/
    EMERGENCY/NON_STOCK/BUY_TO_ORDER)`
  - `TransferPolicy(client, name, transfer_strategy JSONField)`
  - `ServiceLevelPolicy(client, name, target_fill_rate_pct)`
  - `PolicyMatrix(client, abc_class, demand_pattern_class, review_policy FK, replenishment_policy FK,
    coverage_policy FK, safety_stock_logic, stocking_policy FK, transfer_policy FK,
    service_level_policy FK, forecast_trust_pct, planner_approval_rule)` — unique on
    `(client, abc_class, demand_pattern_class)`, 12 rows per client
- [ ] Seed migration / management command: `seed_default_policy_matrix(client_code)` — loads the
      reference matrix from the spec (A×Smooth = Continuous/Min-Max/30d ... C×Lumpy = Buy-to-Order/
      Emergency Stock at HO) as the out-of-box default, editable per client
- [ ] Effective review frequency resolver: `resolve_review_frequency(policy, data_refresh_frequency)`
      → `MAX(policy_frequency, data_refresh_frequency)`
- [ ] Admin: `PolicyMatrixAdmin` (12-cell grid display), inlines for each policy sub-type
- [ ] REST endpoint: `GET/POST /api/ide/policy-matrix/`
- [ ] Unit tests: matrix uniqueness constraint; seed command produces 12 rows; frequency resolver
      picks the max of the two inputs

---

### Sprint 3C.2 — Two-Stage Forecasting (`SALES_CONSENSUS` → `OPERATING_PLAN`)

- [ ] Migration: add `stage` field (`SALES_CONSENSUS` / `OPERATING_PLAN`) to Phase 3B's
      `ForecastVersion`; existing 3B versions default to `SALES_CONSENSUS`
- [ ] Create `mysite/models/ide/forecast_stage.py`:
  - `ForecastNormalizationFactor(version, anchor_node, factor, set_by, created_at)`
  - `ForecastReconciliationException(item, node, forecast_version, computed_net_demand, status)`
- [ ] Create `utils/ide/operating_plan.py`:
  - `apply_normalization_factor(version_id, anchor_node, factor)` — creates a new `OPERATING_PLAN`
    version from the source `SALES_CONSENSUS` version
  - `cascade_operating_plan(version_id)` — reuses 3B's revenue-share disaggregation to push the
    anchor-node number down the sales hierarchy; additive by construction
  - `apply_manual_override(version_id, node, qty)` — flags `is_manual_override=True`; writes a
    `ForecastReconciliationException` for the resulting non-additivity rather than clamping it
- [ ] Celery task `cascade_operating_plan(version_id)` wraps the above for large trees
- [ ] REST endpoints: `POST /api/ide/forecast-versions/{id}/operating-plan/`,
      `GET /api/ide/reconciliation-exceptions/`
- [ ] Unit tests: cascade preserves additivity when no override present; manual override produces
      exactly one `ForecastReconciliationException`; `OPERATING_PLAN` version is immutable once
      consumed by a propagation run (guard, not hard lock — mirrors 3B's `LOCKED` pattern)

---

### Sprint 3C.3 — Supply Network Master Data and Resolution

- [ ] Create `mysite/models/ide/supply_network.py`:
  - `SupplyNetworkRule(client, scope_type ITEM/TAXONOMY/ALL, taxonomy_node nullable, item nullable,
    location, valid_from, valid_to, source_type VENDOR/DC/LOCATION/HO, source_ref, allocation_pct)`
  - `ResolvedSupplySource(item, location, effective_date, source_type, source_node/vendor,
    allocation_pct, resolved_rule FK)` — materialized cache table only, never written to directly
- [ ] Create `utils/ide/supply_network_resolver.py`:
  - `resolve_supply_source(item, location, date)` — generic→specific walk: ITEM exact match →
    TAXONOMY (deepest ancestor with a rule for that location) → ALL → hard `ValidationError` on no
    match (reuses the Phase 2 taxonomy materialized-path walk)
  - `validate_split_sourcing(rules_for_key)` — enforces same-scope-level-only legs and
    `Σ allocation_pct == 100%`
  - `materialize_resolved_supply_source(client_code)` — bulk resolves all item×location combinations,
    writes `ResolvedSupplySource`
- [ ] Celery task `resolve_supply_network(client_code)`: nightly beat + triggered on
      `SupplyNetworkRule` post_save
- [ ] Periodic integrity job: catches rules whose `valid_to` has lapsed and silently broken a
      previously-100%-summing split, without requiring any row edit to surface it
- [ ] Admin: `SupplyNetworkRuleAdmin` with scope-type-aware form (hide irrelevant fields per scope)
- [ ] REST endpoints: `GET/POST /api/ide/supply-network-rules/`, `GET /api/ide/resolved-supply-source/`
- [ ] Unit tests: ITEM beats TAXONOMY beats ALL; no-match raises hard error (never silent fallback);
      mixed-scope-level split rejected; lapsed `valid_to` caught by integrity job; split summing to
      100% passes, 97% fails

---

### Sprint 3C.4 — Demand Propagation Engine

- [ ] Create `mysite/models/ide/propagation.py`:
  - `NodeReplenishmentRequirement(item, node, date, source_leg, quantity)`
- [ ] Create `utils/ide/propagation_engine.py`:
  - `compute_net_own_demand(node, period)` — `FCST(N) − Σ bypass legs of children not sourced from N`
  - `compute_replenishment_requirement(node, source, period)` — recursive `RR(N, via X)` per the spec
    algorithm, generalized to arbitrary depth and bypass patterns
  - `run_propagation(client_code, operating_plan_version_id)` — orchestrates full-network propagation,
    writes `NodeReplenishmentRequirement`
  - `check_conservation_invariant(client_code, version_id)` — `Σ RR at every vendor-facing leg == Σ FCST
    at every end node`; raises (does not warn-and-continue) on violation
- [ ] Celery task `propagate_replenishment_demand(client_code, version_id)`, scheduled per client at
      `resolve_review_frequency()` cadence
- [ ] Regression test suite: encode the worked example from the spec (HO 300 / DC1 200 split 60/40 /
      DC2 100 Vendor-only → RR(DC1,HO)=120, RR(DC1,Vendor)=80, RR(DC2,Vendor)=100,
      RR(HO,Vendor)=240) as a permanent test fixture, re-run on every engine change
- [ ] Unit tests: single-level bypass; multi-level bypass; fully congruent tree (no bypass) reduces to
      simple bottom-up; conservation invariant violation raises with actionable diagnostic (which
      item/location fell through)

---

### Sprint 3C.5 — Supply Position Ingestion and MRP Netting

- [ ] Create `mysite/models/ide/ingestion.py`:
  - `SupplyPositionSnapshot(client, snapshot_id UUID, as_of_datetime, received_at, source_system,
    status RECEIVED/VALIDATED/APPLIED/REJECTED, is_full_snapshot, supersedes self-FK)`
  - `StockOnHand(snapshot, item, node, qty_unrestricted, qty_blocked, qty_in_transit_to_node)` —
    unique on `(snapshot, item, node)`
  - `OpenSupply(snapshot, supply_type PO/STO/WO, external_doc_number, external_line_number, item,
    receiving_node, source_node nullable, vendor nullable, order_qty, received_qty, open_qty,
    expected_receipt_date, order_status)` — unique on
    `(snapshot, supply_type, external_doc_number, external_line_number)`
  - `OpenDemandCommitment(snapshot, item, node, committed_qty, required_date, external_doc_number)`
    — optional per client
- [ ] Create `mysite/models/ide/inventory_position.py`:
  - `InventoryPosition(item, node, date, on_hand, in_transit, net_requirement, min, max, rop,
    ddmrp_red, ddmrp_yellow, ddmrp_green, projected_inventory)`
- [ ] Bulk-ingest DRF endpoints: structural validation (item/node codes resolve, quantities
      non-negative, dates parseable); **reject whole snapshot on any row failure** — no partial apply
- [ ] Celery task `ingest_supply_position_snapshot(snapshot_id)` — materializes `VALIDATED` snapshot
      into a denormalized item×node netting-ready structure
- [ ] Create `utils/ide/netting_engine.py`:
  - `compute_net_requirement(item, node, date)` — `Gross Requirement (from
    NodeReplenishmentRequirement) − on_hand_available − scheduled_receipts + uncommitted_open_demand`
  - Time-fencing: full detail only inside `lead_time + review_period + safety_margin`; aggregated
    total beyond the fence
- [ ] Celery task `run_netting(client_code, snapshot_id)` — writes `InventoryPosition`
- [ ] Sparse-transmission support: ingestion endpoint tolerates omitted zero-position rows without
      treating them as data-quality errors
- [ ] Feed manifest filter: expected-feed generator consults `ItemPlanningProfile.is_active_for_ide`
      before requesting position data
- [ ] Unit tests: partial-failure snapshot rejected wholesale; idempotent re-ingest of same
      `snapshot_id`; netting formula correctness incl. `qty_blocked` excluded; time-fenced aggregation
      matches full-detail sum inside the fence

---

### Sprint 3C.6 — Inventory Policy Engine (Min/Max, ROP, DDMRP, Forecast Trust)

- [ ] Create `utils/ide/inventory_policy_engine.py`:
  - `compute_edu(item, node)` — `EDU = ForecastTrust × FDU + (1 − ForecastTrust) × HDU`, trust % read
    from the item's `PolicyMatrix` cell (defaults: Smooth 90%, Erratic 60%, Intermittent 60%,
    Lumpy 20%)
  - `compute_lead_time_demand(item, node)`, `compute_safety_stock(item, node)` — per policy cell logic
  - `compute_min_max(item, node)` — `Min = LTD + SS`, `Max = Min + Coverage Demand`
  - `compute_rop(item, node)` — continuous-review reorder point
  - `compute_ddmrp_zones(item, node)` — Red/Yellow/Green buffer zones for **all** items (DDMRP items
    use zones operationally; non-DDMRP items use zones for visual monitoring only)
- [ ] Wire policy resolution: item's ABC + SEIL class → `PolicyMatrix` cell → which formula path
      executes (`formula_used` recorded for explainability downstream)
- [ ] Write results to `InventoryPosition` (min/max/rop/ddmrp zone fields, `projected_inventory`)
- [ ] Admin/API: `GET /api/ide/inventory-position/` filtered by item/node/date range
- [ ] Unit tests: EDU blend at each SEIL default trust %; DDMRP zones computed for non-DDMRP items too
      (monitoring-only path); coverage-days bounds (1–180) enforced

---

### Sprint 3C.7 — Vendor Scheme and Carrying-Cost Engine

- [ ] Create `mysite/models/ide/vendor_scheme.py`:
  - `InventoryCarryingCostRate(client, abc_class, demand_pattern_class, annual_carrying_cost_pct,
    valid_from, valid_to)` — unique on `(client, abc_class, demand_pattern_class, valid_from)`,
    reuses ABC/SEIL as grid axes (no new classification)
  - `ExcessInventoryPenaltyTier(client, abc_class, demand_pattern_class, age_bucket_from_days,
    age_bucket_to_days nullable, additional_annual_pct, valid_from, valid_to)`
  - `VendorScheme`, `VendorSchemeScope`, `VendorSchemeSlab` (exact fields per tech-stack delta;
    `category` TRANSACTIONAL is exclusive/most-specific-wins, `category` REBATE is additive and never
    competes with TRANSACTIONAL in the same resolution)
  - `ResolvedVendorScheme` — materialized, same generic→specific pattern as `ResolvedSupplySource`
  - `VendorRebateAccrual(scheme, vendor, period_start, period_end, cumulative_value_to_date,
    cumulative_qty_to_date, estimated_effective_discount_pct, actual_settled_discount_pct nullable,
    settled_at nullable)`
- [ ] `utils/ide/vendor_scheme_resolver.py`: item-specific → taxonomy path (sub-brand before brand) →
      `OVERALL`, materialized on scheme change (reuse resolver pattern from 3C.3)
- [ ] Celery task `compute_rebate_accrual_estimate(scheme_id)` — median (not mean) of last 3–4 settled
      periods' `actual_settled_discount_pct`
- [ ] Create `utils/ide/vendor_breakpoint_evaluator.py`:
  - `evaluate_order_quantity(item, node, base_qty)` — implements the breakpoint trade-off formula from
    the spec exactly (excess_qty / holding-days / carrying-cost / discount-saving / net-benefit /
    argmax, defaulting to `base_qty` if all `net_benefit <= 0`)
  - Applies `estimated_effective_discount_pct` as a flat reduction to `unit_cost_at(B)` uniformly
  - Guardrails: cap `expected_holding_days` at shelf-life/configurable ceiling; MOQ, warehouse
    capacity, cash/budget ceiling as candidate-set **filters**, never formula inputs
- [ ] Celery task `evaluate_vendor_breakpoints(recommendation_id)`
- [ ] Unit tests: transactional-only resolution; rebate additive on top of transactional never
      competing; median rebate calc with sample settled-period data; breakpoint chosen only when
      `net_benefit > 0`; base_qty returned when no slab clears the carrying-cost hurdle; holding-days
      ceiling caps an absurd slow-mover quantity

---

### Sprint 3C.8 — Recommendation and Explainability Engine

- [ ] Create `mysite/models/ide/recommendation.py`:
  - `ReplenishmentRecommendation(item, node, rec_type PURCHASE/TRANSFER/STOCKING/CENTRALIZATION/
    EMERGENCY/ALTERNATIVE_SUPPLY, recommended_qty, policy_cell FK, inputs JSONField, formula_used,
    trigger_reason, alternatives JSONField, expected_outcome JSONField, status)`
  - `PlannerDecision(recommendation, decided_by, decision APPROVE/REJECT/MODIFY, modified_qty,
    decided_at, note)`
- [ ] Create `utils/ide/recommendation_engine.py`:
  - `generate_purchase_recommendation(item, node)` — netting + breakpoint evaluation → recommendation
  - `generate_transfer_recommendation(item, node)` — evaluated when `ReplenishmentPolicy` favors
    TRANSFER_FIRST or when a sibling/parent node carries excess against this node's shortfall
  - `recommend_stocking_strategy(item, node)` — auto-recommends
    LOCAL/CENTRALIZED/DC/VENDOR_DIRECT/TRANSFER_FIRST/EMERGENCY/NON_STOCK/BUY_TO_ORDER based on ABC,
    SEIL, lead time, network demand, service criticality, annual demand, demand frequency (per spec's
    listed inputs)
  - `generate_centralization_recommendation(item)` — network-level candidate when multiple nodes show
    low, erratic local demand better served by a DC/HO buffer
  - Every generator writes the full explainability payload (`inputs`, `policy_cell`, `formula_used`,
    `trigger_reason`, `alternatives`, `expected_outcome`) at creation time, not reconstructed later
- [ ] Celery task `generate_recommendations(client_code)` — orchestrates all generators after netting +
      breakpoint evaluation complete for a review cycle
- [ ] REST endpoints: `GET /api/ide/recommendations/`, `POST /api/ide/recommendations/{id}/decide/`
- [ ] Unit tests: each rec_type generator produces a populated explainability payload; planner
      approval-rule gating (per `PolicyMatrix.planner_approval_rule`) routes high-value/high-risk
      recommendations to mandatory review instead of auto-approval

---

### Sprint 3C.9 — Planner Workbenches (Django Templates + HTMX)

- [ ] Create `ide_ui/` app: `urls.py`, `views.py`, `views_htmx.py` (mirrors `demand_ui`/`inventory_ui`
      structure — server-rendered, **not** a React SPA)
- [ ] Templates under `templates/ide/workbenches/`, one per workbench:
  - **Service Risk Workbench** — items/nodes below target fill rate, ranked by risk
  - **Replenishment Workbench** — PURCHASE recommendations queue, filter/sort/bulk-approve
  - **Transfer Workbench** — TRANSFER recommendations, source/destination pairing view
  - **Inventory Balancing Workbench** — excess-vs-shortfall cross-node view
  - **Vendor Scheme Workbench** — active schemes, accrual progress, breakpoint evaluation log
  - **Exception Management Workbench** — `ForecastReconciliationException` +
    supply-network-integrity-job findings, unresolved snapshot rejections
  - **Policy Governance Workbench** — `PolicyMatrix` CRUD grid, policy cell editor
- [ ] HTMX-powered filter/pagination pattern reused from Phase 2 catalogue (`hx-get`,
      `hx-target="#..."`, `hx-swap="innerHTML"`)
- [ ] `recommendation_decide` HTMX partial: approve/reject/modify inline, writes `PlannerDecision`,
      updates recommendation `status` without full page reload
- [ ] `ClientGroupPermission` module `inventory_decision_engine` wired to all workbench views
- [ ] Unit/integration tests: each workbench renders its filtered queryset; decide-action HTMX partial
      round-trips correctly; permission gate blocks unauthorized roles

---

### Sprint 3C.10 — Multi-Echelon Centralization and Transfer Refinement

- [ ] Extend `recommend_stocking_strategy()` with explicit network-demand-aggregation awareness — a
      node with low local demand but healthy aggregated parent/DC demand should trend toward
      CENTRALIZED/DC stocking rather than LOCAL, per the multi-echelon design principle
- [ ] Transfer-vs-purchase ranking: when both a TRANSFER and a PURCHASE recommendation are viable for
      the same shortfall, rank by landed cost + lead time, surface both as `alternatives` on the
      chosen recommendation
- [ ] Emergency stock path: `EMERGENCY` rec_type triggered when `InventoryPosition` breaches the
      DDMRP red zone (or ROP with insufficient scheduled receipts) inside lead time
- [ ] Unit tests: centralization candidate correctly identified across a 3-node network fixture;
      transfer beats purchase when landed cost is lower and lead time is acceptable; emergency
      triggers only inside the lead-time-breach window, not on every red-zone dip

---

### Sprint 3C.11 — Production Hardening and Scale Validation

- [ ] Deploy IDE Celery tasks with dedicated queue (`ide` queue, separate from Phase 3B `demand`
      queue) to isolate long-running propagation/netting jobs from forecast-run jobs
- [ ] `EXPLAIN ANALYZE` on all Phase 3C indexes (resolved-supply-source, node-replenishment,
      snapshot-scoped netting inputs, recommendation queue, resolved-vendor-scheme)
- [ ] Load test: 100,000 SKU-location combinations — full propagation + netting + recommendation
      generation cycle completes within an agreed batch window (define per-client SLA, e.g. overnight
      batch < 4 hours)
- [ ] Load test: snapshot ingestion of 500K `StockOnHand`/`OpenSupply` rows completes within
      acceptable bounds using time-fencing + sparse transmission
- [ ] End-to-end test: rule change → nightly resolution → propagation → netting → breakpoint
      evaluation → recommendation → planner decision, full chain
- [ ] Verify conservation-invariant regression test runs in CI on every PR touching `utils/ide/`
- [ ] Wire `django-guardian` / `ClientGroupPermission` to all IDE views and API endpoints
- [ ] Document the "IDE is a standalone service — does not own transactional ERP data" boundary
      clearly (README), mirroring the DuckDB/PostgreSQL boundary note from Phase 3B

---

### Sprint 3C.12 — Phase 3A Integration (Optional, evaluate after 3C.11)

- [ ] `OrderLine`/procurement-side hook: an approved `PURCHASE` `ReplenishmentRecommendation` can seed
      a draft `Order` (3A) or an external PO reference — evaluate against actual client workflow
      before building; this is the only planned contact point between 3A and 3C
- [ ] Unit tests: recommendation-to-order handoff preserves qty/item/vendor; recommendation marked
      `status=ACTIONED` on handoff

---

## Phase 3C Dependency Map

```
3C.0 (Foundation)
  └─▶ 3C.1 (Policy Matrix, reuses 3B ABC/SEIL)
        └─▶ 3C.2 (Two-Stage Forecasting)
              └─▶ 3C.3 (Supply Network Resolution)
                    └─▶ 3C.4 (Demand Propagation)
                          └─▶ 3C.5 (Ingestion + MRP Netting)
                                └─▶ 3C.6 (Inventory Policy Engine: Min/Max/ROP/DDMRP)
                                      ├─▶ 3C.7 (Vendor Scheme + Carrying Cost)  ─┐
                                      └────────────────────────────────────────┴─▶ 3C.8 (Recommendation Engine)
                                                                                       │
                                                                    3C.8 ──────────────┴─▶ 3C.9 (Planner Workbenches)
                                                                                                   │
                                                                    3C.9 ─────────────────────────┴─▶ 3C.10 (Multi-Echelon Refinement)
                                                                                                              │
                                                                    All ─────────────────────────────────────┴─▶ 3C.11 (Hardening)
                                                                                                                          │
                                                            3C.11 + Phase 3A Sprint 3.3 ─────────────────────────────────┴─▶ 3C.12 (3A Integration, optional)
```

`3C.2` depends only on Phase 3B Sprints 3B.3/3B.4 (forecast infrastructure) — Phase 3C can start and
run largely in parallel with Phase 3A once that dependency is satisfied.

---

## Phase 3C Effort Estimates

| Sprint | Effort (solo dev) |
|--------|------------------|
| 3C.0 Foundation | 1–2 days |
| 3C.1 Policy Framework & Matrix | 3–4 days |
| 3C.2 Two-Stage Forecasting | 4–5 days |
| 3C.3 Supply Network Resolution | 5–7 days |
| 3C.4 Demand Propagation Engine | 6–8 days |
| 3C.5 Ingestion & MRP Netting | 7–9 days |
| 3C.6 Inventory Policy Engine | 5–6 days |
| 3C.7 Vendor Scheme & Carrying Cost | 6–8 days |
| 3C.8 Recommendation Engine | 5–6 days |
| 3C.9 Planner Workbenches | 8–10 days |
| 3C.10 Multi-Echelon Refinement | 3–4 days |
| 3C.11 Production Hardening | 3–4 days |
| 3C.12 3A Integration (optional) | 2–3 days |
| **Total (3C.0–3C.11)** | **56–73 days** |
| **Total incl. optional 3C.12** | **58–76 days** |

3C.6 and 3C.7 can run in parallel once 3C.5 is complete (both consume `InventoryPosition`/netting
output independently). 3C.9 (workbenches) can begin scaffolding in parallel with 3C.7/3C.8 once
3C.8's REST endpoints are stubbed, same pattern as 3B.7 running alongside 3B.4/3B.5.

---

## Key Risks and Mitigations (Phase 3C)

| Risk | Mitigation |
|------|-----------|
| Supply network / sales hierarchy conflation | Enforce at the model layer — no shared parent-link field; code review checklist item; the resolver never accepts a sales-hierarchy node as a supply-network input |
| Propagation algorithm correctness at scale | Conservation-invariant regression test (worked example from spec) run in CI on every change to `utils/ide/propagation_engine.py`; never relaxed to a warning |
| Snapshot ingestion partial-apply corrupting netting | Whole-snapshot reject-on-any-row-failure is a hard rule, not a default — no code path partially commits a `SupplyPositionSnapshot` |
| Netting horizon data volume (20K+ items × multiple nodes) | Time-fencing applied first (highest impact); delta/CDC feed explicitly deferred to a v2 optimization, not day-one scope |
| Vendor breakpoint formula producing absurd quantities for slow movers | Hard ceiling on `expected_holding_days`; MOQ/capacity/budget as filters, never formula inputs — both enforced in `vendor_breakpoint_evaluator.py`, tested with slow-mover fixtures |
| Rebate logic drifting into threshold-chasing | Explicitly out of scope per mission non-goals; `compute_rebate_accrual_estimate` only ever *informs* landed cost, never triggers order-qty increases on its own |
| Policy Matrix becoming a hardcoded-logic escape hatch | Code review discipline: any new replenishment behavior must be expressible as a `PolicyMatrix` cell field, not a special-cased branch in `recommendation_engine.py` |
| Workbench UI complexity creeping toward needing a SPA | Default to Django+HTMX per workbench; revisit only a specific workbench (not the whole module) if bulk-edit-at-scale is proven necessary |
| Explainability payload becoming an afterthought | `inputs`/`policy_cell`/`formula_used`/`trigger_reason`/`alternatives`/`expected_outcome` are required (non-nullable where feasible) fields on `ReplenishmentRecommendation`, populated at write time by every generator function — enforced by unit test per generator |

---

## Definition of Done (Phase 3C)

- [ ] `PolicyMatrix` (12 cells) editable per client via Policy Governance Workbench; seeded with the
      reference matrix from the spec as default
- [ ] `OPERATING_PLAN` forecasts derive correctly from `SALES_CONSENSUS` via normalization + cascade;
      manual overrides produce a `ForecastReconciliationException`, never silent clamping
- [ ] `SupplyNetworkRule` resolution is generic→specific with hard failure on no match; split sourcing
      validated to sum to 100% on save and via periodic integrity job
- [ ] Demand propagation passes the conservation-invariant regression test on the spec's worked
      example and on at least one multi-level, asymmetric-bypass fixture
- [ ] `SupplyPositionSnapshot` ingestion is all-or-nothing; idempotent re-ingestion produces no
      duplicate netting inputs
- [ ] MRP netting produces `Net Requirement` correctly incorporating on-hand, scheduled receipts, and
      uncommitted open demand
- [ ] DDMRP zones computed for all items (operational for DDMRP-policy items, monitoring-only for
      others)
- [ ] Vendor breakpoint evaluation selects a quantity above `base_qty` only when net benefit is
      positive, respecting MOQ/capacity/budget filters and the holding-days ceiling
- [ ] Every `ReplenishmentRecommendation` carries a complete explainability payload
- [ ] All seven planner workbenches functional with HTMX-driven filter/decide interactions
- [ ] Load test: 100,000 SKU-location combinations complete a full batch cycle within the agreed SLA
- [ ] `manage.py check` clean; 0 migration errors
- [ ] `django-guardian` / `ClientGroupPermission` enforced on all IDE views and API endpoints

---

## Deferred / Future Consideration (Phase 3C)

| Feature | Rationale |
|---------|-----------|
| Full simulation / what-if engine | High complexity, best validated against a working core engine first — candidate for Phase 3D or Phase 4 |
| Live vendor EDI / direct ERP integration | IDE is a standalone service; snapshot ingestion contract is the deliberate integration boundary |
| Automatic PO/STO creation into Phase 3A | Sprint 3C.12 is optional and evaluated only after 3C.11 is validated against real client data |
| Delta/CDC snapshot feed | Explicitly a v2 optimization on top of the day-one full/sparse snapshot contract |
| ML-based demand models (XGBoost, LightGBM) | Statistical models (Croston/SBA/TSB via `statsforecast`/`darts`) only in Phase 3C, consistent with the same non-goal already stated for Phase 3B |
| AG-Grid-style bulk-edit workbench UI | Default is Django+HTMX; revisit per-workbench only if proven necessary at scale |

---
 
## Recommended Overall Sequencing
 
```
Phase 2 (Complete)
    ↓
Phase 3B.0–3B.6  (Actuals + Forecast engine, no UI yet)   ← ~20 days
    ↓  [parallel with 3B.7]
Phase 3A.0–3A.3  (Foundation, Pricing, Inquiry, Order)    ← ~20 days
    ↓
Phase 3B.7–3B.8  (HTMX demand_ui + Order integration)     ← ~10 days
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
| Actuals data quality (missing FKs, wrong item codes) | Row-level error collection in `ActualSaleImport.error_log`; never fail the whole batch for a bad row |
| Stale draft forecast trusted downstream | `stale_actuals` flag set by `flag_stale_forecast_versions` + UI badge; no auto-rerun, planner re-runs explicitly; scheme modification after overrides exist also flags version as stale |
| DuckDB + PostgreSQL dual-engine confusion | DuckDB is used **only inside Celery tasks / aggregates paths** for fast aggregation; all writes go to PostgreSQL only; document this boundary clearly |
 
---
 
## Definition of Done (Phase 3B)
 
- [x] Client staff can upload periodic actuals (CSV/Excel) for planning_location × item × distribution_channel × planning_customer
- [x] Upload is idempotent (re-upload same file produces no duplicates)
- [x] Outlier detection proposes candidates over a planner-chosen period range; confirm/reject/revise/undo/bulk-discard from the HTMX queue; confirmed adjustments net actuals everywhere by default
- [ ] Scheme management: planner registers scheme with uplift/shadow → resolved rows materialize → outlier detection ignores scheme periods → forecast writes `pre_scheme_statistical_qty` + `scheme_qty` → `statistical_qty` = scheme-adjusted → override system works on `statistical_qty` (unchanged) → both columns visible in UI
- [ ] Forecast run completes for 10K SKU × 200 customer × 36 month history in < 15 minutes (load test not yet run)
- [x] Hierarchical reconciliation: top-level total of reconciled forecast equals sum of bottom-up
- [x] Consensus override at Location level disaggregates correctly to leaf lines
- [x] LOCKED version rejects all edits
- [x] Accuracy report shows MAPE / Bias / WMAPE against net actuals for an approved version period
- [ ] Approved forecast version shows suggested quantity on Quotation / Order line form (3B.8, pending 3A)
- [ ] All demand API endpoints enforce `ClientGroupPermission` (demand_planning module) — currently `DemandFeatureMixin` gates on `ClientFeatureControl` only
- [x] `manage.py check` clean; 0 migration errors
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
- [ ] Cache: `pricing_procedure:{client_code}` (1hr), `condition_records:{client_code}:{type}` (15min)
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
