# ─────────────────────────────────────────────────────────────────────────────
# Part 2b — Navbar template snippet
# ─────────────────────────────────────────────────────────────────────────────
#
# Add this <li> into your existing main navbar template (cotton/navbar_v001.html
# or wherever your top nav lives, per the catalogue file's filesystem_map).
# It uses the demand_ui_visible / demand_ui_role variables that the context
# processor in 2a injects into every template automatically.
 
NAVBAR_SNIPPET = '''
{% load i18n %}

{% if demand_ui_visible %}
<li>
  <a href="{% url 'demand_ui:dashboard' client_id=client.client_id %}"
     class="flex items-center gap-2">
    📈 {% trans "Demand Planning" %}
    {% if demand_ui_role == "admin" %}
      <span class="badge badge-xs badge-primary">{% trans "Admin" %}</span>
    {% endif %}
  </a>
</li>
{% endif %}
'''

# Where exactly to put it depends on your navbar's structure. For a typical
# DaisyUI navbar with a <ul class="menu menu-horizontal"> or a dropdown,
# drop the <li> block alongside your other top-level nav items, e.g.:
#
#   <ul class="menu menu-horizontal px-1">
#     <li><a href="...">Catalogue</a></li>
#     <li><a href="...">Orders</a></li>
#     {% if demand_ui_visible %}
#     <li><a href="{% url 'demand_ui:dashboard' client_id=client.client_id %}">
#       📈 Demand Planning
#     </a></li>
#     {% endif %}
#   </ul>


# ─────────────────────────────────────────────────────────────────────────────
# Part 2c — settings.py wiring
# ─────────────────────────────────────────────────────────────────────────────
#
# Register the context processor so demand_ui_visible / demand_ui_role
# are available in EVERY template render, not just demand pages.

SETTINGS_DELTA = '''
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [...],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # ... your existing processors ...
                "mysite.context_processors.demand_planning_nav",   # ← ADD THIS
            ],
        },
    },
]
'''

# Also confirm 'guardian' is in INSTALLED_APPS (per your stack it already
# is, since django-guardian is used elsewhere) and that
# AUTHENTICATION_BACKENDS includes guardian's backend:
#
#   AUTHENTICATION_BACKENDS = [
#       "django.contrib.auth.backends.ModelBackend",
#       "guardian.backends.ObjectPermissionBackend",
#   ]
#
# Without the guardian backend registered, user.has_perm(...) calls in
# location_access.py will silently fall back to Django's default
# (non-object-aware) permission check and always return False for
# object-level grants.
