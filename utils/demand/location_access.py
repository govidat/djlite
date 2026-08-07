# utils/demand/location_access.py
"""
Branch-level authorization for Demand Planning, built on django-guardian
object-level permissions assigned directly to PlanningLocation nodes.

Design
──────
- guardian permission 'mysite.override_at_location' is assigned to a user
  on SPECIFIC PlanningLocation rows (could be a leaf branch, a region, or
  the client root node).
- Access to a node IMPLIES access to all its descendants, computed via the
  materialized `path` field already on PlanningLocation (Sprint 3B.0).
- A client_admin (Django Group 'demand_client_admin') is granted access at
  the client ROOT node only — which implies access to everything below it.
  No need to assign permissions on every node individually for admins.
- A client_planner (Django Group 'demand_client_planner') gets explicit
  guardian permissions on one or more specific nodes (their branch/region).

Why guardian + path-based descendant inference, not row-per-descendant:
  Assigning the permission on every descendant row would mean re-assigning
  permissions every time the location tree changes shape. Storing the
  permission once at the node the user is "rooted" at, then computing
  descendants from `path` at query time, keeps grants stable across
  reorganisations.
"""

from __future__ import annotations

from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from guardian.shortcuts import assign_perm, get_objects_for_user, remove_perm

from mysite.models.demand.hierarchy import PlanningLocation

OVERRIDE_PERM = 'override_at_location'   # codename, defined on PlanningLocation.Meta.permissions
VIEW_PERM     = 'view_at_location'       # read-only access codename

CLIENT_ADMIN_GROUP   = 'demand_client_admin'
CLIENT_PLANNER_GROUP = 'demand_client_planner'


# ─────────────────────────────────────────────────────────────────────────────
# Model Meta addition required on PlanningLocation
# ─────────────────────────────────────────────────────────────────────────────
#
# Add this to PlanningLocation.Meta in mysite/models/demand/hierarchy.py:
#
#     class Meta:
#         ...
#         permissions = [
#             ('override_at_location', 'Can create/edit forecast overrides at this location and below'),
#             ('view_at_location',     'Can view demand planning data at this location and below'),
#         ]
#
# Run makemigrations after adding this — guardian permissions still need
# the Django permission row to exist; guardian links users/groups to it
# per-object via its own UserObjectPermission table.


# ─────────────────────────────────────────────────────────────────────────────
# Granting access
# ─────────────────────────────────────────────────────────────────────────────

def grant_location_access(user, location: PlanningLocation, *, can_override: bool = True) -> None:
    """
    Grant a user permission rooted at `location`. Descendants are implied
    at query time — no need to assign permission on every child row.

    can_override=True  → grants both view_at_location and override_at_location
    can_override=False → grants view_at_location only (read-only planner,
                          e.g. someone who reviews but does not edit)
    """
    assign_perm(VIEW_PERM, user, location)
    if can_override:
        assign_perm(OVERRIDE_PERM, user, location)


def revoke_location_access(user, location: PlanningLocation) -> None:
    """Remove both view and override permission for this user at this node."""
    remove_perm(VIEW_PERM, user, location)
    remove_perm(OVERRIDE_PERM, user, location)


def grant_client_admin_access(user, client) -> None:
    """
    Client admins get permission at the CLIENT ROOT planning location only.
    This implies access to the entire tree via descendant inference.

    Assumes a single root PlanningLocation per client (parent=None, depth=0).
    If a client has multiple root nodes (rare — e.g. two independent
    divisions), call grant_location_access() once per root instead.
    """
    roots = PlanningLocation.objects.filter(client=client, parent__isnull=True)
    for root in roots:
        grant_location_access(user, root, can_override=True)

    group, _ = Group.objects.get_or_create(name=CLIENT_ADMIN_GROUP)
    user.groups.add(group)


def grant_client_planner_access(user, locations: list[PlanningLocation]) -> None:
    """
    Client planners get permission rooted at one or more SPECIFIC nodes —
    e.g. a single branch, or a region covering several branches.
    """
    for loc in locations:
        grant_location_access(user, loc, can_override=True)

    group, _ = Group.objects.get_or_create(name=CLIENT_PLANNER_GROUP)
    user.groups.add(group)


# ─────────────────────────────────────────────────────────────────────────────
# Checking access — the core scope-resolution function
# ─────────────────────────────────────────────────────────────────────────────

def get_authorized_location_ids(user, client, perm: str = OVERRIDE_PERM) -> set[int] | None:
    """
    Return the set of PlanningLocation IDs this user may act on for `perm`,
    INCLUDING all descendants of every node they have direct permission on.

    Returns None if the user has unrestricted access (Django superuser or
    staff with the bypass flag) — callers should treat None as "no filter
    needed," not as "no access."

    Returns an empty set if the user has no grants at all — callers should
    treat this as "deny everything."

    Implementation:
      1. Get the set of nodes guardian says the user has direct permission on
         (could be a branch, a region, or the client root).
      2. For each such node, find ALL descendants via path__startswith
         (the same materialized-path technique used everywhere else in
         the demand planning module).
      3. Union everything into one ID set.
    """
    if user.is_superuser:
        return None

    # Pass the model class (not a client-filtered queryset) to
    # get_objects_for_user: with django-guardian 3.3.x + Django 5,
    # passing a QuerySet hits a values() regression ("in' lookup must
    # have 1 selected fields"). We scope to the client afterwards.
    direct_nodes = get_objects_for_user(
        user, f'mysite.{perm}',
        klass=PlanningLocation,
    ).filter(client=client)

    if not direct_nodes.exists():
        return set()

    authorized_ids: set[int] = set()
    for node in direct_nodes:
        authorized_ids.add(node.pk)
        descendants = PlanningLocation.objects.filter(
            client=client, path__startswith=node.path,
        ).exclude(pk=node.pk).values_list('pk', flat=True)
        authorized_ids.update(descendants)

    return authorized_ids


def user_can_act_at_location(user, location: PlanningLocation, perm: str = OVERRIDE_PERM) -> bool:
    """
    Single-location check: can this user act AT or BELOW the given node?

    Walks the location's ancestor chain (via materialized path) and checks
    whether the user has direct permission on the location itself OR any
    ancestor of it. This is the inverse direction of
    get_authorized_location_ids() — useful when you already have one
    specific location and just need a yes/no answer.
    """
    if user.is_superuser:
        return True

    # Direct permission on this exact node
    if user.has_perm(f'mysite.{perm}', location):
        return True

    # Permission on any ancestor implies permission here too
    ancestor_ids = [int(p) for p in location.path.split('/') if p][:-1]
    if not ancestor_ids:
        return False

    ancestors = PlanningLocation.objects.filter(pk__in=ancestor_ids)
    for ancestor in ancestors:
        if user.has_perm(f'mysite.{perm}', ancestor):
            return True
    return False


def filter_queryset_to_authorized_locations(qs, user, client, location_field: str = 'planning_location'):
    """
    Generic queryset filter — apply authorized-location scoping to any
    queryset that has a FK to PlanningLocation (ForecastLine, ActualSale,
    ForecastAggregate with a location-based agg_key, etc.)

    Usage:
        qs = ForecastLine.objects.filter(version=version)
        qs = filter_queryset_to_authorized_locations(qs, request.user, request.client)
    """
    authorized_ids = get_authorized_location_ids(user, client)
    if authorized_ids is None:
        return qs   # superuser / unrestricted
    if not authorized_ids:
        return qs.none()
    return qs.filter(**{f'{location_field}__in': authorized_ids})
