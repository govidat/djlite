from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User
import nested_admin
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline, TranslationBaseModelAdmin
from .forms import ClientForm, CustomerSignupForm, ClientUserProfileForm, CustomerProfileForm
from django.conf import settings
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2
from .xxadmin_mixins import ClientScopedMixin, _user_has_admin_role
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
# ── ClientUserProfile inline (under ClientAdmin) ──────────────────────



# ── User admin — superuser only, hidden from everyone else ────────────

try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass


# ── Updated get_search_results on CustomUserAdmin ─────────────────────

@admin.register(User)
# ── ClientUserMembership inline ───────────────────────────────────────
# Updated to only show users who belong to the same client

# ── ClientGroup admin — admin role only ──────────────────────────────

@admin.register(ClientGroup)

# ── ClientLocation admin — admin role only ────────────────────────────

@admin.register(ClientLocation)
  

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
