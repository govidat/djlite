# mysite/context_processors.py
#
# Add this function to your existing context_processors.py (or create the
# file if it doesn't exist) and register it in settings.py TEMPLATES
# OPTIONS['context_processors'].
#
# This makes `demand_ui_visible` and `demand_ui_role` available in EVERY
# template without each view having to pass it explicitly — exactly how
# you'd expose something like `client` itself.
 
from utils.feature_control import is_feature_disabled


def demand_planning_nav(request):
    """
    Exposes two variables to every template:

        demand_ui_visible   bool — show the Demand Planning navbar link?
        demand_ui_role       str  — 'admin' | 'planner' | None

    Visibility rules:
      1. demand_planning feature flag must be enabled for this client
         (existing ClientFeatureControl check from Sprint 3B.0)
      2. User must be in demand_client_admin OR demand_client_planner group
      3. Superusers always see it (so support staff can debug)

    This intentionally does NOT check location-level guardian permissions —
    a planner with access to only one branch should still see the nav link
    and land on a dashboard scoped to their branch, not have the link
    hidden entirely. Fine-grained scoping happens inside the demand UI
    views themselves (location_access.py), not at the navbar level.
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'demand_ui_visible': False, 'demand_ui_role': None}

    client = getattr(request, 'client', None)
    if client is None:
        return {'demand_ui_visible': False, 'demand_ui_role': None}

    if user.is_superuser:
        return {'demand_ui_visible': True, 'demand_ui_role': 'admin'}

    feature_result = is_feature_disabled(client, 'demand_planning')
    if feature_result['disabled']:
        return {'demand_ui_visible': False, 'demand_ui_role': None}

    group_names = set(user.groups.values_list('name', flat=True))

    if 'demand_client_admin' in group_names:
        return {'demand_ui_visible': True, 'demand_ui_role': 'admin'}
    if 'demand_client_planner' in group_names:
        return {'demand_ui_visible': True, 'demand_ui_role': 'planner'}

    return {'demand_ui_visible': False, 'demand_ui_role': None}
