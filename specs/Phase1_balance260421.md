# Phase 1 — Remaining Implementation Plan

## How to Read This Document

Items are grouped into **sprints** ordered by dependency. A sprint should not start until all blockers from the previous sprint are resolved. Each item has:
- A **risk / complexity** tag: 🟢 Low · 🟡 Medium · 🔴 High
- A **type** tag: `[fix]` bug or gap · `[feature]` new capability · `[refactor]` structural change · `[infra]` deployment / ops
- **Acceptance criteria** — the definition of done

Dependencies between sprints are called out explicitly. Items within a sprint can be worked in parallel unless noted.

---

## Sprint 1 — Foundation Fixes (Do First, Unblocks Everything Else) - DONE

These are not features — they are structural gaps that will cause pain if done late. Do them before any new feature work.

---

### 1.1 — Split `settings.py` into base / development / production
**Type:** `[refactor]` · **Risk:** 🟡 Medium (easy to make, easy to get wrong)

**Why first:** Every other infra item (SECRET_KEY, DATABASE_URL, Redis, email, ALLOWED_HOSTS) goes into the split settings. Doing this last means touching settings multiple times.

**Steps:**
1. Create `mydj/settings/` package: `__init__.py`, `base.py`, `development.py`, `production.py`
2. Move current `settings.py` content into `base.py`. Remove `DEBUG=True`, `SECRET_KEY`, `DATABASES`, `ALLOWED_HOSTS`, `EMAIL_BACKEND`, `ACCOUNT_EMAIL_VERIFICATION`
3. `development.py`: imports `base`, sets `DEBUG=True`, `SECRET_KEY` from env (fallback to insecure dev key), SQLite `DATABASES`, `EMAIL_BACKEND = console`, `ACCOUNT_EMAIL_VERIFICATION = "optional"`, adds `debug_toolbar` to `INSTALLED_APPS` + middleware
4. `production.py`: imports `base`, sets `DEBUG=False`, `SECRET_KEY` from env (no fallback — raise if missing), `DATABASES` from `DATABASE_URL`, `ALLOWED_HOSTS` from env, `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`, Redis cache, `whitenoise` middleware, removes `debug_toolbar`
5. Update `manage.py` and `wsgi.py` / `asgi.py` to point to `mydj.settings.development` by default; PaaS env var overrides to `mydj.settings.production`
6. Update `TESTING` guard — move debug-toolbar conditional loading into `development.py` directly

**Acceptance criteria:**
- `python manage.py check` passes for both settings modules
- `SECRET_KEY` is not in any tracked file
- `debug_toolbar` is absent from the production config

---

### 1.2 — Verify `AppConfig` and app label consistency
**Type:** `[fix]` · **Risk:** 🟢 Low

**Why:** Silent app label mismatches corrupt migration history and ContentType records (which `mysite` relies heavily on for GenericForeignKey on `ComptextBlock`, `TextstbItem`, `GentextBlock`).

**Steps:**
1. Open `mysite/apps.py` — confirm `name = 'mysite'` and `label = 'mysite'`
2. Run `python manage.py migrate --run-syncdb` on a clean DB and verify no `ContentType` label conflicts
3. Check all existing migrations: `app_label` in `Migration` classes must be `'mysite'`, not `'myapp'` or anything else
4. Run `python manage.py showmigrations` — confirm no unapplied squashed migrations

**Acceptance criteria:**
- `python manage.py check` passes
- `ContentType.objects.filter(app_label='mysite').count()` returns the expected model count

---

### 1.3 — Wire cache invalidation signals
**Type:** `[fix]` · **Risk:** 🟡 Medium · **Blocks:** every content editing workflow

**Why:** Without this, edits made in Django Admin are silently ignored by the page renderer until the cache TTL expires (1 hour). This is a data integrity issue for any real content editing session.

**Steps:**
1. Create `mysite/signals.py`
2. Define a single handler `invalidate_client_cache(sender, instance, **kwargs)` that:
   - Determines `client_id` from the instance (direct FK or traversal up the tree)
   - Calls `cache.delete(f"clientstatic:{client_id}")`
3. Connect the handler via `post_save` and `post_delete` on: `Client`, `Theme`, `Page`, `Layout`, `Component`, `ComponentSlot`, `ComptextBlock`, `TextstbItem`, `SvgtextbadgeValue`
4. For nested models (`ComptextBlock`, `TextstbItem`, `SvgtextbadgeValue`), walk up to `client_id` via `content_object` chain — write a helper `get_client_id_from_instance(instance)` that handles all cases
5. Register signals in `mysite/apps.py` → `ready()` method
6. Restore `use_cache=True` in all `fetch_clientstatic()` call sites (currently hardcoded `False` in some places for debugging)

**Acceptance criteria:**
- Edit a `Component` field in Django Admin → save → next page load reflects the change without a server restart
- Unit test: save a `Page`, assert `cache.get("clientstatic:{client_id}")` is `None`

---

### 1.4 — Confirm URL routing is fully wired
**Type:** `[fix]` · **Risk:** 🟢 Low

**Steps:**
1. Run `python manage.py show_urls` (via `django-extensions`)
2. Verify these URL patterns exist and resolve correctly:
   - `/{client_id}/` → homepage
   - `/{client_id}/<page>/` → `ClientPageView`
   - `/{client_id}/login/` → `client_login`
   - `/{client_id}/signup/` → `client_signup`
   - `/{client_id}/logout/` → `client_logout`
   - `/{client_id}/profile/` → `customer_profile`
   - `/{client_id}/profile/addresses/` → `customer_addresses`
   - `/{client_id}/onboarding/` → `customer_onboarding`
3. Verify allauth URLs are mounted correctly and `SITE_ID=1` has the right domain in the DB

**Acceptance criteria:**
- `show_urls` output contains all routes above
- A browser request to `/{client_id}/login/` redirects to allauth login, not 404

---

## Sprint 2 — Page Rendering Completeness

Depends on: Sprint 1 complete.

---

### 2.1 — 404 handling for unknown client slugs and hidden pages - ✅ Done
**Type:** `[fix]` · **Risk:** 🟢 Low

**Current state:** `CustomerProfileMiddleware` catches `Client.DoesNotExist` and sets `request.client = None`, but views do not consistently handle this — they may raise `AttributeError` or return a confusing 500.

**Steps:**
1. In `CustomerProfileMiddleware`, if `client_id` is present in the URL but `Client.DoesNotExist` is raised: return `HttpResponseNotFound` immediately (short-circuit before the view)
2. In `ClientPageView.get()` (or `get_context_data`): if `page_dict` is empty (page not found or `hidden=True`), raise `Http404`
3. Create `templates/404.html` and `templates/500.html` with client-context-aware styling (use `client` from context if available, fall back to plain layout)
4. Set `handler404` and `handler500` in `mydj/urls.py`

**Acceptance criteria:**
- `GET /unknownclient/home/` → HTTP 404, renders `404.html`
- `GET /validclient/hiddenpage/` → HTTP 404
- `GET /validclient/doesnotexist/` → HTTP 404
- No 500s from missing `request.client`

---

### 2.2 — Homepage routing - ✅ Done
**Type:** `[feature]` · **Risk:** 🟢 Low

**Current state:** `/{client_id}/` has a `landing_page` view that renders a generic template with no client context.

**Steps:**
1. Add a `is_homepage` BooleanField to `Page` (default `False`) — or alternatively use `page_id = 'home'` as a convention (simpler, no migration needed)
2. In `mydj/urls.py`, wire `/{client_id}/` → a view that:
   - Looks up the first non-hidden page with `page_id='home'` for this client, or the first non-hidden page ordered by `order`
   - Redirects to `/{client_id}/{page_id}/`
3. Update `ClientPageView` to handle the home case

**Recommended approach:** Convention over configuration — `page_id='home'` is the homepage. No migration required. Document this in the admin.

**Acceptance criteria:**
- `GET /validclient/` → 302 redirect to `/{client_id}/home/` (or first page)
- If no pages exist: renders a placeholder "coming soon" template, not a 500

---

### 2.3 — Cotton component templates — audit and complete ✅ Done
**Type:** `[feature]` · **Risk:** 🟡 Medium

**Steps:**
1. Run `python manage.py show_urls` and load a page with each `comp_id` type in the DB
2. Audit `mydj/templates/` for cotton template files covering `hero`, `card`, `accordion`, `carousel`
3. For each missing template, create `templates/cotton/{comp_id}.html`:
   - Accept `component` dict from the `page_dict` context
   - Render `figure` slots (image + alt) and `text` slots (iterate `textblocks` → `items`)
   - Apply `css_class` from slot, component, and layout levels
   - Handle `hidden` flags (already filtered in `build_slot` but add template guard)
4. Test each component type end-to-end: DB record → `fetch_clientstatic` → template render → browser output

**Acceptance criteria:**
- A page with each of `hero`, `card`, `accordion`, `carousel` renders without template errors
- `hidden=True` components / slots are not rendered
- Multilingual content: switching language displays correct `SvgtextbadgeValue` for active language

---

### 2.4 — `django-modeltranslation` — confirm `translation.py` registrations ✅ Done
**Type:** `[fix]` · **Risk:** 🟡 Medium

**Steps:**
1. Check `mysite/translation.py` exists with `TranslationOptions` registered for: `Client` (`name`, `nb_title`), `Page` (`name`), `Theme` (`name`), `GlobalVal` (`keyval`)
2. Run `python manage.py sync_translation_fields` — confirm no missing columns
3. Run `python manage.py makemigrations --check` — confirm no pending migrations
4. In Django Admin, verify that translatable fields show per-language tabs/inputs

**Acceptance criteria:**
- `Client._meta.get_field('name_en')` does not raise `FieldDoesNotExist`
- `python manage.py migrate` runs clean with no errors


### 2.5 — NavItem model and decoupled navbar ✅ Done
- `NavItem` model with `get_url()`, modeltranslation on `name`
- `build_nav_item()` in `common_functions.py` with `href` vs `url` separation
- `fetch_clientstatic` prefetch updated
- `navbar_v001_l1recur.html` handles page / url / anchor / label nav_types
- `page_tree` retained in payload for sitemap use; navbar now driven by `header_nav`

---

## Sprint 3 — Auth Completion

Depends on: Sprint 1 complete.

---

### 3.1 — Staff login flow end-to-end
**Type:** `[feature]` · **Risk:** 🟡 Medium

**Current state:** Customer auth (login → onboarding → profile) is fully wired. Staff login is not — there is no `ClientUserProfile`-aware entry point or post-login redirect.

**Steps:**
1. Add a staff login entry point view: `/{client_id}/staff/login/` — sets `request.session['user_type'] = 'staff'` and redirects to `account_login`
2. In `ClientAwareAccountAdapter.get_login_redirect_url()`: check `session['user_type']`:
   - `'staff'` → redirect to Django Admin or a staff dashboard URL
   - `'customer'` → redirect to `/{client_id}/` or `session['login_redirect']`
3. Post-login: if `user_type='staff'` and `ClientUserProfile` does not exist for this user + client → show an error ("Your account is not authorised for this client"), do not create a profile silently
4. Staff logout: mirror `client_logout` logic for staff

**Acceptance criteria:**
- A staff user visiting `/{client_id}/staff/login/` → allauth login → Django Admin (or staff dashboard)
- A customer account attempting to use the staff login path → error message, not admin access
- Logout clears `user_type` from session

---

### 3.2 — `django-guardian` permission enforcement
**Type:** `[feature]` · **Risk:** 🔴 High · **Note:** Can be scoped to admin-only in Phase 1; full view enforcement in Phase 2

**Current state:** `django-guardian` is installed and `Client` has custom permissions defined, but no views or admin classes actually check object-level permissions.

**Phase 1 scope (admin only):**
1. In Django Admin for `Client`-related models (`Page`, `Theme`, `Layout`, `Component`), override `get_queryset()` to filter by `request.user`'s guardian permissions on `Client`
2. Create a `ClientAdminMixin` base class:
   ```python
   def get_queryset(self, request):
       qs = super().get_queryset(request)
       if request.user.is_superuser:
           return qs
       permitted_client_ids = get_objects_for_user(
           request.user, 'mysite.view_client_data', Client
       ).values_list('client_id', flat=True)
       return qs.filter(client__client_id__in=permitted_client_ids)
   ```
3. Apply `ClientAdminMixin` to all `ModelAdmin` classes that have a `client` FK
4. On `ClientUserProfile` creation (via admin), auto-assign `view_client_data` and `edit_client_data` object permissions to the user for their client

**Defer to Phase 2:** View-level guardian enforcement for customer-facing views (these are already scoped by `request.client` from middleware).

**Acceptance criteria:**
- A `ClientUserProfile` staff user in Django Admin can only see their own client's pages, layouts, components
- A superuser sees all clients
- A staff user cannot access another client's data by modifying a URL's PK

---

### 3.3 — `django-admin-sortable2` fully wired ✅ Done
**Type:** `[fix]` · **Risk:** 🟢 Low

**Steps:**
1. Audit all `ModelAdmin` classes for models with `order` fields: `Page`, `Layout`, `ComponentSlot`, `Theme`
2. For each, ensure the `ModelAdmin` inherits from `SortableAdminMixin` or `SortableInlineMixin` (for inlines)
3. Test drag-to-reorder in the browser for each

**Acceptance criteria:**
- Drag-to-reorder works in admin for `Page`, `Layout` (at each level), `ComponentSlot`, `Theme`
- Reordering persists to DB and is reflected in `fetch_clientstatic` output (after cache invalidation)

---

### 3.4 — Resolve `GentextBlock` status ✅ Done
**Type:** `[refactor]` · **Risk:** 🟢 Low

**Current state:** `GentextBlock` is defined in `models.py` but commented out of `build_client_payload`. It was the original mechanism for `Client.name` and `Page.name` — now superseded by `django-modeltranslation` fields directly on the model.

**Decision:** Remove `GentextBlock` in Phase 1.

**Steps:**
1. Confirm `GentextBlock` has no live data (check `GentextBlock.objects.count() == 0`)
2. Remove `GentextBlock` model from `models.py`
3. Remove all `GenericRelation(GentextBlock)` from `Client`, `Page`, `Theme`
4. Remove all `gentextblock_prefetch` references from `common_functions.py`
5. `python manage.py makemigrations` + `migrate`

**Acceptance criteria:**
- `python manage.py migrate` runs clean
- `python manage.py check` passes
- No references to `GentextBlock` remain in the codebase

---

## Sprint 4 — Language Switcher

Depends on: Sprint 1 + Sprint 2.3 (cotton templates) complete.

---

### 4.1 — Language switcher end-to-end ✅ Done
**Type:** `[feature]` · **Risk:** 🟡 Medium

**Current state:** `LocaleMiddleware` is in the middleware stack and `LANGUAGES` is configured, but there is no UI for switching language or persisting the selection per customer per client.

**Steps:**
1. Add a `set_language` view (mirrors `set_theme`):
   ```python
   @require_POST
   def set_language(request, client_id):
       lang = request.POST.get('language')
       client_obj = request.client
       if lang in (client_obj.language_list or []):
           request.session['django_language'] = lang
           translation.activate(lang)
       return redirect(request.META.get('HTTP_REFERER', '/'))
   ```
2. Wire URL: `/{client_id}/set-language/`
3. Persist `preferred_language` on `CustomerProfile.save()` when `active_role='customer'`
4. In `client_context` context processor: activate the correct language before building `page_dict` (currently translation activation may not happen before `fetch_clientstatic` resolves text)
5. Create cotton template `templates/cotton/language_switcher.html`:
   - Iterates `client.languages` (list of language codes from `fetch_clientstatic`)
   - Renders a POST form per language (or a `<select>`) pointing to `set_language`
   - Marks active language
6. Include `<c-language-switcher />` in `base.html` navbar

**Acceptance criteria:**
- A page with `SvgtextbadgeValue` records for `en` and `hi` renders the correct language based on session
- Switching language → page reloads with correct text
- `CustomerProfile.preferred_language` is updated on switch
- Language switcher only shows languages in `client.language_list`

---

### 4.2 — Theme switcher — clean up POST redirect ✅ Done
**Type:** `[fix]` · **Risk:** 🟢 Low

**Current state:** `set_theme` works via full-page POST/redirect. The commented-out Datastar implementation was removed. This is acceptable for Phase 1.

**Steps:**
1. Ensure `set_theme` URL is wired: `/{client_id}/set-theme/`
2. Create cotton template `templates/cotton/theme_switcher.html`:
   - Iterates `client.themes`
   - Renders a POST form per theme pointing to `set_theme`
   - Marks active theme
3. Include `<c-theme-switcher />` in `base.html`
4. **HTMX decision:** If HTMX is adopted (see 4.3), upgrade this to a partial swap. If not, the POST/redirect approach is sufficient for Phase 1.

**Acceptance criteria:**
- Theme switcher UI is visible in the navbar
- Selecting a theme → page reloads with new CSS custom properties injected

---

### 4.3 — HTMX evaluation spike
**Type:** `[feature]` · **Risk:** 🟢 Low (the spike itself) · 🟡 Medium (if adopted)

**Scope:** Evaluate HTMX for two specific use cases only: theme switcher (partial CSS var reload) and language switcher (partial content reload). Do not over-engineer.

**Steps:**
1. Install `django-htmx`: add to `requirements.txt`, add `HtmxMiddleware` to `MIDDLEWARE`
2. Implement theme switcher as an HTMX partial: `set_theme` returns `partials/theme_vars.html` (injects `<style>` tag with CSS vars) instead of a redirect
3. Implement language switcher as an HTMX partial: `set_language` returns the updated navbar text fragment
4. Compare: is the complexity justified vs POST/redirect? HTMX is the right choice if you want to avoid full page reloads for these interactions.

**Decision criteria:** Adopt HTMX if the spike takes <1 day and the result is clearly better. Otherwise, keep POST/redirect — it works.

**Acceptance criteria:**
- Theme switch does not cause a full page reload (HTMX path)
- Or: decision is made and documented: "HTMX adopted / not adopted for Phase 1, reason: ..."

---

## Sprint 5 — Production Hardening

Depends on: Sprints 1–4 complete. This sprint makes the app deployable to PaaS.

---

### 5.1 — `whitenoise` static files
**Type:** `[infra]` · **Risk:** 🟢 Low

**Steps:**
1. `pip install whitenoise`, add to `requirements.txt`
2. In `production.py`: add `whitenoise.middleware.WhiteNoiseMiddleware` immediately after `SecurityMiddleware`
3. Set `STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'`
4. Set `STATIC_ROOT = BASE_DIR / 'staticfiles'`
5. Run `python manage.py collectstatic` locally — verify output in `staticfiles/`

**Acceptance criteria:**
- `python manage.py collectstatic` exits 0
- On PaaS, `GET /static/admin/css/base.css` returns 200 (not 404)

---

### 5.2 — PostgreSQL wiring
**Type:** `[infra]` · **Risk:** 🟢 Low

**Steps:**
1. In `production.py`, replace `DATABASES` with:
   ```python
   import dj_database_url
   DATABASES = {'default': dj_database_url.config(conn_max_age=600)}
   ```
2. Add `dj-database-url` and `psycopg2-binary` to `requirements.txt`
3. On Railway/Render: provision a PostgreSQL instance, copy `DATABASE_URL` into the service's env vars
4. Run `python manage.py migrate` against production DB — verify all migrations apply cleanly
5. Create a superuser on production: `python manage.py createsuperuser`

**Acceptance criteria:**
- `python manage.py dbshell` connects to PostgreSQL (not SQLite) on PaaS
- All migrations applied: `python manage.py showmigrations` shows no `[ ]` entries

---

### 5.3 — Redis cache in production
**Type:** `[infra]` · **Risk:** 🟢 Low

**Steps:**
1. On Railway/Render: provision a Redis instance, copy `REDIS_URL` into env vars
2. In `production.py`, uncomment and update the Redis cache config:
   ```python
   CACHES = {
       "default": {
           "BACKEND": "django.core.cache.backends.redis.RedisCache",
           "LOCATION": env("REDIS_URL"),
       }
   }
   ```
3. Verify `fetch_clientstatic` cache hits in production logs

**Acceptance criteria:**
- A cold request populates the Redis cache
- A warm request returns from cache (verify via debug logs or Redis `MONITOR`)

---

### 5.4 — PaaS deployment and `manage.py check --deploy`
**Type:** `[infra]` · **Risk:** 🟡 Medium

**Steps:**
1. Create `Procfile` (Heroku/Railway/Render format):
   ```
   web: gunicorn mydj.wsgi --log-file -
   release: python manage.py migrate
   ```
2. Set all required env vars on PaaS: `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`, `DJANGO_SETTINGS_MODULE=mydj.settings.production`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
3. Run `python manage.py check --deploy --settings=mydj.settings.production` locally — fix all warnings
4. Push to PaaS — verify build passes, migrations run, gunicorn starts
5. Visit `/{any_client_id}/` — verify page renders correctly

**Acceptance criteria:**
- `manage.py check --deploy` → 0 errors, 0 warnings
- PaaS deploy pipeline: push → build → migrate → serve in under 3 minutes
- A page with a hero component renders correctly in production

---

### 5.5 — Smoke tests and README
**Type:** `[infra]` · **Risk:** 🟢 Low

**Steps:**
1. Write `tests/test_smoke.py` covering:
   - Tenant resolution: `GET /{valid_client_id}/home/` → 200
   - Unknown client: `GET /unknownclient/home/` → 404
   - Auth: `GET /{client_id}/login/` → 200
   - Customer signup flow: POST to `account_signup` → `CustomerProfile` created
   - Cache invalidation: save a `Page`, assert cache is cleared
2. Write `README.md`:
   - Local dev setup (clone, install, `manage.py migrate`, `manage.py tailwind start`)
   - How to create a client and first page in Django Admin
   - PaaS deploy steps
   - Env var reference table

**Acceptance criteria:**
- `python manage.py test tests/test_smoke.py` → all pass
- A new developer can get the app running locally following only the README

---

## Dependency Graph

```
Sprint 1 (Foundation)
    ├── 1.1 Settings split        ←── blocks all infra work
    ├── 1.2 AppConfig verify      ←── blocks migration work
    ├── 1.3 Cache signals         ←── blocks content editing
    └── 1.4 URL routing verify    ←── blocks auth + rendering work

Sprint 2 (Page Rendering)         ←── needs Sprint 1
    ├── 2.1 404 handling
    ├── 2.2 Homepage routing
    ├── 2.3 Cotton templates
    └── 2.4 modeltranslation audit

Sprint 3 (Auth Completion)        ←── needs Sprint 1
    ├── 3.1 Staff login
    ├── 3.2 Guardian enforcement
    ├── 3.3 Sortable admin
    └── 3.4 GentextBlock removal

Sprint 4 (Language + Theme)       ←── needs Sprint 2 + Sprint 3
    ├── 4.1 Language switcher
    ├── 4.2 Theme switcher cleanup
    └── 4.3 HTMX spike

Sprint 5 (Production Hardening)   ←── needs all above
    ├── 5.1 Whitenoise
    ├── 5.2 PostgreSQL
    ├── 5.3 Redis cache
    ├── 5.4 PaaS deploy
    └── 5.5 Smoke tests + README
```

---

## Risk Summary

| Item | Risk | Reason |
|------|------|--------|
| 1.3 Cache invalidation signals | 🟡 | Walking GenericForeignKey chains to get `client_id` is non-trivial |
| 2.3 Cotton templates | 🟡 | Requires matching template structure to the `fetch_clientstatic` dict shape precisely |
| 3.2 Guardian enforcement | 🔴 | Easy to get wrong and accidentally block legitimate admin users; start with superuser bypass |
| 3.1 Staff login | 🟡 | Session state (`user_type`) interacts with allauth adapter in subtle ways |
| 4.1 Language switcher | 🟡 | Translation activation must happen before `fetch_clientstatic` builds text; ordering in middleware/context processor matters |

---

## Items Deliberately Deferred to Phase 2

These appeared in Phase 1 milestone checklists but are not blocking a Phase 1 release:


- Full guardian enforcement on customer-facing views — middleware scoping is sufficient for Phase 1
- HTMX adoption beyond theme/language switcher — POST/redirect is acceptable for all other forms in Phase 1