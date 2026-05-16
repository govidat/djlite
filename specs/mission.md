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
| 2 | Product catalogue per client |
| 3 | eCommerce (cart, checkout, orders) |

---

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

## Phase 3 eCoommerce with Beckn
Phase 3 eCommerce models are designed to be schema-aligned with Beckn Protocol v2.0. Internal models mirror Beckn's core objects (Inquiry, Quotation, Order, Delivery, Picking, Packing, Transportation, Billing, Payment) with to_beckn() serializer methods on each. This makes adding a Beckn network adapter (BPP participation) in Phase 4 a serialization exercise rather than a model redesign. Full Beckn network participation (ONDC integration) is deferred to Phase 4.
Pricing functionality to be structured as below:
Pricing will have discounts, surcharges and taxes. All three will have multiple sub items. Like in SAP pricing procedure, each sub item can be derived in multiple layered sequence. For eg a discount cane be customer specific, customer region specific or for all Customers. Another discount can be Item specific, Item Group specific, Subbrand specifc, Brand specific. Discounts can be absolute values or percentage of a derived value. Some additional details can be at Document header level, for eg 5% discount for some New Customers applied across all items in the Document. Discounts can be a step function based on value slabs. Same logic applicable to surcharges and taxes.