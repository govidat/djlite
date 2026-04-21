# admin_mixins.py
from guardian.shortcuts import get_objects_for_user
from .models import Client, ClientGroup

# Derive app label dynamically — never hardcode 'myapp' or 'mysite'
APP_LABEL = Client._meta.app_label   # → 'mysite'

def _user_has_admin_role(user):
    """User has admin role in ANY active client group."""
    if user.is_superuser:
        return True
    return ClientGroup.objects.filter(
        memberships__user=user,
        role='admin',
        is_active=True,
    ).exists()

class ClientScopedMixin:
    """
    Mixin for any ModelAdmin or Inline whose queryset
    should be scoped to the user's permitted clients.
    Works with the new ClientGroup/ClientUserMembership design.
    Superusers bypass all checks.
    """
    # Add this — controls whether this admin is a structural model
    # that only admin role can change
    admin_role_only = False   # override to True in ClientGroup, ClientLocation

    def _permitted_clients(self, request):
        """
        QS of Client objects user has view access to.
        Cached on request object to avoid repeated DB/guardian hits
        across multiple inlines on the same page.
        """
        if not hasattr(request, '_permitted_clients_qs'):
            if request.user.is_superuser:
                request._permitted_clients_qs = Client.objects.all()
            else:
                request._permitted_clients_qs = get_objects_for_user(
                    request.user,
                    f'{APP_LABEL}.view_client_data',   # ← dynamic 'mysite.view_client_data',
                    klass=Client,
                )
        return request._permitted_clients_qs
    
    def _permitted_client_pks(self, request):
        """Permitted Client PKs (integer id). Used for guardian."""
        if not hasattr(request, '_permitted_client_pks'):
            request._permitted_client_pks = list(
                self._permitted_clients(request).values_list('id', flat=True)
            )
        return request._permitted_client_pks

    def _permitted_client_ids(self, request):
        """
        Flat list of permitted client PKs.
        Cached on request object.
        """
        if not hasattr(request, '_permitted_client_ids_list'):
            request._permitted_client_ids_list = list(
                self._permitted_clients(request).values_list('client_id', flat=True)
            )
        return request._permitted_client_ids_list

    def _client_from_obj(self, obj, max_depth=5):
        """
        Walk FK chain to resolve the Client from any related object.
        Extend this if you have deeper nesting e.g. Shipment → Order → Client.
        """
        if obj is None or max_depth <= 0:
            return None        
        if isinstance(obj, Client):
            return obj
        # Direct FK to client
        if hasattr(obj, 'client'):
            return obj.client
        # 🔁 Walk through all FK fields dynamically
        for field in obj._meta.fields:
            if field.is_relation and field.many_to_one:
                related_obj = getattr(obj, field.name, None)
                if related_obj:
                    client = self._client_from_obj(related_obj, max_depth - 1)
                    if client:
                        return client

        return None       

        """
        # One level deep e.g. OrderLine → Order → Client
        if hasattr(obj, 'order') and hasattr(obj.order, 'client'):
            return obj.order.client
        # Two levels deep e.g. ShipmentItem → Shipment → Order → Client
        if hasattr(obj, 'shipment') and hasattr(obj.shipment, 'order'):
            return obj.shipment.order.client
        return None
        """

    def _has_guardian_perm(self, request, perm, obj=None):
        """Central guardian perm check with superuser bypass."""
        if request.user.is_superuser:
            return True
        if obj is None:
            return bool(self._permitted_client_ids(request))
        client = self._client_from_obj(obj)
        if client is None:
            return False
        #return request.user.has_perm(f'mysite.{perm}', client)
        return request.user.has_perm(f'{APP_LABEL}.{perm}', client)
    # ── ModelAdmin permission hooks ───────────────────────────────────

    def has_module_perms(self, request, app_label=None):
        if request.user.is_superuser:
            return True
        return bool(self._permitted_client_ids(request))

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True

        if getattr(self, 'admin_role_only', False):
            return _user_has_admin_role(request.user)

        return self._has_guardian_perm(request, 'view_client_data', obj)

    """ chatgpt
    def has_view_permission(self, request, obj=None):
        return self._has_guardian_perm(request, 'view_client_data', obj)
    """    
    """ chatgpt
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        # If this is a structural model, only admin role can change it
        if getattr(self, 'admin_role_only', False):
            return _user_has_admin_role(request.user)
        return self._has_guardian_perm(request, 'edit_client_data', obj)
    """
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True

        if getattr(self, 'admin_role_only', False):
            if obj:
                client = self._client_from_obj(obj)
                return ClientGroup.objects.filter(
                    memberships__user=request.user,
                    client=client,
                    role='admin',
                    is_active=True,
                ).exists()
            return _user_has_admin_role(request.user)

        return self._has_guardian_perm(request, 'edit_client_data', obj)

    def has_add_permission(self, request, obj=None):
        """
        obj is the parent object when called from an inline.
        For top-level admins obj is always None.
        """        
        if request.user.is_superuser:
            return True
        if getattr(self, 'admin_role_only', False):
            return _user_has_admin_role(request.user)
        if obj is not None:
            return self._has_guardian_perm(request, 'create_client_data', obj)
        return bool(self._permitted_client_ids(request))
    

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if getattr(self, 'admin_role_only', False):
            return _user_has_admin_role(request.user)
        return self._has_guardian_perm(request, 'admin_client_data', obj)

    # ── Module-level permission check (for commerce models) ───────────

    def has_module_action_permission(self, request, module, action, obj=None):
        """
        Fine-grained check using ClientGroup module permissions.
        Use this in commerce admin classes (OrderAdmin, BillingAdmin etc.)

        Usage in a subclass:
            def has_change_permission(self, request, obj=None):
                return self.has_module_action_permission(request, 'order', 'edit', obj)
        """
        if request.user.is_superuser:
            return True
        client = self._client_from_obj(obj) if obj else None
        if client is None:
            # No object context — check if user has this perm on ANY client
            from .models import ClientGroup
            return ClientGroup.objects.filter(
                memberships__user=request.user,
                is_active=True,
                permissions__module=module,
                permissions__action=action,
            ).exists()
        from utils.permissions import has_module_perm
        return has_module_perm(request.user, client, module, action)