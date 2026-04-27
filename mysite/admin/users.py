import nested_admin
from django.contrib import admin
from django.contrib.auth.models import User
from mysite.models import (Client, ClientUserProfile, ClientGroupPermission, ClientLocation, ClientUserMembership)
from .base import _user_has_admin_role
from .base import ClientScopedMixin

from django.contrib.auth.admin import UserAdmin
APP_LABEL = Client._meta.app_label   # → 'mysite'


try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


class ClientUserProfileInline(nested_admin.NestedStackedInline):
    model         = ClientUserProfile
    extra         = 0
    fields        = ('user', 'mobile', 'is_active')
    #readonly_fields = ('created_at',)
    autocomplete_fields = ('user',)
    admin_role_only = True   # 🔑 important
    classes = ['collapse']
    """
    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return False
        return request.user.has_perm(
            f'{APP_LABEL}.admin_client_data', obj
        )
    """    
    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return _user_has_admin_role(request.user)
    
    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

class CustomUserAdmin(UserAdmin):
    search_fields = ('username', 'email', 'first_name', 'last_name')

    # this contrals if User tab is visible in the ClientAdmin sidebar
    def has_module_permission(self, request):
        if request.user.is_superuser:
            return True
    #    return _user_has_admin_role(request.user)   # 👈 allow access indirectly

    #def has_module_permission(self, request):
    #    return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True

        # Allow Client Admins to use autocomplete
        from mysite.models import ClientGroup
        return ClientGroup.objects.filter(
            memberships__user=request.user,
            role='admin',
            is_active=True,
        ).exists()

    """ changed as per chatgpt above
    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return request.user.has_perm('auth.view_user')
    """
    def has_add_permission(self, request):
        if request.user.is_superuser:
            return True
        return _user_has_admin_role(request.user)   # 👈 allow clientadmin

    #def has_add_permission(self, request):
    #    return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return _user_has_admin_role(request.user)

    #def has_change_permission(self, request, obj=None):
    #    return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    #Since autocomplete_fields uses the autocomplete endpoint rather than formfield_for_foreignkey, 
    # you also need get_search_results to scope results correctly. The autocomplete endpoint doesn't 
    # pass obj context, so use the HTTP_REFERER to resolve the client:
    def _resolve_client_from_referer(self, request):
        
        # Autocomplete requests come from the inline's parent page.
        # Referer URL is e.g. /admin/mysite/clientgroup/5/change/
        # Extract the ClientGroup PK and resolve its client.
        
        import re
        referer = request.META.get('HTTP_REFERER', '')

        # Match /admin/mysite/clientgroup/{pk}/change/
        match = re.search(r'/clientgroup/(\d+)/change/', referer)
        if match:
            group_pk = match.group(1)
            try:
                from mysite.models import ClientGroup
                return ClientGroup.objects.select_related('client').get(
                    pk=group_pk
                ).client
            except ClientGroup.DoesNotExist:
                pass

        # Match /admin/mysite/clientgroup/add/
        # No PK yet — try to get client from session or referer client param
        match = re.search(r'/client/(\d+)/change/', referer)
        if match:
            client_pk = match.group(1)
            try:
                from mysite.models import Client
                return Client.objects.get(pk=client_pk)
            except Client.DoesNotExist:
                pass

        return None


    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        # Always exclude the requesting user themselves
        queryset = queryset.exclude(id=request.user.id)

        if request.user.is_superuser:
            #return queryset, use_distinct
            # Superuser: scope to client resolved from referer
            client = self._resolve_client_from_referer(request)
            if client:
                queryset = queryset.filter(
                    client_profile__client=client,
                    is_superuser=False,
                )
            else:
                # No client context — show all non-superusers
                queryset = queryset.filter(is_superuser=False)
            return queryset, use_distinct

        # Scope autocomplete to same client's staff users only
        # Client admin: scope to their own client
        try:
            client = request.user.client_profile.client
            queryset = queryset.filter(
                client_profile__client=client,
                is_superuser=False,
            )            
            #queryset = queryset.filter(
            #    customer_profiles__client=client,   # same client only
            #    is_superuser=False,
            #)
            
        except ClientUserProfile.DoesNotExist:
            queryset = queryset.none()

        return queryset, use_distinct

        """ How it works
        Superuser opens /admin/mysite/clientgroup/5/change/
        → ClientGroup 5 belongs to Client 'acme'
        → ClientUserMembershipInline renders
        → formfield_for_foreignkey resolves client from URL object_id=5
        → user dropdown filtered to client_profile__client=acme

        Superuser types in autocomplete search box
        → request hits /admin/autocomplete/?app_label=auth&model_name=user&term=john
        → HTTP_REFERER = /admin/mysite/clientgroup/5/change/
        → _resolve_client_from_referer extracts pk=5
        → resolves ClientGroup(5).client = acme
        → queryset filtered to acme's staff users only

        clientadmin opens same page
        → request.user.client_profile.client = acme
        → same filtering applies      

        PREREQUISITE
        The filtering client_profile__client=client only works if your Type 1 staff users have 
        a ClientUserProfile row. Make sure when clientadmin creates a staff user they also 
        create the profile:  
        1. Superuser/clientadmin goes to Client admin page
        2. Adds user via ClientUserProfileInline → ClientUserProfile created
        3. Goes to ClientGroup admin page
        4. Adds membership → dropdown shows only users with profile for this client ✓        

        """



class ClientGroupPermissionInline(admin.TabularInline):
    model  = ClientGroupPermission
    extra  = 1
    fields = ('module', 'action')

    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return False
        return request.user.has_perm(
            f'{APP_LABEL}.admin_client_data', obj.client
        )

    has_change_permission = has_add_permission
    has_delete_permission = has_add_permission


#class ClientLocationInline(nested_admin.NestedTabularInline):
#    model  = ClientLocation
#    extra  = 0
#    fields = ('location_id', 'name', 'location_type', 'is_active')


class ClientUserMembershipInline(admin.TabularInline):
    model               = ClientUserMembership
    extra               = 1
    fields              = ('user',)
    autocomplete_fields = ('user',)
    #Since autocomplete_fields uses the autocomplete endpoint rather than formfield_for_foreignkey, 
    # you also need get_search_results to scope results correctly. The autocomplete endpoint doesn't 
    # pass obj context, so use the HTTP_REFERER to resolve the client:
    def _get_client_from_request(self, request, obj=None):
        
        #Resolve the Client from:
        #1. obj — the parent ClientGroup instance (editing)
        #2. URL object_id — the ClientGroup PK (adding)
        
        # Case 1: obj is the ClientGroup instance
        if obj is not None and hasattr(obj, 'client'):
            return obj.client

        # Case 2: get ClientGroup from URL object_id
        group_id = request.resolver_match.kwargs.get('object_id')
        if group_id:
            try:
                from mysite.models import ClientGroup
                return ClientGroup.objects.select_related('client').get(
                    pk=group_id
                ).client
            except ClientGroup.DoesNotExist:
                pass

        return None

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user':
            client = self._get_client_from_request(request)
            if client:
                if request.user.is_superuser:
                    # Superuser: restrict to users whose profile
                    # belongs to this specific client
                    kwargs['queryset'] = User.objects.filter(
                        client_profile__client=client,
                        is_superuser=False,
                    ).order_by('username')
                else:
                    # Client admin: same restriction
                    kwargs['queryset'] = User.objects.filter(
                        client_profile__client=client,
                        is_superuser=False,
                    ).order_by('username')
            else:
                kwargs['queryset'] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


    """    
    def get_formset(self, request, obj=None, **kwargs):
        
        #Attach client PK to request so autocomplete can use it
        
        if obj:
            # obj = ClientGroup → get its client
            request._current_client_id = obj.client.id
        else:
            request._current_client_id = None

        return super().get_formset(request, obj, **kwargs)
    """
    """
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        formfield = super().formfield_for_foreignkey(db_field, request, **kwargs)

        if db_field.name == "user" and request.resolver_match:
            object_id = request.resolver_match.kwargs.get("object_id")

            if object_id:
                try:
                    group = ClientGroup.objects.select_related('client').get(pk=object_id)
                    client_pk = group.client.id

                    # 🔑 Inject client into autocomplete URL
                    formfield.widget.attrs["data-autocomplete-light-url"] += f"?client_id={client_pk}"

                except ClientGroup.DoesNotExist:
                    pass

        return formfield
    """
    """
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user': #and not request.user.is_superuser:
            # Only show users whose ClientUserProfile belongs to this client
            client_id = request.resolver_match.kwargs.get('object_id')
            if client_id:
                try:
                    client = Client.objects.get(pk=client_id)
                    kwargs['queryset'] = User.objects.filter(
                        client_profile__client=client,  # scoped to same client
                        is_superuser=False,
                    )
                except Client.DoesNotExist:
                    kwargs['queryset'] = User.objects.none()
            else:
                kwargs['queryset'] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    """    


    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return _user_has_admin_role(request.user)
        return request.user.has_perm(
            f'{APP_LABEL}.view_client_data', obj.client
        )

    def has_add_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is None:
            return False
        return request.user.has_perm(
            f'{APP_LABEL}.admin_client_data', obj.client
        )

    def has_change_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_add_permission(request, obj)


class ClientGroupAdmin(ClientScopedMixin, admin.ModelAdmin):
    inlines       = [ClientGroupPermissionInline, ClientUserMembershipInline]
    list_display  = ('name', 'client', 'role', 'is_active')
    list_filter   = ('role', 'is_active')
    search_fields = ('name', 'client__client_id')
    filter_horizontal = ('locations',)
    admin_role_only = True

    def has_module_permission(self, request):   #chatgpt permission instead of perms in Django5
        return _user_has_admin_role(request.user)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(
            client__client_id__in=self._permitted_client_ids(request)
        )

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'client':
            kwargs['queryset'] = self._permitted_clients(request)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_inlines(self, request, obj=None):
        if obj is None:
            return [ClientGroupPermissionInline]
        return [ClientGroupPermissionInline, ClientUserMembershipInline]

class ClientLocationAdmin(ClientScopedMixin, admin.ModelAdmin):
    list_display  = ('location_id', 'name', 'client', 'location_type', 'is_active')
    list_filter   = ('location_type', 'is_active')
    search_fields = ('location_id', 'name', 'client__client_id')

    def has_module_permission(self, request):   #chatgpt permission instead of perms in Django5
        return _user_has_admin_role(request.user)   # ← admin role only

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(client__client_id__in=self._permitted_client_ids(request))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'client':
            kwargs['queryset'] = self._permitted_clients(request)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
  