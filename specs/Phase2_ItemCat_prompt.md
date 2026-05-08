Phase2 - Catalogue
For my multi-tenant SaaS application using:
- Django (SQLlite in DEV and PostgreSQL in PRD)
- Django Templates with Cotton
- Tailwind CSS + DaisyUI
- modeltranslation to have multi language labels
- To be added - HTMX for interactivity to be added (no heavy frontend frameworks)
- To be added - Generic Taxonomy / TaxonomyTerm model (most flexible)

I need a scalable "Generic Item Catalog System" with the following requirements:

--------------------------------------------------
1. MULTI-TENANCY
--------------------------------------------------
- Each record belongs to a Client (tenant)
- There is also a "global" (application-level) dataset
- Client-specific data overrides global data
- Queries must always prioritize:
    client-specific > global fallback

--------------------------------------------------
2. GENERIC ITEM MODEL
--------------------------------------------------
- Items are generic and reusable across domains:
    (products, projects, songs, documents, etc.)
- Avoid hardcoding fields specific to one domain
- Use a flexible structure:
    - core fields (id, name, status, timestamps)
    - optional JSONB field for dynamic attributes
- Global Item to be made available for common items. Eg a Shampoo from a particular Brand will be an Item for multiple Store Clients. For multiple Auto Component Distributors, a Component from a OEM will have the same data and can be derived from a Global data.

--------------------------------------------------
3. MULTIPLE HIERARCHIES (CRITICAL)
--------------------------------------------------
- Items can belong to multiple independent hierarchies (3–4 types), for example:
    - Category hierarchy
    - Geography hierarchy
    - Department hierarchy
    - Custom client-defined hierarchy

- Each hierarchy:
    - is tree-structured (parent-child)
    - can exist at:
        a) global level
        b) client level

- Client hierarchy overrides global hierarchy

- Many-to-many relationship:
    Item ↔ HierarchyNode

--------------------------------------------------
4. FILTERING SYSTEM (FACETED SEARCH)
--------------------------------------------------
- Left sidebar:
    - Hierarchy filters (tree view with expand/collapse)
    - Attribute filters (JSON-based fields)

- Main panel:
    - Filtered items list

- Filters must support:
    - multiple selections
    - combination filters (AND logic)

--------------------------------------------------
5. HTMX INTERACTION
--------------------------------------------------
- No page reloads
- When user clicks filter:
    - update item list via HTMX
    - update pagination via HTMX

- Use:
    hx-get
    hx-target
    hx-swap

- Server returns partial templates

--------------------------------------------------
6. PAGINATION
--------------------------------------------------
- Server-side pagination
- Works with filters
- HTMX-based navigation (no reload)

--------------------------------------------------
7. PERFORMANCE
--------------------------------------------------
- Avoid N+1 queries
- Use:
    select_related
    prefetch_related
- Optimize hierarchy queries (recursive or materialized path)

--------------------------------------------------
8. UI (TAILWIND + DAISYUI)
--------------------------------------------------
- Layout:
    - Left sidebar (filters)
    - Right main content (items grid/list)

- Components:
    - Collapsible tree (hierarchy)
    - Checkbox filters
    - Card/list view toggle

--------------------------------------------------
9. DELIVERABLES REQUIRED
--------------------------------------------------
Provide:

A. DATA MODEL
- Django models for:
    - Item
    - Hierarchy
    - HierarchyNode (tree structure)
    - ItemHierarchyMapping

- Include support for:
    - global vs client data
    - override logic
    - If required, we can have a reference item maintained at Gloabl or Client level, which is in turn used by the Client Item.
    - Item and Hierarchy can also be maintained at a Global level by SuperUser
    - For eg for a set of Auto Component Distributor clients, at Global level, superadmin will maintain the Item and Hierarchy.
    - At Client level the clientadmin to have the option to use the Global Item and/or Global Hierarchy as well as Client Level Item and/or Hierarchy. At Client level they can have the option of building on top of Global Item data.
    - Item and Hierarchy to align with GS1 standards of codification
    - Want to maintain attribute and values at Hierarchy level and Item level. The attribuet values to be inherited by the Item from its parent and grand parent with the lower level values taking precedence over higher level.
    - Global level data to be maintained by superuser. Client level data to be created/ edited/ deleted by clientadmin. However Client admin to be able to see the Global values in dropdown and select and use wherever required.  

B. QUERY LOGIC
- Efficient queryset examples for:
    - applying hierarchy filters
    - merging global + client data
    - erging with my fetch_clientstatic code

C. VIEWS
- Django views for:
    - catalog page
    - HTMX filter endpoint
    - pagination endpoint

D. TEMPLATES
- Base template
- Filter sidebar partial
- Item list partial
- Pagination partial

E. HTMX INTEGRATION
- Show exact HTML attributes:
    hx-get
    hx-trigger
    hx-target
    hx-swap

F. PERFORMANCE STRATEGY
- Indexing suggestions
- PostgreSQL JSONB usage
- Handling deep hierarchies

G. OPTIONAL (ADVANCED)
- Suggest using django-mptt or treebeard
- Suggest caching strategy (Redis)

H. Pls give the delta additions to my .md documents
I. Item wise implementation plan.
J. A sample for Products as Item
K. The template to have two options - A. Direct html blob and B.Using the detailed Layout > Component ... that I already have.
L. This catalog to be the base for Phase 3 eCommerce. Basically this catalogue to be extendable for qty selection and shopping cart creatin.
M. My schema to be fully aligned with Beckn protocol, I want my Phase 3 eCommerce to be aligned with this. https://github.com/beckn/protocol-specifications-v2; https://github.com/beckn/schemas
--------------------------------------------------

Ensure:
- Code is production-grade
- Clean separation of concerns
- Works for large datasets (20k+ items)
- Code snippets required for Model, Url, Views, Queries, NestedAdmin, authorization, signals etc.
- Provide delta additions to .md files.