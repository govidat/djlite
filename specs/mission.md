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
| 3B | Demand Planning: actuals ingestion, statistical forecasting, hierarchical reconciliation, consensus override — **builds before 3A; feeds into 3A order creation** |
| 3A | eCommerce: Inquiry → Quotation → Order lifecycle, SAP-style pricing engine, Beckn-aligned models — **in progress** |
| 4 | Beckn / ONDC network participation: BPP role, async callbacks, digital signatures, ONDC registry |


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

### 9. Demand Planning Module (Phase 3B)
 
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
A dedicated Taxonomy slug `product_planning` carries the 3–5 level product grouping used in forecasting (Category → Sub-category → Brand → SKU). This reuses Phase 2 infrastructure without new models.
 
**Geography / Location Hierarchy** — extends `ClientLocation`.
`ClientLocation` gains a `parent` self-FK (nullable) enabling a Region → Branch → Location tree. Depth is unrestricted; materialized path is added alongside the FK for efficient subtree queries (same pattern as `TaxonomyNode`).
 
**Sales Hierarchy** — new model tree.
`SalesNode(client, name, level_label, parent→self, location→ClientLocation nullable)` represents the org chart of the sales force. `CustomerSalesAssignment(customer, sales_node, valid_from, valid_to)` assigns each Customer to a leaf SalesNode with date effectivity.
 
Demand Planning to be a stand alone module and hence Customer data to be independent of CustomerProfile which is eCommerce dependent. Let a standalone Client level Customer Hierarchy be maintained for Demand Planning. This can be an arbitrary planning level Customer Hierarchy and data to be pushed directly and does not have any linkage to eCommerce sales. 
Item hierarchy to flow from catalog module that is already in place. 
Sales team hierarchy to be made separately for this module. 
Separate Client Location hierarchy to be made for this stand alone Demand Planning module. This also need not have any direct link with ClientLocation model which has operational siginificance for eCommerce. 
At the lowest level, demand data will be maintained at  Planning Location, Item, Customer level (can included specific Customers or a planning Customer to represent a group of unspecified Customers). As a result of Demand Planning forecast data is expected at Location / Item level at the minimum and if required at Location / Customer / Item level.
 
#### Data Ingestion Models
 
| Model | Key Fields | Notes |
|-------|-----------|-------|
| `ActualSale` | client, item, variant, customer, location, year, month, qty, revenue (MoneyField) | Row = one SKU × Customer × Location × Month |
| `ActualSaleLocation` | client, location, year, month, total_qty, total_revenue (MoneyField) | Summary-level actuals; used when SKU-level detail is unavailable |
| `ActualSaleImport` | client, import_date, source_file, row_count, status, errors (JSONField) | Import job tracking |
 
Both `ActualSale` and `ActualSaleLocation` are **append-only by design**. Corrections are made by posting a new row with a negative quantity delta (same convention as accounting ledgers), preserving a full audit trail. A `resolved_actuals` database view (or materialized view) aggregates the net position per key combination.
 
Unique constraint on `ActualSale`: `(client, item, customer, location, year, month)` — enforced at DB level; import service uses `INSERT ... ON CONFLICT DO UPDATE` for idempotency.
 
#### Forecast Engine Architecture
 
**Forecast versioning** is first-class. Every forecast run produces a `ForecastVersion` record; multiple versions coexist for the same Client and period so that statistical, consensus, and approved forecasts can be compared.
 
| Model | Key Fields | Notes |
|-------|-----------|-------|
| `ForecastVersion` | client, version_label, base_period_end, horizon_months, engine_config (JSONField), status, created_by | One per run or consensus cycle |
| `ForecastLine` | version, item, customer, location, year, month, statistical_qty, override_qty, final_qty | Leaf-level (SKU × Customer × Location × Month). `final_qty = override_qty if set, else statistical_qty` |
| `ForecastAggregate` | version, agg_level (LOCATION/SALES_NODE/PRODUCT_GROUP/CLIENT), agg_key (JSONField), year, month, statistical_qty, override_qty, final_qty | Pre-computed roll-ups for UI performance |
| `ForecastOverride` | version, override_level, override_key (JSONField), year, month, override_qty, override_pct, override_note, created_by | Stores the user's intent; disaggregation is computed separately |
| `ForecastAccuracy` | version, item, customer, location, year, month, actual_qty, forecast_qty, mape, bias | Populated post-actuals for tracking accuracy |
 
**Statistical engine** runs as a Celery task:
1. Pull actuals matrix from PostgreSQL (or DuckDB for fast OLAP aggregation).
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
 
After each month closes, a Celery task joins `ActualSale` against the approved `ForecastVersion` for that period and writes `ForecastAccuracy` records. Metrics computed per leaf and rolled up: `MAPE`, `Bias`, `WMAPE`. Results are surfaced in the client dashboard.
 
#### Integration with Phase 3A eCommerce
 
- When a staff user creates a `Quotation` or `Order`, the approved `ForecastVersion` for the Customer × Item combination is offered as a suggested quantity.
- `OrderLine` gains a nullable FK `forecast_line` — populated when the order line originates from a forecast suggestion.
- This closes the plan-to-order loop and enables future forecast accuracy measurement against actual orders (not just actuals uploads).
#### Non-Goals for Phase 3B
 
- No probabilistic forecasting (prediction intervals) — deferred to Phase 4.
- No external data feeds (weather, macro indicators) — deferred.
- No real-time point-of-sale data ingestion — batch monthly upload only.
- No ML models (XGBoost, LightGBM) — statistical models only in Phase 3B.

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
