# utils/permissions.py
from django.core.cache import cache
from mysite.models import ClientLocation, ClientGroup, ClientGroupPermission, ClientUserMembership 


def _get_user_groups(user, client):
    """
    All active groups this user belongs to for this client.
    Cached per request if request object passed, else short-lived cache.
    """
    cache_key = f"user_groups:{user.pk}:{client.pk}"
    groups = cache.get(cache_key)
    if groups is None:
        groups = list(
            ClientGroup.objects.filter(
                memberships__user=user,
                client=client,
                is_active=True,
            ).prefetch_related('permissions', 'locations')
        )
        cache.set(cache_key, groups, 300)  # 5 min
    return groups


def has_module_perm(user, client, module, action, location=None):
    """
    Check if user can perform action on module, optionally scoped to a location.

    Usage:
        has_module_perm(request.user, client, 'order', 'edit')
        has_module_perm(request.user, client, 'order', 'edit', location=store_a)
    """
    if user.is_superuser:
        return True

    groups = _get_user_groups(user, client)
    if not groups:
        return False

    for group in groups:
        # Admin role bypasses module checks
        if group.role == 'admin':
            if location is None or group.has_location_access(location):
                return True

        # Viewer role can only view
        if group.role == 'viewer' and action != 'view':
            continue

        # Check module permission
        has_perm = any(
            p.module == module and p.action == action
            for p in group.permissions.all()
        )
        if not has_perm:
            continue

        # Check location scope
        if location is not None and not group.has_location_access(location):
            continue

        return True

    return False


def get_user_permissions(user, client):
    """
    Returns dict of all permissions the user has for a client.
    Unions permissions across all groups.

    Returns:
    {
        'role': 'staff',                        # highest role across groups
        'modules': {('order', 'edit'), ...},    # unioned module+action pairs
        'locations': ['store_a', 'store_b'],    # [] means all locations
        'all_locations': True/False,
    }
    """
    if user.is_superuser:
        return {
            'role':          'admin',
            'modules':       {(m, a) for m, _ in ClientGroupPermission.MODULE_CHOICES
                              for a, _ in ClientGroupPermission.ACTION_CHOICES},
            'locations':     [],
            'all_locations': True,
        }

    groups = _get_user_groups(user, client)
    if not groups:
        return {'role': None, 'modules': set(), 'locations': [], 'all_locations': False}

    # Determine highest role across all groups
    role_rank  = {'viewer': 1, 'staff': 2, 'admin': 3}
    top_role   = max(groups, key=lambda g: role_rank.get(g.role, 0)).role

    # Union all module permissions
    modules = set()
    for group in groups:
        if group.role == 'admin':
            modules = {(m, a) for m, _ in ClientGroupPermission.MODULE_CHOICES
                       for a, _ in ClientGroupPermission.ACTION_CHOICES}
            break
        for p in group.permissions.all():
            modules.add((p.module, p.action))

    # Union locations — if any group has no location restriction, user gets all
    all_locations = any(not g.locations.exists() for g in groups)
    location_ids  = []
    if not all_locations:
        seen = set()
        for group in groups:
            for loc in group.locations.all():
                if loc.location_id not in seen:
                    location_ids.append(loc.location_id)
                    seen.add(loc.location_id)

    return {
        'role':          top_role,
        'modules':       modules,
        'locations':     location_ids,
        'all_locations': all_locations,
    }