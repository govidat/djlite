Following is a compilation of codes for an UI for Demand Planning module. This is different from the api.
Good, the catalogue pattern gives me the exact template I need to follow: a Track A page (static blob + Django-rendered chrome via `render_client_template`), HTMX swap targets, mobile drawer pattern, and `{% url ... client_id=client.client_id %}` URL conventions.

Let me build this out properly. Given the size, I'll structure it as: views.py, urls.py (HTMX-facing, separate from the API), templates (page + partials), and a base layout with the nav menu.
## 1. URLs — `mysite/urls_demand_ui.py` (HTMX-facing, separate from the API)
## 2. Views — `mysite/demand_ui/views.py`
## 3. Base layout with side menu — `templates/demand/_base_demand.html`
## 4. Sidebar nav partial
## 5. Dashboard page
## 6. Version list page + partial
## 7. Version create form (modal partial + standalone page)
## 8. Version detail page — the hub with tabs to lines/aggregates/overrides/accuracy/export
## 9. Run status partial — the polling component (most important UX piece)