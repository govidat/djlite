# Platform Operations Guide — Superadmin

This guide covers everything a platform superadmin needs to onboard clients,
configure the system, manage the data model, and operate the platform in
production. It assumes Django admin access and direct database / server access.

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Tech Stack at a Glance](#2-tech-stack-at-a-glance)
3. [Initial Server Setup](#3-initial-server-setup)
4. [Onboarding a New Client](#4-onboarding-a-new-client)
5. [Language and Localisation](#5-language-and-localisation)
6. [Theme System](#6-theme-system)
7. [User Management](#7-user-management)
8. [Item Catalogue Administration](#8-item-catalogue-administration)
9. [Demand Planning Administration](#9-demand-planning-administration)
10. [Feature Flags](#10-feature-flags)
11. [Global Key-Value Store (GlobalVal)](#11-global-key-value-store-globalval)
12. [Background Jobs and Celery](#12-background-jobs-and-celery)
13. [Caching](#13-caching)
14. [Deployment and Releases](#14-deployment-and-releases)
15. [Common Superadmin Tasks](#15-common-superadmin-tasks)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Platform Overview

This is a **multi-tenant SaaS CMS and commerce platform**. A single deployment
hosts multiple SME clients. Each client operates in full isolation — their own
pages, users, content, themes, settings, and (in Phase 3A) their own commerce
documents and pricing rules.

**Access pattern:** All client-facing URLs are prefixed by `/{client_id}/`.
Tenant identity is resolved on every request by `CustomerProfileMiddleware`,
which attaches `request.client` from the URL kwargs.

**Current phases:**

| Phase | Status | Scope |
|-------|--------|-------|
| 1 | Complete | Multi-tenant CMS, page builder, multilingual content, auth |
| 2 | Complete | Generic item catalogue, multi-taxonomy filtering |
| 3B | In progress | Demand planning: actuals upload, statistical forecasting, consensus overrides |
| 3A | Planned | eCommerce: Inquiry → Quotation → Order → Delivery → Billing |
| 4 | Planned | Beckn / ONDC network participation |

**Superadmin responsibilities:**
- Provisioning and configuring new client tenants
- Managing global taxonomy nodes and global items
- Configuring theme presets
- Managing background job infrastructure (Celery, Redis)
- System-wide feature flag management
- Database migrations and deployments
- Monitoring and troubleshooting

---

## 2. Tech Stack at a Glance

| Layer | Technology |
|-------|-----------|
| Backend framework | Django 5.x (`mysite` app label) |
| Database | PostgreSQL |
| Cache / Celery broker | Redis |
| Background tasks | Celery + Celery Beat |
| Auth | django-allauth with custom `ClientAwareAccountAdapter` |
| Object permissions | django-guardian |
| Multilingual fields | django-modeltranslation |
| Admin UI | Django Admin + django-nested-admin |
| Templates | django-cotton + DaisyUI + HTMX |
| Forecasting (Phase 3B) | Nixtla StatsForecast + HierarchicalForecast + Polars + DuckDB |
| Commerce (Phase 3A) | djmoney (MoneyField), Razorpay, Stripe |
| Deployment | Railway / Render (single git push) |

---

## 3. Initial Server Setup

### Environment variables

Set the following in your PaaS dashboard or `.env`:

```
DJANGO_SECRET_KEY=<long random string>
DATABASE_URL=postgres://user:pass@host:5432/dbname
REDIS_URL=redis://host:6379/0
DJANGO_SETTINGS_MODULE=mysite.settings.production
ALLOWED_HOSTS=yourdomain.com
```

For Phase 3A commerce, also set:

```
RAZORPAY_KEY_ID=rzp_live_...
RAZORPAY_KEY_SECRET=...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_SECRET_KEY=sk_live_...
```

### First deploy

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

### Celery (required from Phase 3B onwards)

Add to `Procfile`:

```
web: gunicorn mysite.wsgi
worker: celery -A mysite worker --loglevel=info
beat: celery -A mysite beat --loglevel=info
```

Set `CELERYD_TASK_SOFT_TIME_LIMIT = 1800` for forecast jobs.

### Verify

```bash
python manage.py check --deploy
```

Zero issues required before go-live.

---

## 4. Onboarding a New Client

### Step 1 — Create the Client record

In Django Admin → **Clients** → Add Client.

| Field | What to enter |
|-------|--------------|
| `client_id` | Short slug, URL-safe, e.g. `acme` — used in all URL prefixes; **immutable after creation** |
| `name` | Display name in the admin |
| `name_en` / `name_hi` etc. | Translated display names per active language |
| `parent` | Set if this is a sub-client or franchise unit; leave blank for a top-level client |
| `language_list` | JSON array of active language codes, e.g. `["en", "hi"]` — must be a subset of `settings.LANGUAGES` |
| `base_currency` | ISO 4217, e.g. `INR` — default document currency (Phase 3A) |
| `allowed_currencies` | JSON array, e.g. `["INR", "USD"]` — available in document currency dropdown |

Save. Django signals will:
- Copy the system default `PricingProcedure` to this client (Phase 3A, when active).
- Create a default `ClientFeatureControl` record.

### Step 2 — Assign a Theme

In Django Admin → **Themes** → Add Theme.

- Set `client` FK to the new client.
- Set `preset` to the base `ThemePreset` (see §6).
- Leave `overrides` blank to use preset defaults, or add token overrides as JSON.

### Step 3 — Configure Client Locations

In Django Admin → **Client Locations** → Add.

Each `ClientLocation` represents a warehouse, branch, or office.

| Field | Notes |
|-------|-------|
| `client` | FK to the client |
| `name` | Branch name |
| `parent` | Set for a Region → Branch → Location tree |
| `is_dispatch_location` | `True` if orders can be fulfilled from here (Phase 3A) |
| `allow_delivery_split` | Whether this location allows splitting a single order across multiple deliveries |
| `allow_partial_shipment` | Whether short-ships are allowed from this location |
| `enable_picking`, `enable_packing`, `enable_transportation` | Warehouse operation flags (Phase 3A) |

### Step 4 — Create Client Groups (roles)

In Django Admin → **Client Groups** → Add.

Standard roles to create for every client:

| Role slug | Typical use |
|-----------|------------|
| `admin` | Full access to all client modules |
| `staff` | Content editing; no user management |
| `viewer` | Read-only |
| `sales` | Access to commerce documents (Phase 3A) |
| `warehouse` | Access to picking/packing/delivery (Phase 3A) |
| `planner` | Access to demand planning module (Phase 3B) |

For each group, add `ClientGroupPermission` records specifying which modules
(`cms`, `catalogue`, `demand_planning`, `inquiry`, `quotation`, `order`, etc.)
and which actions (`view`, `create`, `edit`, `delete`) the group has access to.

### Step 5 — Grant object-level permission (django-guardian)

Run in a management shell or add to your onboarding script:

```python
from guardian.shortcuts import assign_perm
from mysite.models import Client
from django.contrib.auth.models import User

client = Client.objects.get(client_id='acme')
admin_user = User.objects.get(username='acme_admin')

assign_perm('view_client_data', admin_user, client)
assign_perm('edit_client_data', admin_user, client)
assign_perm('create_client_data', admin_user, client)
assign_perm('admin_client_data', admin_user, client)
```

### Step 6 — Create initial Pages

In Django Admin → **Pages** → Add.

- Set `client`, `slug`, `nb_title_en` (navbar title).
- For Track A (raw HTML): also create a `PageContent` record with `language_code='en'` and paste the HTML blob.
- For Track B (component tree): leave `PageContent` blank; use `Layout` / `Component` admin instead.

### Step 7 — Verify the client site

Navigate to `/{client_id}/` and confirm the correct theme and pages render.

---

## 5. Language and Localisation

### Adding a new language globally

1. Add to `settings.LANGUAGES`:
   ```python
   LANGUAGES = [
       ('en', 'English'),
       ('hi', 'Hindi'),
       ('fr', 'French'),
       ('ta', 'Tamil'),
       ('te', 'Telugu'),   # new
   ]
   ```
2. Run `python manage.py makemigrations` — `django-modeltranslation` adds
   `_te` columns to all registered translatable models.
3. Run `python manage.py migrate`.
4. Run `python manage.py update_translation_fields` to populate new columns
   with the English fallback.

### Enabling a language for a specific client

In Django Admin → **Clients** → edit client → update `language_list`:
```json
["en", "hi", "te"]
```

Only languages listed here are offered to that client's users.

### Language fallback order

Requested language → `settings.LANGUAGE_CODE` (English) → first available.

### GlobalVal translations

`GlobalVal` / `GlobalValCat` is the key-value store for UI strings. Add
translations per language code in Django Admin → **Global Vals**.

---

## 6. Theme System

### Theme Presets

`ThemePreset` records hold base design tokens (colour, typography, spacing,
border-radius, shadows). Superadmin creates and maintains presets.

In Django Admin → **Theme Presets** → Add.

Tokens are stored as JSON, e.g.:

```json
{
  "color_primary": "#1D9E75",
  "color_secondary": "#534AB7",
  "font_sans": "'Inter', sans-serif",
  "border_radius_base": "8px"
}
```

These are injected as CSS custom properties into `base.html`.

### Per-client overrides

In Django Admin → **Themes** → select a client's theme → edit `overrides`:

```json
{
  "color_primary": "#E8593C"
}
```

Override keys replace the preset value. Non-overridden keys fall through to
the preset. The merge is handled by `resolve_theme()` at request time.

---

## 7. User Management

### Two user types

| Type | Model | Relation to User | Scope |
|------|-------|-----------------|-------|
| Client user (staff) | `ClientUserProfile` | OneToOne | One client only |
| Customer user | `CustomerProfile` | ForeignKey | One profile per client, same Django User can be customer of many clients |

### Creating a client staff user

1. Django Admin → **Users** → Add → set username / email / password.
2. Django Admin → **Client User Profiles** → Add → link `user` and `client`.
3. Django Admin → **Client User Memberships** → Add → assign to a `ClientGroup`.

Or use the client admin's own user management UI once the client admin is set up.

### Creating a customer user

Customer users self-register via `/{client_id}/accounts/signup/`. The custom
`ClientAwareAccountAdapter` creates a `CustomerProfile` scoped to that client
automatically on registration.

### Active role resolution

Every request carries `request.active_role` (`staff` / `customer` / `None`),
set by middleware from the authenticated user's profile records.

### Resetting a user's password (manual)

```bash
python manage.py changepassword <username>
```

---

## 8. Item Catalogue Administration

### Global items vs client items

| Type | Created by | Visible to |
|------|-----------|-----------|
| `GlobalItem` | Superadmin | All clients (read-only) |
| `Item` (client-specific) | Client admin or superadmin | That client only |

A client-specific `Item` with the same `item_id` as a `GlobalItem` overrides
it for that client.

### Global taxonomy nodes

The `Taxonomy` / `TaxonomyNode` system supports multiple independent hierarchies
identified by a `slug`. Superadmin manages global nodes that all clients share.

Key taxonomy slugs:

| Slug | Purpose |
|------|---------|
| `gpc` | GS1 GPC 4-level hierarchy: Segment → Family → Class → Brick |
| `product_planning` | Product hierarchy used by the demand planning engine |
| `geography` | Geographic hierarchy for demand planning |

In Django Admin → **Taxonomies** → select a taxonomy → **Taxonomy Nodes** → Add.

Materialized `path` is computed automatically on save by a `pre_save` signal.

### Bulk upload

```bash
python manage.py bulk_upload --client acme --file items.csv
```

See `bulk_upload` management command `--help` for CSV column spec.

### GS1 GPC alignment

`GlobalItem` follows GS1 GPC: each item maps to a `Brick` node (the leaf of
the Segment → Family → Class → Brick tree). Superadmin maintains this tree
under the `gpc` taxonomy.

---

## 9. Demand Planning Administration (Phase 3B)

### Prerequisites

Feature must be enabled for the client:

In Django Admin → **Client Feature Controls** → select client → set
`demand_planning = True`.

### Sales hierarchy setup

In Django Admin → **Sales Nodes** → Add.

Build the sales org tree: e.g. National → Region → Area → Rep.

- `level_label`: human-readable label for that tier (e.g. `Region`, `Rep`).
- `parent`: FK to parent node; blank for top-level.
- `location`: optionally link to a `ClientLocation` (e.g. a branch office).

Materialized `path` is computed automatically.

In Django Admin → **Customer Sales Assignments** → Add to assign customers
to leaf sales nodes. Use `valid_from` / `valid_to` for date-effective
assignments.

### Monitoring forecast jobs

In Django Admin → **Forecast Versions** → filter by client and status.

Statuses:

| Status | Meaning |
|--------|---------|
| `DRAFT` | Created; not yet run |
| `RUNNING` | Celery task in progress |
| `READY` | Statistical run complete; awaiting consensus |
| `IN_REVIEW` | Sent to planners for override |
| `APPROVED` | Client admin approved |
| `LOCKED` | Immutable; used as the baseline |
| `FAILED` | Engine error; check Celery logs |

For a `FAILED` version, inspect `ForecastVersion.error_detail` and Celery
worker logs. Common causes: actuals data has unmapped item IDs; summing matrix
construction failed due to empty hierarchy.

### Monitoring actuals imports

In Django Admin → **Actual Sale Imports** → filter by client.

Check `errors` JSONField for row-level failures. A partial import (status
`COMPLETE` with non-zero errors) is normal — planners should fix and re-upload
the affected rows.

### Accuracy tracking

`ForecastAccuracy` records are written automatically by a monthly Celery Beat
task (`compute_forecast_accuracy`). To trigger manually for a specific version
and period:

```python
from mysite.tasks.demand import compute_forecast_accuracy
compute_forecast_accuracy.delay(version_id=42, year=2025, month=11)
```

---

## 10. Feature Flags

`ClientFeatureControl` records gate features per client. Managed in Django Admin
→ **Client Feature Controls**.

### Phase 1 / 2 flags

| Key | Effect |
|-----|--------|
| `cms` | Core CMS enabled |
| `catalogue` | Item catalogue enabled |

### Phase 3B flags

| Key | Effect |
|-----|--------|
| `demand_planning` | Demand planning module visible to client admin |
| `actuals_upload` | Actuals upload endpoint enabled |
| `forecast_run` | Forecast run trigger enabled |
| `consensus_override` | Consensus grid editable |
| `forecast_approval` | Approve / Lock actions enabled |

### Phase 3A flags (when active)

| Key | Effect |
|-----|--------|
| `inquiry` | Inquiry document flow enabled |
| `quotation` | Quotation document flow enabled |
| `picking` | Warehouse picking step enabled |
| `packing` | Warehouse packing step enabled |
| `transportation` | Transportation consolidation enabled |
| `billing_consolidation` | Multiple deliveries can be combined on one invoice |
| `multi_currency` | Currency dropdown visible on commerce documents |
| `partial_shipment` | Part-shipment and back-order allowed |

The utility `feature_enabled(client, location, key)` checks location-level
flags first, then client-level. Always use this helper — never query
`ClientFeatureControl` directly in views.

---

## 11. Global Key-Value Store (GlobalVal)

`GlobalVal` / `GlobalValCat` is the translation store for UI strings.

In Django Admin → **Global Val Cats** → create a category (e.g. `nav`, `errors`).
In Django Admin → **Global Vals** → add key-value pairs per category and
language code.

These are resolved in templates via the `gv` context variable:

```html
{{ gv.nav.home }}
```

Fallback: requested language → `en` → key string itself.

Values are cached in Redis. To bust the cache after a bulk edit:

```bash
python manage.py shell -c "
from django.core.cache import cache
cache.delete_pattern('globalval:*')
"
```

---

## 12. Background Jobs and Celery

### Task inventory

| Task | Module | Trigger | Notes |
|------|--------|---------|-------|
| `process_actuals_import` | `demand` | File upload | Parses CSV/Excel; writes ActualSale rows |
| `process_summary_actuals_import` | `demand` | File upload | Writes ActualSaleLocation rows |
| `run_forecast` | `demand` | API POST | Full forecast pipeline; up to 30 min |
| `propagate_override` | `demand` | Override POST (large subtree) | Disaggregates override to leaf lines |
| `compute_forecast_accuracy` | `demand` | Monthly Celery Beat | Joins ForecastLine with ActualSale |
| `send_order_confirmation` | `commerce` | Payment confirmed | Email to customer + client staff |
| `send_quotation_email` | `commerce` | Quotation sent | Email with PDF attachment |
| `generate_invoice_pdf` | `commerce` | Invoice issued | Stores PDF URL on Invoice |
| `recalculate_pricing` | `commerce` | ConditionRecord saved | Recomputes open Quotations/Orders |

### Monitoring

Use Flower (Celery monitoring dashboard):

```bash
pip install flower
celery -A mysite flower
```

Or check the Celery worker logs in your PaaS dashboard.

### Retrying a failed task

```python
from celery.result import AsyncResult
result = AsyncResult('task-id-here')
result.retry()
```

### Task time limits

```python
# settings/production.py
CELERYD_TASK_SOFT_TIME_LIMIT = 1800   # 30 min — forecast jobs
CELERYD_TASK_TIME_LIMIT = 2100        # 35 min hard kill
```

---

## 13. Caching

All caches use Redis. Cache keys follow `{domain}:{identifier}` naming.

| Cache key pattern | Content | TTL | Invalidated by |
|-------------------|---------|-----|----------------|
| `globalval:{lang}` | All GlobalVal entries for a language | 1 hour | `post_save` on GlobalVal |
| `clientstatic:{client_id}` | Full page + theme payload from `fetch_clientstatic()` | Until explicitly busted | Page / Theme `post_save` |
| `sales_hierarchy:{client_id}` | SalesNode tree JSON | 1 hour | `post_save` on SalesNode |
| `location_hierarchy:{client_id}` | ClientLocation tree JSON | 1 hour | `post_save` on ClientLocation |
| `pricing_procedure:{client_id}` | PricingProcedure + steps | 1 hour | `post_save` on PricingProcedure / PricingStep |
| `condition_records:{client_id}:{type}` | ConditionRecord lookup | 15 min | `post_save` on ConditionRecord |
| `currency_rules:{client_id}` | ClientCurrencyRule list | 1 hour | `post_save` on ClientCurrencyRule |
| `forecast_aggregates:{version_id}:{agg_level}` | Pre-computed demand aggregates | Until version status changes | `ForecastVersion` status `post_save` |

To manually clear all cache for a client:

```python
from django.core.cache import cache
client_id = 'acme'
cache.delete_pattern(f'*:{client_id}*')
```

---

## 14. Deployment and Releases

### Deploying a new release

```bash
git push origin main
```

Railway / Render auto-deploys on push. The `release` phase in `Procfile` runs:

```
release: python manage.py migrate && python manage.py collectstatic --noinput
```

### Zero-downtime migrations

Avoid multi-step schema changes in a single deploy. Pattern:

1. Deploy: add nullable column (no migration required in views yet).
2. Deploy: backfill data.
3. Deploy: add NOT NULL constraint.

### Rolling back

```bash
python manage.py migrate mysite 0042  # target the previous migration
git push origin main~1:main --force   # roll back code
```

Always take a database snapshot before deploying destructive migrations.

### Health check endpoint

`GET /health/` returns `HTTP 200` with `{"status": "ok"}`. Use this for
PaaS health checks and uptime monitoring.

---

## 15. Common Superadmin Tasks

### Add a new language to an existing client

1. Ensure the language is in `settings.LANGUAGES` and migrations are run.
2. In Django Admin → **Clients** → edit `language_list` JSON to include the new code.
3. In Django Admin → **Global Vals** → add translations for the new language code for all keys in all categories.
4. For each `Page` with `PageContent` records, add a new `PageContent` row with the new `language_code` and translated HTML.

### Move a client to a different parent (franchise restructure)

In Django Admin → **Clients** → set `parent` FK. No data migration needed;
the parent-child relationship is advisory and affects navigation display only.

### Export actuals data for a client

```python
import polars as pl
from mysite.models.demand.actuals import ActualSale

qs = ActualSale.objects.filter(client_id='acme').values(
    'item_id', 'customer_id', 'location_id', 'year', 'month',
    'qty', 'revenue_amount', 'revenue_currency'
)
df = pl.DataFrame(list(qs))
df.write_csv('/tmp/acme_actuals.csv')
```

### Force-lock a ForecastVersion

```python
from mysite.models.demand.forecast import ForecastVersion
v = ForecastVersion.objects.get(pk=42)
v.status = 'LOCKED'
v.save(update_fields=['status'])
```

### Clear a client's page cache after bulk content update

```python
from django.core.cache import cache
cache.delete('clientstatic:acme')
```

### Check which Celery tasks are queued

```bash
celery -A mysite inspect reserved
celery -A mysite inspect active
```

---

## 16. Troubleshooting

### Client site shows wrong theme or stale content

Cache not invalidated. Run:

```python
from django.core.cache import cache
cache.delete('clientstatic:acme')
```

### Forecast job stuck in RUNNING

Check the Celery worker is alive:

```bash
celery -A mysite inspect ping
```

If the worker crashed mid-task, the version will be stuck. Reset manually:

```python
ForecastVersion.objects.filter(pk=42).update(status='FAILED')
```

Then re-trigger the run from the client admin UI.

### Migration fails on deploy

Run locally first:

```bash
python manage.py migrate --plan
```

Check for dependency conflicts. If a migration references a model that has
been moved to a different app, update the dependency in the migration file.

### `manage.py check` reports wrong app label

All models must use `app_label = 'mysite'` in their `Meta` class. If a model
uses `myapp` or is missing the `Meta.app_label`, migrations will be generated
in the wrong location.

### Actuals import completes but row count is lower than expected

Check `ActualSaleImport.errors` in Django Admin. Common causes:
- Item ID in the file does not match any `Item` or `GlobalItem` for this client.
- Customer ID does not match any `CustomerProfile` for this client.
- Duplicate rows in the source file — only one row per `(item, customer, location, year, month)` is kept.

### Permission denied on a commerce view

Check `ClientGroupPermission` for the user's `ClientGroup`. The module key
(e.g. `order`) and action (e.g. `create`) must both be present. Also check
that django-guardian `view_client_data` permission is assigned to the user
for the client object.
