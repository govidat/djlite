# admin_mixins.py
from guardian.shortcuts import get_objects_for_user
from mysite.models import Client, ClientGroup, GlobalItem, Item, Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue
from django.conf import settings
from django.db.models import Q
from django import forms
from django.core.exceptions import PermissionDenied

# Derive app label dynamically — never hardcode 'myapp' or 'mysite'
APP_LABEL = Client._meta.app_label   # → 'mysite'
"""
def _user_has_admin_role(user):
    #User has admin role in ANY active client group.
    if user.is_superuser:
        return True
    return ClientGroup.objects.filter(
        memberships__user=user,
        role='admin',
        is_active=True,
    ).exists()
"""
"""
def _user_has_admin_role(user):
    #User has admin role in ANY active client group.

    # IMPORTANT: admin login page uses AnonymousUser
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    return ClientGroup.objects.filter(
        memberships__user=user,
        role='admin',
        is_active=True,
    ).exists()
"""
def _user_has_admin_role(user, client=None):

    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    qs = ClientGroup.objects.filter(
        memberships__user=user,
        role='admin',
        is_active=True,
    )

    if client:
        qs = qs.filter(client=client)

    return qs.exists()

class ClientScopedMixin:
    """
    ClientScopedMixin
        ├── client discovery
        ├── permission checks
        ├── FK ownership resolution
        └── admin scoping

    Mixin for any ModelAdmin or Inline whose queryset
    should be scoped to the user's permitted clients.
    Works with the new ClientGroup/ClientUserMembership design.
    Superusers bypass all checks.
    """
    # Add this — controls whether this admin is a structural model
    # that only admin role can change
    admin_role_only = False   # override to True in ClientGroup, ClientLocation

    """
    def _permitted_clients(self, request):
        
        #QS of Client objects user has view access to.
        #Cached on request object to avoid repeated DB/guardian hits
        #across multiple inlines on the same page.
        
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
    """
    # faster way of getting from Client instead of from Guardian as mentioned above
    def _permitted_clients(self, request):

        if not hasattr(request, "_permitted_clients_qs"):

            if request.user.is_superuser:
                qs = Client.objects.all()

            else:
                qs = Client.objects.filter(
                    groups__memberships__user=request.user,
                    groups__is_active=True,
                ).distinct()

            request._permitted_clients_qs = qs

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
        Flat list of permitted client_id.
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
        # to restrict scope CLIENT_PARENT_FIELDS = ['client', 'item', 'page', 'layout', 'component', 'slot', 'parent', ]
        for field in obj._meta.fields:
            #if field.name not in CLIENT_PARENT_FIELDS:
            #    continue
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
            #return bool(self._permitted_client_ids(request))
            return bool(self._permitted_client_pks(request))
        client = self._client_from_obj(obj)
        if client is None:
            return False
        #return request.user.has_perm(f'mysite.{perm}', client)
        return request.user.has_perm(f'{APP_LABEL}.{perm}', client)
    # ── ModelAdmin permission hooks ───────────────────────────────────

    def has_module_perms(self, request, app_label=None):
        if request.user.is_superuser:
            return True
        #return bool(self._permitted_client_ids(request))
        return bool(self._permitted_client_pks(request))

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        
        if getattr(self, 'admin_role_only', False):
            client = self._client_from_obj(obj) if obj else None
            return _user_has_admin_role(
                request.user,
                client=client,
            )
        """
        if getattr(self, 'admin_role_only', False):
            return _user_has_admin_role(request.user)
        """
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
            client = self._client_from_obj(obj) if obj else None
            return _user_has_admin_role(
                request.user,
                client=client,
            )        
        """
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
        """
        return self._has_guardian_perm(request, 'edit_client_data', obj)

    def has_add_permission(self, request, obj=None):
        """
        obj is the parent object when called from an inline.
        For top-level admins obj is always None.
        """        
        if request.user.is_superuser:
            return True
        if getattr(self, 'admin_role_only', False):
            client = self._client_from_obj(obj) if obj else None
            return _user_has_admin_role(
                request.user,
                client=client,
            )        

        #if getattr(self, 'admin_role_only', False):
        #    return _user_has_admin_role(request.user)
        if obj is not None:
            return self._has_guardian_perm(request, 'create_client_data', obj)
        #return bool(self._permitted_client_ids(request))
        return bool(self._permitted_client_pks(request))
    

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if getattr(self, 'admin_role_only', False):
            client = self._client_from_obj(obj) if obj else None
            return _user_has_admin_role(
                request.user,
                client=client,
            )        

        #if getattr(self, 'admin_role_only', False):
        #    return _user_has_admin_role(request.user)
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
            #from .models import ClientGroup
            return ClientGroup.objects.filter(
                memberships__user=request.user,
                is_active=True,
                permissions__module=module,
                permissions__action=action,
            ).exists()
        from utils.permissions import has_module_perm
        return has_module_perm(request.user, client, module, action)
    
    def get_queryset(self, request):

        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        permitted_clients = self._permitted_clients(request)

        # Client model itself and Proxies of Client
        #if self.model == Client:
        #    return qs.filter(
        #        pk__in=permitted_clients.values("pk")
        #    )
        
        if issubclass(self.model, Client):
            return qs.filter(
                pk__in=permitted_clients.values("pk")
            )

        model_fields = [f.name for f in self.model._meta.fields]

        # Direct client FK
        if 'client' in model_fields:
            return qs.filter(
                client__in=permitted_clients
            )

        # Page → Client
        if 'page' in model_fields:
            return qs.filter(
                page__client__in=permitted_clients
            )

        # Layout → Page → Client
        if 'layout' in model_fields:
            return qs.filter(
                layout__page__client__in=permitted_clients
            )

        # Component → Layout → Page → Client
        if 'component' in model_fields:
            return qs.filter(
                component__layout__page__client__in=permitted_clients
            )

        # Slot → Component → Layout → Page → Client
        if 'slot' in model_fields:
            return qs.filter(
                slot__component__layout__page__client__in=permitted_clients
            )

        return qs

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs
    ):

        if request.user.is_superuser:
            return super().formfield_for_foreignkey(
                db_field,
                request,
                **kwargs
            )

        permitted_clients = self._permitted_clients(request)

        related_model = db_field.remote_field.model

        if hasattr(related_model, 'client'):

            kwargs["queryset"] = related_model.objects.filter(
                client__in=permitted_clients
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs
        )

class ClientLanguageMixin:
    """
    Mixin for any inline nested under Client.
    Resolves the parent client's language_list from:
      1. The inline object's own client FK (editing)
      2. The URL's object_id (adding)
      3. Fallback: all settings.LANGUAGES
    """
    TRANSLATED_FIELDS = ()   # override in each inline

    def _get_client_languages(self, request, obj=None):
        # Case 1: editing an existing inline object
        if obj and obj.pk:
            try:
                return obj.client.language_list or self._all_lang_codes()
            except AttributeError:
                pass

        # Case 2: adding — client_id is the object_id in the URL
        client_id = request.resolver_match.kwargs.get('object_id')
        if client_id:
            try:
                client = Client.objects.get(pk=client_id)
                return client.language_list or self._all_lang_codes()
            except Client.DoesNotExist:
                pass

        return self._all_lang_codes()

    def _all_lang_codes(self):
        return [code for code, _ in settings.LANGUAGES]

    def _build_language_fieldsets(self, lang_codes, extra_fields=()):
        """
        Builds fieldsets like:
          ('English', {'fields': ('name_en',)}),
          ('Tamil',   {'fields': ('name_ta',)}),
          ...
          ('Common',  {'fields': ('zip_code', ...)})
        """
        lang_dict = dict(settings.LANGUAGES)
        fieldsets = []
        for code in lang_codes:
            label = lang_dict.get(code, code.upper())
            fields = tuple(f"{field}_{code}" for field in self.TRANSLATED_FIELDS)
            fieldsets.append((label, {'fields': fields}))
        if extra_fields:
            fieldsets.append(('Common', {'fields': extra_fields}))
        return fieldsets

    def get_fieldsets(self, request, obj=None):
        lang_codes = self._get_client_languages(request, obj)
        return self._build_language_fieldsets(
            lang_codes,
            extra_fields=self.non_translated_fields
        )

    def get_fields(self, request, obj=None):
        lang_codes = self._get_client_languages(request, obj)
        fields = [
            f"{field}_{code}"
            for code in lang_codes
            for field in self.TRANSLATED_FIELDS
        ]
        return fields + list(self.non_translated_fields)


class ClientLanguageMixinV2:
    """
    Mixin that is more flexible to work with fieldsets.
    Resolves the Client language lit and superlist for superuser.
    Returns only the language dependent part as main language and other languages for flexi use.

    Usage as below:
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'description', 'care_instructions'],
            obj
        )

        return (
            ('GS1 Identification', {
                'fields': ('gtin', 'gpc_brick_code', 'global_item_id', 'domain', 'status'),
                'classes': ('collapse',),
            }),

            ('Main Language', {
                'fields': main_ln_fields,
            }),

            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),    ....
    """    
    TRANSLATED_FIELDS = ()

    def _get_client_language_config(self, request, obj=None):
        """
        Returns (default_language, allowed_languages).

        Priority:
        1. Superuser → full settings.LANGUAGES
        2. obj is a Client → use obj directly
        3. obj has a .client FK → use obj.client
        4. URL object_id → look up Client by PK
        5. request.client (middleware) → use if set
        6. Fallback → full settings.LANGUAGES
        """

        # 1. Superuser gets all languages
        if request.user.is_superuser:
            default = settings.LANGUAGE_CODE
            allowed = [code for code, _ in settings.LANGUAGES]
            return default, allowed

        # 2. obj is itself a Client instance (ClientAdmin change page)
        if obj is not None and isinstance(obj, Client):
            default = obj.default_language or settings.LANGUAGE_CODE
            allowed = obj.language_list or [default]
            return default, allowed

        # 3. obj has a direct client FK (inline editing a related model)
        if obj is not None and hasattr(obj, 'client') and obj.client is not None:
            client = obj.client
            default = client.default_language or settings.LANGUAGE_CODE
            allowed = client.language_list or [default]
            return default, allowed

        # 4. Resolve from URL object_id (admin change page, obj not yet loaded)
        #    This handles the case where get_fieldsets is called before obj is set
        object_id = request.resolver_match.kwargs.get('object_id')
        if object_id:
            # Cache on request to avoid repeated DB hits across multiple inlines
            if not hasattr(request, '_admin_client_lang_config'):
                try:
                    # object_id may be the Client PK (ClientAdmin)
                    # or a related model PK (inline) — try Client first
                    client = Client.objects.get(pk=object_id)
                    request._admin_client_lang_config = (
                        client.default_language or settings.LANGUAGE_CODE,
                        client.language_list or [settings.LANGUAGE_CODE]
                    )
                except (Client.DoesNotExist, ValueError):
                    # object_id is not a Client PK — walk up via obj
                    request._admin_client_lang_config = None

            if request._admin_client_lang_config is not None:
                return request._admin_client_lang_config

        # 5. request.client from middleware (works for non-admin URLs)
        client = getattr(request, 'client', None)
        if client is not None:
            default = client.default_language or settings.LANGUAGE_CODE
            allowed = client.language_list or [default]
            return default, allowed

        # 6. Fallback — should rarely reach here
        default = settings.LANGUAGE_CODE
        allowed = [code for code, _ in settings.LANGUAGES]
        return default, allowed

        """
        #Returns:
        #(default_language, allowed_languages)
        

        # 1. Superuser → full access
        if request.user.is_superuser:
            default = settings.LANGUAGE_CODE
            allowed = [code for code, _ in settings.LANGUAGES]
            return default, allowed

        # 2. From request.client (middleware)
        client = getattr(request, 'client', None)
        if client:
            default = client.default_language or settings.LANGUAGE_CODE
            allowed = client.language_list or [default]
            return default, allowed

        # 3. Fallback
        default = settings.LANGUAGE_CODE
        allowed = [code for code, _ in settings.LANGUAGES]
        return default, allowed    
        """


    def get_translated_field_groups(self, request, fields, obj=None):  
        #Returns:
        #    (main_fields, other_fields)
                
        default_lang, lang_codes = self._get_client_language_config(request, obj)

        main_fields = []
        other_fields = []

        for field in fields:
            for lang in lang_codes:
                f = f"{field}_{lang}"
                if lang == default_lang:
                    main_fields.append(f)
                else:
                    other_fields.append(f)

        return main_fields, other_fields    


class BaseAdminInlinecss:
    class Media:
        css = {'all': ('admin/css/custom_inline.css',)}
        
# admin/mixins.py
"""
class GlobalReadOnlyAdminMixin:

    def has_view_permission(self, request, obj=None):
        return request.user.is_staff

    def has_module_permission(self, request):
        return request.user.is_staff

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
"""

class SharedOrClientScopedMixin(ClientScopedMixin):
    """
    Allows:
    - global rows (client=None)
    - rows for permitted clients

    Used for catalogue/taxonomy models.
    """

    client_field_name = "client"
    # ---------------------------------------------------------
    # Restrict client dropdown
    # ---------------------------------------------------------
    """ Merged with another code block below
    def formfield_for_foreignkey(self, db_field, request, **kwargs):

        if db_field.name == self.client_field_name:

            if request.user.is_superuser:
                kwargs["queryset"] = Client.objects.all()

            else:
                kwargs["queryset"] = self._permitted_clients(request)

        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )
    """
    # ---------------------------------------------------------
    # Default initial client
    # ---------------------------------------------------------

    def get_changeform_initial_data(self, request):

        initial = super().get_changeform_initial_data(request)

        if request.user.is_superuser:
            return initial

        clients = self._permitted_clients(request)

        # Auto-default if only one client
        if clients.count() == 1:
            initial["client"] = clients.first().pk

        return initial

    # ---------------------------------------------------------
    # Hide client field if only one permitted client
    # ---------------------------------------------------------
    """
    def get_form(self, request, obj=None, **kwargs):

        form = super().get_form(request, obj, **kwargs)

        if request.user.is_superuser:
            return form

        clients = self._permitted_clients(request)

        if clients.count() == 1 and "client" in form.base_fields:
            form.base_fields["client"].widget = forms.HiddenInput()

        return form
    """

    # ---------------------------------------------------------
    # Queryset filtering
    # ---------------------------------------------------------

    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        permitted_clients = self._permitted_clients(request)

        return qs.filter(
            Q(**{f"{self.client_field_name}__isnull": True}) |
            Q(**{f"{self.client_field_name}__in": permitted_clients})
        )

    # ---------------------------------------------------------
    # Prevent editing global rows
    # ---------------------------------------------------------

    def has_change_permission(self, request, obj=None):

        if request.user.is_superuser:
            return True

        # Global/shared rows are read-only
        if obj and getattr(obj, "client", None) is None:
            return False

        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):

        if request.user.is_superuser:
            return True

        # Global/shared rows are read-only
        if obj and getattr(obj, "client", None) is None:
            return False

        return super().has_delete_permission(request, obj)


    # ---------------------------------------------------------
    # FK dropdown filtering
    # ---------------------------------------------------------

    def formfield_for_foreignkey(self, db_field, request, **kwargs):

        if request.user.is_superuser:
            return super().formfield_for_foreignkey(
                db_field, request, **kwargs
            )

        permitted_clients = self._permitted_clients(request)

        # Client dropdowns
        if db_field.name == self.client_field_name:
            if request.user.is_superuser:
                kwargs["queryset"] = Client.objects.all()
            else:
                kwargs["queryset"] = self._permitted_clients(request)

        # Item dropdowns
        if db_field.name == "item":
            kwargs["queryset"] = Item.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        # Taxonomy dropdowns
        if db_field.name == "taxonomy":
            kwargs["queryset"] = Taxonomy.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        # TaxonomyNode dropdowns
        elif db_field.name == "node":
            kwargs["queryset"] = TaxonomyNode.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        # NodeAttributeType dropdowns
        elif db_field.name == "attribute_type":
            kwargs["queryset"] = NodeAttributeType.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        # NodeAttributeValue dropdowns
        elif db_field.name == "predefined_value":
            kwargs["queryset"] = NodeAttributeValue.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        # Global items are view-only shared
        elif db_field.name == "global_item":
            kwargs["queryset"] = GlobalItem.objects.all()

        return super().formfield_for_foreignkey(
            db_field, request, **kwargs
        )

    # ---------------------------------------------------------
    # M2M filtering
    # ---------------------------------------------------------

    def formfield_for_manytomany(self, db_field, request, **kwargs):

        if request.user.is_superuser:
            return super().formfield_for_manytomany(
                db_field, request, **kwargs
            )

        permitted_clients = self._permitted_clients(request)

        # Item.taxonomy_mappings etc.
        if db_field.name == "nodes":
            kwargs["queryset"] = TaxonomyNode.objects.filter(
                Q(client__isnull=True) |
                Q(client__in=permitted_clients)
            )

        return super().formfield_for_manytomany(
            db_field, request, **kwargs
        )

    # ---------------------------------------------------------
    # Final server-side enforcement
    # ---------------------------------------------------------

    def save_model(self, request, obj, form, change):

        if not request.user.is_superuser:

            permitted_clients = self._permitted_clients(request)

            # Auto-assign client if only one allowed client
            if getattr(obj, "client_id", None) is None:

                if permitted_clients.count() == 1:
                    obj.client = permitted_clients.first()

            # Prevent creating/editing global rows
            if getattr(obj, "client", None) is None:
                raise PermissionDenied(
                    "Cannot create or edit global objects."
                )

            # Prevent spoofing another client
            if obj.client not in permitted_clients:
                raise PermissionDenied(
                    "You cannot assign objects to this client."
                )

        super().save_model(request, obj, form, change)    