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
- [ ] Split `settings.py` into `base.py` / `development.py` / `production.py`
- [ ] Move `SECRET_KEY` to environment variable
- [ ] `whitenoise` for static files
- [ ] PostgreSQL wiring via `DATABASE_URL` env var
- [ ] Deploy skeleton app to Railway/Render (establish pipeline early)

### Milestone 1.2 — Multi-Tenancy Core ✅ Done
- [x] `Client` model: `client_id` (LowercaseCharField), `parent` (self-FK for hierarchy), `language_list` (JSONField), `theme_list` (JSONField), translatable `name` / `nb_title`
- [x] `CustomerProfileMiddleware`: resolves `/{client_id}/` → `request.client`; URL kwargs → session fallback
- [x] `client_context` context processor: consumes `request.client`, calls `fetch_clientstatic()`, delivers `client`, `theme`, `page_dict` to all templates
- [x] `ClientLocation` model: `location_id`, `location_type` (store/branch/warehouse/office), FK to `Client`
- [x] `LowercaseCharField` custom field for all natural-key IDs
- [ ] Explicit `AppConfig` for `mysite` (verify app label matches in all migrations)
- [ ] URL namespace: confirm `/{client_id}/` prefix routes are fully wired in `urls.py`

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
- [ ] `django-modeltranslation` translation classes registered in `translation.py` for `Client`, `Page`, `Theme`, `GlobalVal` — confirm registrations are complete and migrations generated
- [ ] Language switcher UI wired end-to-end (session-based language preference per customer per client)

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
- [ ] `GentextBlock` is present but currently unused in `build_client_payload` (commented out) — decide: keep for future use or remove
- [ ] `django-admin-sortable2` fully wired into admin classes for all sortable models

### Milestone 1.6 — Data Serialisation & Caching Layer ✅ Done
- [x] `fetch_clientstatic(client_id, use_cache, timeout)` — single deeply-prefetched query + cache
- [x] `build_client_payload()` — builds full client dict (languages, themes, pages, page_tree)
- [x] `build_page()` / `build_layout()` / `build_component()` / `build_slot()` — recursive tree builders
- [x] `build_blocks()` / `build_stb_item()` / `build_values()` — text content serialisers
- [x] `build_page_tree()` — builds nested page hierarchy dict for navigation bar
- [x] `serialize_model()` — generic model → dict with modeltranslation grouping
- [x] `resolve_theme()` — merges ThemePreset base tokens with Theme.overrides
- [x] `THEME_PRESET_FIELDS` cached at import time
- [x] `LocMemCache` configured (`translations-cache`)
- [ ] **Cache invalidation signals** — `post_save` on `Client`, `Page`, `Layout`, `Component`, `ComponentSlot`, `Theme` must call `cache.delete(f"clientstatic:{client_id}")`. Not yet implemented. Without this, content edits don't reflect until cache expires or server restarts.
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

### Milestone 1.8 — Interactive Forms (Pending decision)
- [ ] **HTMX vs Datastar decision** — Datastar was dropped. Evaluate HTMX for: theme switcher, language switcher, inline content editing. Spike and decide.
- [ ] Theme switcher wired with HTMX partial response (currently full-page POST redirect)
- [ ] Language switcher UI component

### Milestone 1.9 — Production Hardening
- [ ] Split `settings.py` into `base` / `development` / `production`
- [ ] `SECRET_KEY` moved to env var; `DEBUG=False` in production config
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` set via env vars
- [ ] `ACCOUNT_EMAIL_VERIFICATION = "mandatory"` in production
- [ ] `whitenoise` static files verified on PaaS
- [ ] `DATABASE_URL` env var driving PostgreSQL
- [ ] Redis cache wired in production
- [ ] Cache invalidation signals implemented
- [ ] `manage.py check --deploy` passes with no warnings
- [ ] Basic smoke tests: tenant resolution, page render, auth flows
- [ ] README with local dev setup and deploy instructions

---

## Open Decisions

| Decision | Status | Notes |
|----------|--------|-------|
| HTMX vs Datastar | Datastar dropped. HTMX not yet added. | Spike HTMX for theme/language switcher and inline editing |
| `GentextBlock` retention | Present but unused | Decide: keep for future use or remove to reduce model complexity |
| `models.py` split | Single file, growing large | Split into `models/` package before Phase 2 |
| Staff admin UI | Django Admin (current) | Re-evaluate custom dashboard after Phase 1 with real client feedback |
| Cache invalidation | Not implemented | Required before production — `post_save` signals on all content models |

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

---

## Phase 3 — eCommerce

**Goal**: Customers can purchase products. Clients can manage orders.

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