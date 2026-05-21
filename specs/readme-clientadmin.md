# Platform Guide — Client Admin

This guide is for the admin user of an SME client on the platform. It covers
day-to-day operations: managing your site content, users, items, demand planning,
and (when active) commerce documents. You do not need developer access or
knowledge of the underlying server to use this guide.

---

## Table of Contents

1. [What You Can Do as Client Admin](#1-what-you-can-do-as-client-admin)
2. [Logging In](#2-logging-in)
3. [Managing Your Site Pages](#3-managing-your-site-pages)
4. [Managing Navigation](#4-managing-navigation)
5. [Managing Your Theme](#5-managing-your-theme)
6. [Managing Your Team](#6-managing-your-team)
7. [Managing Customers](#7-managing-customers)
8. [Item Catalogue](#8-item-catalogue)
9. [Demand Planning](#9-demand-planning)
10. [Commerce Documents (Phase 3A)](#10-commerce-documents-phase-3a)
11. [Pricing Rules (Phase 3A)](#11-pricing-rules-phase-3a)
12. [Locations and Warehouses](#12-locations-and-warehouses)
13. [Languages](#13-languages)
14. [Common Tasks](#14-common-tasks)
15. [Getting Help](#15-getting-help)

---

## 1. What You Can Do as Client Admin

As a client admin you have full access to your own client workspace. You cannot
see or affect any other client's data. Your key responsibilities are:

- Publish and update pages on your client site
- Manage your team's user accounts and their roles
- Add and maintain your item catalogue
- Upload monthly sales actuals and manage demand forecasts
- Configure pricing rules and manage commerce documents (when enabled)
- Manage your warehouse locations and sales hierarchy

What you **cannot** do (platform superadmin only):
- Add new languages globally
- Create or edit theme presets
- Access another client's data
- Run database migrations or server commands

---

## 2. Logging In

Your admin interface is at:

```
/{your_client_id}/admin/
```

Use the username and password provided by your platform operator. If you have
forgotten your password, use the **Forgot password** link on the login page.

Your client site (what your customers see) is at:

```
/{your_client_id}/
```

The demand planning application (Phase 3B, if enabled) is at:

```
/{your_client_id}/planning/
```

---

## 3. Managing Your Site Pages

### Understanding the two content tracks

Your site supports two ways of building pages, and both can be used on the
same site:

**Track A — Raw HTML pages**
You or a designer authors the page in any external tool (Figma export,
Pinegrow, hand-coded HTML) and pastes the final HTML into the admin. This
is the fastest way to publish polished, pixel-perfect pages.

**Track B — Component pages**
Pages are built from a structured tree of components (hero sections, cards,
accordions, carousels) managed directly in the admin. This track is designed
for pages that clients edit regularly without developer involvement.

### Adding a new page

1. Go to **Pages** → **Add Page**.
2. Fill in:
   - `Slug` — the URL segment, e.g. `about-us` → your page will be at `/{client_id}/about-us/`
   - `Navbar title` (per language) — the label shown in your navigation
   - `Parent` — set if this is a sub-page (creates nested URLs)
3. Save.

### Publishing content (Track A)

1. Open the page in the admin.
2. Scroll to **Page Contents** → **Add Page Content**.
3. Set `language_code` to `en` (or the relevant language).
4. Paste your full HTML into the `html` field.
5. Save. The page is live immediately.

To add content in another language, add a second **Page Content** row with
a different `language_code`.

### Publishing content (Track B)

1. Open the page → scroll to **Layouts** → add a `Section` (level 10).
2. Inside the section, add a `Row` (level 20), then a `Col` (level 30), then a `Cell` (level 40).
3. On the Cell, add a **Component** (type: `hero`, `card`, `accordion`, `carousel`).
4. On the Component, add **Component Slots** for images and text.
5. For text slots, link a `ComptextBlock` and add per-language text entries.

### Unpublishing / hiding a page

Set `is_active = False` on the Page record. The page will return a 404 to
visitors but remain in the admin for editing.

---

## 4. Managing Navigation

Your site navigation (header, footer, sidebar) is managed separately from
the page tree via **Nav Items**. This means you can:

- Show external links in the nav without creating a page for them.
- Use different labels and ordering from the page hierarchy.
- Group items with label-only nav entries (no link).

### Adding a nav item

1. Go to **Nav Items** → **Add Nav Item**.
2. Fill in:
   - `Label` (per language) — shown in the nav
   - `url` — full URL or relative path; leave blank for a grouping label
   - `parent` — set for a dropdown sub-item
   - `order` — controls display order; lower number = first
   - `location` (header / footer / sidebar)
3. Save. Changes are live immediately.

---

## 5. Managing Your Theme

### Changing theme token overrides

Your theme is based on a preset configured by the platform operator. You can
override individual design tokens (colours, fonts, spacing) without changing
the preset.

1. Go to **Themes** → select your theme.
2. Edit the `overrides` field as JSON. Example:
   ```json
   {
     "color_primary": "#1D9E75",
     "color_secondary": "#534AB7"
   }
   ```
3. Save. Changes apply to all your pages immediately.

Contact the platform operator if you need to change your base theme preset or
add a new font.

---

## 6. Managing Your Team

### User roles

Your team members are assigned to **Client Groups** which control what they
can see and do. Standard roles:

| Role | What they can do |
|------|-----------------|
| `admin` | Full access to all modules |
| `staff` | Edit content; no user management |
| `viewer` | Read-only access to content |
| `sales` | Access to Inquiries, Quotations, Orders (Phase 3A) |
| `warehouse` | Access to Deliveries, Picking, Packing (Phase 3A) |
| `planner` | Access to Demand Planning module (Phase 3B) |

### Inviting a new team member

1. Ask the platform operator to create a Django User account for the person
   (or, if self-registration is enabled for staff, direct them to the signup page).
2. Go to **Client User Profiles** → **Add** → link the `user` and confirm `client` is your client.
3. Go to **Client User Memberships** → **Add** → assign the user to the appropriate **Client Group**.

### Changing a team member's role

1. Go to **Client User Memberships** → find the person's membership record.
2. Change `group` to the new role.
3. Save.

### Restricting a user to a specific location

If you want a warehouse user to only see deliveries from a specific branch:

1. Go to **Client User Memberships** → find the membership.
2. Set `location` to the relevant `ClientLocation`.
3. Save. The user will only see data scoped to that location.

### Deactivating a team member

1. Ask the platform operator to set `is_active = False` on the Django User record.
   (Client admins cannot deactivate user accounts directly for security reasons.)

---

## 7. Managing Customers

Customers are end-users of your site. They register themselves via:

```
/{client_id}/accounts/signup/
```

A `CustomerProfile` is created automatically scoped to your client.

### Viewing customer profiles

Go to **Customer Profiles** → search by name or email.

### Customer addresses

Each customer can have multiple addresses. Address types:

| Type | Used for |
|------|---------|
| `BILL_TO` | Billing address on invoices |
| `SHIP_TO` | Delivery address on orders |
| `BOTH` | Used for both billing and shipping |

Customer addresses can be managed by the customer themselves from their
profile page, or by your team from **Customer Addresses** in the admin.

### Customer language and theme preferences

Each `CustomerProfile` stores:
- `preferred_language` — the language the customer's site renders in
- `preferred_theme` — their active theme (if multiple themes are offered)

---

## 8. Item Catalogue

### Global items vs your items

The platform superadmin maintains a **Global Item** catalogue based on the
GS1 product classification hierarchy. You can reference global items and create
client-specific items that override them.

**Your items** are visible only to your client. A client item with the same
`item_id` as a global item takes precedence for your site.

### Adding an item

1. Go to **Items** → **Add Item**.
2. Fill in:
   - `item_id` — unique identifier (SKU code, GTIN, or internal code)
   - `name` (per language)
   - `attributes` — any domain-specific fields as JSON (e.g. `{"weight_kg": 1.5, "colour": "red"}`)
   - `is_active` — controls visibility on your catalogue pages
3. Save.

### Assigning items to taxonomy nodes (filtering)

Items are tagged to nodes in one or more taxonomies to power the faceted
filter sidebar on your catalogue pages.

1. Open an Item → scroll to **Item Taxonomy Nodes** → **Add**.
2. Select the relevant `TaxonomyNode` (e.g. a product category, geography, or department).
3. Save.

The filter sidebar updates automatically — no code change needed.

### Bulk uploading items

Download the Excel template from **Items** → **Bulk Upload** → **Download Template**.

Fill in the columns (item_id, name_en, name_hi, attributes JSON, taxonomy nodes).

Upload via **Items** → **Bulk Upload** → **Upload File**.

A background job processes the file; you will see the import status in
**Item Imports** within a few minutes.

### Item variants

For Phase 3A commerce, an `ItemVariant` record represents a specific size,
colour, or configuration of an item. Add variants via **Item Variants** →
linked to the parent `Item`.

---

## 9. Demand Planning

> This section applies if the `demand_planning` feature is enabled for your client.
> Access the planning application at `/{client_id}/planning/`.

### Overview

The demand planning module allows your team to:
1. Upload historical monthly sales actuals (SKU × Customer × Location).
2. Run a statistical forecast over those actuals.
3. Review and adjust the forecast in a consensus grid.
4. Approve and lock the final forecast.
5. Track how accurate previous forecasts were against actual sales.

Approved forecasts feed into Phase 3A as suggested order quantities.

### Setting up the sales hierarchy

Before uploading actuals, make sure your sales org tree is configured.

In the admin → **Sales Nodes** → build your tree from top to bottom:
e.g. `National → North Region → Delhi Area → Rep A`.

In **Customer Sales Assignments** → assign each customer to the leaf sales
node that manages them, with a `valid_from` date.

This hierarchy is used to group forecasts and override them at the region or
area level.

### Uploading actuals

1. Open the planning app → **Actuals** tab.
2. Download the actuals template (Excel) from the **Download Template** button.
3. Fill in columns: `item_id`, `customer_id`, `location_id`, `year`, `month`, `qty`, `revenue`.
4. Drag and drop the completed file onto the upload area, or click **Browse**.
5. The import runs in the background — the status updates automatically.
   - **Complete** — all rows imported successfully.
   - **Complete with errors** — most rows imported; check the error list for rows that failed (usually a missing item ID or customer ID).
   - **Failed** — the file format was unreadable; check the column headers match the template.

Re-uploading the same file is safe — the system updates existing rows rather
than creating duplicates.

You can also upload **location summary actuals** (location × month totals without
SKU detail) from the **Summary Actuals** tab. These are used as a cross-check
against the SKU-level rollup.

### Running a forecast

1. Open the planning app → **Forecast** tab → **New Run**.
2. Select:
   - **Base period end** — the last month of actuals to use as input (e.g. Oct 2025).
   - **Horizon** — how many months to forecast (e.g. 12).
   - **Reconciliation method** — `MinTrace (OLS)` is the recommended default for most clients.
3. Click **Run Forecast**. A progress bar shows while the engine runs (typically 5–15 minutes for a full client).
4. When complete, the forecast opens automatically in the **Consensus Grid**.

### Reviewing and overriding the forecast

The **Consensus Grid** shows:
- Rows: your items grouped by product category, location, or sales node (use the **Group by** selector to switch).
- Columns: one per forecast month.
- Cell colours:
  - **White** — statistical forecast, unchanged.
  - **Yellow** — you or a colleague has entered a consensus override.
  - **Grey** — the version is locked; no further edits.

**To override a cell:**
Click the cell → type the new quantity → press Enter. The system disaggregates
your change to the underlying SKU-level rows proportionally (based on historical
sales shares). A loading indicator appears while this runs in the background.

**To override at a higher level** (e.g. set a whole region's forecast for Q1):
Select the region row → click **Override Region** → enter the total quantity or
percentage change → confirm. The change cascades to all SKUs under that region.

**To revert an override:**
Click the overridden cell → click **Revert to statistical**.

### Approving the forecast

When your team is satisfied with the consensus forecast:

1. Open **Forecast Versions** → select the version.
2. Click **Send for Review** (moves to `IN_REVIEW` status).
3. Once reviewed, click **Approve** (moves to `APPROVED` status).
4. When no further changes are needed, click **Lock** (moves to `LOCKED` — immutable).

Only `LOCKED` versions feed into the Phase 3A Order suggestion flow.

### Comparing forecast versions

Open **Forecast Versions** → select two versions → click **Compare**. An
overlay chart shows both versions side by side at any aggregate level. Use this
to compare the statistical baseline against the approved consensus.

### Accuracy report

After each month closes, the system automatically compares your approved
forecast against the actual sales uploaded for that month.

Open the planning app → **Accuracy** tab to see:
- **MAPE** (Mean Absolute Percentage Error) — lower is better; < 20% is good for most SME contexts.
- **Bias** — positive bias means the forecast was consistently too high; negative means too low.
- **WMAPE** (Weighted MAPE) — the overall accuracy weighted by sales volume.

Filter by product group, location, or sales node to identify where your
forecast is least accurate and focus override effort there next cycle.

---

## 10. Commerce Documents (Phase 3A)

> This section applies when the eCommerce module is enabled.

### Document flow

Commerce can start at different points depending on your process:

```
Inquiry  →  Quotation  →  Order  →  Delivery  →  Invoice  →  Payment
                ↑               ↑
          (skip Inquiry)  (skip both — direct order)
```

When you promote a document to the next stage (e.g. Quotation → Order), all
line items carry forward automatically. You can edit quantities, addresses, and
the currency before confirming.

### Inquiries

An Inquiry captures a customer's initial interest before pricing is confirmed.

1. Go to **Inquiries** → **Add Inquiry**.
2. Set the customer, currency, bill-to and ship-to addresses.
3. Add line items (item, quantity, indicative unit price).
4. Save → share with the customer or use internally.
5. When ready to price, click **Create Quotation** — all lines carry forward.

### Quotations

A Quotation runs the pricing engine automatically and produces a priced
document for the customer.

1. Create from an Inquiry (recommended) or directly from **Quotations** → **Add**.
2. Review the pricing breakdown (one line per pricing condition applied).
3. Adjust any line quantities if needed.
4. Click **Send** to email the quotation PDF to the customer.
5. When accepted, click **Create Order**.

### Orders

1. Create from a Quotation (recommended), from a cart checkout (customer-initiated),
   or directly from **Orders** → **Add**.
2. Review the order: check currency, bill-to, ship-to addresses.
   - Individual lines can have different ship-to addresses (e.g. line 1 to Mumbai,
     line 2 to Delhi).
3. Click **Confirm** to lock the order and trigger fulfillment.

### Deliveries

After an order is confirmed, one or more Deliveries are planned.

**Split deliveries:** If your client settings allow, a single order can be
fulfilled across multiple deliveries (e.g. partial stock now, remainder next week).

To create a delivery:

1. Open the Order → **Plan Deliveries** → the system groups lines by ship-to address
   and dispatch location.
2. Review the proposed split → **Confirm Delivery Plan**.
3. Each Delivery appears in **Deliveries** → track status: `CONFIRMED → DISPATCHED → DELIVERED`.

**Partial shipment:** If you can only ship part of a line's quantity, create
the Delivery with the available quantity. The remaining `open_qty` either:
- Creates a back-order Delivery automatically (if partial shipment is allowed), or
- Short-closes the remaining quantity (if not allowed).

This is controlled by your location and client settings — ask your platform
operator to configure.

### Invoices

An Invoice can consolidate one or more Deliveries into a single billing document.

1. Go to **Invoices** → **Add Invoice**.
2. Select one or more Deliveries to consolidate.
3. Review the invoice lines (auto-populated from delivery lines).
4. Set `payment_terms` and `due_date`.
5. Click **Issue** — a PDF is generated and emailed to the customer automatically.

### Payments

Customers pay via the checkout flow on your site (Razorpay for INR, Stripe for
other currencies). Payment status updates automatically via webhook.

To manually record an offline payment:

1. Go to **Payments** → **Add Payment**.
2. Set the Invoice, amount, currency, method (`BANK_TRANSFER`, `CASH`, etc.), and `paid_at`.
3. Save.

### Returns and refunds

1. Go to **Returns** → **Add Return**.
2. Link the original Order and Delivery.
3. Add return lines with quantities and reason.
4. Once approved, go to **Refunds** → **Add Refund** → link the Return and the
   original Payment → process the gateway refund.

---

## 11. Pricing Rules (Phase 3A)

Your pricing engine works like a sequence of conditions — discounts, surcharges,
and taxes — applied one after another to build the final price.

### Pricing procedure

Your client has one **Pricing Procedure** (copied from the system default when
your account was created). Each procedure is a numbered list of **Pricing Steps**.

In the admin → **Pricing Procedures** → select your procedure → review and
reorder **Pricing Steps**.

### Condition types

Each step applies a **Condition Type** — for example:

| Condition Type | Category | Calc type |
|---------------|----------|-----------|
| Base price | — | Absolute |
| Customer discount | Discount | Percentage of base |
| Volume discount | Discount | Step function (slab) |
| GST 18% | Tax | Percentage of net |

### Condition records

A **Condition Record** holds the actual value for a condition type, valid for a
date range, and keyed by a combination of customer, item, brand, or group.

Example: `Customer discount` of 5% for Customer `CUST001`, valid 1 Jan 2025 –
31 Dec 2025, on item group `PHARMA_API`.

To add:
1. Go to **Condition Records** → **Add**.
2. Select `condition_type`.
3. Fill in `key_combination` (JSON): e.g. `{"customer_id": "CUST001", "item_group": "PHARMA_API"}`.
4. Set `valid_from`, `valid_to`.
5. Enter `amount` (absolute) or `rate` (percentage).
6. Optionally add **Condition Scales** for step/slab pricing.

### Volume slabs (step pricing)

For a condition record, add **Condition Scales**:

| From quantity | Rate |
|--------------|------|
| 0 | 0% |
| 100 | 3% |
| 500 | 5% |
| 1000 | 8% |

The engine picks the applicable slab at order time.

### Currency on documents

The document currency defaults to your `base_currency` (set by the platform
operator). If multiple currencies are enabled for your account, a dropdown
appears on the Inquiry / Quotation / Order header. Select the currency before
adding lines — all prices on the document will be in that currency.

---

## 12. Locations and Warehouses

Go to **Client Locations** to manage your branches, warehouses, and offices.

### Location tree

Locations support a hierarchy (Region → Branch → Warehouse). Set `parent` to
build the tree. This tree is used by:
- The demand planning module to aggregate forecasts by location.
- The sales hierarchy assignment (linking sales reps to a home branch).
- Delivery planning (which warehouse ships which order).

### Key location flags

| Flag | Effect |
|------|--------|
| `is_dispatch_location` | Orders can be shipped from this location |
| `allow_delivery_split` | This location allows one order → multiple deliveries |
| `allow_partial_shipment` | This location can ship partial quantities (back-order the rest) |
| `enable_picking` | Warehouse picking step is required before dispatch |
| `enable_packing` | Warehouse packing step is required before dispatch |
| `enable_transportation` | Deliveries from this location use a Transportation document |

Contact the platform operator if you need to change these flags — they affect
order fulfillment behaviour.

---

## 13. Languages

Your site's active languages are configured by the platform operator in your
client settings (`language_list`). As client admin you can:

- Add **translated content** for pages, nav items, and items in the languages
  already active for your account.
- Set a customer's `preferred_language` on their profile.

You **cannot** add a new language globally — contact your platform operator.

### Adding a translation for a page

1. Open the **Page Content** for the page.
2. Add a new **Page Content** row with the target `language_code` and the
   translated HTML blob.

### Adding translations to items

Open an **Item** → fill in `name_hi`, `name_fr`, etc. (the translated name
fields are listed per active language).

---

## 14. Common Tasks

### Publish a new page quickly

1. **Pages** → **Add Page** → set slug, navbar title, parent.
2. **Page Contents** → **Add** → set `language_code = en`, paste HTML.
3. Navigate to `/{client_id}/{slug}/` to verify.

### Update the homepage

Find the `Page` with `slug = home` (or whatever your homepage slug is) →
open its `PageContent` → replace the HTML blob → save.

### Add a product to the catalogue

**Items** → **Add Item** → fill `item_id`, `name_en`, `attributes` JSON →
go to **Item Taxonomy Nodes** → tag to the relevant category nodes → save.

### Check why a customer cannot log in

**Customer Profiles** → search by email → check `is_active` on the linked
Django User (ask the platform operator to reactivate if needed).

### See all open orders

**Orders** → filter by `status = CONFIRMED` or `status = PROCESSING`.

### Download the forecast for a period

In the planning app → **Forecast Versions** → select the approved version →
**Export CSV**. The file contains `item_id, customer_id, location_id, year,
month, final_qty` for all leaf lines.

### Check if an actuals upload succeeded

In the planning app → **Actuals** → **Import History** → select the import →
review `status` and `errors`. If errors exist, download the error report,
correct the source file, and re-upload (the system will update existing rows,
not create duplicates).

### Rerun a forecast after uploading new actuals

1. Go to the planning app → **Forecast** → **New Run**.
2. Select the same base period and horizon as the previous run.
3. The new version will appear alongside old versions — compare them before approving.

---

## 15. Getting Help

### Contact your platform operator for:
- Adding or removing languages globally
- Changing your base theme preset
- Adjusting location flags (dispatch, split, partial shipment)
- Deactivating user accounts
- Database-level queries or exports
- Any issue with Celery background jobs or cache

### Self-serve troubleshooting:

| Symptom | First thing to check |
|---------|---------------------|
| Page shows old content | Did you save the PageContent record? Clear browser cache. If still stale, contact the platform operator to clear the server-side page cache. |
| Forecast stuck on "Running" | Check **Forecast Versions** — if status is `FAILED`, re-trigger the run. If still `RUNNING` after 30 minutes, contact the platform operator. |
| Actuals import shows errors | Open the import record → review `errors` JSON → correct those rows in your source file → re-upload. |
| Order line shows no suggested quantity | No approved and locked forecast version exists for that Customer × Item combination. Approve and lock a forecast version first. |
| Customer says they can't place an order | Check that the item has `is_active = True` and is tagged to at least one taxonomy node visible in the catalogue. |
| Quotation pricing looks wrong | Open the Quotation → scroll to **Pricing Result Lines** → each step is listed. Identify which condition record produced an unexpected value and correct it in **Condition Records**. |
