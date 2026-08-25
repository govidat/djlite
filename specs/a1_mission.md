# Mission

## Product Vision

Build a multi-tenant SaaS CMS platform that empowers small and medium enterprises (SMEs) to create, manage, and publish multi-language web presences — without needing developer involvement for day-to-day content operations.

The platform starts as a page-builder CMS and grows incrementally into a full-featured digital commerce solution.

---

## Core Goals

### 1. Multi-Tenant Client Onboarding
- The platform hosts multiple SME clients under a single deployment.
- Each client operates in a fully isolated context: their own pages, users, content, themes, and settings.
- Clients are accessed via path prefix routing: `/{client_id}/`.
- Tenant identity is resolved on every request by `CustomerProfileMiddleware`, which attaches `request.client` (a `Client` instance) from URL kwargs, with a session fallback. Context processors consume `request.client` without re-querying.
- Clients support a **parent-child hierarchy** (`Client.parent` self-FK) enabling sub-client or franchise structures.

### 2. Responsive & Cross-Platform
- All client-facing pages must be fully responsive across desktop, tablet, and mobile viewports via Tailwind CSS.
- The architecture is designed not to block a future native mobile app. The `fetch_clientstatic()` payload (a plain Python dict) is already decoupled from the HTTP layer and is suitable for a future API layer.

### 3. Fully Dynamic Multi-Language Support
- Languages are configured globally in `settings.LANGUAGES` (currently: `en`, `hi`, `fr`, `ta`).
- Per-client active languages are stored in `Client.language_list` (a JSONField array of language codes).
- Translatable model fields (e.g. `name`, `nb_title` on `Client`, `Page`, `Theme`) are expanded by `django-modeltranslation` into per-language DB columns (`name_en`, `name_hi`, etc.) in the same table.
- Component text content uses a separate multi-level translation model: `ComptextBlock` → `TextstbItem` → `SvgtextbadgeValue` (keyed by `language_code`). This handles rich per-component multilingual text without modeltranslation overhead on content fields.
- UI strings are managed via `GlobalVal` / `GlobalValCat` (a key-value store), resolved per language through the `gv` template context variable.
- Language fallback order: requested language → `settings.LANGUAGE_CODE` (`en`) → first available.

### 4. Composable Page Builder

The platform supports two parallel page authoring tracks. Both coexist on the same `Page` model and can be mixed across pages within the same client site.

**Track A — Raw HTML (Phase 1 primary authoring path)**
- A `PageContent` model stores a raw HTML blob per page per language (`language_code` + `html` fields).
- HTML is authored outside Django using any visual tool (Figma exports, Pinegrow, Locofy, hand-coded) and pasted into Django Admin.
- The renderer checks for a `PageContent` record first; if found, it renders the blob directly via `{{ content.html|safe }}`.
- Multilingual: one `PageContent` row per language per page. Language resolution follows the standard fallback: active language → `en` → first available.
- The navbar is decoupled from the page tree via a dedicated `NavItem` model.
  Client-facing navigation (header, footer, sidebar) is configured independently
  of which pages exist, allowing external links, label-only groupings, and
  different ordering from the page hierarchy.
- This track is used for all Phase 1 pages where the developer controls content.

**Track B — Structured Component Tree (Phase 2+ client-managed content)**
- Clients construct pages from a nested content hierarchy:
  ```
  Client → Page → Layout (Section / Row / Col / Cell) → Component → ComponentSlot
  ```
- `Layout` is a single self-referential model with a numeric `level` field (`10=Section`, `20=Row`, `30=Col`, `40=Cell`), avoiding separate Section/Row/Column/Cell tables.
- `Component` (OneToOne to a `level=40` Layout) carries the component type (`hero`, `card`, `accordion`, `carousel`) and all component-level styling fields.
- `ComponentSlot` (FK to `Component`) is either a `figure` slot (image URL + alt) or a `text` slot (linked to `ComptextBlock` via GenericRelation for multilingual copy).
- The full page + theme payload is serialised into a cacheable Python dict by `fetch_clientstatic()` and delivered to templates via the `client_context` context processor.
- This track is used for pages requiring structured, queryable, client-editable content.

Both `Page` and `Client` support a self-referential parent-child hierarchy for nested navigation trees regardless of which track is used.

### 5. Theme System
- Themes are per-client (`Theme` FK to `Client`), referencing a system `ThemePreset` for base design tokens.
- Per-client token overrides are stored in `Theme.overrides` (JSONField) and resolved at runtime by `resolve_theme()`.
- Tokens cover colour, typography, spacing, border-radius, and shadows — injected as CSS custom properties into `base.html`.
- Active theme is stored in `request.session['active_theme_id']` and resolved by the `client_context` context processor on every request.

### 6. Two-Tier User Model
- **Client Users** (`ClientUserProfile`): Staff of the SME client. Uses Django's built-in `User` with a `OneToOneField`. Scoped exclusively to one client. Role-based access managed via `ClientGroup` (roles: `admin`, `staff`, `viewer`) with optional location scoping via `ClientLocation`.
- **Customer Users** (`CustomerProfile`): End-users of the client's site. Uses a `ForeignKey` to `User` (not OneToOne), so one Django `User` can be a customer of multiple clients. Each client relationship is an isolated profile with `preferred_language`, `preferred_theme`, and linked `CustomerAddress` records.
- `ClientGroup` → `ClientGroupPermission` provides module-level (e.g. `cms`, `cart`, `order`) and action-level (`view`, `create`, `edit`, `delete`) permissions per group, with optional `ClientLocation` scoping.
- `ClientUserMembership` assigns users to groups; `clean()` enforces cross-client integrity.
- `django-guardian` provides object-level permissions on `Client` (custom permissions: `view_client_data`, `edit_client_data`, `create_client_data`, `admin_client_data`).
- Both user types flow through `django-allauth` with a custom `ClientAwareAccountAdapter`.
- The active role (`staff` / `customer` / `None`) is resolved on every request by middleware and stored on `request.active_role`.

### 7. Phased Feature Expansion

| Phase | Scope |
|-------|-------|
| 1 | Multi-tenant CMS: page builder, multilingual content, theme system, user auth — **substantially complete** |
| 2 | Generic Item Catalogue: domain-agnostic items, multi-taxonomy, HTMX faceted filters — **complete** |
| 3B | Demand Planning: actuals ingestion, scheme management (planned promo uplift + scheme-netted baseline), item lifecycle (substitution with qty conversion, discontinuation, new-item introduction), outlier detection and planner-confirmed net actuals, statistical forecasting, hierarchical reconciliation, consensus override — **substantially complete** |
| 3A | eCommerce: Inquiry → Quotation → Order lifecycle, SAP-style pricing engine, Beckn-aligned models — **in progress** |
| 3C | **Inventory Decision Engine**: policy-driven replenishment, multi-echelon supply network propagation, MRP-style netting, DDMRP, vendor-scheme cost optimization, exception-driven planner workbenches — **builds after 3B; consumes `OPERATING_PLAN` forecasts only, never `SALES_CONSENSUS`; independent of 3A except for shared `Item`/`ClientLocation` master data** |
| 4 | Beckn / ONDC network participation: BPP role, async callbacks, digital signatures, ONDC registry; probabilistic forecasting; ML demand models |


## Non-Goals (Phase 1)

- No native mobile app (responsive web only).
- No drag-and-drop visual page editor — HTML is authored externally and pasted in. The structured component editor is built in Phase 2.
- No payment processing.
- No product catalogue.
- No subdomain or custom domain routing (path-prefix only).

---

## Success Criteria (Phase 1)

- A new client can be onboarded and publish a multilingual, multi-page site by pasting HTML into Django Admin — no code changes required.
- Pages authored via `PageContent` (Track A) and pages authored via the component tree (Track B) both render correctly from the same `Page` model.
- Client staff can manage content via Django Admin with role and location-based access control.
- Customer users can register, log in, and maintain separate profiles per client.
- Pages render correctly on mobile, tablet, and desktop.
- `fetch_clientstatic()` serves a fully cached payload describing a client's pages, themes, and content tree with no N+1 queries.
- Deployment to PaaS (Railway / Render) is automated via a single git push.

## Phase 2 Addition — Generic Item Catalogue
 
### 8. Generic Item Catalogue
- Items are domain-agnostic (`Item` model) — can represent products, projects,
  songs, or documents. Domain-specific fields go in a `attributes` JSONB field.
- Items can be **global** (available to all clients) or **client-specific**.
  Client-specific items override global items of the same `item_id`.
- Multiple independent hierarchies (Category, Geography, Department, etc.)
  are supported via a `Taxonomy` / `TaxonomyNode` model using **materialized
  path** for efficient subtree queries.
- Items are tagged to taxonomy nodes via `ItemTaxonomyNode` (M2M).
- Faceted filter sidebar (checkbox per node, HTMX-powered, no page reloads).
- Catalogue pages support both Track A (raw HTML blob) and Track B
  (component tree) — same dual-track pattern as regular pages.
- `ItemVariant` model is included for Phase 3 eCommerce readiness.
  `CartItem` and `OrderItem` will FK to `Item` / `ItemVariant` in Phase 3.
- Two-tier item catalogue: GlobalItem (superuser, GS1-aligned) + Item (client-derived)
- GS1 GPC 4-level hierarchy: Segment → Family → Class → Brick
- Attribute inheritance: TaxonomyNode attrs inherited by items, overridable at item level
- Client can reference and derive from global items and global taxonomy nodes  

### 8a. Client Sector Classification
- Each Client is classified by industry via a dedicated global `sector`
  taxonomy (e.g. Industrial > Automotive > AutoComponents) — reuses the same
  `Taxonomy` / `TaxonomyNode` machinery, no new hierarchy code.
- `Client.sector` points at the deepest matching node; ancestor walk enables
  most-specific-wins behaviour for anything keyed by sector.
- First consumer: `SectorTemplate` — DB-owned template defaults resolved by
  client override → sector chain → global default (see tech-stack doc).

### 8b. Country Dimension

The platform supports multi-country websites for clients that operate across
national borders. Country is an optional, opt-in dimension — clients that serve
a single market leave it disabled and incur zero overhead.

**Core models:**
- `Country` (PK = ISO 3166-1 alpha-2 code, e.g. `IN`, `US`, `FR`) — global
  lookup, superadmin-managed. Seeded with IN, US, FR, DE, MY.
- `Client.allowed_countries` — JSONField, null = country disabled, list of
  ISO codes = enabled.
- `Client.default_country_code` — fallback when no session country is set.

**Session-based active country:**
- `request.session['active_country_code']` — resolved on every request by
  `CustomerProfileMiddleware`, validated against `Client.allowed_countries`.
- `set_country` POST view — sets the session, validates against allowed list.

**Template resolution:**
- `SectorTemplate` and `ClientTemplate` gain a nullable `country` FK.
- Resolution order becomes: client+country → client+NULL → sector+country →
  sector+NULL → global+country → global+NULL.
- Cache key includes country code (`client_template:{id}:{key}:{country}`).

**UI:**
- Navbar country switcher (`select_country.html` cotton component) — dropdown
  showing flag emoji + country name for each allowed country.
- Footer displays active country flag and name.
- Country selector shown only when `Client.is_country_enabled()` and >1 country.

**Geo-detection:**
- On first authenticated visit (no session country), IP-based geo-detection
  via `django-geoip2` + `django-ipware` sets the session country.
- Detected country must be in `Client.allowed_countries` to be used.

## Phase 3B Demand Planning Module
 
#### Business Context
 
Each Client has:
- A **Customer base** (200 customers) purchasing from multiple **Client Locations** (warehouses / branches).
- A **Sales Hierarchy** — a dedicated tree of sales reps/managers through which each Customer is serviced, independent of which physical location ships to them.
- **36 months of historical actuals** at two granularities:
  - **SKU × Customer × Location × Month** (transaction-level granularity).
  - **Location × Month** (summary-level actuals, available even where SKU-level detail is absent).
The module generates statistical forecasts, allows business consensus overrides at any hierarchy level, and produces a final agreed forecast that can flow directly into Purchase Orders and production plans.
 
#### Hierarchy Architecture
 
Three independent hierarchies operate in parallel on the same Item and Customer base:
 
**Product Hierarchy** — extends the existing `Taxonomy` / `TaxonomyNode` system.
A dedicated Taxonomy slug `product_planning` carries the 3–5 level product grouping used in forecasting (Category → Sub-category → Brand → SKU). This reuses Phase 2 infrastructure without new models. If a separate 'product_planning' is not used then the generic 'gpc' to be used. Alternatively the hierarchy to be used for planning purpose to be part of the Client Master (TBD).
 
**Geography / Location Hierarchy** — extends `ClientLocation`.
`ClientLocation` gains a `parent` self-FK (nullable) enabling a Region → Branch → Location tree. Depth is unrestricted; materialized path is added alongside the FK for efficient subtree queries (same pattern as `TaxonomyNode`).
Important change: This Location Hierarchy is not relevant for forecasting purpose. This can be dropped and the Sales Hierarchy alone to be used for aggregation. Leaf location from which a Customer is served to be part of the forecast process as we want the independent demand to be captured at that level. Any sale to be mapped to the lowest level in the Sales Hierarchy. Simplest is a one to one mapping with the location. Else Customer Groups to be maintained and linked to the lowest in Sales Hierarchy.
 
**Sales Hierarchy** — new model tree.
`SalesNode(client, name, level_label, parent→self, location→ClientLocation nullable)` represents the org chart of the sales force. (Deprecated — `CustomerSalesAssignment(customer, sales_node, valid_from, valid_to)` assigns each Customer to a leaf SalesNode with date effectivity.)
`SalesForecastLink(client, planning_location, distribution_channel, planning_customer, sales_node, valid_from, valid_to)` maps the demand-planning dimensions to a SalesNode with date effectivity. Three shapes are supported: location + distribution_channel + planning_customer, location + distribution_channel, and location only (PlanningCustomer and DistributionChannel nullable). `SalesForecastLinkAdmin` exposes `client, planning_location, distribution_channel, planning_customer` as fields with list filters on `client, distribution_channel, valid_to`.

Demand Planning to be a stand alone module and hence Customer data to be independent of CustomerProfile which is eCommerce dependent. Let a standalone Client level Customer Hierarchy be maintained for Demand Planning. This can be an arbitrary planning level Customer Hierarchy and data to be pushed directly and does not have any linkage to eCommerce sales. 
Item hierarchy to flow from catalog module that is already in place. 
Sales team hierarchy to be made separately for this module. 
Separate Client Location hierarchy to be made for this stand alone Demand Planning module. This also need not have any direct link with ClientLocation model which has operational siginificance for eCommerce. 
At the lowest level, demand data will be maintained at  Planning Location, Item, Customer level (can included specific Customers or a planning Customer to represent a group of unspecified Customers). As a result of Demand Planning forecast data is expected at Location / Item level at the minimum and if required at Location / Customer / Item level.
 
#### Data Ingestion Models
  
| Model | Key Fields | Notes |
|-------|-----------|-------|
| `ActualSale` | client, planning_location, item (→ `Item`), planning_customer (nullable), distribution_channel, period_type, period_start, qty, revenue (Decimal, nullable) | Row = one planning_location × item × planning_customer × distribution_channel × period. `period_end` auto-computed from `period_start` + `period_type`. `import_batch` FK links each row to its upload job. |
| `ActualSaleLocation` | client, planning_location, period_type, period_start, total_qty, total_revenue | Summary-level actuals; used when item-level detail is unavailable |
| `ActualSaleImport` | client, uploaded_by, uploaded_at, file_name, period_type, row_count, status (pending/processing/done/failed), error_log | Import job tracking; one `import_batch` FK on every `ActualSale` / `ActualSaleLocation` row |

Both `ActualSale` and `ActualSaleLocation` are written by an **idempotent bulk upsert** keyed on the natural grain: the import service performs a bulk `ON CONFLICT DO UPDATE` (equivalent of `INSERT ... ON CONFLICT DO UPDATE`), so re-importing the same source file re-applies values without duplicating rows. Corrections are made by re-importing corrected values (or via Django Admin); there is no append-only delta/ledger layer and no `resolved_actuals` view.

`ActualSale` unique constraint on `(client, planning_location, item, planning_customer, distribution_channel, period_type, period_start)` — enforced at DB level. A supporting composite index `ix_actualsale_grain_lookup` covers the same key for the forecast engine's natural-key lookups. `planning_customer = NULL` is allowed (demand for "unspecified customers"); `distribution_channel` defaults to `'00'` (Common).

#### Outlier Management (Actuals Exception Handling)

Real actuals occasionally contain one-off events (bulk sales, data-entry errors, partial-period anomalies) that should not shape the statistical baseline. This is handled as a hybrid system/planner workflow, not a pure automated filter and not a pure manual review queue.

Design principle: ActualSale remains exactly as documented — one row per client × planning_location × item × distribution_channel × planning_customer × period_type × period_start combination, enforced by the existing unique constraint. Outlier handling is a separate, additive layer that never mutates or deletes an actual row.

One-to-one adjustment. Each outlier adjustment is a single mutable record tied one-to-one to the specific ActualSale row it adjusts (OneToOneField), not a separately-keyed grain match. Since ActualSale rows don't duplicate at this grain, this is a clean 1:1 — no aggregation across rows is needed to compute a net position for a given row.
Partial exclusion. An adjustment is not all-or-nothing. The planner records how much of the row's qty/revenue is attributable to the one-off event — e.g. 400 of 500 qty and 3,500 of 5,000 revenue — rather than excluding the whole row. Qty and revenue adjustments are captured independently, since a bulk order often carries a different unit rate than the row's normal mix. Revenue adjustment is optional, mirroring ActualSale.revenue being nullable.
Detection. Detection is planner-triggered, not import-driven: the planner picks a period range on the Outlier Detection form and the system proposes candidate rows via a residual-based statistical pass (MAD thresholding on `ForecastingConfig.mad_threshold`, with a persistence check — a value that persists across `persistence_periods` is treated as a regime change and left alone). The system only ever proposes `CANDIDATE` rows; it never auto-confirms. Rows already carrying an adjustment are skipped 1:1 and never re-proposed, so re-running detection is idempotent. Detection range, run identity, and timing are recorded on `ForecastingConfig` (`last_outlier_detection_run_at/by/range_start/range_end`).
Detection sensitivity is Client-configurable via `ForecastingConfig.mad_threshold` / `persistence_periods` / `min_history_periods`, seeded from a system starter default — the same reused pattern as the existing per-Client SEIL/ADI-CV² thresholds.
Planner review queue. Planners confirm, reject, or revise system-detected candidates from an HTMX outlier queue (filterable by CANDIDATE / CONFIRMED / REJECTED), and may discard candidates in bulk (selected or the whole filtered set). Decisions can be undone (`undo` restores a CANDIDATE). A "one-off" call can be revisited later by editing the same adjustment record. Guards ship with the workflow: re-importing actuals over a period that would overwrite a row with a CONFIRMED adjustment requires an explicit overlap confirmation, and Django Admin warns before deleting an ActualSale that has adjustments.
Net position, computed at query time. Because the grain is 1:1 and duplicate-free, "net actuals" for a given row is simply qty − qty_adjustment (and revenue − revenue_adjustment where both are present) for CONFIRMED adjustments — computed via a join at query time (`actuals_queryset_with_net`) in the forecast engine, reporting, and ABC classification code paths, rather than maintained as a separately materialized table. This avoids a staleness-tracking layer for a subtraction this cheap.
Net by default everywhere. The statistical forecast engine, financial/revenue reporting, and ABC classification all read the net position by default (`ForecastingConfig.forecast_uses_net_actuals`, `reporting_uses_net_actuals`, `abc_classification_uses_net_actuals`, all default True). A Client can opt any one of these back to raw ActualSale via its own flag if, for example, finance wants the bulk sale visible in revenue reporting.
Stale forecasts. `flag_stale_forecast_versions` runs after detection/decision changes and marks any forecast version whose base actuals have moved, so downstream consumers never trust a version built over pre-adjustment data.
Hierarchy scope. Outlier adjustments apply at the leaf ActualSale row. Hierarchy roll-ups (Product / Sales / Location) are computed programmatically off the already-net leaf rows — adjustments are never independently propagated up a hierarchy.

#### Sales Promotion Scheme Management (Planned Promo Impact)

Consumer products and auto components run sales promotion schemes (1-for-1, buy-2-get-1-free, %-off,
dealer free-goods) from time to time. The observable pattern is a demand (qty) spike during the scheme,
a dip pre/post (pull-forward / wait-for-scheme), and a revenue effect that is **independent** of the qty
effect — a 1-for-1 scheme doubles qty while revenue stays flat. Because product-group (`taxon_*`) grains
forecast **revenue**, and `update_weighted_avg_prices` derives price from `revenue/qty`, an unhandled
scheme distorts the revenue level, the learned seasonality, and every qty conversion at disaggregation.

Design principle — the scheme layer is **upstream of the outlier layer**, enforced as one shared baseline
definition: `baseline = Actuals − scheme impact − outlier`. Scheme netting is **multiplicative**
(uplift scales with demand level), outlier netting stays **subtractive**:

```
net_qty     = (qty     / (1 + expected_qty_uplift_pct))  − outlier_qty_adjustment
net_revenue = (revenue / (1 + expected_value_uplift_pct)) − revenue_adjustment
```

Ordering is non-negotiable and enforced in code: **outlier detection runs on scheme-netted series**, so
its median/MAD baseline is already scheme-free and a scheme spike can never be flagged as an outlier. A
scheme is a planned, repeatable event — unlike an outlier (one-off noise) it is removed from history
*and* re-applied to the forecast horizon.

Independent value uplift. `expected_qty_uplift_pct` and `expected_value_uplift_pct` are independent
planner-entered fields. Revenue is never derived from qty-uplift × discount, because schemes break that
link (1-for-1 = qty +100%, value 0%). `discount_pct` is metadata only — it may pre-fill a default value
uplift, never authoritative. Guards: `value_uplift ≤ −100%` is invalid; a zero-qty-uplift scheme (pure
price promo) still nets revenue.

Models. `SalesScheme` (client, scheme_code, status DRAFT/ACTIVE/ARCHIVED, the two uplift fields,
 `discount_pct`, plus the pre/post shadow fields `shadow_periods` and `pull_forward_pct`);
 `SalesSchemeScope` (OVERALL / TAXONOMY planning-group subtree / **BRAND** / ITEM, with optional
 planning_location / planning_customer / distribution_channel filters — mirrors `VendorSchemeScope`);
 `SalesSchemePeriod`
 (one bucket at the forecast period_type — a period in the past nets history, a period in the horizon
 re-adds uplift, so no separate future/historical flag is needed); `ResolvedSalesSchemePeriod`
 (materialized scheme→actuals coverage keyed to the ActualSale grain, rebuilt on scheme activation —
 the same "resolve on change, materialize for reads" pattern as `ResolvedVendorScheme`); and
 `SalesSchemeOccurrence` (closed-scheme actual-vs-expected data-checking).

**Brand / vendor-specific schemes.** In this domain the scheme's "vendor" **is the Brand**, and the
 brand→item link lives in the **item taxonomy**, not the planning product hierarchy (which is
 category-based and spans brands). A scheme that covers one vendor across many product groups is one
 `SalesScheme` with several scope rows — e.g. a `BRAND` row per brand plus any `TAXONOMY`/`ITEM` rows.
 `BRAND` scoping targets a Brand node in the taxonomy named by the new `ForecastingConfig.brand_taxonomy`
 slug (the prerequisite: brand nodes with item mappings must exist); membership is the **union** of all
 `ItemTaxonomyNode` mappings beneath the node, so items spread across multiple planning product groups
 are all covered. Scope resolution is tree-aware (each row expands from its own node's taxonomy) and
 overlapping rows within one scheme are deduplicated most-specific-wins
 (`ITEM > BRAND > TAXONOMY > OVERALL`).

Pre/post shadow (pull-forward) is **in scope**, on both the baseline and the horizon. A fraction of a
scheme's netted-out uplift is pulled forward from neighbouring periods rather than incremental:
`SalesScheme.pull_forward_pct` (default 0.50) splits uplift into pulled vs incremental, and
`shadow_periods` (default 0 = off) sets how many buckets on each side of the window are depressed.
The add-back (history) and the dip (horizon) are **anchor-based and symmetric**: both use
`U = window_qty × (1 − 1/qty_factor)`, weighted by a 50/50 pre/post split and an exponential decay
(`1/2^j`) normalized per side. Value shadow anchors to the window's `expected_value_uplift_pct`, so a
1-for-1 (value uplift 0) has no value shadow; the residual pre/post revenue dip is documented baseline
noise. Same-grain shadow rows from different schemes add additively.

Netting is computed at query time via `actuals_queryset_with_net`, composed scheme-first-then-outlier,
and is the single source of truth for the forecast engine, series profiles, price update, outlier
detection, reporting, and ABC classification (gated by `ForecastingConfig.scheme_net_actuals`, default
True — mirroring the outlier flags).

Forecast output carries both numbers. `ForecastLine` stores the statistical (baseline) value unchanged
and adds a scheme overlay for horizon periods covered by an ACTIVE scheme
(`ForecastingConfig.scheme_apply_forecast_uplift`, default True): window periods get
`scheme_qty = statistical_qty × (1 + qty_uplift)` and
`scheme_value = statistical_value × (1 + value_uplift)`; shadow periods get a dip
`scheme_qty = statistical_qty − window_statistical_qty × (1 − 1/anchor_qty_factor) × weight` anchored
to the window line's baseline. Each overlay line carries the covering `scheme_id`. `final_qty` defaults
to the baseline; planners can promote the scheme number. `ForecastAggregate` rolls the overlay up with
`scheme_qty` / `total_scheme_value`.

Detection and review. `detect_scheme_candidates` runs on **raw** product-group aggregates and proposes
candidate periods not covered by a tagged scheme, with implied qty uplift
(period demand / median of neighbours − 1). Planners register schemes (scope, periods, uplifts) and
approve/activate them from an HTMX queue (mirroring the outlier queue). Activating a scheme materializes
resolved rows, flags affected DRAFT forecast versions stale, and re-triggers outlier detection on the
covered range.

Data-checking and estimation. When a scheme closes, `SalesSchemeOccurrence` measures actual qty uplift,
actual value uplift, and actual pull-forward (missing volume in the shadow buckets vs the window uplift)
independently from actuals and compares against expectations. Future registrations with the same
`scheme_code` pre-fill expected uplift **and** `pull_forward_pct` from the **median** of the last few
occurrences (same median-not-mean choice as the 3C vendor-rebate accrual estimation), so the shadow
default calibrates from real closed schemes.

Feature control. `scheme_management` `ClientFeatureControl` key (parent `demand_planning`); detection
sensitivity mirrors the outlier fields with `last_scheme_detection_run_at/by/range_start/range_end`.

#### Item Lifecycle Management (Substitution / Discontinuation / Introduction)

Items go through lifecycle events that a naive "one item, one series" forecast model cannot represent.
Three events are supported under one umbrella, sharing one admin/HTMX UI, one config flag, and one
consumer pipeline — but each lands in a different layer:

1. **Substitution (replacement code — Scenario 3).** An item with past sales is superseded in the
   future by a **new item code** (repack, reformulation, supersession); the retired code's
   **historical actuals feed the new code's forecast** from its launch date onward, with a **quantity
   conversion** when unit sizes change (e.g. `2 old = 1 new`). `ItemSubstitution(client, old_item,
   new_item, conversion_factor, effective_from)` maps a retired code to exactly one successor
   (`unique (client, old_item)`); a successor may aggregate many retired codes. `conversion_factor`
   scales qty **and** revenue identically (per-unit price preserved): `new_qty = old_qty × factor`,
   `new_revenue = old_revenue × factor`. **Direct mapping only (MVP)** — an item may not be both a
   predecessor and a successor, which excludes chains and cycles by construction. This is a
   **baseline re-key layer**: it runs inside the shared composed helper (`actuals_queryset_with_net`)
   **after** scheme + outlier netting, re-keying each old-item row to the successor and scaling it
   when `period_start < effective_from` (null = whole history; exclusive cutoff, so converted history
   and the successor's own actuals are disjoint in time and never double counted). The retired old
   item's own **forecast is nil on/after `effective_from`** — the successor owns the demand from the
   handover date.

2. **Discontinuation (Scenario 1).** An item is withdrawn with an **effective date**; even though
   past actuals exist, **post effective date the forecast is nil** — there is no successor.
   `ItemDiscontinuation(client, item, effective_from)` (`unique (client, item)`; NULL = nil
   immediately). The item keeps its full history (it still feeds reporting, ABC, and accuracy) — this
   is a **forecast-output filter** at `write_forecast_lines` (no `ForecastLine` for horizon periods
   `>= effective_from`), not a data mutation and not an `Item` master-data status change. Periods
   before the date forecast normally from the item's own history.

3. **Introduction (Scenario 2).** A **new item** introduced from an effective date has **no history**;
   the client names a **reference item code whose forecast is copied onto the new item**, scaled by a
   **ratio**, and bounded by an optional **from-date / to-date** window, until the new item
   accumulates **enough historical data** (`ForecastingConfig.min_history_periods` own periods).
   `ItemIntroduction(client, new_item, reference_item, ratio, copy_from, copy_to)` (`unique (client,
   new_item)`; `ratio > 0`). The copy stops at the **earlier** of `copy_to` and "enough own history".
   The reference item is **not retired** — it keeps its own series. This is a **forecast-output copy**
   at `write_forecast_lines`: the new item's line = reference statistical line × `ratio`, tagged with
   `borrowed_from_item` / `borrowed_ratio` on `ForecastLine` so borrowed lines are transparent to
   planners; qty and value scale by the same `ratio` (per-unit price preserved).

**One lifecycle directive per item:** the event-subject roles (old_item / new_item of substitution,
discontinued item, introduction new_item) are pairwise exclusive — an item holds exactly one role.
The `reference_item` of an introduction is not an event subject (it is an ordinary forecasted item)
and may overlap, except that an introduction's `new_item` may not itself be another introduction's
`reference_item` (no chains).

All three layers are gated by a single `ForecastingConfig.use_item_lifecycle` flag (default True) for
every consumer — forecast matrix, series profiles, weighted-avg price, outlier detection (which skips
retired substitution old_items but keeps discontinued items' own history detectable), forecast-line
write, reporting and ABC. A new `item_lifecycle` `ClientFeatureControl` key + HTMX list/form +
Django Admin complete the feature, mirroring the scheme-management patterns.

#### Forecast Engine Architecture
 
**Forecast versioning** is first-class. Every forecast run produces a `ForecastVersion` record; multiple versions coexist for the same Client and period so that statistical, consensus, and approved forecasts can be compared.
 
| Model | Key Fields | Notes |
|-------|-----------|-------|
| `ForecastVersion` | client, version_label, period_type, base_period_end, horizon_periods, engine_config (JSONField), status, run_status, stale_actuals, created_by, approved_by, copied_from | One per run or consensus cycle. Lifecycle `DRAFT → IN_REVIEW → APPROVED → LOCKED`. `run_status` (QUEUED → … → COMPLETE / FAILED) tracks the Celery run separately from the workflow status; `stale_actuals` is set by `flag_stale_forecast_versions` when a confirmed adjustment lands inside the version's horizon after the run |
| `ForecastLine` | version, item, planning_location, planning_customer (nullable), distribution_channel, period_type, period_start, statistical_qty, override_qty, final_qty, forecast_level, model_used, price_used, scheme_id (nullable), scheme_qty, scheme_value | Leaf grain (item × location × customer × channel × period). `final_qty = override_qty if set, else statistical_qty`; `forecast_level` tags which grain the statistical forecast was computed at before disaggregation; `scheme_qty`/`scheme_value` are the scheme-uplift overlay (NULL outside scheme windows) |
| `ForecastAggregate` | version, agg_level (LOCATION/SALES_NODE/PRODUCT_GROUP/CLIENT), agg_key (JSONField), period_start, statistical_qty, override_qty, final_qty, scheme_qty, total_scheme_value | Pre-computed roll-ups for UI performance |
| `ForecastOverride` | version, override_level, override_key (JSONField), period_start, override_qty, override_pct, override_note, created_by (custom weights in `OverrideSplitWeight`) | Stores the user's intent; disaggregation is computed separately |
| `ForecastAccuracy` | version, item, planning_location, planning_customer, distribution_channel, period_start, actual_qty, forecast_qty, mape, bias | Populated post-actuals for tracking accuracy |
 
**Statistical engine** runs as a Celery task:
1. Pull the baseline actuals matrix (net of scheme impact first, then CONFIRMED outlier adjustments) from PostgreSQL (DuckDB is used in-process for fast OLAP rollups on the aggregates/accuracy paths).
2. Build a Polars DataFrame per hierarchy leaf.
3. Run `StatsForecast` models (ETS, AutoARIMA, CrostonSBA for intermittent demand) per series.
4. Run `HierarchicalForecast` MinTrace reconciliation across the three hierarchy dimensions.
5. Write `ForecastLine` + `ForecastAggregate` records for the resulting `ForecastVersion`.
**Reconciliation** uses Nixtla's `HierarchicalForecast` library. The summing matrix `S` is constructed from the three hierarchy trees at run time. Supported reconciliation methods configurable per Client: `BottomUp`, `TopDown (AHP)`, `MinTrace (OLS)`, `MinTrace (WLS)`.
 
#### Consensus Override Workflow
 
Business users override at **any level** of any hierarchy (e.g., "Region North, Q3, +15%"). The override is stored as a `ForecastOverride` record and disaggregated to `ForecastLine` records using one of:
- **Proportional split** — historical actuals share.
- **Equal split** — uniform distribution across children.
- **Custom split** — user-defined weights stored in `OverrideSplitWeight`.
Override propagation runs synchronously for small subtrees (<500 leaf nodes) and as a Celery task for large subtrees.
 
**Approval workflow:**
`ForecastVersion.status` machine: `DRAFT → IN_REVIEW → APPROVED → LOCKED`.
- `LOCKED` versions cannot be modified; they can be copied to a new `DRAFT`.
- Approved versions feed into the Phase 3A Order creation flow as a suggested order quantity on `OrderLine`.
#### Accuracy Tracking
 
After a version is generated, a Celery task joins net `ActualSale` against the version's `ForecastLine` records across the `accuracy_lookback_periods` window and writes `ForecastAccuracy` records. Metrics computed per leaf and rolled up: `MAPE`, `Bias`, `WMAPE`. Results are surfaced in the client dashboard and via the demand API.
 
#### Integration with Phase 3A eCommerce
 
- When a staff user creates a `Quotation` or `Order`, the approved `ForecastVersion` for the Customer × Item combination is offered as a suggested quantity.
- `OrderLine` gains a nullable FK `forecast_line` — populated when the order line originates from a forecast suggestion.
- This closes the plan-to-order loop and enables future forecast accuracy measurement against actual orders (not just actuals uploads).
#### Non-Goals for Phase 3B
 
- No probabilistic forecasting (prediction intervals) — deferred to Phase 4.
- No external data feeds (weather, macro indicators) — deferred.
- No real-time point-of-sale data ingestion — batch monthly upload only.
- No ML models (XGBoost, LightGBM) — statistical models only in Phase 3B.
- Scheme management covers planner-entered uplift on historical (netting) and planned (horizon re-add) periods, with system-proposed candidates for review, including the pre/post pull-forward shadow (add-back on history, dip on the horizon). Bounded simplifications: value shadow anchors only to the window's `expected_value_uplift_pct` (a 1-for-1's residual pre/post revenue dip is baseline noise); a shadow whose anchor window falls outside the forecast horizon is skipped with a warning; no causal attribution of pull-forward beyond the `pull_forward_pct` + decay model, which is calibrated empirically from closed schemes.
- Outlier handling covers statistical candidate detection and planner-confirmed exclusion from the forecast baseline (and, by default, from reporting/ABC classification) only. It is not a general data-quality / anomaly-detection product; it does not attempt to auto-correct root-cause data entry errors upstream of ActualSale.
### 10. Inventory Decision Engine (Phase 3C)

#### Naming and Scope Correction

This module is named the **Inventory Decision Engine (IDE)**, not a "replenishment engine." Replenishment
is only one of the decisions it makes. The engine also makes forecast-consumption decisions,
stocking-location decisions, transfer decisions, procurement-quantity decisions, centralization
decisions, and service-level decisions — all policy-driven and all explainable.

#### Business Context

Each Client operates a multi-tier physical stocking network (Vendor → HO → DC → Location) carrying
20,000+ SKUs. The IDE converts inventory position, demand classification, forecast, and supply-network
data into ranked, explainable replenishment/transfer/stocking recommendations — reducing the planning
surface from tens of thousands of SKU-locations down to a small set of exceptions a human planner
actually reviews and decides on.

#### Core Design Principles

- **Policy-driven, never hardcoded.** Every decision (review cadence, replenishment method, coverage
  days, safety-stock logic, preferred supply source, forecast trust, stocking strategy, transfer
  strategy, approval threshold) is derived from a configurable `PolicyMatrix` cell, not from
  code-level branching.
- **Exception-driven planner workflow.** Target funnel: 80,000 SKU-locations → ~5,000 system
  recommendations → ~500 exceptions surfaced → ~50 planner decisions per cycle. Planners work
  workbenches, not SKU lists.
- **Multi-echelon aware.** Every recommendation accounts for the local node, its parent(s), the
  distribution center, and the ultimate vendor source, recognizing demand-aggregation effects across
  the network — not just local reorder math.
- **Explainable by construction.** Every recommendation persists its inputs, the policy cell that
  fired, the formula used, the trigger reason, alternative options considered, and the expected
  outcome. Nothing is a black-box number.

#### Two Hierarchies, Kept Structurally Separate

The Sales/Forecast Hierarchy (Total → Region → Branch → Location, from Phase 3B) and the Supply
Network (Vendor → HO → DC → Location) are **not the same tree** and must never share a parent-link
field. The Supply Network is item-specific, time-dependent, and may diverge in shape from the sales
hierarchy at any node. The IDE resolves *where demand is sourced from* by walking the Supply Network,
while reading *how much demand exists* from FCST values that live on the Sales Hierarchy.

#### Two-Stage Forecasting Feeds the IDE

Phase 3B's `ForecastVersion`/`ForecastLine` machinery is extended with two forecast "stages" rather
than replaced:
- **`SALES_CONSENSUS`** — the existing Phase 3B consensus forecast. Not guaranteed additive up the
  tree; owned by the sales team.
- **`OPERATING_PLAN`** — derived from `SALES_CONSENSUS` by applying a planner-set normalization factor
  at an anchor node, then cascading down using the same revenue-share disaggregation logic already
  built for Total→Region→Branch→Item. Additive by construction unless a planner manually overrides a
  node (flagged `is_manual_override`).

**The IDE consumes `OPERATING_PLAN` exclusively.** `SALES_CONSENSUS` never reaches supply planning
directly. Non-additivity introduced by manual overrides is never silently clamped — it is written to a
`ForecastReconciliationException` for planner review.

#### Demand Classification (reused, not reinvented)

ABC classification and Syntetos-Boylan (SEIL: Smooth/Erratic/Intermittent/Lumpy, via ADI/CV²
thresholds) already exist from Phase 3B (`AbcClassDefinition` and the SEIL classifier). Phase 3C
**reuses these as the two axes of a 3×4 `PolicyMatrix`** rather than introducing a parallel
classification scheme. Thresholds remain client-configurable.

#### Policy Matrix

A 12-cell matrix (ABC × SEIL) where each cell configures: Review Policy, Replenishment Policy,
Coverage Days, Safety Stock Logic, Preferred Supply Source, Forecast Trust %, Stocking Strategy,
Transfer Strategy, and Planner Approval Rules. Effective review frequency for any SKU-location is
`MAX(policy_frequency, data_refresh_frequency)`.

#### Effective Daily Usage

`EDU = ForecastTrust × FDU + (1 − ForecastTrust) × HDU`, where Forecast Trust is a per-SEIL-class
configurable percentage (Smooth 90%, Erratic 60%, Intermittent 60%, Lumpy 20% as defaults).

#### Non-Goals for Phase 3C

- No full simulation / what-if engine (deferred — candidate for Phase 3D or Phase 4).
- No live vendor EDI integration — supply-position data arrives via a versioned snapshot ingestion
  contract the client pushes to; the IDE is a standalone service that does not own transactional ERP
  data.
- No automatic PO/STO creation against 3A `Order`/`Delivery` — Phase 3C produces recommendations only;
  wiring a recommendation into an actual purchase/transfer document is a 3A/3C integration step
  evaluated after 3C's core engine is validated.
- No probabilistic/ML forecasting — reuses Phase 3B's `StatsForecast`/Nixtla stack (Croston, SBA, TSB
  added for intermittent/lumpy demand); ML models remain deferred to Phase 4.
- No rebate-threshold-chasing logic — rebate accrual only *informs* landed-cost comparisons; it never
  by itself triggers a bulk order.

#### Success Criteria (Phase 3C)

- Inventory investment reduction of 15–30% at target service levels, measured against a client's
  pre-IDE baseline (directional target, not a hard gate).
- Explainable recommendation surfaced for 100% of SKU-locations in scope — every recommendation
  traceable to its policy cell, formula, and inputs.
- Exception funnel demonstrably narrows: system recommendations → flagged exceptions → planner
  decisions, at roughly the 80,000 → 5,000 → 500 → 50 ratio described in design principles.
- `Σ RR` (replenishment requirement) at every vendor-facing leg equals `Σ FCST (OPERATING_PLAN)` at
  every end node — the conservation invariant holds as a standing regression test.
- Engine scales to 100,000+ SKU-location combinations per client without exceeding the netting-run
  time budget established in Sprint 3C production hardening.
## Phase 3 eCoommerce with Beckn
Input:
Phase 3 eCommerce models are designed to be schema-aligned with Beckn Protocol v2.0. Internal models mirror Beckn's core objects (Inquiry, Quotation, Order, Fulfilment, Picking, Packing, Transportation, Billing, Payment) with to_beckn() serializer methods on each. This makes adding a Beckn network adapter (BPP participation) in Phase 4 a serialization exercise rather than a model redesign. Full Beckn network participation (ONDC integration) is deferred to Phase 4.
Business Domains needed:
Inquiry
Quotation
Cart
Order
OrderLine
Delivery
Shipment
Picking
Packing
Invoice
Payment
Return
Refund

Pricing functionality to be structured as below:

Pricing will have discounts, surcharges and taxes. All three will have multiple sub items. Like in SAP pricing procedure, each sub item can be derived in multiple layered sequence. For eg a discount can be customer specific, customer region specific or for all Customers. Another discount can be Item specific, Item Group specific, Subbrand specifc, Brand specific. Discounts can be absolute values or percentage of a derived value. Some additional details can be at Document header level, for eg 5% discount for some New Customers applied across all items in the Document. Discounts can be a step function based on value slabs. Same logic applicable to surcharges and taxes. 

SAP Concept	          My Requirement
Condition Types	      discounts/taxes/surcharges
Access Sequence	      customer/item/brand/group
Condition Tables	    layered lookup
Pricing Procedure	    sequential calculation
Requirement routines	conditional applicability
Scales/slabs	        step pricing
Header conditions	    document discounts
Statistical conditions	analytics
Group conditions	    aggregated discounts

cart/order
    ↓
pricing context
    ↓
access sequence resolution
    ↓
condition collection
    ↓
step execution
    ↓
pricing result tree

Client Model to have allowed_currency list and base_currency field. Initially base_currency to be the default currency. Later, the document currency will be determined by Client Country and Customer Country. Also in the document, in the source document, the user can choose a currency from drop down based on the above. 
The flow may start from Inquiry > Quotation > Order... or Quotation > Order .... or Order > .... In all the cases the previous document items will flow to the next one with option for editing.
Order can be delivered by multiple Deliveries (Delivery split) and this split can be allowed or disallowed by the Customer in the Order or as per the Client Location flag. 
Transportation document can combine multiple Deliveries and a Billing document can combine multiple Deliveries. 
Picling, Packing, Transportation can be optional and flagged as per Client setting or Client location setting. 
Customer can have multiple addresses Bill_To, Ship_To . Order line items can be to different Ship_To and Bill_To. Delivery locations can be from multiple Client locations based on a flag in Client level.
Decision can be for One Order, One Delivery or splits as per Client Location, Client setting.
Decision to part ship and track the remaining quantity for a new Delivery or short close can be based on a flag at Client Location, Client level in that order of priority.
Output:
## CHANGE 2 — Add currency fields to Client model (add after §8 Generic Item Catalogue intro)
 
### Currency Configuration on Client
 
- `Client.allowed_currencies` — JSONField, list of ISO 4217 codes e.g. `["INR","USD","EUR"]`.
- `Client.base_currency` — CharField(3), ISO 4217, default `"INR"`. The system default for all new documents.
- Document currency determination order (implemented progressively):
  1. **Phase 3 initial**: document currency defaults to `Client.base_currency`.
  2. **Phase 3 later**: resolved from a `ClientCurrencyRule` table keyed by (client_country, customer_country) → currency.
  3. **In-document override**: user selects any currency from `Client.allowed_currencies` via a dropdown on Inquiry / Quotation / Order header; the selection is persisted on the document.
- All monetary fields on commerce documents store `(amount NUMERIC, currency CHAR(3))` pairs — never raw floats. A `Money` value object wraps these at the application layer.
---
 
 
## Phase 3 eCommerce with Beckn
 
### Document Flow
 
Phase 3 supports flexible entry points into the commerce flow. All paths converge on the same `Order` model:
 
```
Inquiry  ──┐
            ├──▶  Quotation  ──┐
                                ├──▶  Order  ──▶  Delivery(ies)  ──▶  Transportation
                Order (direct)─┘                                  ──▶  Billing
```
 
**Flow variants supported:**
- `Inquiry → Quotation → Order`
- `Quotation → Order`
- `Order` (direct entry)
**Document continuity:** when a downstream document is created from an upstream one, all line items flow forward automatically as an editable copy. `source_doc_type` + `source_doc_id` fields on each document record the origin. Source documents are never mutated by this promotion step.
 
### Business Domain Models
 
| Domain | Key Models | Notes |
|--------|-----------|-------|
| Inquiry | `Inquiry`, `InquiryLine` | Optional entry point; converts to Quotation |
| Quotation | `Quotation`, `QuotationLine` | From Inquiry or standalone; converts to Order |
| Order | `Order`, `OrderLine` | Central commerce object; mixed Bill-To / Ship-To per line |
| Delivery | `Delivery`, `DeliveryLine` | One or more per Order (split rules apply) |
| Picking | `Picking`, `PickingLine` | Optional; per `ClientFeatureControl` / `ClientLocation` flag |
| Packing | `Packing`, `PackingLine` | Optional; per same flags |
| Transportation | `Transportation`, `TransportationDelivery` | Consolidates multiple Deliveries |
| Billing | `Invoice`, `InvoiceLine`, `InvoiceDelivery` | Consolidates multiple Deliveries |
| Payment | `Payment`, `PaymentAllocation` | Allocated against Invoices |
| Return | `Return`, `ReturnLine` | References original Order / Delivery |
| Refund | `Refund` | References Return and Payment |
 
### Delivery Split Rules
 
An Order can be fulfilled by one or multiple Deliveries. Split behaviour is governed by a three-level flag priority (first matching rule wins):
 
1. `Order.allow_delivery_split` — customer-set at order time (if the client permits customer override).
2. `ClientLocation.allow_delivery_split` — fulfilling warehouse / branch flag.
3. `Client.allow_delivery_split` — platform-wide default.
**Part-shipment and back-order:** if a Delivery covers only part of an `OrderLine` quantity, the open remainder is handled by another flag cascade (`ClientLocation.allow_partial_shipment` → `Client.allow_partial_shipment`):
- `True` → open quantity rolls into a new Delivery (back-order).
- `False` → open quantity is short-closed (cancelled).
**Dispatch locations:** eligible source locations are `ClientLocation` records where `is_dispatch_location=True`. Whether multiple locations can serve a single Order is controlled by `Client.multi_location_dispatch`.
 
### Transportation and Billing Consolidation
 
- A `Transportation` document groups one or more `Delivery` records into a single shipment. A Delivery belongs to at most one Transportation.
- An `Invoice` (Billing) document groups one or more `Delivery` records. A Delivery belongs to at most one Invoice.
- Both are optional and toggled by `ClientFeatureControl` or `ClientLocation` flags (`enable_picking`, `enable_packing`, `enable_transportation`, `enable_billing_consolidation`).
### Customer Address Model (Phase 3 extension)
 
- `CustomerAddress.address_type` gains enum values: `BILL_TO`, `SHIP_TO`, `BOTH`.
- `CustomerProfile` can hold multiple addresses of each type.
- `Order` header carries `bill_to_address` FK and `ship_to_address` FK (defaulted from `CustomerProfile`).
- `OrderLine` can independently override `ship_to_address` and `bill_to_address` — enabling mixed-destination orders within a single Order.
- Deliveries are generated per distinct `ship_to_address` across OrderLines, subject to split rules.
### Pricing Engine (SAP Pricing Procedure equivalent)
 
| SAP Concept | Phase 3 Model |
|-------------|---------------|
| Condition Type | `PricingConditionType` — discount / surcharge / tax; absolute or % of a derived base |
| Access Sequence | `ConditionAccessSequence` — resolution order: customer → customer-region → all; item → item-group → sub-brand → brand → all |
| Condition Tables | `ConditionRecord` — keyed by access key combination, date-effective |
| Pricing Procedure | `PricingProcedure` — ordered list of `PricingStep` records; one per Client (system default copied on Client creation) |
| Requirement Routines | `PricingStep.requirement` — Python dotted-path to a callable returning bool |
| Scales / Slabs | `ConditionScale` — step function keyed by value or quantity breaks |
| Header Conditions | `PricingStep.apply_at = HEADER` — apportioned across lines |
| Statistical Conditions | `PricingStep.is_statistical = True` — computed but excluded from totals |
| Group Conditions | `PricingStep.group_key` — condition aggregated across lines before application |
 
**Pricing execution flow:**
```
cart / order
    ↓
build PricingContext (customer, items, quantities, document currency)
    ↓
access sequence resolution → ConditionRecord lookup per step
    ↓
scale / slab evaluation if applicable
    ↓
sequential step execution → PricingResultLine per step per line
    ↓
header conditions apportioned across lines
    ↓
final totals (net, tax, gross) stored on Order / Quotation
```
 
All intermediate step values are stored in `PricingResultLine` for auditability and for serialisation into Beckn `Quotation.breakup`.
 
### Beckn v2.0 Alignment
 
Internal models mirror Beckn core objects with `to_beckn()` serializer methods:
 
| Internal Model | Beckn Object |
|----------------|-------------|
| `Inquiry` | `BecknSearch` |
| `Quotation` | `BecknQuotation` |
| `Order` | `BecknOrder` |
| `Delivery` | `BecknFulfillment` |
| `Invoice` | `BecknBilling` |
| `Payment` | `BecknPayment` |
 
`CustomerAddress` adds `gps`, `area_code`, `state`, `landmark` fields to match Beckn `Location.address` schema. Full BPP network participation (ONDC registry, async callbacks, digital signatures) is deferred to Phase 4.
