from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import GlobalVal
from utils.globalval import bust_globalval_cache

from django.core.cache import cache
from guardian.shortcuts import assign_perm, remove_perm
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from .models import User, ClientGroup, ClientLocation, ClientUserProfile, CustomerProfile, ClientUserMembership, ClientGroupPermission, Client, Theme, Page, Layout, Component, ComponentSlot, ComptextBlock, SvgtextbadgeValue, TextstbItem

"""
@receiver(post_save, sender=GlobalVal)
@receiver(post_delete, sender=GlobalVal)
def clear_globalval_cache(sender, **kwargs):
    bust_globalval_cache()
"""
# ── GlobalVal cache signals ───────────────────────────────────────────

@receiver(post_save, sender=GlobalVal)
@receiver(post_delete, sender=GlobalVal)
def globalval_changed(sender, **kwargs):
    """Bust globalval cache whenever any GlobalVal is saved or deleted."""
    #from utils.globalval import bust_globalval_cache
    bust_globalval_cache()



# ── Guardian permission sets ──────────────────────────────────────────
# Map roles to standard Django model permissions
# These are the model-level permissions Django admin checks first
#CMS_MODELS = [User, Client, Theme, Page, Layout, Component, ComponentSlot, ComptextBlock, SvgtextbadgeValue, TextstbItem,  ClientGroup, ClientLocation, ClientGroupPermission, ClientUserMembership]   # add Layout, Component etc.
#CMS_MODELS = [Client]   # Removed Inline values.

# Full CRUD based on role — CMS content models
CONTENT_MODELS = [
    Theme, Page, Layout, Component,
    ComponentSlot, ComptextBlock, SvgtextbadgeValue, TextstbItem,
]

# Only admin role gets add/change/delete — structural models
ADMIN_ONLY_MODELS = [
    ClientGroup,
    ClientLocation,
    ClientGroupPermission,
    ClientUserMembership,
    ClientUserProfile,    # ← add — clientadmin can manage staff profiles
]

# ADMIN Add only for Admin — needed for user creation
ADMIN_ADD_ONLY_MODELS = [
    User,
]

# Actions per role per category
CONTENT_ROLE_ACTIONS = {
    'viewer': ['view'],
    'staff':  ['view', 'add', 'change'],
    'admin':  ['view', 'add', 'change', 'delete'], 
}

# Split Client out from other admin models
CLIENT_MODEL_ACTIONS = {
    'viewer': [],
    'staff':  [],
    'admin':  ['view', 'change'],   # ← no 'add', no 'delete'
}

ADMIN_ONLY_ROLE_ACTIONS = {
    'viewer': [],        # ← no permissions at all
    'staff':  [],        # ← no permissions at all
    'admin':  ['view', 'add', 'change', 'delete'],
}


"""
# signals.py — future ecommerce models
ECOMMERCE_MODELS = [
    # Order, Delivery, Shipment, Billing...  add when ready
]

ECOMMERCE_ROLE_ACTIONS = {
    'viewer': ['view'],
    'staff':  ['view', 'change'],   # staff can process but not create/delete
    'admin':  ['view', 'add', 'change', 'delete'],
}
"""

def _get_model_permissions(role):
    perms = []

    # Client — admin can edit but never create or delete
    ct = ContentType.objects.get_for_model(Client)
    for action in CLIENT_MODEL_ACTIONS.get(role, []):
        try:
            perms.append(Permission.objects.get(
                codename=f"{action}_{Client._meta.model_name}",
                content_type=ct,
            ))
        except Permission.DoesNotExist:
            pass

    # Admin-only models — only admin role gets any perms
    for model in ADMIN_ONLY_MODELS:
        ct = ContentType.objects.get_for_model(model)
        for action in ADMIN_ONLY_ROLE_ACTIONS.get(role, []):
            try:
                perms.append(Permission.objects.get(
                    codename=f"{action}_{model._meta.model_name}",
                    content_type=ct,
                ))
            except Permission.DoesNotExist:
                pass

    # Content models — full CRUD based on role
    for model in CONTENT_MODELS:
        ct = ContentType.objects.get_for_model(model)
        for action in CONTENT_ROLE_ACTIONS.get(role, []):
            try:
                perms.append(Permission.objects.get(
                    codename=f"{action}_{model._meta.model_name}",
                    content_type=ct,
                ))
            except Permission.DoesNotExist:
                pass


    # View-only (User) — ONLY for admin role, for autocomplete
    if role == 'admin':
        for model in ADMIN_ADD_ONLY_MODELS:
            ct = ContentType.objects.get_for_model(model)
            for action in ['view', 'add']:
                try:
                    perms.append(Permission.objects.get(
                        codename=f"{action}_{model._meta.model_name}",
                        content_type=ct,
                    ))
                except Permission.DoesNotExist:
                    pass
    return perms
    


ALL_CLIENT_PERMS = [
    'view_client_data',
    'edit_client_data',
    'create_client_data',
    'admin_client_data',
]

ROLE_GUARDIAN_PERMS = {
    'viewer': ['view_client_data'],
    'staff':  ['view_client_data', 'edit_client_data', 'create_client_data'],
    'admin':  ['view_client_data', 'edit_client_data', 'create_client_data', 'admin_client_data'],
}


# ── Helpers ───────────────────────────────────────────────────────────

def _sync_user_guardian_perms(user, client):
    """
    Recompute guardian perms for a user on a client
    by taking the union across all their active groups.
    """
    groups = ClientGroup.objects.filter(
        memberships__user=user,
        client=client,
        is_active=True,
    )

    # Union guardian perms across all groups
    perms_to_grant = set()
    for group in groups:
        perms_to_grant.update(ROLE_GUARDIAN_PERMS.get(group.role, []))

    # Remove all existing then reassign unioned set
    for perm in ALL_CLIENT_PERMS:
        remove_perm(perm, user, client)
    for perm in perms_to_grant:
        assign_perm(perm, user, client)

    # is_staff required for Django admin access
    should_be_staff = bool(perms_to_grant)
    if not user.is_superuser and user.is_staff != should_be_staff:
        user.is_staff = should_be_staff
        user.save(update_fields=['is_staff'])

def _sync_user_model_perms(user, client):
    """
    Sync standard Django model-level permissions.
    Takes the highest role the user has across all their groups for this client.
    Uses categorised model permission sets — content vs admin-only vs view-only.
    """
    groups = ClientGroup.objects.filter(
        memberships__user=user,
        client=client,
        is_active=True,
    )

    if not groups.exists():
        # User has no groups for this client
        # Check if they have groups for OTHER clients before clearing
        has_other_groups = ClientGroup.objects.filter(
            memberships__user=user,
            is_active=True,
        ).exclude(client=client).exists()

        if not has_other_groups:
            # Truly no groups anywhere — remove all model perms
            user.user_permissions.clear()
        return

    # Find highest role across all groups for this client
    role_rank = {'viewer': 1, 'staff': 2, 'admin': 3}
    top_role  = max(groups, key=lambda g: role_rank.get(g.role, 0)).role

    # Get permissions using new categorised function — no CMS_MODELS arg
    perms = _get_model_permissions(top_role)

    # Set them — replaces existing model perms
    user.user_permissions.set(perms)


def _ensure_staff(user):
    if not user.is_staff:
        user.is_staff = True
        user.save(update_fields=['is_staff'])


def _revoke_staff_if_unused(user):
    if not user.is_superuser and not user.client_memberships.exists():
        user.is_staff = False
        user.user_permissions.clear()
        user.save(update_fields=['is_staff'])


def _bust_user_group_cache(user, client):
    cache.delete(f"user_groups:{user.pk}:{client.pk}")


# ── ClientUserMembership signals ──────────────────────────────────────
"""
@receiver(post_save, sender=ClientUserMembership)
def membership_saved(sender, instance, **kwargs):
    user   = instance.user
    client = instance.group.client
    _ensure_staff(user)
    _bust_user_group_cache(user, client)
    _sync_user_guardian_perms(user, client)
    _sync_user_model_perms(user, client)    # ← this was missing
"""
@receiver(post_save, sender=ClientUserMembership)
def membership_saved(sender, instance, **kwargs):
    user   = instance.user
    client = instance.group.client
    # ✅ STEP 1: Ensure staff profile exists
    staff_profile, created = ClientUserProfile.objects.get_or_create(
        user=user,
        defaults={"client": client}
    )
    # ⚠️ Safety: If profile exists but wrong client (edge case)
    if not created and staff_profile.client != client:
        raise ValueError(
            f"User {user} already belongs to another client as staff."
        )
    # ✅ STEP 2: Remove customer profile for SAME client (optional but recommended)
    #CustomerProfile.objects.filter(
    #    user=user,
    #    client=client
    #).delete()

    # ✅ STEP 3: Your existing logic (unchanged)
    _ensure_staff(user)
    _bust_user_group_cache(user, client)
    _sync_user_guardian_perms(user, client)
    _sync_user_model_perms(user, client)

"""
@receiver(post_delete, sender=ClientUserMembership)
def membership_deleted(sender, instance, **kwargs):
    user   = instance.user
    client = instance.group.client
    _bust_user_group_cache(user, client)
    _sync_user_guardian_perms(user, client)
    _sync_user_model_perms(user, client)    # ← this was missing
    _revoke_staff_if_unused(user)
"""
@receiver(post_delete, sender=ClientUserMembership)
def membership_deleted(sender, instance, **kwargs):
    user   = instance.user
    client = instance.group.client

    _bust_user_group_cache(user, client)
    _sync_user_guardian_perms(user, client)
    _sync_user_model_perms(user, client)

    # ✅ STEP: Check if user still belongs to any group in this client
    still_has_groups = ClientGroup.objects.filter(
        memberships__user=user,
        client=client,
        is_active=True,
    ).exists()

    if not still_has_groups:
        # Remove staff profile
        ClientUserProfile.objects.filter(
            user=user,
            client=client
        ).delete()

        # Optional: recreate customer profile
        #CustomerProfile.objects.get_or_create(
        #    user=user,
        #    client=client
        #)

    _revoke_staff_if_unused(user)

# ── ClientGroup signals ───────────────────────────────────────────────


@receiver(post_save, sender=ClientGroup)
def group_saved(sender, instance, **kwargs):
    """
    If the group role changes, recompute perms for ALL members
    since guardian perms are derived from role.
    """
    for membership in instance.memberships.select_related('user'):
        _bust_user_group_cache(membership.user, instance.client)
        _sync_user_guardian_perms(membership.user, instance.client)
        _sync_user_model_perms(membership.user, instance.client)   # ← add


@receiver(post_delete, sender=ClientGroup)
def group_deleted(sender, instance, **kwargs):
    """Recompute perms for all members when a group is deleted."""
    for membership in instance.memberships.select_related('user'):
        _bust_user_group_cache(membership.user, instance.client)
        _sync_user_guardian_perms(membership.user, instance.client)
        _sync_user_model_perms(membership.user, instance.client)   # ← add



# to bust client cache if models are edited
# ── Helper: walk up to client_id from any model instance ─────────────

def get_client_id_from_instance(instance):
    """
    Walk up the ownership chain to find the client_id.
    Returns None if the chain cannot be resolved (e.g. orphaned record).
    """

    try:
        # Direct
        if isinstance(instance, Client):
            return instance.client_id

        # One hop via client FK
        if isinstance(instance, (Theme, Page)):
            return instance.client.client_id

        # Two hops: Layout → page → client
        if isinstance(instance, Layout):
            return instance.page.client.client_id

        # Three hops: Component → layout → page → client
        if isinstance(instance, Component):
            return instance.layout.page.client.client_id

        # Four hops: ComponentSlot → component → layout → page → client
        if isinstance(instance, ComponentSlot):
            return instance.component.layout.page.client.client_id

        # GenericForeignKey models — content_object is the parent
        # ComptextBlock.content_object is a ComponentSlot
        if isinstance(instance, ComptextBlock):
            slot = instance.content_object
            if isinstance(slot, ComponentSlot):
                return slot.component.layout.page.client.client_id
            return None

        # TextstbItem.content_object is a ComptextBlock
        if isinstance(instance, TextstbItem):
            block = instance.content_object
            if isinstance(block, ComptextBlock):
                slot = block.content_object
                if isinstance(slot, ComponentSlot):
                    return slot.component.layout.page.client.client_id
            return None

        # SvgtextbadgeValue → textstbitem → content_object (ComptextBlock) → ...
        if isinstance(instance, SvgtextbadgeValue):
            item = instance.textstbitem
            block = item.content_object
            if isinstance(block, ComptextBlock):
                slot = block.content_object
                if isinstance(slot, ComponentSlot):
                    return slot.component.layout.page.client.client_id
            return None

    except Exception:
        # Any broken FK chain (e.g. mid-delete cascade) — fail silently
        return None

    return None


# ── Signal handler ────────────────────────────────────────────────────

def invalidate_client_cache(sender, instance, **kwargs):
    """
    Single handler for post_save and post_delete on all content models.
    Resolves client_id and deletes the clientstatic cache entry.
    """
    client_id = get_client_id_from_instance(instance)
    if client_id:
        cache_key = f"clientstatic:{client_id}"
        cache.delete(cache_key)


# ── Registration helper (called from AppConfig.ready) ─────────────────

def register_signals():


    models_to_watch = [
        Client,
        Theme,
        Page,
        Layout,
        Component,
        ComponentSlot,
        ComptextBlock,
        TextstbItem,
        SvgtextbadgeValue,
    ]

    for model in models_to_watch:
        post_save.connect(invalidate_client_cache, sender=model)
        post_delete.connect(invalidate_client_cache, sender=model)


