# Tech Stack

## Overview

Server-side rendered Django 5.2 application. Tailwind CSS for styling, `django-cotton` for component templates, `django-modeltranslation` for field-level i18n, and a cached `fetch_clientstatic()` layer as the primary data delivery mechanism. PostgreSQL in production. Deployed to a PaaS (Railway or Render).

---

## Backend

### Core Framework

| Package | Version | Purpose |
|---------|---------|---------|
| `Django` | 5.2.4 | Core web framework |
| `gunicorn` | latest | WSGI server for production |
| `whitenoise` | latest | Static file serving on PaaS |
| `psycopg2-binary` | latest | PostgreSQL adapter (production) |

Phase 3 addition
 Package | Version | Purpose |
|---------|---------|---------|
| `djangorestframework` | latest stable | REST API layer for mobile / Beckn adapter; used for commerce document endpoints |
| `django-filter` | latest stable | DRF filter backend for Order / Delivery list APIs |
| `celery` | 5.x | Background task queue — order confirmation email, pricing recalculation, document promotion jobs |
| `redis` | latest | Celery broker + result backend; replaces LocMemCache in production |
| `djmoney` | latest | `MoneyField` — stores `(amount, currency)` pairs; integrates with `py-moneyed` for arithmetic |
| `babel` | latest | Currency formatting and locale-aware number rendering |


### Authentication & Authorization

| Package | Version | Notes |
|---------|---------|-------|
| `django-allauth` | 65.10.0 | Auth flows for both `ClientUserProfile` and `CustomerProfile`. Custom `ClientAwareAccountAdapter` in `mysite/adapters.py`. |
| `django-allauth-ui` | 1.8.1 | Pre-built Tailwind-compatible allauth templates (`widget_tweaks` + `slippers` are its dependencies — both installed). |
| `django-guardian` | 3.3.1 | Object-level permissions on `Client`. `ObjectPermissionBackend` is registered in `AUTHENTICATION_BACKENDS`. |

**Auth backend order (as configured):**
1. `django.contrib.auth.backends.ModelBackend` — Django admin / username login
2. `guardian.backends.ObjectPermissionBackend` — object-level permissions
3. `allauth.account.auth_backends.AuthenticationBackend` — email-based login

**Key auth decisions:**
- Django's built-in `User` is used directly (no `AbstractBaseUser` subclass). `ClientUserProfile` and `CustomerProfile` are profile models hanging off it.
- `ClientUserProfile` uses `OneToOneField` (one staff role per user).
- `CustomerProfile` uses `ForeignKey` (one profile per user per client, enforced by `unique_together`).
- `ACCOUNT_EMAIL_VERIFICATION = "optional"` in development. Must be changed for production.

### Content & Multilingual

| Package | Version | Notes |
|---------|---------|-------|
| `django-modeltranslation` | 0.20.2 | Installed **before** `django.contrib.admin`. Adds `_<lang>` columns for registered fields (`name`, `nb_title`, etc.) on `Client`, `Page`, `Theme`. Must be listed before `django.contrib.admin` in `INSTALLED_APPS`. |

**Translation architecture — two parallel systems:**

1. **`django-modeltranslation`** — for structural fields on `Client`, `Page`, `Theme` (e.g. page names, navbar titles). Columns are generated at migration time.
2. **`ComptextBlock` → `TextstbItem` → `SvgtextbadgeValue`** — for component content (titles, body copy, button labels). Language is stored as a plain `language_code` CharField. This keeps component content flexible without generating schema changes per language addition.

### Admin & Content Management

| Package | Version | Notes |
|---------|---------|-------|
| `django-nested-admin` | 4.1.6 | Installed **before** `django.contrib.admin` in `INSTALLED_APPS`. Enables nested inlines for the `Layout → Component → ComponentSlot → ComptextBlock` hierarchy. |
| `django-admin-sortable2` | 2.2.8 | Drag-to-reorder for `Layout`, `ComponentSlot`, `Page` ordering fields. |

**Known constraint:** `django-unfold` was trialled but is incompatible with `django-nested-admin` and is **commented out**.

### Developer Utilities

| Package | Version | Notes |
|---------|---------|-------|
| `django-extensions` | 4.1 | `shell_plus`, `graph_models`, `show_urls`. |
| `django-debug-toolbar` | 6.0.0 | Loaded conditionally — only when `not TESTING`. Panels: Timer, SQL, Cache, Templates, Request, Settings. History and Profiling panels disabled. |

---

## Frontend

### Styling

| Package | Version | Notes |
|---------|---------|-------|
| `django-tailwind` | 4.2.0 | `TAILWIND_APP_NAME = 'theme'`. |
| `django-browser-reload` | 1.18.0 | Currently **commented out** in both `INSTALLED_APPS` and `MIDDLEWARE`. Re-enable when active frontend development is underway. |
| `django-cotton` | 2.1.3 | Installed via `django_cotton.apps.SimpleAppConfig`. Template dirs: `mydj/templates`. Uses the `cached.Loader` chain. Provides the component template layer for `hero`, `card`, `accordion`, `carousel` component types. |

**Template loader chain (order matters):**
```python
"django_cotton.cotton_loader.Loader"
"django.template.loaders.filesystem.Loader"
"django.template.loaders.app_directories.Loader"
```
Wrapped in `cached.Loader`. `APP_DIRS = False` (required by cotton — overrides the default).

### Interactivity

- **`datastar-py`** was trialled but dropped (`# datastar-py==0.8.0 # NOT WORKING PROPERLY DROPPED`).
- Currently no HTMX or Datastar in use. Interactive forms (theme switcher, profile, addresses) use standard Django form POST + redirect.
- **Decision required:** Re-evaluate HTMX vs Datastar for Phase 1 completion — specifically for inline admin editing and the theme switcher (`set_theme` view). See open decisions.

---

## Data Architecture

### Primary Key Strategy
- Models use Django's default `BigAutoField` (`DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'`).
- `LowercaseCharField` is used for natural-key ID fields (`client_code`, `page_code`, `theme_code`, etc.) — auto-lowercased on save via `get_prep_value`.

### The `fetch_clientstatic()` Pattern
The central data delivery mechanism. On every page request:
1. `CustomerProfileMiddleware` resolves `request.client` from URL path (one DB query or none if cached).
2. `client_context` context processor calls `fetch_clientstatic(client_code)`.
3. `fetch_clientstatic` checks cache first (`clientstatic:{client_code}`). On miss, runs a single deeply-prefetched query across `Client → Page → Layout → Component → ComponentSlot → ComptextBlock → TextstbItem → SvgtextbadgeValue`.
4. Result is serialised to a plain Python dict by `build_client_payload()` and cached.
5. Templates consume `{{ client }}`, `{{ page_dict }}`, `{{ theme }}` — never raw ORM calls.
6. `header_nav` and `footer_nav` are built from `NavItem` records prefetched
  alongside pages and themes. `build_nav_item()` calls `item.get_url(client_code)`
  to resolve the full path for `page` nav_types, storing it as `item.href`
  (separate from the raw `item.url` field used for active-state matching).
  Nav labels use modeltranslation (`name_en`, `name_hi` etc.) and are grouped
  under `translations.name` by `serialize_model()` — consistent with `Page`
  and `Client` translatable fields.
### Dual-Track Page Rendering

Pages can be rendered via two tracks that coexist on the same `Page` model:

**Track A — `PageContent` (raw HTML, Phase 1 primary path)**
- `PageContent(page, language_code, html)` stores one HTML blob per page per language.
- `ClientPageView` checks for a `PageContent` record for the active language before falling through to the component tree.
- Language fallback: active language → `en` → first available `PageContent` row.
- HTML is authored externally (any visual tool) and pasted into Django Admin.

**Track B — Component tree (structured, Phase 2+ path)**
- `fetch_clientstatic()` payload drives rendering via cotton component templates.
- Used for pages requiring structured, client-editable, queryable content.

**Rendering priority in `ClientPageView`:**
```
1. PageContent for active language       → render raw HTML
2. PageContent for fallback language     → render raw HTML
3. Component tree from fetch_clientstatic → render via cotton templates
4. Neither found                          → Http404
```

### `serialize_model()` Utility
A reusable helper in `utils/common_functions.py` that serialises a model instance to a dict, automatically:
- Grouping modeltranslation fields into a `translations` nested dict (e.g. `{'name': {'en': ..., 'hi': ...}}`).
- Excluding virtual proxy fields and their per-language column variants.
- Resolving FK fields to their `_id` values.

### Key Model Relationships

```


Client (client_code, parent→self, language_list, theme_list)
  ├── Theme (theme_code, themepreset→ThemePreset, overrides JSON)
  ├── Page (page_code, parent→self, order)
  │     ├── PageContent (language_code, html)          ← Track A: raw HTML per language
  │     └── Layout (level 10/20/30/40, parent→self, slug, order)   ← Track B: component tree
  │           └── Component [OneToOne, level=40 only]
  │                 └── ComponentSlot (slot_type: figure|text, order)
  │                       └── ComptextBlock [GenericRelation]
  │                             └── TextstbItem [GenericRelation]
  │                                   └── SvgtextbadgeValue (language_code, stext, ltext)
  ├── NavItem (name[translatable], location, nav_type, page→Page[optional],
  │            url, order, open_in_new_tab, parent→self)
  │     └── NavItem children (same shape, one level deep)
  ├── ClientLocation (location_code, location_type)
  ├── ClientGroup (clientgroup_code, role, locations M2M)
  │     ├── ClientGroupPermission (module, action)
  │     └── ClientUserMembership (user→User)
  ├── ClientUserProfile (user→User [OneToOne])
  └── CustomerProfile (user→User [FK], unique_together user+client)
        └── CustomerAddress (street, city, zip, country, is_default)

ThemePreset (themepreset_code, colours, typography, spacing, radius, shadow)
GlobalValCat → GlobalVal (key, keyval — modeltranslation expands keyval_*)
```

---

## Request / Response Flow

```
HTTP Request
    ↓
SecurityMiddleware → SessionMiddleware → LocaleMiddleware → CommonMiddleware
    ↓
CsrfViewMiddleware → AuthenticationMiddleware
    ↓
CustomerProfileMiddleware          ← sets request.client, request.active_role,
    ↓                                 request.client_profile, request.customer_profile
MessageMiddleware → AccountMiddleware (allauth)
    ↓
View (e.g. ClientPageView)
    ↓
Context Processors run:
  • settings_constants             ← LANGUAGE_CODE
  • auth                           ← request.user
  • globalval                      ← gv / gvt (UI string lookup)
  • client_context                 ← client dict, theme tokens, page_dict
    ↓
Template renders (cotton components consume client/page/theme dicts)
```

---

## Infrastructure & Deployment

| Concern | Tool / Service |
|---------|---------------|
| PaaS hosting | Railway (primary) or Render (fallback) |
| Static files | WhiteNoise (served directly from Django) |
| Media files | PaaS volume mount (Phase 1) → S3 / Cloudflare R2 in Phase 2 |
| Environment config | `django-environ` or env vars directly |
| Background tasks | None in Phase 1. Celery + Redis deferred to Phase 2. |
| Cache (prod) | Redis (config present but commented out in settings) |

---

## Project Structure (Actual)

```
mydj/                            ← Django project root
  ├── settings/
  │   ├── base.py                ← shared settings
  │   ├── development.py         ← DEBUG=True, SQLite, debug-toolbar
  │   └── production.py          ← DEBUG=False, PostgreSQL, Redis, whitenoise
  ├── urls.py
  ├── templates/                 ← Global templates (base.html, landing.html, 404.html, 500.html)
  │   ├── cotton/                ← django-cotton component templates (hero, card, accordion, carousel)
  │   └── client/                ← coming_soon.html
  └── context_processors.py     ← settings_constants, globalval, client_context

mysite/                          ← Primary app
  ├── models.py                  ← All models (Client, Page, PageContent, Layout, Component,
  │                                 ComponentSlot, User profiles, Groups, Themes, GlobalVal,
  │                                 ThemePreset, text content tree)
  ├── views/
  │   ├── __init__.py            ← re-exports all views (urls.py imports unchanged)
  │   ├── main.py                ← ClientPageView, client_home, landing_page, set_theme,
  │   │                             custom_404, custom_500
  │   ├── auth.py                ← client_login, client_signup, client_logout
  │   └── customer.py            ← customer_onboarding, customer_profile, addresses
  ├── signals.py                 ← cache invalidation on post_save / post_delete; Guardian
  │                                 `ADMIN_ONLY_MODELS` permission sync (admin-role CRUD per
  │                                 model); outlier stale-flag + scheme_changed receivers
  ├── apps.py                    ← MysiteConfig, registers signals in ready()
  ├── adapters.py                ← ClientAwareAccountAdapter (allauth)
  ├── forms.py                   ← CustomerProfileForm, CustomerAddressForm
  └── middleware/
        └── customer_profile.py  ← CustomerProfileMiddleware (path-based client resolution)

utils/
  ├── common_functions.py        ← fetch_clientstatic(), build_client_payload(), serialize_model(),
  │                                 build_page(), build_layout(), build_component(), resolve_theme()
  └── globalval.py               ← get_globalval()

theme/                           ← django-tailwind theme app
```

---

## Known Issues / Constraints

1. **`models.py` is a single large file** — splitting into `models/` package is a natural next step before Phase 2.
2. **`django-browser-reload` is commented out** — re-enable for active frontend development.
3. **Datastar dropped** — no interactive JS library currently in use. HTMX evaluation pending for theme/language switcher.
4. **`DATA_UPLOAD_MAX_NUMBER_FIELDS = 5000`** — set to accommodate deep nested admin inlines. Monitor in production.
5. **`PageContent.html` is rendered unsanitised** — content is developer-authored only in Phase 1 so `|safe` is acceptable. If clients ever paste their own HTML in Phase 2, a sanitiser (e.g. `bleach`) must be added before the `|safe` filter.


## Phase 2 Additions — Catalogue Stack
 
### New Models (mysite/models/catalogue.py)
 
| Model | Purpose |
|-------|---------|
| `Taxonomy` | Hierarchy type (Category, Geography, etc.). Global or client-scoped. |
| `TaxonomyNode` | Tree node using materialized path (`path` CharField). |
| `Item` | Generic item (product, document, etc.). Global or client-scoped. |
| `ItemTaxonomyNode` | M2M: Item ↔ TaxonomyNode across any hierarchy. |
| `ItemImage` | Additional images per item. |
| `ItemVariant` | Optional variants (size, colour). Phase 3 eCommerce hook. |

  New models: GlobalItem, GlobalItemTaxonomyNode, GlobalItemAttributeValue,
              NodeAttributeType, NodeAttributeValue, ItemAttributeValue
  GS1 fields: gtin (GTIN-8/12/13/14), gpc_brick_code (8-digit)
  Derivation pattern: Item.global_item FK, resolved_name()/resolved_attributes() methods
  Attribute inheritance: NodeAttributeType → NodeAttributeValue → GlobalItemAttributeValue
                         → ItemAttributeValue (deepest wins)
                          
### Query Pattern — Catalogue vs clientstatic
 
| Data | Cached in clientstatic? | Reason |
|------|------------------------|--------|
| Taxonomy trees | Yes — separately (`taxonomy_tree:{client}:{slug}`) | Small, stable, reusable |
| Item list | No — queried per request | Filter-dependent, too large |
| Item detail | No — queried per request | Single record, indexed |
 
### HTMX Integration
- `django-htmx` middleware added to `MIDDLEWARE`
- Filter checkboxes: `hx-get` → `catalogue_filter` view → returns `items_list.html` partial
- Pagination: `hx-get` with `?page=N` → same partial
- `hx-target="#items-container"`, `hx-swap="innerHTML"`
- `hx-include="[name='node']:checked, [name='q']"` — includes all active filters
### Performance
- PostgreSQL JSONB GIN index on `Item.attributes` for attribute filtering
- `text_pattern_ops` B-tree index on `TaxonomyNode.path` for subtree queries
- Taxonomy trees cached in Redis (1 hour TTL, invalidated on node save)
- Items never cached in bulk — queried with `select_related` + `prefetch_related`
- Default pagination: 24 items/page (fits 3-col and 4-col grids)
### Key Model Relationships (updated)
 
```
Client
  ├── Taxonomy (slug, global or client-scoped)
  │     └── TaxonomyNode (materialized path, parent→self)
  ├── Item (item_code, status, attributes JSONB, global or client-scoped)
  │     ├── ItemTaxonomyNode → TaxonomyNode (M2M)
  │     ├── ItemImage (order, is_primary)
  │     └── ItemVariant (variant_code, price, stock, attributes)
  └── ... (existing models unchanged)

Item (base — id, name, description, status, image, order, client)
  ├── ProductItem    (price, currency, sku, weight_g, dimensions)  [OneToOne]
  ├── SongItem       (duration_s, bpm, key, artist, album)         [OneToOne]
  ├── DocumentItem   (page_count, format, file_url, version)       [OneToOne]
  └── attributes     (JSONField on Item — catches anything else)

```


## Phase 2 Completed — Catalogue Stack (Actual)

### Caching Strategy

| Cache key | Content | TTL | Invalidated by |
|-----------|---------|-----|---------------|
| `clientstatic:{client_code} - {lang}` | Full CMS payload | 1 hour | post_save on CMS models |
| `taxonomy_tree:{client}:{slug}` | Taxonomy node tree | 1 hour | post_save on TaxonomyNode |
| `catalogue_base_ids:{client}:{status}` | Base item ID set | 5 min | post_save on Item |
| `client_templates:{client_code}` | Template resolution dict | 1 hour | post_save on ClientTemplate |

### Admin Performance

- `list_select_related` on all ModelAdmin classes with FK to Client
- `raw_id_fields = ('client',)` on catalogue admin to prevent 207× Client query
- Inline `get_queryset()` overrides with `select_related` on FK chains
- `ClientTemplate` resolution cached (was 15ms per catalogue request)
- If Client is fully nested then 400 + queries
- Client admin broken down to sub sets using admin_proxies to reduce the query load
  - Client
  - ClientContentStructured - for Page > Layout
  - ClientContentHtml - for Page > Htmlblob
  - ClientTemplatewrapper - To call Client specific template blobs for catalogue > item_details, filters
  - ClientStaff - for user definitions

### Key Architectural Decisions Made

| Decision | Outcome |
|----------|---------|
| HTMX vs Datastar | HTMX adopted for catalogue filters and pagination |
| Brand in taxonomy vs model field | Brand removed from Item/GlobalItem — taxonomy only |
| GlobalItem media inheritance | `Item.inherit_global_media` flag + `resolved_medias()` model method |
| Client template customisation | `ClientTemplate` DB model + `render_client_template` template tag |
| Filter state preservation | `hx-push-url="true"` on filter interactions |
| Catalogue page caching | Base item IDs cached 5min; taxonomy trees cached 1hr |
| `I18nFallbackMixin` | Mixin on Item providing `resolve_i18n_field()` — 5-level priority |

### Models Added in Phase 2

```
GlobalItem → GlobalItemTaxonomyNode, GlobalItemAttributeValue, GlobalItemMedia
Taxonomy → TaxonomyNode → NodeAttributeType → NodeAttributeValue
Item → ItemTaxonomyNode, ItemAttributeValue, ItemMedia, ItemVariant
       → ProductItem, SongItem, DocumentItem, ServiceItem
ClientTemplate (client-specific template fragments stored in DB)
ClientBlock - Kill switch for any Client or all Clients for a specific period
ClientFeatureControl - Kill switch to disallow features like Catalogue, eCommerce
  > Middleware > Template
  > Signals.py catches any changes to ClientFeatureControl and kills cache
  > utils.py > feature_control
```

### utils > i18n.py > resolve_translated_value — resolve modelTranslation field values
```
1. Item.{field}_{active_lang}
2. Item.{field}_{client_base_lang}
3. Empty string
```
Applied to: `name`, `description`, `care_instructions` on `Item`.

### `ClientLanguageMixinV2` — More flexible language helper in admin screens
Applied in Admin where modelTranslation fields are required
BaseAdminInlinecss - to have single line collapse headers


Applied to: `name`, `description`, `care_instructions` on `Item`.

### `Item.resolved_medias()` — Media inheritance

When `Item.inherit_global_media=True` and `GlobalItem` is set:
- `ItemMedia` records always included
- `GlobalItemMedia` records appended for types not covered by ItemMedia
- `SimpleNamespace` wrapper makes GlobalItemMedia template-compatible
- Result sorted by `order`
- Prefetch paths: `medias` → `prefetched_medias`, `global_item__medias` → `prefetched_global_medias`
## Phase 3B — Demand Planning Stack
 
### New Python Packages
 
| Package | Version | Purpose |
|---------|---------|---------|
| `statsforecast` | latest stable (Nixtla) | Fast statistical forecasting — AutoETS, AutoARIMA, CrostonSBA, Theta. Handles thousands of SKUs efficiently via vectorised Numba backend |
| `hierarchicalforecast` | latest stable (Nixtla) | Hierarchical reconciliation — MinTrace (OLS/WLS), BottomUp, TopDown (AHP). Constructs and applies the summing matrix `S` |
| `polars` | latest stable | In-process DataFrame library for fast SKU × Customer × Month matrix construction and aggregation. Significantly faster than pandas for 10K SKU × 200 customer × 36 month tensors |
| `duckdb` | latest stable | In-process OLAP engine. Used inside Celery forecast tasks for fast hierarchical rollups from PostgreSQL tables without loading full tables into memory |
| `prophet` | latest stable (Meta) | Optional per-series model for series with strong seasonality + holidays; used when AutoETS/AutoARIMA underperform |
| `celery` | 5.x | Already in Phase 3A. Forecast jobs run as long-running Celery tasks |
| `redis` | latest | Already in Phase 3A. Celery broker |
| `djmoney` | not used in 3B | Revenue is stored as plain `DecimalField` on `ActualSale` / `ActualSaleLocation` (nullable) — no `MoneyField` |
| `openpyxl` | latest | Excel import/export for actuals upload and forecast download (planners live in Excel) |
| `pandas` | latest | Required by `statsforecast` and `hierarchicalforecast` internally; also used in import pipeline for CSV/Excel parsing |
 
### Demand Planning Model Package Layout

```
mysite/models/
    demand/
        __init__.py
        hierarchy.py         # PlanningLocation, PlanningCustomer, SalesNode,
                             #   SalesForecastLink, ZZCustomerSalesAssignment (deprecated)
        actuals.py           # ActualSale, ActualSaleLocation, ActualSaleImport,
                             #   ActualSaleOutlierAdjustment, ItemPlanningProfile
        schemes.py           # SalesScheme, SalesSchemeScope, SalesSchemePeriod,
                             #   ResolvedSalesSchemePeriod, SalesSchemeOccurrence
        lifecycle.py         # ItemSubstitution, ItemDiscontinuation, ItemIntroduction
        forecast.py          # ForecastVersion, ForecastLine, ForecastAggregate,
                             #   ForecastOverride, OverrideSplitWeight, ForecastAccuracy,
                             #   AbcClassDefinition, ForecastingConfig,
                             #   SeriesLevelEvaluation, SeriesProfile
```

`DistributionChannel` (code PK, label, is_active) lives in `mysite/models/global_config.py`, and
`Client.allowed_distribution_channels` / `ClientFeatureControl` in `mysite/models/client.py`.
 
### Key Model Relationships (Phase 3B)

```
Client
  ├── PlanningLocation (client, parent→self, materialized path)
  ├── PlanningCustomer (client, parent→self, materialized path)
  ├── SalesNode (client, name, level_label, parent→self)
  │     └── SalesForecastLink (planning_location, distribution_channel, planning_customer,
  │                            sales_node, valid_from, valid_to)
  │           shapes: loc+channel+customer / loc+channel / loc-only (nullable dims)
  ├── DistributionChannel (code '00'=Common, label, is_active)      [global_config.py]
  │     └── Client.allowed_distribution_channels (JSONField; NULL = channel-less client,
  │           everything defaults to '00'/Common — NOT "any channel allowed")
  ├── ActualSale (planning_location, item, planning_customer [nullable],
  │     distribution_channel [default '00'], period_type, period_start, qty, revenue [Decimal,
  │     nullable]; period_end auto-computed)
  │     └── ActualSaleOutlierAdjustment (OneToOne → ActualSale; qty_adjustment,
  │           revenue_adjustment, status CANDIDATE/CONFIRMED/REJECTED, detected_by, notes)
  ├── SalesScheme (client, scheme_code, status DRAFT/ACTIVE/ARCHIVED,
  │     expected_qty_uplift_pct, expected_value_uplift_pct [independent], discount_pct
  │     [metadata], shadow_periods [default 0 = off], pull_forward_pct [default 0.5])
  │     ├── SalesSchemeScope (scope_type OVERALL/TAXONOMY/BRAND/ITEM, taxonomy_node, item,
  │     │     planning_location / planning_customer / distribution_channel filters — nullable = all;
  │     │     BRAND = Brand node in ForecastingConfig.brand_taxonomy — the scheme's "vendor";
  │     │     membership = UNION of ItemTaxonomyNode mappings under the node, so one BRAND row
  │     │     covers items across many planning product groups; resolved tree-aware from the
  │     │     node's own taxonomy; within-scheme overlap deduped most-specific-wins
  │     │     ITEM > BRAND > TAXONOMY > OVERALL)
  │     ├── SalesSchemePeriod (period_type, period_start, period_end auto) — past buckets net
  │     │     history, future buckets re-add horizon uplift
  │     ├── ResolvedSalesSchemePeriod (scheme, item, planning_location, planning_customer,
  │     │     distribution_channel, period_type, period_start,
  │     │     WINDOW: qty_factor/value_factor = 1+uplift (netting divides);
  │     │     SHADOW: is_shadow, shadow_side, shadow_offset, anchor_period_start,
  │     │       anchor_qty_factor/anchor_value_factor (copies), addback_qty/value_weight
  │     │       (pf × side_share × decay^j, normalized) — netting adds back / horizon dips)
  │     │     ← materialized scheme→actuals coverage (resolve-on-change, join-at-read, same
  │     │       pattern as ResolvedVendorScheme); the query-time netting join target
  │     └── SalesSchemeOccurrence (period, actual_qty_uplift_pct, actual_value_uplift_pct,
  │           actual_pull_forward_pct, qty/value/pull-forward variance) — closed-scheme
  │           data-check + uplift & shadow estimation source
  ├── ItemSubstitution (client, old_item, new_item, conversion_factor, effective_from, notes)
  │       — Scenario 3: retired code → successor with unit conversion
  │       (new_qty = old_qty × factor, same factor on revenue; per-unit price preserved).
  │       unique (client, old_item); direct-mapping only (an item may not be both predecessor
  │       and successor). A re-key layer in the shared netting helper (after scheme+outlier),
  │       converting old rows when period_start < effective_from (exclusive cutoff) — nothing
  │       materialized; the retired old item's own forecast is nil on/after effective_from
  ├── ItemDiscontinuation (client, item, effective_from, notes)
  │       — Scenario 1: item withdrawn; forecast NIL on/after effective_from (NULL = nil
  │       immediately). unique (client, item). Forecast-output filter at write_forecast_lines;
  │       history kept for reporting/ABC/accuracy — no data mutation, no Item status change
  ├── ItemIntroduction (client, new_item, reference_item, ratio, copy_from, copy_to, notes)
  │       — Scenario 2: new item with no history borrows a reference item's statistical forecast
  │       × ratio, bounded by [copy_from, copy_to] (NULL bounds) and by enough own history
  │       (ForecastingConfig.min_history_periods); copy stops at the earlier. unique
  │       (client, new_item); reference not retired; borrowed lines tagged borrowed_from_item /
  │       borrowed_ratio. Forecast-output copy at write_forecast_lines
  │       ← one lifecycle directive per item: subject roles pairwise exclusive
  ├── ActualSaleLocation (planning_location, period_type, period_start, total_qty, total_revenue)
  ├── ActualSaleImport (import_batch on every ActualSale row; status, errors JSONField)
  └── ForecastVersion (version_label, period_type, base_period_end, horizon_periods,
        engine_config, status DRAFT→IN_REVIEW→APPROVED→LOCKED, run_status, stale_actuals,
        created_by, approved_by, copied_from)
        ├── ForecastLine (item, planning_customer [nullable], planning_location,
        │                 distribution_channel, period_type, period_start,
        │                 statistical_qty, override_qty, final_qty, forecast_level,
        │                 model_used, price_used,
        │                 scheme_id [nullable], scheme_qty, scheme_value [overlay],
        │                 borrowed_from_item [nullable FK — ItemIntroduction reference],
        │                 borrowed_ratio [nullable Decimal — copied lines only])
        ├── ForecastAggregate (agg_level, agg_key JSONField, period_start,
        │                      statistical_qty, override_qty, final_qty,
        │                      scheme_qty, total_scheme_value)
        ├── ForecastOverride (override_level, override_key JSONField, period_start,
        │                     override_qty, override_pct, override_note, created_by)
        │     └── OverrideSplitWeight (child_key, weight)
        ├── ForecastAccuracy (item, planning_customer, planning_location,
        │                     distribution_channel, period_start,
        │                     actual_qty, forecast_qty, mape, bias)
        ├── ForecastingConfig (mad_threshold, persistence_periods, min_history_periods,
        │     forecast_uses_net_actuals / reporting_uses_net_actuals /
        │     abc_classification_uses_net_actuals [default True],
        │     last_outlier_detection_run_at/by/range_start/range_end,
        │     scheme_net_actuals / scheme_apply_forecast_uplift [default True],
        │     brand_taxonomy [nullable slug: taxonomy carrying the Brand level — the scheme's
        │       "vendor"; prerequisite for BRAND scope],
        │     use_item_lifecycle [default True — apply all three lifecycle layers: re-key
        │       retired items' netted actuals to their successor, nil withdrawn items'
        │       forecast after their effective date, copy a reference item's forecast onto a
        │       newly introduced item until it has enough own history],
        │     last_scheme_detection_run_at/by/range_start/range_end)
        ├── SeriesProfile (grain encoding, model selection per series)
        └── SeriesLevelEvaluation (per-series evaluation record)
```
 
### Forecasting Engine Architecture

#### Celery Task: `run_forecast(version_id)`

```
mysite/tasks/demand/
  ├── run_forecast.py              # run_forecast(version_id), apply_overrides(version_id),
  │                                #   compute_accuracy(client_id)
  ├── import_actuals.py            # process_actuals_import(import_id),
  │                                #   process_summary_actuals_import(import_id)
  ├── detect_outliers.py           # run_outlier_detection(client_code, target_period_start,
  │                                #   target_period_end, triggered_by_user_id) — reads SCHEME-NETTED
  │                                #   series; flag_stale_forecast_versions(actual_sale_id)
  ├── detect_scheme_candidates.py  # detect_scheme_candidates(client_code, target_period_start,
  │                                #   target_period_end, triggered_by_user_id) — raw product-group
  │                                #   spike detection, implied-qty-uplift suggestion
  ├── resolve_scheme_scope.py      # resolve_scheme_scope(scheme_id) — materializes
  │                                #   ResolvedSalesSchemePeriod WINDOW + SHADOW rows on
  │                                #   scheme activation/edit
  ├── record_scheme_occurrences.py # record_scheme_occurrence(scheme_id, period_type,
  │                                #   period_start) — actual-vs-expected data-check incl.
  │                                #   actual pull-forward estimation
  ├── compute_series_profiles.py   # compute_series_profiles(client_id, period_type)
  └── notifications.py             # send_forecast_status_email (status-change digest)

utils/demand/
  ├── actuals_net.py               # actuals_queryset_with_net() — composed baseline netting,
  │                                #   SCHEME FIRST (WINDOW divide /, SHADOW add-back +,
  │                                #   correlated Subquery), THEN OUTLIER (−), THEN ITEM
  │                                #   SUBSTITUTION re-key (eff_item / scale by conversion_factor)
  ├── outlier_detection.py         # statistical candidate detection engine (MAD + persistence)
  ├── scheme_detection.py          # product-group spike detection + implied-uplift estimation
  ├── scheme_scope.py              # scope→item-set resolution (TAXONOMY subtree / ITEM / OVERALL)
  ├── compute_series_profiles.py   # grain-encoding + profile computation engine
  ├── forecast_engine.py           # statistical forecast engine (Polars + StatsForecast);
  │                                #   build_scheme_forecast_factors() for horizon uplift;
  │                                #   write_forecast_lines applies lifecycle output layers:
  │                                #   discontinuation nil (≥ effective_from) + introduction
  │                                #   borrow (reference × ratio, window + min_history bound)
  ├── hierarchy_utils.py           # hierarchy walk / summing-matrix helpers
  ├── location_access.py           # planner location scoping
  └── periods.py                   # period arithmetic (compute_period_end etc.)
```
1. Load actuals from PostgreSQL for client + base window. When
   `ForecastingConfig.forecast_uses_net_actuals` is enabled, the queryset is built via
   `actuals_queryset_with_net()` — a **composed** baseline helper that nets SCHEME impact first
   (WINDOW rows divide multiplicatively: `qty / (1+qty_uplift)`, `revenue / (1+value_uplift)`; SHADOW
   rows add back a weighted share of their anchor window's netted-out uplift via correlated Subquery,
   gated by `scheme_net_actuals`) and THEN subtracts CONFIRMED
   `ActualSaleOutlierAdjustment` adjustments; else raw qty/revenue columns.
   DuckDB is used in-process for fast OLAP rollups on the aggregates / accuracy paths.
   → Polars DataFrame (columns: unique_id, ds, y) where unique_id is the grain encoding
   (e.g. `item_loc_dc_cust`, `item_loc_dc`, `item_loc`, `item_salesnode_{node_id}`,
   `taxon_{node_id}_*`, `manual`) produced by `compute_series_profiles`.
2. Build hierarchy summing matrix S:
   Walk PlanningLocation tree, SalesNode tree, and the product TaxonomyNode tree
   (`product_planning` slug). Construct S as a numpy array (Nixtla HierarchicalForecast format).
3. Run StatsForecast:
   models from `engine_config.models` (default `["AutoETS", "AutoARIMA"]`; CrostonSBA used for
   intermittent series), `season_length` from config. Pick best model per series by
   cross-validation MAPE.
4. Run HierarchicalForecast reconciliation:
   hrec = HierarchicalReconciliation(reconcilers=[MinTrace(method='ols')]) — method from
   `engine_config.reconciliation` (BottomUp / MinTrace_ols / MinTrace_wls_struct).
5. Write ForecastLine records (bulk_create, batch 5000), one per evaluated grain; each row
   carries `forecast_level` + `model_used` (suppressed by `store_all_level_forecasts=false`).
6. Write ForecastAggregate records for each agg_level.
7. Update ForecastVersion.run_status through QUEUED → PROFILING → RUNNING → RECONCILING →
   AGGREGATING → COMPLETE (or FAILED with run_error traceback); version workflow status is
   unchanged (DRAFT until a planner submits for review).
8. Notify requesting user via `send_forecast_status_email`.

#### Celery Task: `apply_overrides(version_id)`

```
1. Load all ForecastOverride records for the version
2. Resolve each override's subtree (override_key) to leaf ForecastLine records
3. Determine disaggregation method (PROPORTIONAL / EQUAL / CUSTOM)
4. For PROPORTIONAL: compute shares from the net actuals query helper for the same period last year
5. Update ForecastLine.override_qty for each leaf (final_qty = override_qty when set)
6. Recompute ForecastAggregate roll-ups for affected keys
7. If subtree < 500 leaves: run synchronously; else submit as Celery task
```

#### Celery Task: `compute_accuracy(client_id)` — nightly

```
1. Load APPROVED/LOCKED ForecastVersion records for the client
2. Load net ActualSale (via actuals_queryset_with_net) for each version's horizon window
3. Join on (item, planning_customer, planning_location, distribution_channel, period_start)
4. Compute MAPE, Bias, WMAPE per leaf and per aggregate level
5. Write ForecastAccuracy records
```

### Data Import Pipeline

**CSV / Excel upload** (monthly actuals):
- `ActualSaleImport` job created on upload (HTMX form at `actuals_upload`; overlaps with CONFIRMED adjustments require explicit confirmation via `actuals_upload_overlap` guard)
- Celery task `process_actuals_import(import_id)`:
  - Reads file with `pandas.read_excel` / `pandas.read_csv`
  - Validates: item exists, planning_location exists, planning_customer exists, distribution_channel exists, period valid
  - Bulk upsert (`ON CONFLICT DO UPDATE`) on `ActualSale` natural key (idempotent)
  - Writes errors to `ActualSaleImport.error_log`
  - Updates status: `pending → processing → done / failed`

run_outlier_detection(client_code, target_period_start, target_period_end, triggered_by_user_id=None)
  Triggered by: planner submission of the Outlier Detection range form (HTMX), NOT import completion
  1. Load ForecastingConfig for client (lazily create with system defaults if absent)
  2. Pull ActualSale rows for the client within [target_period_start, target_period_end]
  3. Apply SCHEME-NETTING first (scheme_net_actuals) via the shared composed helper
     (scheme_netted_queryset — reads r.scheme_net_qty, which DIVIDES window rows by 1+uplift and
     ADDS BACK shadow shares): detection must run on scheme-netted series so scheme spikes AND
     pre/post dips are never proposed as outliers and the median/MAD baseline is scheme-free
  4. Apply ITEM SUBSTITUTION re-key (use_item_lifecycle) — the successor's series includes the
     retired code's netted history (converted by conversion_factor, period_start < effective_from),
     and retired items themselves are SKIPPED (their history is owned by the successor); discontinued
     items are NOT skipped (their history is their own and still feeds reporting/ABC/accuracy)
  5. Run residual-based detection (MAD threshold) per series using config.mad_threshold
  6. Skip series with fewer than config.min_history_periods periods of history
  7. Distinguish transient spike vs sustained level shift using config.persistence_periods
  8. bulk_create ActualSaleOutlierAdjustment rows (status='CANDIDATE', detected_by='SYSTEM'),
     one per flagged ActualSale row (OneToOneField — skip rows that already have an adjustment;
     a row with any adjustment is never re-proposed, so re-running is idempotent);
     suggested qty/revenue adjustments are computed against the SCHEME-NETTED values
  9. Notify planner(s) of new candidates via Django message / email digest
  10. Record last_outlier_detection_run_at/by/range_start/range_end on ForecastingConfig

flag_stale_forecast_versions(actual_sale_id)
  Triggered by: post-save on ActualSaleOutlierAdjustment status changes; ALSO called for each
  covered period when a SalesScheme is activated/edited (scheme changes move the baseline)
  1. Find DRAFT ForecastVersions whose base_period_end / horizon window covers the
     actual_sale's period_start
  2. Mark them with a `stale_actuals=True` flag (does not auto-rerun; surfaced in the HTMX
     UI as "actuals changed since this draft was generated — rerun recommended")

resolve_scheme_scope(scheme_id)
  Triggered by: post-save on SalesScheme when status becomes ACTIVE (and on scope/period edits)
  1. Bail unless status == ACTIVE
  2. For each SalesSchemeScope resolve the item set — tree-aware, from the node's OWN taxonomy:
     OVERALL → all client items; TAXONOMY → _scheme_scope_item_ids subtree (UNION of
     ItemTaxonomyNode mappings beneath the node within its own taxonomy tree — covers planning
     product groups exactly as before); BRAND → same union resolver on the brand node
     (validated to sit in ForecastingConfig.brand_taxonomy); ITEM → the single item. The
     planning-grain helper _taxon_node_item_ids is NOT reused here (primary-mapping-only, would
     return zero items for a brand node)
  3. Within-scheme dedup most-specific-wins (ITEM > BRAND > TAXONOMY > OVERALL) per item so a
     BRAND row + TAXONOMY row overlapping the same item apply one factor, not two
  4. Cross item-set × SalesSchemePeriod × scope dims → WINDOW ResolvedSalesSchemePeriod rows with
     qty_factor = 1 + expected_qty_uplift_pct, value_factor = 1 + expected_value_uplift_pct
  5. If shadow_periods > 0, additionally build 2 × shadow_periods SHADOW rows per window
     (is_shadow=True, shadow_side, shadow_offset, anchor_period_start, copies of the window's
     factors, addback weight = pull_forward_pct × side_share × decay^j normalized); leave
     qty_factor/value_factor NULL on shadow rows
  5. transaction.atomic(): delete + bulk_create the scheme's resolved rows
  6. Detect overlap (>1 ACTIVE scheme with a WINDOW row covering the same grain+period) — log
     warning, deterministic most-specific-wins (ITEM > TAXONOMY > OVERALL). A grain+period being a
     window for one scheme and a shadow for another is expected and composes additively

detect_scheme_candidates(client_code, target_period_start, target_period_end, triggered_by_user_id=None)
  Triggered by: planner submission of the Scheme Detection range form (HTMX), before outlier detection
  1. Aggregate RAW actuals to the product-group (TAXON_*) grain for the window + lookback
  2. Run MAD + persistence spike detection per series; skip periods already covered by an ACTIVE
     scheme (window OR shadow row)
  3. Suggest expected_qty_uplift_pct = period_demand / median(neighbouring periods) − 1
  4. Record DRAFT candidates → scheme review queue (never auto-activate)
  5. Record last_scheme_detection_run_at/by/range_start/range_end on ForecastingConfig

**Summary-level upload** (location × period totals):
- Same pipeline writes to `ActualSaleLocation`
- Used as cross-check against item-level rollups; discrepancy > 5% flagged
### Database Indexes (Phase 3B)
 
Add via `RunSQL` in migration:
 
```sql
-- ActualSale period-filtered lookups (migration 0048)
CREATE INDEX ix_actualsale_loc_period     ON mysite_actualsale (client_id, planning_location_id, period_type, period_start);
CREATE INDEX ix_actualsale_item_period    ON mysite_actualsale (client_id, item_id, period_type, period_start);
CREATE INDEX ix_actualsale_cust_period    ON mysite_actualsale (client_id, planning_customer_id, period_type, period_start);
CREATE INDEX ix_actualsale_period_range   ON mysite_actualsale (client_id, period_type, period_start, period_end);

-- ActualSale natural-grain engine lookups (migration 0063)
CREATE INDEX ix_actualsale_grain_lookup   ON mysite_actualsale (client_id, planning_location_id, distribution_channel_id, planning_customer_id, period_type, period_start);

-- ActualSaleLocation (migration 0054)
CREATE INDEX ix_actualsaleloc_period      ON mysite_actualsalelocation (client_id, planning_location_id, period_type, period_start);

-- SalesForecastLink lookups (migrations 0065 / 0066)
CREATE INDEX ix_sfl_client_loc            ON mysite_salesforecastlink (client_id, planning_location_id);
CREATE INDEX ix_sfl_loc_from              ON mysite_salesforecastlink (client_id, planning_location_id, valid_from);

-- Outlier candidate queue lookups (status filter is the hot path for the review queue, migration 0066)
CREATE INDEX ix_outlieradj_status         ON mysite_actualsaleoutlieradjustment (status);

-- Resolved scheme coverage lookups (scheme netting subqueries + horizon factor build)
CREATE INDEX ix_resolvedschemepen_grain   ON mysite_resolvedsaleschemperiod (item_id, planning_location_id, distribution_channel_id, planning_customer_id, period_start, period_type);
CREATE INDEX ix_resolvedschemepen_scheme  ON mysite_resolvedsaleschemperiod (scheme_id, period_start);
CREATE INDEX ix_resolvedschemepen_shadow  ON mysite_resolvedsaleschemperiod (is_shadow, period_type, period_start);

-- Item lifecycle lookups (substitution subquery + output-layer reads at line-write time)
CREATE INDEX ix_itemsubst_old            ON mysite_itemsubstitution (client_id, old_item_id);
CREATE INDEX ix_itemsubst_new            ON mysite_itemsubstitution (client_id, new_item_id);
CREATE INDEX ix_itemdisc_item            ON mysite_itemdiscontinuation (client_id, item_id);
CREATE INDEX ix_itemintro_new            ON mysite_itemintroduction (client_id, new_item_id);
CREATE INDEX ix_itemintro_ref            ON mysite_itemintroduction (client_id, reference_item_id);
```

Hierarchy nodes (PlanningLocation / PlanningCustomer / SalesNode) use the `MaterializedPathMixin` pattern (materialized `path` + text_pattern_ops B-tree) inherited from Phase 2's `TaxonomyNode`.
 
### Frontend (Phase 3B)

The demand planning UI is **Django Templates + Tailwind + HTMX**, served under `/{client_code}/planning/` via the `mysite/demand_ui/` app — the same stack as Phase 1/2/3A. It is **not** a React SPA. Planners drive the workflow through server-rendered pages whose interactive parts (filters, run progress, outlier confirm/reject/revise/undo, bulk discard, overlap confirmations) are HTMX fragments returned as partials. A **DRF JSON API** (`mysite/api/demand/`) coexists for programmatic access (hierarchy trees, actuals queries, forecast version CRUD/run/approve) — see the endpoint table below.

**Key UI views (`mysite/demand_ui/views.py`, templates under `templates/demand/`):**
1. **Actuals Dashboard** — actuals list + aggregates, filter bar with an `exclude_outliers` toggle (net vs raw).
2. **Actuals Upload** — HTMX form + polling upload status; overlap-with-CONFIRMED-adjustments guard requires explicit confirmation.
3. **Outlier Queue** — filterable by CANDIDATE / CONFIRMED / REJECTED; confirm / reject / revise / undo per row; bulk discard of selected or all candidates; out-of-band update of the nav-badge candidate count.
4. **Outlier Detection** — range-picker form (`_detection_form.html`) that triggers `run_outlier_detection` and shows the triggered result (`_detection_triggered.html`); decisions report view.
5. **Scheme Management** — scheme list / registration form (scope lines incl. a **BRAND picker**
   populated from `ForecastingConfig.brand_taxonomy` — the scheme's vendor — gated off with a
   "set up brand taxonomy" message when unconfigured; periods, uplift inputs plus
   shadow inputs `shadow_periods` / `pull_forward_pct`; pre-fills value uplift from discount as a
   default), system-proposed candidate review queue with approve/activate (materializes resolved
   window + shadow rows + re-triggers outlier detection on the covered range), occurrence data-check
   report (actual vs expected uplift, incl. actual pull-forward). Mirrors the outlier queue; gated on
   `scheme_ui_visible`.
6. **Forecast Run** — create a version, trigger run, poll `run_status` via HTMX partials.
7. **Item Lifecycle** — three event sections: **Item Substitutions** (retired-code → successor
   mapping, old_item, new_item, `conversion_factor`, `effective_from`, notes — the successor's series
   transparently includes the retired code's converted netted history via the composed helper),
   **Item Discontinuations** (item, `effective_from` — forecast nil on/after the date), and
   **Item Introductions** (new_item, reference_item, `ratio`, `copy_from`, `copy_to` — new item
   borrows the reference's forecast until it has enough own history). All three gated on
   `item_lifecycle_ui_visible`.
8. **Consensus Override Grid** — version lines grid with override value/qty/% editors, custom split weights, affected-lines preview, propagation status.
9. **Version detail / accuracy** — lines, aggregates, accuracy by category/location/period/item, xlsx export. Forecast lines display both baseline and scheme overlay (`scheme_qty`/`scheme_value`) and the borrowed-line attribution (`borrowed_from_item`/`borrowed_ratio`).

**Django Admin (Phase 3B):** new `mysite/admin/demand_schemes.py` module (mirrors
`demand_forecast.py`): `SalesSchemeAdmin(ClientScopedMixin)` with scope/period/occurrence inlines,
read-only `ResolvedSalesSchemePeriodAdmin` (WINDOW/SHADOW row-kind badge), scheme flags in
`ForecastingConfigAdmin`, scheme columns in `ForecastLineAdmin`/`ForecastAggregateAdmin`; registered in
`mysite/admin/__init__.py`. New `mysite/admin/demand_lifecycle.py` with
`ItemSubstitutionAdmin(ClientScopedMixin)` (old_item → new_item, conversion_factor, effective_from),
`ItemDiscontinuationAdmin(ClientScopedMixin)` (item, effective_from), and
`ItemIntroductionAdmin(ClientScopedMixin)` (new_item, reference_item, ratio, copy_from, copy_to);
`use_item_lifecycle` in the `ForecastingConfigAdmin` fieldset. Module-level access is gated by the
Guardian `ADMIN_ONLY_MODELS` permission sync in `mysite/signals.py` (scheme + lifecycle models
registered → admin-role CRUD on migrate); per-client rows are scoped by `ClientScopedMixin`/
`_user_has_admin_role`. HTMX scheme views are feature-gated on `scheme_ui_visible` and reuse the same
admin-role check as the outlier queue; the three lifecycle list/forms are gated on
`item_lifecycle_ui_visible`.

### REST API Endpoints (Phase 3B, under `mysite/api/demand/`)

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/location-hierarchy/` | GET | PlanningLocation tree for client |
| `/sales-hierarchy/` | GET | SalesNode tree for client |
| `/sales-forecast-links/` | GET, POST | List / create SalesForecastLink |
| `/sales-forecast-links/{id}/` | GET, DELETE | Detail / delete link |
| `/actuals/upload/` | POST | Multipart file upload; creates `ActualSaleImport` job |
| `/actuals/upload/{id}/` | GET | Poll import job status |
| `/actuals/` | GET | Filtered actuals query (item, planning_location, planning_customer, distribution_channel, period range) |
| `/actuals/template/` | GET | Download upload template xlsx |
| `/forecast-versions/` | GET, POST | List versions; create + trigger run |
| `/forecast-versions/{id}/` | GET | Version detail + status |
| `/forecast-versions/{id}/lines/` | GET | Leaf-level lines (paginated, filterable) |
| `/forecast-versions/{id}/aggregates/` | GET | Roll-up data by agg_level |
| `/forecast-versions/{id}/overrides/` | GET, POST | List / create overrides |
| `/forecast-versions/{id}/overrides/{oid}/` | GET, DELETE | Override detail / delete |
| `/forecast-versions/{id}/overrides/{oid}/affected-lines/` | GET | Which lines an override touched |
| `/forecast-versions/{id}/overrides/{oid}/split-weights/` | GET, POST | Custom split weights |
| `/forecast-versions/{id}/run/` | POST | Trigger forecast run |
| `/forecast-versions/{id}/run-status/` | GET | Poll run progress |
| `/forecast-versions/{id}/approve/` | POST | Transition status to APPROVED |
| `/forecast-versions/{id}/export/` | GET | xlsx export |
| `/forecast-versions/{id}/accuracy/` | GET | Accuracy metrics for version |
| `/series-profiles/`, `/series-profiles/{id}/`, `/series-profiles/{id}/evaluations/` | GET | Series profile / evaluation read APIs |
| `/forecasting-config/` | GET | ForecastingConfig (net-usage flags, thresholds, last detection run) |

Outlier interactions (confirm / reject / revise / undo / bulk discard / detection trigger) are **HTMX-only** via `mysite/demand_ui/` routes (`outlier_queue`, `outlier_confirm`, `outlier_reject`, `outlier_revise`, `outlier_undo_decision`, `outlier_bulk_delete`, `outlier_detection_form`, `trigger_outlier_detection`, `outlier_decisions_report`) — there are no `/api/demand/outliers/` REST endpoints.

Scheme interactions (registration, candidate review, activate, occurrence report) are likewise **HTMX-only** via `mysite/demand_ui/` routes under `/schemes/` — there are no `/api/demand/schemes/` REST endpoints.

### Caching (Phase 3B additions)

The demand module reads directly from PostgreSQL — no dedicated cache keys are implemented. Hierarchy
trees are resolved via the `MaterializedPathMixin` path columns (`path LIKE 'x/%'` subtree queries);
aggregates are pre-computed `ForecastAggregate` rows rather than cached roll-ups. (A `sales_hierarchy`
/ `location_hierarchy` / `forecast_aggregates` cache layer was considered in the plan but not built.)

### `ClientFeatureControl` Keys Added (Phase 3B)

`demand_planning`, `actuals_upload`, `outlier_management`, `scheme_management`, `item_lifecycle`, `forecast_run`, `consensus_override`, `forecast_approval`.

`Client.allowed_distribution_channels` (JSONField, default NULL) sits alongside: `NULL` means a
channel-less client whose every `ActualSale`/`ForecastLine` defaults to `'00'` (Common) — it does **not**
mean "any channel allowed". The helpers `is_distribution_channel_enabled()` and
`get_allowed_distribution_channel_codes()` on `Client` drive the drop-downs and the `'00'` default.

## Phase 3C — Inventory Decision Engine Stack

### New Python Packages

| Package | Version | Purpose |
|---------|---------|---------|
| `darts` | latest stable | Additional forecasting backend for TSB (Teunter-Syntetos-Babai) intermittent-demand models not in `statsforecast`; used alongside existing Croston/SBA from Phase 3B |
| `statsforecast` | already in 3B | Reused — Croston/SBA already wired for intermittent series |
| `numpy` | already present (transitive) | Explicit dependency — summing-matrix and netting arithmetic in `utils/ide/` |
| `pandas` | already in 3B | Reused for netting-matrix construction and vendor-slab evaluation |
| `polars` | already in 3B | Reused — DuckDB → Polars pull pattern for large item×node matrices |
| `duckdb` | already in 3B | Reused — in-process OLAP for propagation/netting joins over PostgreSQL tables |
| `celery` / `redis` | already present | Reused — netting runs, recommendation generation, materialization jobs |

**No new frontend framework.** The IDE frontend is **Django Templates + Tailwind + DaisyUI + HTMX** —
same stack as Phase 1/2/3A/3B. This is deliberate: planner workbenches are exception-review UIs
(filtered tables, drill-down, approve/reject actions), which fit the server-rendered + HTMX pattern
better than a data-grid SPA. If a future workbench needs AG-Grid-style bulk editing at scale, revisit
per-workbench rather than defaulting the whole module to
SPA.

---

### Inventory Decision Engine Model Package Layout

```
mysite/models/
    ide/
        __init__.py
        classification.py    # (re-exports AbcClassDefinition / SEIL classifier from demand/)
        policy.py             # PolicyMatrix, ReviewPolicy, ReplenishmentPolicy, CoveragePolicy,
                              #   StockingPolicy, TransferPolicy, ServiceLevelPolicy
        supply_network.py     # SupplyNetworkRule, ResolvedSupplySource
        forecast_stage.py     # ForecastNormalizationFactor, ForecastReconciliationException
                              #   (extends demand/forecast.py's ForecastVersion with stage field)
        propagation.py        # NodeReplenishmentRequirement
        ingestion.py           # SupplyPositionSnapshot, StockOnHand, OpenSupply, OpenDemandCommitment
        inventory_position.py # InventoryPosition, DDMRP buffer zone fields
        vendor_scheme.py      # InventoryCarryingCostRate, ExcessInventoryPenaltyTier,
                              #   VendorScheme, VendorSchemeScope, VendorSchemeSlab,
                              #   ResolvedVendorScheme, VendorRebateAccrual
        recommendation.py     # ReplenishmentRecommendation, PlannerDecision
```

---

### Key Model Relationships (Phase 3C)

```
Client
  ├── ItemPlanningProfile (item, is_active_for_ide, ...)   ← filters the expected-feed manifest
  ├── PolicyMatrix (client, abc_class, demand_pattern_class)   ← 12 cells (reuses 3B's AbcClassDefinition
  │     ├── review_policy → ReviewPolicy                          + SEIL classifier as axes)
  │     ├── replenishment_policy → ReplenishmentPolicy
  │     ├── coverage_policy → CoveragePolicy
  │     ├── stocking_policy → StockingPolicy
  │     ├── transfer_policy → TransferPolicy
  │     ├── service_level_policy → ServiceLevelPolicy
  │     ├── forecast_trust_pct
  │     └── planner_approval_rule
  │
  ├── ForecastVersion (existing, Phase 3B)
  │     └── stage field added: SALES_CONSENSUS | OPERATING_PLAN
  ├── ForecastNormalizationFactor (version, anchor_node, factor, set_by, is_manual_override)
  ├── ForecastReconciliationException (item, node, forecast_version, computed_net_demand, status)
  │
  ├── SupplyNetworkRule (client, scope_type ITEM/TAXONOMY/ALL, taxonomy_node/item, location,
  │     valid_from, valid_to, source_type VENDOR/DC/LOCATION/HO, source_ref, allocation_pct)
  │     └── ResolvedSupplySource (item, location, effective_date, source_type, source_node/vendor,
  │           allocation_pct, resolved_rule FK)   ← materialized cache, never resolved at run time
  │
  ├── NodeReplenishmentRequirement (item, node, date, source_leg, quantity)
  │     ← output of demand propagation; sole input to buffer sizing / netting / PO-vs-transfer decision
  │
  ├── SupplyPositionSnapshot (client, snapshot_id UUID, as_of_datetime, received_at, source_system,
  │     status RECEIVED/VALIDATED/APPLIED/REJECTED, is_full_snapshot, supersedes self-FK)
  │     ├── StockOnHand (snapshot, item, node, qty_unrestricted, qty_blocked, qty_in_transit_to_node)
  │     ├── OpenSupply (snapshot, supply_type PO/STO/WO, external_doc_number, external_line_number,
  │     │     item, receiving_node, source_node, vendor, order_qty, received_qty, open_qty,
  │     │     expected_receipt_date, order_status)
  │     └── OpenDemandCommitment (snapshot, item, node, committed_qty, required_date, external_doc_number)
  │
  ├── InventoryPosition (item, node, date, on_hand, in_transit, net_requirement, min, max, rop,
  │     ddmrp_red, ddmrp_yellow, ddmrp_green, projected_inventory)
  │
  ├── InventoryCarryingCostRate (client, abc_class, demand_pattern_class, annual_carrying_cost_pct,
  │     valid_from, valid_to)
  │     └── ExcessInventoryPenaltyTier (client, abc_class, demand_pattern_class, age_bucket_from_days,
  │           age_bucket_to_days, additional_annual_pct, valid_from, valid_to)
  │
  ├── VendorScheme (client, vendor, scheme_code, category TRANSACTIONAL/REBATE,
  │     scheme_type QTY_SLAB/VALUE_SLAB/FLAT_PCT/CUMULATIVE_REBATE, computation_basis, valid_from,
  │     valid_to, status)
  │     ├── VendorSchemeScope (scheme, scope_type OVERALL/TAXONOMY/ITEM, taxonomy_node, item)
  │     │     └── VendorSchemeSlab (scope, slab_from, slab_to, discount_pct, discount_amount_per_unit)
  │     └── VendorRebateAccrual (scheme, vendor, period_start, period_end, cumulative_value_to_date,
  │           cumulative_qty_to_date, estimated_effective_discount_pct, actual_settled_discount_pct,
  │           settled_at)
  ├── ResolvedVendorScheme (materialized, same generic→specific pattern as ResolvedSupplySource)
  │
  └── ReplenishmentRecommendation (item, node, rec_type PURCHASE/TRANSFER/STOCKING/CENTRALIZATION/
        EMERGENCY/ALTERNATIVE_SUPPLY, recommended_qty, policy_cell FK, inputs JSONField,
        formula_used, trigger_reason, alternatives JSONField, expected_outcome JSONField, status)
        └── PlannerDecision (recommendation, decided_by, decision APPROVE/REJECT/MODIFY,
              modified_qty, decided_at, note)
```

---

### Forecast Consumption Rule (hard constraint)

The IDE **never reads `SALES_CONSENSUS` forecasts or raw `SupplyNetworkRule` rows directly**. It only
ever touches:
- `OPERATING_PLAN` forecast lines, and
- the materialized `ResolvedSupplySource` / `NodeReplenishmentRequirement` tables.

Enforce this at the query-layer boundary (`utils/ide/` functions accept a version already filtered to
`stage='OPERATING_PLAN'`; there is no code path that accepts a raw `SupplyNetworkRule` queryset).

---

### Supply Network Rule Resolution

Reuses the Phase 2 taxonomy materialized-path pattern (same mechanism as the dynamic taxonomy filter
injection built for the catalogue):

1. `scope_type = ITEM` — exact item + location match wins.
2. `scope_type = TAXONOMY` — walk the item's taxonomy path from its own node to root; deepest matching
   ancestor for that location wins.
3. `scope_type = ALL` — location-wide default.
4. No match at any level → **hard validation error**, never a silent fallback.

All legs of a split-sourcing resolution must come from the same scope level (never mix an ITEM-level
leg with a TAXONOMY-level leg in one resolution). `Σ allocation_pct` across legs must equal 100% —
validated on save **and** via a periodic integrity job (a rule's `valid_to` lapsing can silently break
a previously-valid split without any row being edited).

Resolution is **never computed at run time** — materialized nightly (or on rule change) into
`ResolvedSupplySource`, one row per allocation leg, carrying an FK back to the originating
`SupplyNetworkRule` for audit.

---

### Demand Propagation Algorithm

```
NetOwnDemand(N) = FCST(N) − Σ [ FCST(C) × alloc_pct(C → X)
                                  for C in sales_children(N)
                                  for X in resolved_sources(C)
                                  where X != N ]

For each resolved source X of N:
    RR(N, via X) = ( NetOwnDemand(N)
                    + Σ [ RR(C, via N) for C in sales_children(N) where N ∈ resolved_sources(C) ] )
                    × allocation_pct(N → X)
```

Generalizes to arbitrary depth and arbitrary bypass patterns; does not assume the sales hierarchy and
supply network are congruent below the point of divergence.

**Conservation invariant** (regression test run after every engine change):
`Σ RR at every vendor-facing leg == Σ FCST (OPERATING_PLAN) at every end node`. A violation indicates a
resolution bug, not a data anomaly — never silently tolerated.

---

### MRP-Style Netting

```
Net Requirement(item, node, date) = Gross Requirement(item, node, date)   ← from NodeReplenishmentRequirement
                                   − On Hand Available (qty_unrestricted)
                                   − Scheduled Receipts (Open PO + Open STO due before/at date)
                                   + Committed Demand not yet reflected in Gross Requirement (open SO)
```

**Ingestion contract:** bulk-ingest per entity type (or one composite payload) via DRF endpoints.
Validate structurally at ingestion (item/node codes resolve, quantities non-negative, dates
parseable) and **reject the whole snapshot on failure** — never partially apply. A Celery task
materializes a `VALIDATED` snapshot into a denormalized item×node netting-ready structure; the
netting run never queries raw ingestion tables directly.

**Reducing data load** (apply in this priority order):
1. **Time fencing** — full on-hand/open-supply detail only needed within `lead_time + review_period +
   safety_margin`; beyond that, an aggregated "total qty due after fence date" per item-node suffices.
2. **Delta/CDC feed** — v2 optimization; persist last-applied position, client sends only changes since
   last successful snapshot plus a periodic full reconciliation snapshot.
3. **Sparse transmission** — omit item-node rows with zero on-hand and no open supply.
4. **Frequency tiering by ABC/demand-pattern class** — A-class feeds daily; C-class can run 3–7 day
   cycles.
5. **Filter the expected-feed manifest** by active `ItemPlanningProfile` — never request position data
   for inactive/discontinued/non-stocked item-node combinations.

---

### Vendor Scheme & Order-Quantity Breakpoint Evaluation

Order quantity is evaluated **after** MRP netting produces `base_qty`, at each vendor slab breakpoint
above it:

```
For each slab breakpoint B > base_qty (ascending):
    excess_qty = B − base_qty
    expected_holding_days = excess_qty / periodic_consumption_rate(item, node)   # from OPERATING_PLAN FCST
    daily_carrying_cost = item_value × (carrying_pct + excess_penalty_pct) / 365
    incremental_carrying_cost = excess_qty × daily_carrying_cost × expected_holding_days / 2
    discount_saving = (base_unit_cost − unit_cost_at(B)) × B
    net_benefit(B) = discount_saving − incremental_carrying_cost

Choose qty = argmax over {base_qty, all breakpoints} of net_benefit; default to base_qty if all <= 0
```

`estimated_effective_discount_pct` (rebate, computed as the **median** — not mean — of the last 3–4
settled periods' `actual_settled_discount_pct`) is applied as a further flat reduction to
`unit_cost_at(B)` uniformly across candidates; it changes landed cost, not the shape of the trade-off,
and never by itself triggers bulk-ordering to chase a threshold.

**Guardrails:** cap `expected_holding_days` at item max shelf-life or a configurable ceiling. Treat
MOQ, warehouse capacity, and cash/budget ceiling as **filters on the candidate breakpoint set**, never
as inputs to the cost formula. Log `discount_saving`, `incremental_carrying_cost`, and `net_benefit`
per order line on the `ReplenishmentRecommendation` — planners need this visible before trusting an
engine-driven quantity bump.

---

### Explainability Contract

Every `ReplenishmentRecommendation` row persists, at write time (not reconstructed later):
`inputs` (JSONField — the actual values consumed), `policy_cell` (FK to the `PolicyMatrix` cell that
fired), `formula_used` (identifies which formula path executed — e.g. `ROP`, `DDMRP`,
`ORDER_UP_TO_COVERAGE`), `trigger_reason`, `alternatives` (JSONField — other candidate options
considered and why they lost), `expected_outcome` (JSONField).

---

### Database Indexes (Phase 3C)

```sql
-- Supply network resolution cache lookups
CREATE INDEX ix_resolvedsupplysource_item_location
    ON mysite_resolvedsupplysource (item_id, location_id, effective_date);

-- Replenishment requirement lookups by node/date
CREATE INDEX ix_nodereplenishmentrequirement_node_date
    ON mysite_nodereplenishmentrequirement (node_id, item_id, date);

-- Snapshot-scoped netting inputs
CREATE INDEX ix_stockonhand_snapshot_item_node
    ON mysite_stockonhand (snapshot_id, item_id, node_id);

CREATE INDEX ix_opensupply_snapshot_item_node
    ON mysite_opensupply (snapshot_id, item_id, receiving_node_id, expected_receipt_date);

-- Recommendation queue for planner workbenches
CREATE INDEX ix_replenishmentrecommendation_status_client
    ON mysite_replenishmentrecommendation (client_id, status, rec_type);

-- Vendor scheme resolution
CREATE INDEX ix_resolvedvendorscheme_item_vendor
    ON mysite_resolvedvendorscheme (item_id, vendor_id, effective_date);
```

---

### REST API Endpoints (Phase 3C, under `mysite/api/ide/`)

| Endpoint | Method | Notes |
|----------|--------|-------|
| `/supply-network-rules/` | GET, POST | CRUD on `SupplyNetworkRule`; triggers re-resolution on save |
| `/resolved-supply-source/` | GET | Read-only materialized cache, filterable by item/location |
| `/forecast-versions/{id}/operating-plan/` | GET, POST | Apply `ForecastNormalizationFactor`; cascade |
| `/reconciliation-exceptions/` | GET | `ForecastReconciliationException` queue |
| `/policy-matrix/` | GET, POST | CRUD on 12-cell `PolicyMatrix` per client |
| `/snapshots/` | POST | Bulk ingest `SupplyPositionSnapshot` + child entities (composite payload) |
| `/snapshots/{id}/` | GET | Poll snapshot status (RECEIVED → VALIDATED → APPLIED/REJECTED) |
| `/inventory-position/` | GET | Filtered `InventoryPosition` query (item, node, date range) |
| `/vendor-schemes/` | GET, POST | CRUD on `VendorScheme` + nested scopes/slabs |
| `/recommendations/` | GET | Filtered `ReplenishmentRecommendation` queue for a workbench |
| `/recommendations/{id}/decide/` | POST | Records `PlannerDecision` (approve/reject/modify) |

Authentication: DRF Session Auth, consistent with the server-rendered HTMX frontend (no separate SPA auth
concern, as in Phase 3B).

---

### Caching (Phase 3C additions)

| Cache key | Content | TTL | Invalidated by |
|-----------|---------|-----|----------------|
| `resolved_supply_source:{client_code}` | Materialized supply-source cache | Until nightly job / rule change | Celery beat job; post_save on `SupplyNetworkRule` |
| `resolved_vendor_scheme:{client_code}` | Materialized vendor-scheme resolution | Until scheme change | post_save on `VendorScheme`/`VendorSchemeSlab` |
| `policy_matrix:{client_code}` | 12-cell policy matrix | 1 hour | post_save on `PolicyMatrix` |
| `carrying_cost_rate:{client_code}` | `InventoryCarryingCostRate` + penalty tiers | 1 hour | post_save on either model |

---

### Background Tasks (Celery)

| Task | Trigger | Notes |
|------|---------|-------|
| `resolve_supply_network(client_code)` | Nightly beat + `SupplyNetworkRule` post_save | Materializes `ResolvedSupplySource`; runs the `Σ allocation_pct == 100%` integrity check |
| `resolve_vendor_schemes(client_code)` | Nightly beat + `VendorScheme` post_save | Materializes `ResolvedVendorScheme` |
| `cascade_operating_plan(version_id)` | Planner sets `ForecastNormalizationFactor` | Applies factor at anchor node, cascades via revenue-share disaggregation, writes `ForecastReconciliationException` for non-additive manual overrides |
| `propagate_replenishment_demand(client_code, version_id)` | Scheduled per client review cadence (`MAX(policy_frequency, data_refresh_frequency)`) | Runs the NetOwnDemand/RR algorithm; writes `NodeReplenishmentRequirement`; runs conservation-invariant check |
| `ingest_supply_position_snapshot(snapshot_id)` | Snapshot POST | Validates structurally; rejects whole snapshot on any row failure; materializes denormalized netting-ready structure on success |
| `run_netting(client_code, snapshot_id)` | Snapshot `APPLIED` + propagation complete | Computes `Net Requirement` per item×node; writes `InventoryPosition` |
| `evaluate_vendor_breakpoints(recommendation_id)` | Netting produces `base_qty` > 0 for a PURCHASE candidate | Runs the breakpoint trade-off; attaches chosen qty + reasoning to the recommendation |
| `generate_recommendations(client_code)` | After netting + breakpoint evaluation | Applies `PolicyMatrix` cell logic per SKU-location; writes `ReplenishmentRecommendation` with full explainability payload |
| `compute_rebate_accrual_estimate(scheme_id)` | Scheduled (period close cadence) | Recomputes `estimated_effective_discount_pct` as median of last 3–4 settled periods |

---

### `ClientFeatureControl` Keys Added (Phase 3C)

`inventory_decision_engine`, `supply_network_rules`, `ddmrp`, `vendor_schemes`, `planner_workbenches`.

---

### Folder structure additions

```
mysite/
├── models/
│   └── ide/                       # per model package layout above
├── api/
│   └── ide/
│       ├── urls.py
│       └── views.py
├── ide_ui/                        # Django-template + HTMX planner workbenches (NOT a React SPA)
│   ├── urls.py
│   ├── views.py
│   └── views_htmx.py
├── tasks/
│   └── ide/
│       ├── resolve_supply_network.py
│       ├── propagate_demand.py
│       ├── ingest_snapshot.py
│       ├── run_netting.py
│       ├── evaluate_vendor_breakpoints.py
│       └── generate_recommendations.py
├── templates/
│   └── ide/
│       ├── dashboard.html
│       ├── workbenches/
│       │   ├── service_risk.html
│       │   ├── replenishment.html
│       │   ├── transfer.html
│       │   ├── inventory_balancing.html
│       │   ├── vendor_scheme.html
│       │   ├── exception_management.html
│       │   └── policy_governance.html
│       └── partials/
├── static/
│   └── ide/
└── utils/
    └── ide/
        ├── supply_network_resolver.py
        ├── propagation_engine.py
        ├── netting_engine.py
        ├── vendor_breakpoint_evaluator.py
        └── recommendation_engine.py
```
## Phase 3 eCommerce models with Beckn

Commerce models follow Beckn v2.0 schema vocabulary. BecknFulfillment, BecknBilling, BecknQuotation are standalone models (not embedded in Order) matching Beckn's structural separation. Each has a to_beckn() method for future API adapter. CustomerAddress adds gps, area_code, state, landmark fields to match Beckn Location.address schema.
# tech-stack.md — Delta Updates (Phase 3)


## Phase 3 — eCommerce Stack

### Commerce Models Package Layout

```
mysite/models/
    commerce/
        __init__.py
        inquiry.py          # Inquiry, InquiryLine
        quotation.py        # Quotation, QuotationLine
        order.py            # Order, OrderLine
        delivery.py         # Delivery, DeliveryLine
        picking.py          # Picking, PickingLine  [optional]
        packing.py          # Packing, PackingLine  [optional]
        transportation.py   # Transportation, TransportationDelivery [optional]
        billing.py          # Invoice, InvoiceLine, InvoiceDelivery
        payment.py          # Payment, PaymentAllocation
        returns.py          # Return, ReturnLine, Refund
        pricing.py          # PricingProcedure, PricingStep, ConditionType,
                            # ConditionAccessSequence, ConditionRecord,
                            # ConditionScale, PricingResultLine
        currency.py         # ClientCurrencyRule, Money value object helpers
```

### Key Model Relationships (Phase 3 additions)

```
Client
  ├── allowed_currencies (JSONField)
  ├── base_currency (CharField)
  ├── allow_delivery_split (BooleanField)
  ├── allow_partial_shipment (BooleanField)
  ├── multi_location_dispatch (BooleanField)
  ├── PricingProcedure (FK → Client)
  │     └── PricingStep (ordered; FK → PricingProcedure, ConditionType, AccessSequence)
  ├── ClientCurrencyRule (client_country, customer_country → currency)
  └── ClientLocation
        ├── allow_delivery_split (BooleanField)
        ├── allow_partial_shipment (BooleanField)
        ├── is_dispatch_location (BooleanField)
        ├── enable_picking (BooleanField)
        ├── enable_packing (BooleanField)
        ├── enable_transportation (BooleanField)
        └── enable_billing_consolidation (BooleanField)

CustomerProfile
  └── CustomerAddress (address_type: BILL_TO / SHIP_TO / BOTH, gps, area_code, state, landmark)

Inquiry (source_doc_type=None, source_doc_id=None, currency, bill_to, ship_to)
  └── InquiryLine (item, qty, unit_price, ship_to_override)

Quotation (source_doc → Inquiry or None, currency, pricing_result)
  └── QuotationLine → PricingResultLine (per step per line)

Order (source_doc → Quotation or None, bill_to, ship_to, allow_delivery_split override)
  └── OrderLine (ship_to_address override, bill_to_address override, open_qty, closed_qty)

Delivery (order, source_lines M2M OrderLine, dispatch_location → ClientLocation)
  └── DeliveryLine (order_line, delivered_qty)
  → TransportationDelivery (M2M)
  → InvoiceDelivery (M2M)

Picking (delivery, optional)
Packing (picking or delivery, optional)
Transportation (consolidates Deliveries)
Invoice (consolidates Deliveries, currency, payment_terms)
  └── InvoiceLine
Payment → PaymentAllocation → Invoice
Return → ReturnLine → Refund
```

### Money / Currency Architecture

- `djmoney.MoneyField` is used on all monetary columns: `unit_price`, `line_total`, `discount_amount`, `tax_amount`, `gross_total`, etc.
- `MoneyField` stores two DB columns: `{field}_amount` (NUMERIC) + `{field}_currency` (CHAR 3).
- Currency on a document is set at header level and propagated to lines; line-level currency override is not supported (all lines must share the document currency).
- `Client.allowed_currencies` drives the dropdown on Inquiry / Quotation / Order header. `Client.base_currency` is the default selection.
- `ClientCurrencyRule(client, client_country, customer_country, currency)` is evaluated after `base_currency` default and before user override.

### Pricing Engine Implementation Notes

- `PricingProcedure` is per-Client. On Client creation a signal copies the system default procedure.
- `PricingStep` fields: `step_number` (ordering), `condition_type` (FK), `access_sequence` (FK), `apply_at` (LINE / HEADER), `is_statistical`, `group_key`, `requirement` (dotted-path string to a callable), `from_step` (base amount reference for % conditions).
- `ConditionRecord` fields: `condition_type`, `key_combination` (JSONField — the resolved access key), `valid_from`, `valid_to`, `amount` (MoneyField or decimal for %), `scale` (FK to ConditionScale or null).
- `ConditionScale` fields: `condition_record`, `scale_type` (VALUE / QTY), `breaks` (JSONField array of `{from, rate_or_amount}`).
- `PricingResultLine` fields: `document_ct` (GenericFK to Order/Quotation), `line_ref`, `step_number`, `condition_type`, `base_amount`, `condition_value`, `result_amount`, `is_statistical`.

### Document Promotion Flow (technical)

A `promote_document(source_instance, target_model)` service function handles all flow variants:
1. Validates source document status allows promotion.
2. Deep-copies header fields to target model, sets `source_doc_type` + `source_doc_id`.
3. Creates target lines from source lines (preserving quantities, item refs, address overrides).
4. If target is `Order`: runs pricing engine and stores `PricingResultLine` records.
5. Returns the target instance in `DRAFT` status for user editing before confirmation.

### REST API Layer (for mobile / Beckn adapter)

- `djangorestframework` added; routers under `mysite/api/`.
- Phase 3 endpoints: `InquiryViewSet`, `QuotationViewSet`, `OrderViewSet`, `DeliveryViewSet`, `InvoiceViewSet`.
- Authentication: DRF Token Auth for internal use; JWT deferred to Phase 4.
- Serializers expose `to_beckn()` output via a `?format=beckn` query param on detail endpoints.

### Caching (Phase 3 additions)

| Cache key | Content | TTL | Invalidated by |
|-----------|---------|-----|----------------|
| `pricing_procedure:{client_code}` | Serialised PricingProcedure + steps | 1 hour | post_save on PricingProcedure / PricingStep |
| `condition_records:{client_code}:{condition_type}` | ConditionRecord lookup table | 15 min | post_save on ConditionRecord |
| `currency_rules:{client_code}` | ClientCurrencyRule list | 1 hour | post_save on ClientCurrencyRule |

### Background Tasks (Celery)

| Task | Trigger | Notes |
|------|---------|-------|
| `send_order_confirmation` | Order status → CONFIRMED | Email to Customer + Client staff |
| `send_quotation_email` | Quotation status → SENT | Email with PDF attachment |
| `recalculate_pricing` | ConditionRecord post_save | Recomputes open Quotation / Order pricing in background |
| `generate_invoice_pdf` | Invoice status → ISSUED | Renders PDF, stores URL on Invoice |

### `ClientFeatureControl` / `ClientLocation` Flags Added (Phase 3)

Extend existing `ClientFeatureControl` model with Phase 3 feature keys:
`inquiry`, `quotation`, `picking`, `packing`, `transportation`, `billing_consolidation`, `multi_currency`, `partial_shipment`.

Extend `ClientLocation` with boolean fields:
`enable_picking`, `enable_packing`, `enable_transportation`, `enable_billing_consolidation`,
`allow_delivery_split`, `allow_partial_shipment`, `is_dispatch_location`.

### Folder structure
mysite/
├── core/                          # Shared across all apps
│   ├── middleware.py              # ClientScopedMiddleware, request.client
│   ├── context_processors.py
│   ├── feature_control.py        # is_demand_feature_disabled → generalise to is_feature_disabled
│   └── mixins.py                 # login_required helpers, _is_htmx, _feature_gate, _client_url_kwargs
│
├── models/                        # All Django models, organised by domain
│   ├── client.py                  # Client, PlanningLocation, etc.
│   ├── catalogue.py
│   ├── demand/
│   │   ├── forecast.py
│   │   └── actuals.py
│   ├── inventory/                 # Phase 2
│   │   └── ...
│   └── ecommerce/                 # Phase 3
│       └── ...
│
├── api/                           # JSON APIs — one sub-package per domain
│   ├── demand/
│   │   ├── urls.py
│   │   └── views.py
│   ├── inventory/
│   └── ecommerce/
│
├── demand_ui/                     # HTMX UI — Demand Planning
│   ├── urls.py
│   ├── views.py
│   ├── views_drilldown.py
│   └── views_htmx.py             # renamed from forecast_htmx.py
│
├── inventory_ui/                  # Phase 2 — mirrors demand_ui exactly
│   ├── urls.py
│   └── views.py
│
├── ecommerce_ui/                  # Phase 3
│   ├── urls.py
│   └── views.py
│
├── tasks/                         # Celery tasks, organised by domain
│   ├── demand/
│   │   ├── run_forecast.py
│   │   ├── import_actuals.py
│   │   └── compute_series_profiles.py
│   ├── inventory/
│   └── ecommerce/
│
├── templates/
│   ├── base.html
│   ├── core/
│   ├── demand/
│   │   ├── dashboard.html
│   │   ├── version_list.html
│   │   └── partials/
│   ├── inventory/
│   └── ecommerce/
│
├── static/
│   ├── demand/
│   ├── inventory/
│   └── ecommerce/
│
├── views.py                       # Only core/catalogue views (landing, auth, profile, catalogue)
└── urls.py                        # Root URL conf — mounts everything below

------------------------------------------------------------------------------------------------------------------------------
## To Build complete hrml file and push to PageContent

## Stich Prompt: 
Correct Stitch prompt — when using Google Stitch, use exactly this prompt structure:

"Design an [page type] page for a [business type]. Output plain HTML only — no React, no JSX, no <script> tags. Use only Tailwind CSS utility classes and DaisyUI component classes for all styling. No inline style attributes anywhere."

That last sentence is the critical one — Stitch defaults to inline styles if you don't explicitly forbid them.

## Claude Prompt: 
"Generate a complete [page type] page in plain HTML. Use only Tailwind CSS v4 utility classes and DaisyUI v5 component classes. No inline styles. No React. Use semantic colour tokens like bg-primary, text-base-content, bg-base-200. The page will be pasted into a Django PageContent field and rendered inside an existing base.html that already has a navbar and footer, so do not include <html>, <head>, or <body> tags."

## v0.dev (Vercel)
Generates UI from prompts. Defaults to React/shadcn but you can ask for plain HTML + Tailwind. Output quality is high. Requires some cleanup to remove React-specific syntax.
Prompt addition needed:

"Output plain HTML only. No JSX, no React, no components. Use DaisyUI v5 classes."

Workflow: Generate → copy HTML → strip any className= (change to class=) → paste into PageContent.

## Pinegrow
A desktop visual editor that works directly with Tailwind and DaisyUI. You design visually, it writes the HTML with proper Tailwind classes. Unlike web-based tools, it has explicit DaisyUI component support.
Best fit for your workflow if you want a proper visual editor. Free trial available, paid after that.
Workflow: Design in Pinegrow → Export HTML → paste into PageContent.

## Recommended workflow for Phase 1
Given you're one developer doing this quickly:
For structured pages (about, contact, team): use Claude directly with the prompt pattern above. Fast, no conversion, uses your exact DaisyUI tokens.
For copy-paste sections (hero banners, feature grids, testimonials): use HyperUI or Flowbite — browse, find a section you like, copy HTML, paste. Takes 2 minutes per section.
For full page layouts: combine the two — use HyperUI for structure, ask Claude to adapt it to DaisyUI component classes and your colour tokens.
The key constraint to keep in mind for all tools: always check the output for style= attributes and replace them with Tailwind classes, and always remove <html>, <head>, <body> wrapper tags before pasting into PageContent.


Key changes to be done:
0. ✅ DONE (Sprint 2.10): Client belongs to an Industry Classification (`Client.sector`, global `sector` taxonomy: Industrial > Automotive > AutoComponent) and site chrome is resolved per Classification — see section below.
1. ✅ DONE: Per-client catalogue class list — `Client.catalogue_taxonomy_slugs` (ordered JSON array of taxonomy slugs) controls which item classes appear in the catalogue LHS filter and in what order; NULL/empty = show all active taxonomies (legacy behavior).
2. [ ] Fields to capture planning-hierarchy pooling logic
3. [ ] If such a logic exists then a menu to recalculate the planning-hierarchy by planner as part of the planning-dashboard

---

## Client Sector Classification & Template Resolution (implemented)

### Sector taxonomy (reuses Taxonomy/TaxonomyNode)
- New taxonomy type `'sector'` (`TAXONOMY_TYPES` in `mysite/models/catalogue.py`).
- One global `Taxonomy(slug='sector')`; node tree seeded by data migration
  `0082_seed_sector_taxonomy`: `industrial(001)` > `automotive(001.002)` > `autocomponents(001.002.003)`.
  Materialized paths follow the existing convention: `parent.path + f".{order:03d}"`.
- `Client.sector` FK → `TaxonomyNode` (`null=True`, blank allowed, `on_delete=SET_NULL`,
  `related_name='clients'`, limited to nodes of the sector taxonomy).
- **Path-uniqueness caveat**: materialized paths are only unique *within* a taxonomy.
  Any code matching on bare `path=` must scope by `taxonomy_id` (this bit
  accuracy-report lookups; fixed in `utils/demand/accuracy_report.py`).

### SectorTemplate model (`mysite/models/client.py`)
| Field | Notes |
|-------|-------|
| `template_key` | Choice from Client's `TEMPLATE_CHOICES` (now includes `demand_sidebar_nav`) |
| `sector_node` | FK → TaxonomyNode, nullable. **NULL row = the active global default** |
| `country` | FK → Country, nullable. **NULL = all countries (default)**. Selects country-specific template overrides. |
| `htmlblob` | Translated (modeltranslation: en/fr/hi/ta + original column) |
| `is_active` | Only active rows resolve |

Constraints: unique `(sector_node, country, template_key)` among active rows; conditional
unique index enforces exactly one active NULL-sector NULL-country row per key.

### Resolution chain (uniform for ALL keys — navbar, footer, demand sidebar, …)
Implemented in `mysite/templatetags/my_tags.py::render_client_template`:

1. `ClientTemplate` for `(client, key, country=X)` — client+country override.
2. `ClientTemplate` for `(client, key, country=NULL)` — client override.
3. `SectorTemplate` rows walking the client's sector chain with `country=X` **deepest → root**;
   most-specific non-blank active blob wins.
4. `SectorTemplate` with `sector_node IS NULL` and `country=X` — country-specific global default.
5. `SectorTemplate` rows walking the client's sector chain with `country=NULL` **deepest → root**;
   existing behaviour for country-disabled clients.
6. `SectorTemplate` with `sector_node IS NULL` and `country=NULL` — seeded global default.
7. Nothing found → render empty string + `logger.warning`.

The old in-tag filesystem map and `_resolve_client_templates()` /
`template_info` payload in `utils/catalogue_queries.py` were **removed** —
the DB is the single source of defaults.

**Cotton caveat**: `<c-*>` component tags only compile through the Django loader
chain, not plain `Template()` rendering. Seeded defaults that need cotton wrap
the include instead, e.g. `{% include 'cotton/navbar_v001.html' %}`.

### Caching & invalidation
- `client_template:{client_code}:{key}:{country}` → resolved HTML (LocMemCache fallback clears everything).
- `sector_chain:{client_code}` → list of ancestor node ids (deepest-first), exception-safe.
- Invalidation (`mysite/signals.py`): SectorTemplate save/delete clears
  `client_template:*`; any `TaxonomyNode` move busts all chains; Client save
  refreshes its own chain + templates.

### Admin & permissions
- Standalone `SectorTemplateAdmin` (superuser-only via `ADMIN_ONLY_MODELS`);
  translated fieldsets via `ClientLanguageMixinV2`.
- `sector` picker added to Client admin General fieldset.

### Migrations & ops
- `0081_*` schema · `0082_seed_sector_taxonomy` idempotent tree seed ·
  `0083_seed_global_default_templates` seeds all 8 keys into every language column.
- `0088_*` adds `country` FK to SectorTemplate + new UniqueConstraints.
- `0089_*` adds `country` FK to ClientTemplate + updates unique_together.
- Defaults are DB-owned from here on: change them in admin, not in git — deploys no longer alter rendered chrome.
- Regression guard: `mysite/tests/test_sector_templates.py` fails if a future
  `TEMPLATE_CHOICES` addition ships without a seeded default.

---

## Catalogue LHS Filter — Per-Class Selection & Order (implemented)

`Client.catalogue_taxonomy_slugs` (JSONField, migration 0084): ordered array of
taxonomy slugs, e.g. `["gpc", "brand"]`.

- **Resolution** (`utils/catalogue_queries.py::get_resolved_taxonomies`):
  configured list → only those slugs, display order = list order; unknown /
  inactive slugs skipped; duplicates collapse to first occurrence (guards
  hand-edited JSON). NULL/empty → legacy behavior: all active taxonomies
  (client-specific overriding global) sorted by `Taxonomy.order`.
- **Scope**: catalogue LHS filter only. Item tagging and other consumers unaffected.
- **Admin**: "Catalogue class order" CSV field on Client General fieldset
  (`ClientForm.clean_catalogue_taxonomy_order`) — validates slugs against the
  taxonomies that client can see (global + own), normalizes case/whitespace,
  dedupes; blank input stores NULL.
- **Tests**: `mysite/tests/test_catalogue_taxonomy_order.py`.

## Catalogue LHS Filter — Tri-State Tree, Rolled-Up Counts, Accurate Facets (implemented)

Value-Summary-style filter tree on the catalogue page (desktop sidebar + mobile
drawer), replacing the plain checkbox list.

- **Tri-state selection** (`get_taxonomy_tree(..., selected_node_ids=...)`):
  selecting a node selects its whole subtree (descendants render `checked`);
  an ancestor fully covered by the selection renders checked, one only partly
  covered (a sibling subtree unselected) renders `data-partial`; nothing above
  the chosen node auto-checks. Mirrors demand's `_selection_state` semantics.
- **Rolled-up counts**: every node badge shows the number of distinct items in
  its entire subtree (`_subtree_item_counts` — bottom-up merge over
  materialized paths from BOTH `ItemTaxonomyNode` and
  `GlobalItemTaxonomyNode`, so derived items count too; cross-child double
  tags deduped). Counts are computed per level during the walk so leaves,
  middles, and roots each keep their own value. Every badge matches the query
  result size at the root.
- **Own-facet-excluded attribute counts**: when attribute filters narrow the
  item set, value counts for each attribute ignore that attribute's own
  selections and re-count against everything else (`_facet_value_counts`) —
  sibling values stay visible with live counts instead of disappearing.
- **Taxonomy-wins dedupe**: if a client resolves a taxonomy whose slug equals
  an attribute type slug (typically `brand`), the duplicate ATTRIBUTE facet
  block is suppressed for that slug AND the legacy flat Brand section is
  dropped (`brands = []`) — the taxonomy block is the single source.
- **Templates**: `partials/filter_node.html` / `filter_node_mobile.html`
  rewritten to tx-widget markup (`tx-node`, toggle with
  `onclick="txToggleNode(this)"`, children `<ul id="cat-tx-children-{id}">`,
  depth > 0 starts collapsed); attr values carry count badges + server-computed
  `checked`. Assets: `taxonomy_tree.css/js` wired into both
  `page_catalogue.html` and `page_catalogue_html.html`.
- **DB blob sync**: new management command
  `mysite/management/commands/sync_sectortemplate_defaults.py` rewrites global
  default `SectorTemplate.htmlblob*` rows from `templates/catalogue/partials/*`
  (`--dry-run` supported) — used after editing the sidebar shell, since it
  lives in the DB, not in a rendered file.
- **Tests**: `mysite/tests/test_catalogue_lhs_facets.py` (rollup + dedupe of
  counts, tri-state annotations, own-facet-excluded facets, brand suppression,
  markup contract).