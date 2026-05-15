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
- `LowercaseCharField` is used for natural-key ID fields (`client_id`, `page_id`, `theme_id`, etc.) — auto-lowercased on save via `get_prep_value`.

### The `fetch_clientstatic()` Pattern
The central data delivery mechanism. On every page request:
1. `CustomerProfileMiddleware` resolves `request.client` from URL path (one DB query or none if cached).
2. `client_context` context processor calls `fetch_clientstatic(client_id)`.
3. `fetch_clientstatic` checks cache first (`clientstatic:{client_id}`). On miss, runs a single deeply-prefetched query across `Client → Page → Layout → Component → ComponentSlot → ComptextBlock → TextstbItem → SvgtextbadgeValue`.
4. Result is serialised to a plain Python dict by `build_client_payload()` and cached.
5. Templates consume `{{ client }}`, `{{ page_dict }}`, `{{ theme }}` — never raw ORM calls.
6. `header_nav` and `footer_nav` are built from `NavItem` records prefetched
  alongside pages and themes. `build_nav_item()` calls `item.get_url(client_id)`
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


Client (client_id, parent→self, language_list, theme_list)
  ├── Theme (theme_id, themepreset→ThemePreset, overrides JSON)
  ├── Page (page_id, parent→self, order)
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
  ├── ClientLocation (location_id, location_type)
  ├── ClientGroup (group_id, role, locations M2M)
  │     ├── ClientGroupPermission (module, action)
  │     └── ClientUserMembership (user→User)
  ├── ClientUserProfile (user→User [OneToOne])
  └── CustomerProfile (user→User [FK], unique_together user+client)
        └── CustomerAddress (street, city, zip, country, is_default)

ThemePreset (themepreset_id, colours, typography, spacing, radius, shadow)
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
  ├── signals.py                 ← cache invalidation on post_save / post_delete
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
  ├── Item (item_id, status, attributes JSONB, global or client-scoped)
  │     ├── ItemTaxonomyNode → TaxonomyNode (M2M)
  │     ├── ItemImage (order, is_primary)
  │     └── ItemVariant (variant_id, price, stock, attributes)
  └── ... (existing models unchanged)

Item (base — id, name, description, status, image, order, client)
  ├── ProductItem    (price, currency, sku, weight_g, dimensions)  [OneToOne]
  ├── SongItem       (duration_s, bpm, key, artist, album)         [OneToOne]
  ├── DocumentItem   (page_count, format, file_url, version)       [OneToOne]
  └── attributes     (JSONField on Item — catches anything else)

```
bash
cat >> /home/claude/specs/tech-stack.md << 'EOF'

---

## Phase 2 Completed — Catalogue Stack (Actual)

### Caching Strategy

| Cache key | Content | TTL | Invalidated by |
|-----------|---------|-----|---------------|
| `clientstatic:{client_id}` | Full CMS payload | 1 hour | post_save on CMS models |
| `taxonomy_tree:{client}:{slug}` | Taxonomy node tree | 1 hour | post_save on TaxonomyNode |
| `catalogue_base_ids:{client}:{status}` | Base item ID set | 5 min | post_save on Item |
| `client_templates:{client_id}` | Template resolution dict | 1 hour | post_save on ClientTemplate |

### Admin Performance

- `list_select_related` on all ModelAdmin classes with FK to Client
- `raw_id_fields = ('client',)` on catalogue admin to prevent 207× Client query
- Inline `get_queryset()` overrides with `select_related` on FK chains
- `ClientTemplate` resolution cached (was 15ms per catalogue request)

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
```

### `I18nFallbackMixin` — Field resolution priority

```
1. Item.{field}_{active_lang}
2. Item.{field}_{client_base_lang}
3. GlobalItem.{field}_{active_lang}
4. GlobalItem.{field}_{client_base_lang}
5. Empty string
```

Applied to: `name`, `description`, `care_instructions` on `Item`.

### `Item.resolved_medias()` — Media inheritance

When `Item.inherit_global_media=True` and `GlobalItem` is set:
- `ItemMedia` records always included
- `GlobalItemMedia` records appended for types not covered by ItemMedia
- `SimpleNamespace` wrapper makes GlobalItemMedia template-compatible
- Result sorted by `order`
- Prefetch paths: `medias` → `prefetched_medias`, `global_item__medias` → `prefetched_global_medias`

## Phase 3 eCommerce models with Beckn

Commerce models follow Beckn v2.0 schema vocabulary. BecknFulfillment, BecknBilling, BecknQuotation are standalone models (not embedded in Order) matching Beckn's structural separation. Each has a to_beckn() method for future API adapter. CustomerAddress adds gps, area_code, state, landmark fields to match Beckn Location.address schema.

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