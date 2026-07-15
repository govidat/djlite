Following is a compilation of codes for an UI for Demand Planning module. This is different from the api.
Good, the catalogue pattern gives me the exact template I need to follow: a Track A page (static blob + Django-rendered chrome via `render_client_template`), HTMX swap targets, mobile drawer pattern, and `{% url ... client_id=client.client_id %}` URL conventions.

Let me build this out properly. Given the size, I'll structure it as: views.py, urls.py (HTMX-facing, separate from the API), templates (page + partials), and a base layout with the nav menu.
## 0. General flow
### Demand Planning UI — Plain-English Flow

### Part 1: Who Sees the Menu, and Why

**The problem we're solving:** Not every user should see "Demand Planning" in the navbar. Only client admins and planners should — regular staff or unrelated users should never see it at all.

**How it works, step by step:**

1. Every time *any* page loads, Django runs a small function (the "context processor") in the background, before the template even starts rendering.
2. That function asks three questions in order:
   - Is this client paying for / has enabled the Demand Planning feature? (checked via the existing `ClientFeatureControl` flag)
   - Is the logged-in user in the "demand_client_admin" group, or the "demand_client_planner" group?
   - Is this user a superuser (support staff override)?
3. Based on the answers, it sets two flags: `demand_ui_visible` (show the menu item or not) and `demand_ui_role` (admin or planner — used to show a little badge).
4. The navbar template just checks `{% if demand_ui_visible %}` and shows or hides the link. No view code needs to think about this — it's automatic everywhere.

**Important nuance:** This check is *deliberately shallow*. It does **not** check whether the user can see every branch — it only checks "does this person belong to the Demand Planning world at all." The fine-grained "which branch can you touch" decision happens later, inside the actual pages. This separation matters: a planner restricted to one branch should still see the menu and land on their own branch's dashboard — not have the entire menu item disappear because they're not authorized everywhere.

---

### Part 2: Who Can Touch What — The Branch Scoping Model

**The problem we're solving:** A branch manager for Delhi should be able to enter forecast overrides for Delhi and anything below Delhi in the org tree — but not for Mumbai, and not for the whole company total above Delhi.

**The mental model — think of it like building keys:**

Imagine every location in your company (Total → Region → Branch) is a locked room, and rooms are nested inside each other like Russian dolls. If someone hands you the key to a room, you can also get into every smaller room inside it, automatically — you don't need separate keys for each one.

**How this is actually built:**

1. Every `PlanningLocation` (your Total, Regions, Branches) already stores a "path" — a breadcrumb trail of its position in the tree, like `1/4/12/` meaning "node 12, whose parent is node 4, whose parent is node 1."
2. We use Django's existing permission library (`django-guardian`) to say "User X has the override_at_location permission **on node 12**."
3. When the system needs to check "can User X act on node 47?", it doesn't look up a giant list — it just checks: is 47 the same as 12, or does 47's path start with 12's path (meaning 47 is *inside* 12)? If yes, access is granted, because access cascades downward through the tree automatically.
4. **Granting access is a one-time action.** When a client admin is onboarded, they get the key to the Total node — which automatically unlocks everything below it, forever, even if branches are added or moved around later. A branch manager gets the key to just their branch.
5. **Revoking is just as simple** — remove the one permission grant, and access to everything below it disappears immediately, with no cleanup needed across child nodes.

---

### Part 3: The Drill-Down Screen — What a Planner Actually Sees

**The problem we're solving:** Nobody can make sense of 20,000 SKU-level forecast rows. But everybody can make sense of "Delhi Branch is forecast to do ₹42 lakh next month."

**The screen, described as if you were using it:**

1. You log in. You click "Demand Planning" in the navbar.
2. You land on a screen showing **one big number** — your authorized total. If you're an admin, that's the whole company. If you're the Delhi branch manager, you only ever land on Delhi — you never even see the company total as your starting point.
3. Below that big number is a list of the next level down — if you're looking at "Total," you see Regions. If you're looking at a Region, you see Branches within it. If you're looking at a Branch, you see... nothing more, because branches are the bottom of the location tree (an "leaf").
4. Every row in that list is clickable. Clicking "North Region" replaces the whole screen with North Region's number and *its* children (the branches inside North). A breadcrumb trail at the top (Total → North Region → Delhi) lets you click back up at any point.
5. If you click all the way down to a branch and there's nothing left to drill into, the screen offers one more option: "View item-level forecast lines" — this is the deliberate escape hatch to see the raw SKU detail, but it's one extra click away, not the default view. The system wants you to think in totals first.
6. At the top of whichever level you're viewing, there's a date dropdown (which forecast period you're looking at) and — **only if you're authorized to edit at this exact spot** — an "Enter Override" button. If you're a planner without override rights at this level (maybe you can only *view* it, not edit it), that button simply doesn't appear. You're not shown a button that would just error out if clicked.

---

### Part 4: Entering an Override — What Happens Behind the Scenes

**The problem we're solving:** A planner needs to say "I think Delhi should actually do ₹45 lakh, not the ₹42 lakh the statistics predicted" — and have that change ripple down to the individual SKUs correctly, without letting them accidentally type in a different branch's code.

**Step by step:**

1. You click "Enter Override" while looking at Delhi's number. A small popup form appears.
2. Notice what's **missing** from this form: there is no text box asking "which location is this for?" The location is locked to Delhi already, because the form was opened *from* the Delhi screen. You cannot accidentally type "Mumbai" — the system already knows where you are.
3. You choose one of three ways to express your override: an exact quantity, a percentage bump, or a target ₹ value. You can only fill in one of the three — the form enforces that.
4. As you type a number, the screen quietly shows you a live preview: "if you set this, here's roughly how Delhi's child branches will shift." This happens without a page reload — it's a background request that updates just that preview panel.
5. When you hit Save, two separate security checks happen — once when the form was first opened, and **again** right before the data is actually written to the database. This second check matters because of timing: imagine the form was open in your browser for ten minutes, and during that time an admin revoked your Delhi access. Without the second check, your stale form could still slip through and write data you're no longer allowed to touch. The second check closes that gap.
6. Once saved, a background job (Celery task) picks up the override and pushes it down through Delhi's children — proportionally, by default, meaning each sub-branch's share of the change is based on how much they historically contributed to Delhi's total.
7. The screen automatically refreshes to show Delhi's new number, now flagged "Overridden."

---

### Part 5: Sprint Script Summary (in Sequence)

```
Sprint Task 1 — Permission foundation
  → Add two new permission types directly onto the PlanningLocation model
    (the ability to "view" and the ability to "override" at a location).
  → Run a database migration so these permission types exist.

Sprint Task 2 — Access-granting utilities
  → Write small reusable functions:
      "grant this user access rooted at this location"
      "check if this user can act at this location" (walks up the tree)
      "give me every location ID this user is allowed to touch" (walks down the tree)

Sprint Task 3 — Navbar visibility
  → Write the background check that runs on every page load (feature flag
    + group membership).
  → Wire it into settings so it runs automatically everywhere.
  → Add the conditional menu item to the existing navbar template.

Sprint Task 4 — Drill-down screen
  → Build one view that shows: current location's number, breadcrumb trail,
    children list, and (if authorized) an Override button.
  → Build the matching child-row template — each row is clickable and
    swaps the entire panel for the next level down.
  → Add the "leaf node" fallback that offers item-level detail as an
    extra step.

Sprint Task 5 — Override form
  → Build the popup form that is pre-locked to whichever location the
    planner was viewing when they clicked "Override."
  → Enforce the three-mode (qty / percent / value) mutual exclusivity.
  → Add the live preview that recalculates as the planner types.
  → Double-check permissions both when the form opens AND when it's submitted.
  → On save, hand off to the existing background job that pushes the
    change down through the hierarchy.
```
## 1. URLs — `mysite/urls_demand_ui.py` (HTMX-facing, separate from the API)
mysite/demand_ui/urls.py

## 2. Views — `mysite/demand_ui/views.py`
mysite/demand_ui/views.py
## 3. Base layout with side menu — `templates/demand/_base_demand.html`
templates/demand/_base_demand.html
## 4. Sidebar nav partial
templates/demand/partials/sidebar_nav.html
## 5. Dashboard page
templates/demand/dashboard.html
## 6. Version list page + partial
templates/demand/version_list.html
templates/demand/partials/version_table_body.html

## 7. Version create form (modal partial + standalone page)
templates/demand/version_create.html
templates/demand/partials/version_create_form.html

## 8. Version detail page — the hub with tabs to lines/aggregates/overrides/accuracy/export
templates/demand/version_detail.html
## 9. Run status partial — the polling component (most important UX piece)
templates/demand/partials/run_status.html

Implemntation steps
Sprint Task 1 — Permission foundation
  → Add two new permission types directly onto the PlanningLocation model
    (the ability to "view" and the ability to "override" at a location).
  → Run a database migration so these permission types exist.
    1a. Guardian permission setup on PlanningLocation
    utils/demand/location_access.py
    1b. Model delta — add guardian permissions to PlanningLocation.Meta
    hierarchy_model_delta.py

Sprint Task 2 — Access-granting utilities
  → Write small reusable functions:
      "grant this user access rooted at this location"
      "check if this user can act at this location" (walks up the tree)
      "give me every location ID this user is allowed to touch" (walks down the tree)
    Part 2 — Navbar Visibility
    2a. Context processor exposing demand planning access
    context_processors.py
    2b: The actual navbar template snippet that uses those variables
    2c: Settings wiring to register the context processor
    navbar_and_settings.py

Sprint Task 3 — Navbar visibility
  → Write the background check that runs on every page load (feature flag
    + group membership).
  → Wire it into settings so it runs automatically everywhere.
  → Add the conditional menu item to the existing navbar template.

Sprint Task 4 — Drill-down screen
  → Build one view that shows: current location's number, breadcrumb trail,
    children list, and (if authorized) an Override button.
  → Build the matching child-row template — each row is clickable and
    swaps the entire panel for the next level down.
  → Add the "leaf node" fallback that offers item-level detail as an
    extra step.
    mysite/demand_ui/views_drilldown.py
    templates/demand/drilldown.html
    templates/demand/partials/drilldown_override_form.html
    templates/demand/partials/drilldown_panel.html

Sprint Task 5 — Override form
  → Build the popup form that is pre-locked to whichever location the
    planner was viewing when they clicked "Override."
  → Enforce the three-mode (qty / percent / value) mutual exclusivity.
  → Add the live preview that recalculates as the planner types.
  → Double-check permissions both when the form opens AND when it's submitted.
  → On save, hand off to the existing background job that pushes the
    change down through the hierarchy.