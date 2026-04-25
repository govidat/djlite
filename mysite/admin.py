from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
import nested_admin
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline, TranslationBaseModelAdmin
from .forms import ClientForm, CustomerSignupForm, ClientUserProfileForm, CustomerProfileForm
from django.conf import settings
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2
from .admin_mixins import ClientScopedMixin, _user_has_admin_role
# Register your models here.
from .models import GlobalValCat, GlobalVal, ThemePreset, Client, Theme, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue

from .models import NavItem, Page, PageContent, Layout, Component, ComponentSlot, ClientUserProfile, CustomerProfile, CustomerAddress

# using guardian
from .models import ClientUserMembership, ClientGroup, ClientGroupPermission, ClientLocation
#from unfold.admin import ModelAdmin  # unfold ui NOT WORKING WITH nested-admin
#from django.contrib.contenttypes.admin import GenericTabularInline

#from .models import SUPPORTED_LANGUAGES   # your list of (code, label) tuples

# ── Reusable mixin ────────────────────────────────────────────────────
# Centralises the "climb up to Client and get language_list" logic
# so ThemeInline, PageInline (and any future inline) can reuse it.

# Derive app label dynamically — never hardcode 'myapp' or 'mysite'
APP_LABEL = Client._meta.app_label   # → 'mysite'

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


class GlobalValInline(TranslationBaseModelAdmin, nested_admin.NestedTabularInline):
    model  = GlobalVal
    extra  = 1
    fields = ['key'] + [f'keyval_{code}' for code, _ in settings.LANGUAGES]
    # Renders as:
    # | key      | keyval_en | keyval_hi | keyval_fr | keyval_ta |
    # | logout   | Logout    | hiLogout  | frLogout  |           |


@admin.register(GlobalValCat)
class GlobalValCatAdmin(nested_admin.NestedModelAdmin):
    inlines     = [GlobalValInline]
    list_display = ('globalvalcat_id',)
    search_fields = ('globalvalcat_id',)

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline

class ThemePresetAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    #fields = ["language_id", "label_obj"]
    search_fields = ("themepreset_id",)

class SvgtextbadgeValueInline(nested_admin.NestedTabularInline):
    model  = SvgtextbadgeValue
    extra  = 0
    fields = ('language_code', 'stext', 'ltext')

    def get_language_choices(self, request):
        """
        Resolve client's language_list from the URL's object_id.
        Caches result on the request object so Client is queried
        only once per page load, regardless of how many inline
        rows are rendered.
        """
        # Return cached result if already resolved this request
        if hasattr(request, '_cached_client_lang_choices'):
            return request._cached_client_lang_choices

        from django.conf import settings
        choices = list(settings.LANGUAGES)   # fallback

        client_id = request.resolver_match.kwargs.get('object_id')
        if client_id:
            try:
                client = Client.objects.get(pk=client_id)
                lang_codes = client.language_list or []
                lang_dict  = dict(settings.LANGUAGES)
                choices = [(code, lang_dict.get(code, code)) for code in lang_codes]
            except Client.DoesNotExist:
                pass

        # Cache on request — lives only for this request/response cycle
        request._cached_client_lang_choices = choices
        return choices

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'language_code':
            kwargs['widget'] = forms.Select(
                choices=self.get_language_choices(request)
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

class TextstbItemInline(nested_admin.NestedGenericStackedInline):
    model = TextstbItem
    fields = ("item_id", "ltext", "hidden", "order", "css_class", "svg_text")
    extra = 0
    inlines = [SvgtextbadgeValueInline]
    classes = ['collapse']


class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    #fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

class GentextBlockInline(nested_admin.NestedGenericStackedInline):
    model = GentextBlock
    fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

# ── ThemeInline ───────────────────────────────────────────────────────

class ThemeInline(ClientLanguageMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model = Theme
    extra = 0
    classes = ['collapse']
    #inlines = [GentextBlockInline]

    TRANSLATED_FIELDS = ('name',)
    non_translated_fields = ('theme_id', 'themepreset', 'ltext', 'order', 'hidden', 'is_default')   # adjust to your actual fields


class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    extra = 0
    classes = ['collapse']
    inlines = [TextstbItemInline]

# Option 3 Common Component Model
# ── Component inlines ─────────────────────────────────────────

class ComponentSlotInline(nested_admin.NestedStackedInline):
    model = ComponentSlot
    fk_name = "component"
    extra = 0
    classes = ['collapse']
    fields = [
        "slot_type", "order", "hidden", "ltext", "css_class",
        "actions_class", # text for card, hero
        "image_url", "alt", "figure_class",   # figure
        "accordion_checked",                             # accordion text slot
    ]
    inlines = [ComptextBlockInline]

    class Media:
        js = ("admin/js/component_admin.js",)


class ComponentInline(nested_admin.NestedStackedInline):
    model = Component
    extra = 0
    classes = ['collapse']
    fields = [
        "comp_id", "order", "hidden", "ltext", "css_class",
        "card_body_class", # card
        "hero_content_class", "hero_overlay", "hero_overlay_style",            # hero
        "accordion_type", "accordion_name",    # accordion
        "config",
    ]
    inlines = [ComponentSlotInline]

    class Media:
        js = ("admin/js/component_admin.js",)


class LayoutInline(nested_admin.NestedStackedInline):
    model = Layout
    extra = 0
    classes = ['collapse']
    fields = ["level", "slug", "order", "hidden", "css_class", "style", "parent"]
    show_change_link = True
    inlines = [ComponentInline]

    class Media:
        js = ("admin/js/layout_admin.js",)

class PageContentInline(nested_admin.NestedStackedInline):
    model   = PageContent
    classes = ['collapse']
    extra   = 0
    fields  = ['language_code', 'html']

"""
class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [GentextBlockInline, LayoutInline]
"""
class PageInline(ClientLanguageMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [LayoutInline, PageContentInline]                        # GentextBlockInline,  whatever Page's child inline is

    TRANSLATED_FIELDS = ('name',)                   # add more if Page has other translated fields
    non_translated_fields = ('page_id', 'ltext', 'order', 'parent', 'hidden')    # adjust to your actual fields

class NavItemInline(ClientLanguageMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model = NavItem
    extra = 0
    classes = ['collapse']
    #inlines = [LayoutInline, PageContentInline]                        # GentextBlockInline,  whatever Page's child inline is

    TRANSLATED_FIELDS = ('name',)                   # add more if Page has other translated fields
    non_translated_fields = ('location', 'nav_type', 'page', 'url', 'order', 'parent', 'hidden', 'open_in_new_tab')    # adjust to your actual fields

# ── ClientUserProfile inline (under ClientAdmin) ──────────────────────

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


@admin.register(Client)
class ClientAdmin(ClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin):
    form         = ClientForm
    list_display = ('client_id', 'parent', 'nb_title_svg_pre', 'nb_title_svg_suf')
    inlines      = [ThemeInline, PageInline, NavItemInline, ClientUserProfileInline]
    TRANSLATED_FIELDS = ('name', 'nb_title')
    admin_role_only = True

    def _language_fieldsets(self, lang_codes):
        lang_dict = dict(settings.LANGUAGES)
        return [
            (lang_dict.get(code, code.upper()), {
                'fields': tuple(f"{field}_{code}" for field in self.TRANSLATED_FIELDS)
            })
            for code in lang_codes
        ]

    def get_fieldsets(self, request, obj=None):
        if obj and obj.language_list:
            lang_codes = obj.language_list
        else:
            lang_codes = [code for code, _ in settings.LANGUAGES]
        return [
            ('Identity', {
                'fields': ('client_id', 'parent', 'language_choices',
                           'nb_title_svg_pre', 'nb_title_svg_suf')
            }),
            *self._language_fieldsets(lang_codes),
        ]

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        return _user_has_admin_role(request.user)

    def has_module_perms(self, request):        # chatgpt
        return request.user.is_superuser or _user_has_admin_role(request.user)
    """
    def has_view_permission(self, request, obj=None):
        # Explicitly call mixin method — bypass TranslationBaseModelAdmin
        return ClientScopedMixin.has_view_permission(self, request, obj)

    def has_change_permission(self, request, obj=None):
        # Explicitly call mixin method — bypass TranslationBaseModelAdmin
        return ClientScopedMixin.has_change_permission(self, request, obj)
    """
    def get_queryset(self, request):
        # Call NestedModelAdmin's get_queryset directly — skip TranslationBaseModelAdmin
        qs = nested_admin.NestedModelAdmin.get_queryset(self, request)
        if request.user.is_superuser:
            return qs
        # Explicitly use ClientScopedMixin method
        return qs.filter(
            client_id__in=ClientScopedMixin._permitted_client_ids(self, request)
        )

    class Media:
        js = ("admin/js/layout_admin.js", "admin/js/component_admin.js",)

# ── User admin — superuser only, hidden from everyone else ────────────

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

"""
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    search_fields = ('username', 'email')

    def has_module_permission(self, request):  # instead of has_module_perms
        return request.user.is_superuser        # ← superuser only
    # chatgpt        
    #def has_view_permission(self, request, obj=None):
    #    if request.user.is_superuser:
    #        return True
    #    # Allow view_user perm so autocomplete endpoint works
    #    # but has_module_perms=False keeps it off the sidebar
    #    return request.user.has_perm('auth.view_user')
    #
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

    def get_queryset(self, request):   # chatgpt
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        # Client admins should not see superusers
        return qs.filter(is_superuser=False, is_active=True)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        if request.user.is_superuser:
            return queryset, use_distinct

        # ── KEY CHANGE: scope to requesting user's client only ────────
        try:
            client = request.user.client_profile.client
            queryset = queryset.filter(
                client_profile__client=client,    # same client only
                is_superuser=False,
            )
        except ClientUserProfile.DoesNotExist:
            queryset = queryset.none()            # safety: show nothing

        return queryset, use_distinct
"""

# ── Updated get_search_results on CustomUserAdmin ─────────────────────

@admin.register(User)
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
        """
        client_pk = request.GET.get('client_id')   # ✅ NOW WORKS
        print("CLIENT PK:", client_pk, None)
        if client_pk:
            queryset = queryset.filter(
                customer_profiles__client__id=client_pk,
                is_superuser=False,
                is_active=True,
            )
        else:
            queryset = queryset.none()

        return queryset.distinct(), use_distinct
        """
        """
        # 👇 This comes from Inline
        client_pk = getattr(request, '_current_client_id', None)
        print("CLIENT PK:", getattr(request, '_current_client_id', None))
        if client_pk:
            queryset = queryset.filter(
                customer_profiles__client__id=client_pk,
                is_superuser=False,
                is_active=True,
            )
        else:
            queryset = queryset.none()

        return queryset.distinct(), use_distinct       
        """
        """
        if request.user.is_superuser:
            return queryset, use_distinct

        # Scope autocomplete to same client's staff users only
        
        try:
            client = request.user.client_profile.client
            queryset = queryset.filter(
                customer_profiles__client=client,   # same client only
                is_superuser=False,
            )
        except ClientUserProfile.DoesNotExist:
            queryset = queryset.none()

        return queryset, use_distinct
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


class ClientLocationInline(nested_admin.NestedTabularInline):
    model  = ClientLocation
    extra  = 0
    fields = ('location_id', 'name', 'location_type', 'is_active')

"""
class ClientUserMembershipInline(admin.TabularInline):
    model  = ClientUserMembership
    extra  = 1
    fields = ('user',)
    #raw_id_fields = ('user',)
    autocomplete_fields = ('user',)   # ← replaces raw_id_fields
    # addition due to ClientUserProfile
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'user' and not request.user.is_superuser:
            # Only show users belonging to this client
            try:
                client = request.user.client_profile.client
                kwargs['queryset'] = User.objects.filter(
                    client_profile__client=client,
                    is_superuser=False,
                )
            except ClientUserProfile.DoesNotExist:
                kwargs['queryset'] = User.objects.none()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
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
"""
# ── ClientUserMembership inline ───────────────────────────────────────
# Updated to only show users who belong to the same client

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

# ── ClientGroup admin — admin role only ──────────────────────────────

@admin.register(ClientGroup)
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

# ── ClientLocation admin — admin role only ────────────────────────────

@admin.register(ClientLocation)
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
    

# ── CustomerAddress inline ────────────────────────────────────────────
"""
class CustomerAddressInline(admin.TabularInline):
    model  = CustomerAddress
    extra  = 0
    fields = ('label', 'street', 'city', 'zip_code', 'country_code', 'is_default')
"""
# ── CustomerProfile admin ─────────────────────────────────────────────
"""
@admin.register(CustomerProfile)
class CustomerProfileAdmin(ClientScopedMixin, admin.ModelAdmin):
    inlines      = [CustomerAddressInline]
    list_display = ('user', 'client', 'mobile', 'preferred_language', 'is_active')
    list_filter  = ('client', 'is_active')
    search_fields = ('user__email', 'user__first_name', 'mobile')
    readonly_fields = ('user', 'client')

    def has_module_permission(self, request):
        # Visible to clientadmin and superuser only
        return _user_has_admin_role(request.user)

    def has_add_permission(self, request):
        # Customers self-register — admin never creates CustomerProfiles
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Scope to permitted clients
        return qs.filter(
            client__client_id__in=self._permitted_client_ids(request)
        )

"""

"""
# Future eCommerce models
@admin.register(Order)
class OrderAdmin(ClientScopedMixin, admin.ModelAdmin):

    def has_module_perms(self, request):
        if request.user.is_superuser:
            return True
        # Visible only if user has any order permission
        from utils.permissions import has_module_perm
        # Need client context here — check across all their clients
        return ClientGroup.objects.filter(
            memberships__user=request.user,
            permissions__module='order',
            is_active=True,
        ).exists()
"""

#admin.site.register(Language, LanguageAdmin)
admin.site.register(ThemePreset, ThemePresetAdmin)



# Future Commerce Admin like Order, Delivery Billing
"""
@admin.register(Order)
class OrderAdmin(ClientScopedMixin, admin.ModelAdmin):

    def has_view_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'order', 'view', obj)

    def has_change_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'order', 'edit', obj)

    def has_add_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'order', 'create', obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'order', 'delete', obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Scope to permitted clients first
        qs = qs.filter(client_id__in=self._permitted_client_ids(request))
        # Then scope to permitted locations if user has location restrictions
        from utils.permissions import get_user_permissions
        # Location scoping per order — only if needed
        return qs


@admin.register(Billing)
class BillingAdmin(ClientScopedMixin, admin.ModelAdmin):

    def has_view_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'billing', 'view', obj)

    def has_change_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'billing', 'edit', obj)

    def has_add_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'billing', 'create', obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_action_permission(request, 'billing', 'delete', obj)
"""
"""
class HeroCardTextInline(nested_admin.NestedStackedInline):
    model = HeroCardText
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroCardFigureInline(nested_admin.NestedStackedInline):
    model = HeroCardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "figure_class", "position_id", "image_url", "alt", "css_class" )
    classes = ['collapse']

class HeroCardInline(nested_admin.NestedStackedInline):
    model = HeroCard
    extra = 0
    max_num = 1
    #fields = ("order", "hidden", "ltext", "css_class", "body_class")
    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        (None, {"fields": ["css_class", "body_class"]}),
    ]        
    inlines = [HeroCardTextInline, HeroCardFigureInline]
    classes = ['collapse']

class HeroTextInline(nested_admin.NestedStackedInline):
    model = HeroText
    extra = 0
    max_num = 1
    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        ("Actions", {"fields": ["actions_class", "actions_position_id"]}), 
    ]    
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroFigureInline(nested_admin.NestedStackedInline):
    model = HeroFigure
    extra = 0
    max_num = 1    
    #fields = ("order", "hidden", "ltext", "figure_class", "position_id", "image", "css_class" )

    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        (None, {"fields": ["figure_class", "position_id"]}),
        (None, {"fields": ["image_url", "alt"]}),
        (None, {"fields": ["css_class"]}), 
    ]    
    classes = ['collapse']

class CardTextInline(nested_admin.NestedStackedInline):
    model = CardText
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class CardFigureInline(nested_admin.NestedStackedInline):
    model = CardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "figure_class", "position_id", "image_url", "alt", "css_class" )
    classes = ['collapse'] 

class AccordionTextInline(nested_admin.NestedStackedInline):
    model = AccordionText
    extra = 0
    max_num = 5
    fields = ("ltext", "order", "checked", "hidden")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroInline(nested_admin.NestedStackedInline):
    model = Hero
    extra = 0
    max_num = 1    
    fields = ("css_class", "herocontent_class", "overlay", "overlay_style")
    inlines = [HeroTextInline, HeroFigureInline, HeroCardInline]
    classes = ['collapse']

class CardInline(nested_admin.NestedStackedInline):
    model = Card
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "body_class")
    inlines = [CardTextInline, CardFigureInline]
    classes = ['collapse']

class AccordionInline(nested_admin.NestedStackedInline):
    model = Accordion
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "type", "name")
    inlines = [AccordionTextInline]
    classes = ['collapse']

@admin.register(Layout)
class LayoutAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client", "page", "parent", "order", "level", "css_class", "style", "hidden", "slug")
    fieldsets = [
        (None, {"fields": ["client", "page", "order", "level", "slug", "parent"]}),
        (None, {"fields": ["css_class", "style"]}),
        (None, {"fields": ["hidden"]}),
        (None, {"fields": ["comp_id"]}),       
    ]    
    # ideally layout can be an inline under page. but we are not able to brnach to a component inline from another inline.
    # client is kept, so that layout can be a separate admin tab. in that we are braching to component type admin.
    inlines = []
    classes = ['collapse']
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        if obj.level == 40:
            if obj.comp_id == 'card':            
                return [CardInline(self.model, self.admin_site)]
            if obj.comp_id == 'hero':            
                return [HeroInline(self.model, self.admin_site)]
            if obj.comp_id == 'accordion':            
                return [AccordionInline(self.model, self.admin_site)]            
        return []


class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []

class ThemeInline(nested_admin.NestedStackedInline):
    model = Theme
    extra = 0
    classes = ['collapse']
    #list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []

class SvgtextbadgeValueInline(nested_admin.NestedStackedInline):
    model = SvgtextbadgeValue
    extra = 1
    classes = ['collapse']

class LanguageAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    fields = ["language_id", "label_obj"]
    search_fields = ("language_id",)

@admin.register(Client)
class ClientAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client_id", "parent")
    #search_fields = ("client_id",)
    form = ClientForm
    # Hide the raw JSON field in the admin display
    fields = ['client_id', 'parent', 'language_choices'] 
    list_display = ('client_id', 'parent')
    inlines = [GentextBlockInline, ThemeInline, PageInline]
    class Media:
        js = ("admin/js/layout_admin.js", "admin/js/component_admin.js",)
"""