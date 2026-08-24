# SQLite → PostgreSQL Migration Plan

**Project:** djlite (demand planning) — repo `/home/govidat/Documents/learning/djlite`
**Target:** PostgreSQL 17 (already running on `localhost:5432`, data dir `/var/lib/pgsql/17/data/`)
**Decisions locked in:** preserve existing data via `dumpdata` · user runs `sudo` for role creation · dev + tests fully on Postgres · DB name **`djlite_dev`**

## Audit results (why this works with zero app-code changes)
- Only SQLite-related code note is `utils/demand/compute_series_profiles.py:621-627` (comment about `bulk_create` `RETURNING`). It is **Postgres-first, not SQLite-specific** — Django 5.2 returns PKs on both backends. `SeriesProfile.chosen_evaluation` will now populate correctly (was NULL on SQLite).
- `SeriesProfile.objects.bulk_create(update_conflicts=True, unique_fields=...)` (line 702) — supported on both.
- All Postgres composite indexes in migrations are pre-written and guarded by `vendor != 'postgresql'` — they no-op on SQLite and will activate on Postgres.
- No `django.contrib.postgres` fields, no raw SQL, no SQLite functions, no `.extra()`. DuckDB is in-memory only. `JSONField` is portable.

## Status snapshot when resuming
- Settings: `mydj/settings/development.py` hardcodes SQLite. `manage.py`/`wsgi.py`/`asgi.py` all use `mydj.settings.development`.
- Current SQLite data (to be preserved): 6 clients, 24 items, 2812 actual sales, 5330 forecast lines, 78 series profiles, 312 evaluations, 468 accuracy rows, 24 versions.
- No `psycopg` driver installed; no `dj-database-url`.
- `db.sqlite3` is git-tracked.

---

## Phase 0 — Backup (do first, still on SQLite)
```bash
cp db.sqlite3 /tmp/djlite-sqlite-backup.sqlite3
```

## Phase 1 — Provision Postgres (requires sudo)
```bash
# 1. pick a dev password once, e.g. export PGPASS='welcome'
sudo -u postgres psql -c "CREATE ROLE djadmn WITH LOGIN PASSWORD 'welcome' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE djlite_dev OWNER djadmn;"
```
`CREATEDB` is required so pytest can auto-create `test_djlite_dev`.

## Phase 2 — Dump data from SQLite (BEFORE switching settings)
```bash
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude=contenttypes --exclude=admin.logentry --exclude=sessions \
  --exclude=django_celery_results.tasksresult \
  -o /tmp/djlite_dump.json
```
(Excludes regenerable/noise tables; permissions/contenttypes are recreated by `migrate`'s post_migrate.)

## Phase 3 — Switch settings
1. `requirements.txt`: add line `psycopg[binary]>=3.2`, then `.venv/bin/pip install "psycopg[binary]"`
2. `mydj/settings/development.py` — replace the `DATABASES` block:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'djlite_dev',
        'USER': 'djadmn',
        'PASSWORD': 'welcome',          # match Phase 1
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
# Rollback (SQLite):
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }
```
3. (Optional, for later deploy) `production.py`: uncomment the `dj_database_url` block and add `dj-database-url` to requirements.

## Phase 4 — Migrate + load + reset sequences
```bash
python manage.py migrate
python manage.py loaddata /tmp/djlite_dump.json
python manage.py sqlsequencereset mysite auth account admin contenttypes sites | python manage.py dbshell
```
- `migrate` applies all 77 mysite migrations + third-party; creates the 5 guarded composite indexes.
- `sqlsequencereset` fixes Postgres sequences after the load.

## Phase 5 — Verify
```bash
.venv/bin/python -m pytest mysite/tests/demand -q --tb=short
```
- Auto-creates `test_djlite_dev`. Watch for: tests asserting SQLite-specific error strings (e.g. "UNIQUE constraint failed"), Decimal strictness. Fix if any appear.
- Smoke test: `python manage.py runserver` → load a version page → run one series-profile computation + one forecast run on a demo version; confirm `SeriesProfile.chosen_evaluation` is populated (was NULL on SQLite).

## Phase 6 — Cleanup
```bash
git rm --cached db.sqlite3
# uncomment/add "db.sqlite3" to .gitignore
mv db.sqlite3 /tmp/db.sqlite3.retired   # backup already in /tmp
```

## Rollback (if anything goes wrong)
1. Revert `development.py` `DATABASES` to the commented SQLite block.
2. Restore: `cp /tmp/djlite-sqlite-backup.sqlite3 db.sqlite3`
3. Leave the Postgres role/DB in place or drop via: `sudo -u postgres psql -c "DROP DATABASE djlite_dev;" -c "DROP ROLE djadmn;"`

---

## Execution log (2026-08-13)
✅ **Completed.** All phases executed; 211/211 tests pass on Postgres; smoke test OK.

### Deviations / fixes applied along the way
- **`pip` missing in `.venv`** (uv-created venv) → bootstrapped via `python -m ensurepip`, then installed `psycopg[binary]`.
- **`django_celery_results.tasksresult` wrong exclude** → actual model is `django_celery_results.taskresult`.
- **Latent bugs in 3 guarded Postgres index migrations** (never fired on SQLite, all in `vendor != 'postgresql'` blocks):
  - `0021` & `0024`: `documentitem_format_idx` / `serviceitem_fulfillment_type_idx` used `WHERE artist != ''` (copy-paste) → corrected to `format` / `fulfillment_type`.
  - `0024`: `item_global_item_idx` had a stray trailing `'`.
  - `0048`: three `ON  ON` double-keyword typos + leftover `REPLACE #` editor comments.
- **`dumpdata --natural-primary` breaks `auth.permission`** (`Permission.natural_key()` calls `content_type` during deserialization, but only `content_type_id` is set) → re-dumped **without** `--natural-primary` (kept `--natural-foreign`).
- **Fixtures + signals**: loading `ClientUserMembership`/`ClientGroup` fired `post_save` → `_sync_user_guardian_perms` (`assign_perm`/`remove_perm`), colliding with the fixture's guardian rows. Loaded with the 4 guardian receivers (`membership_saved`, `membership_deleted`, `group_saved`, `group_deleted`) disconnected, so the fixture's guardian data loads verbatim.

### Data deliberately excluded (dead/stale rows referencing removed models)
| Item | SQLite | Postgres | Why |
|---|---|---|---|
| `auth_permission` | 338 | 326 | excluded from fixture; regenerated by `migrate`. The 12 extra are stale (removed models) |
| `auth_user_user_permissions` | 351 | 347 | 4 stale `*_customersalesassignment` (model renamed → `planningcustomer`) |
| `mysite_textstbitem` | 10 | 4 | 6 empty rows referencing deprecated `GentextBlock` (unregistered, see `models/__init__.py:43`) |
| `mysite_svgtextbadgevalue` | 10 | 4 | 6 empty rows whose `textstbitem` FK pointed at the removed stubs |

All other tables match SQLite exactly (verified per-table counts). Rollback data intact at `/tmp/djlite-sqlite-backup.sqlite3`; retired `db.sqlite3` at `/tmp/db.sqlite3.retired`.

### Smoke test (all on Postgres real data)
- `compute_series_profiles.run(3, 'month')` → **`chosen_evaluation` now populates** (was NULL on SQLite); 48 profiles classified.
- `run_forecast.run(11)` on a never-run draft → `COMPLETE`, 288 forecast lines, 162 aggregates.


### Drill down 
Exact files for the drill-down/tree filter functionality:
Views (server endpoints)
- mysite/views/taxonomy_tree.py — taxonomy panel + lazy children (taxonomy_tree_panel, taxonomy_tree_children), _ancestor_ids_to_expand (line 38)
- mysite/views/sales_tree.py — sales panel + lazy children (sales_tree_panel, sales_tree_children), _ancestor_ids_to_expand (line 28)
- mysite/demand_ui/views.py:789-827 — wires selected node ids to subtree DB queries (get_sales_node_subtree_ids_multi, resolve_node_subtree_ids_multi)
Templates
- templates/taxonomy_tree/partials/taxonomy_tree_node.html — recursive node (checkbox, toggle, lazy hx-get)
- templates/taxonomy_tree/partials/taxonomy_tree_children.html — children partial swapped by htmx
- templates/taxonomy_tree/partials/taxonomy_tree_panel.html — whole panel
- templates/demand/partials/aggregates_filter_bar.html — aggregate tree containers + applyFilters
- templates/demand/partials/actuals_aggregates_filter_bar.html — actuals variant
- templates/demand/partials/actuals_filter_bar.html, lines_filter_bar.html, series_filter_bar.html — other tree uses
Helpers
- utils/taxonomy_filters.py — parse_node_ids_param + subtree id resolution
- utils/demand/hierarchy_utils.py — get_sales_node_subtree_ids_multi
Client-side
- mysite/static/admin/js/taxonomy_tree.js — cascade + expand/collapse logic
- mysite/static/admin/css/taxonomy_tree.css — tree styling

Drill-down params are never stored on a version. They're purely URL query params (?sales_node_ids=...&taxonomy_node_ids=...) on the Value Summary page:
- Every link into that page (the "Value Summary" tab at templates/demand/version_detail.html:86, and the level tabs at templates/demand/version_aggregates.html:21) opens with no params, so the trees start empty.
- The view only reads them from request.GET (mysite/demand_ui/views.py:788-796), and the tree panels load from those same params (aggregates_filter_bar.html:129-152).
So the earlier versions "had" drill-down parameters only because you'd selected tree nodes on those pages and the selections were sitting in the URL / page state. The moment you navigate to a fresh version (or reload), the trees clear — no data was ever saved for any version.
Also note the tree only appears when agg_level is sales or item_hierarchy; at the default total level there's no drill-down at all.
To get the same drill-down on "2601-2606 accuracy": open its Value Summary → pick Sales or Item Category level → re-tick the tree nodes. The filtering then applies exactly like the earlier versions. If you want to reuse the exact same selection, copy the URL from an earlier version's page (it contains the params) and paste it for the new version — that will re-apply the same drill-down instantly.