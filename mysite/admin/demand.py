from django.contrib import admin

from modeltranslation.admin import TranslationBaseModelAdmin
from .base import _user_has_admin_role, ClientLanguageMixinV2, BaseAdminInlinecss, ClientScopedMixin

"""
class PlanningLocationAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "level_label", "is_leaf", "depth", "is_active"]
    list_filter   = ["client", "is_leaf", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["path", "depth"]
"""
class PlanningLocationAdmin(ClientScopedMixin, ClientLanguageMixinV2, BaseAdminInlinecss, TranslationBaseModelAdmin, admin.ModelAdmin):
    list_select_related = ('client',)
    admin_role_only = True    
    list_filter     = ("client", "is_leaf", "is_active")
    search_fields   = ["code", "name"]
    #raw_id_fields = ('client', )
    readonly_fields = ["path", "depth"]
    autocomplete_fields = (
        'client',
        'parent',
    )
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'level_label'],
            obj
        )

        return (
            ('General', {
                'fields': ('client', 'parent', 'code', 'is_leaf', 'is_active', 'notes', 'path', 'depth'),
                'classes': ('collapse',),
            }),            
             ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
    
        )
    """
    def has_add_permission(self, request):
        return _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)
    """
"""
class PlanningCustomerAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "customer_type", "level_label", "is_active"]
    list_filter   = ["client", "customer_type", "is_active"]
    search_fields = ["code", "name", "external_id"]
    readonly_fields = ["path", "depth"]
"""

class PlanningCustomerAdmin(ClientScopedMixin, ClientLanguageMixinV2, BaseAdminInlinecss, TranslationBaseModelAdmin, admin.ModelAdmin ):
    list_select_related = ('client',)
    admin_role_only = True    
    list_filter     = ("client", "customer_type", "is_active")
    search_fields   = ["code", "name", "external_id"]
    #raw_id_fields = ('client', )
    readonly_fields = ["path", "depth"]
    autocomplete_fields = (
        'client',
        'parent',
    )

    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'level_label'],
            obj
        )

        return (
            ('General', {
                'fields': ('client', 'parent', 'code', 'customer_type', 'external_id', 'is_active', 'notes', 'path', 'depth' ),
                'classes': ('collapse',),
            }),            
             ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
    
        )
    """
    def has_add_permission(self, request):
        return _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)
    """
"""
class SalesNodeAdmin(admin.ModelAdmin):
    list_display  = ["code", "name", "level_label", "is_active"]
    list_filter   = ["client", "is_active"]
    search_fields = ["code", "name"]
    readonly_fields = ["path", "depth"]
"""
class SalesNodeAdmin(ClientScopedMixin, ClientLanguageMixinV2, BaseAdminInlinecss, TranslationBaseModelAdmin, admin.ModelAdmin ):
    list_select_related = ('client',)
    admin_role_only = True    
    list_filter     = ("client", "is_active")
    search_fields   = ["code", "name"]
    #raw_id_fields = ('client', )
    readonly_fields = ["path", "depth"]
    autocomplete_fields = (
        'client',
        'parent',
    )

    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'level_label'],
            obj
        )

        return (
            ('General', {
                'fields': ('client', 'parent', 'code', 'planning_location', 'is_active'),
                'classes': ('collapse',),
            }),            
             ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
    
        )
    """
    def has_add_permission(self, request):
        return _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)
    """

class CustomerSalesAssignmentAdmin(admin.ModelAdmin):
    list_display  = ["client", "planning_customer", "sales_node", "valid_from", "valid_to"]
    list_filter   = ["client", "sales_node__client"]
    search_fields = ["planning_customer__code", "sales_node__code"]
    admin_role_only = True
    autocomplete_fields = (
        'client',
        'planning_customer',
        'sales_node'
    )

# ── Prerequisite: ItemAdmin must declare search_fields ───────────────────────
# In your existing ItemAdmin, ensure this is present:
#
#   class ItemAdmin(admin.ModelAdmin):
#       search_fields = ["item_id", "name", "name_en", "name_hi"]
#
# autocomplete_fields on ActualSaleAdmin requires it.
# ─────────────────────────────────────────────────────────────────────────────

class ActualSaleAdmin(admin.ModelAdmin):

    # ── List view ─────────────────────────────────────────────────────────────
    list_display   = [
        "client",
        "period_type", "period_start", "period_end",
        "planning_location", "item", "planning_customer",
        "qty", "revenue",
    ]
    list_filter    = ["client", "period_type", "planning_location"]
    search_fields  = [
        "item__item_id",    # Item.item_id  (your primary identifier)
        "item__name",       # default language name
        "planning_customer__code",
        "planning_customer__name",
    ]
    date_hierarchy = "period_start"
    readonly_fields = ["period_end"]        # auto-computed, never hand-edited

    # ── Form: autocomplete for item (avoids huge <select>) ────────────────────
    autocomplete_fields = ["item", "planning_customer", "planning_location"]

    # ── Client-scope the item queryset ────────────────────────────────────────
    def get_form(self, request, obj=None, **kwargs):
        """
        Restrict the item, planning_location, and planning_customer dropdowns
        to the client already set on the ActualSale being edited.
        For new records the full queryset is shown (client not yet chosen).
        """
        from mysite.models import Item
        from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer

        form = super().get_form(request, obj, **kwargs)

        if obj and obj.client_id:
            if "item" in form.base_fields:
                form.base_fields["item"].queryset = (
                    Item.objects.filter(client=obj.client, status="active")
                    .order_by("item_id")
                )
            if "planning_location" in form.base_fields:
                form.base_fields["planning_location"].queryset = (
                    PlanningLocation.objects.filter(client=obj.client, is_active=True)
                    .order_by("path")
                )
            if "planning_customer" in form.base_fields:
                form.base_fields["planning_customer"].queryset = (
                    PlanningCustomer.objects.filter(client=obj.client, is_active=True)
                    .order_by("path")
                )
        return form

    admin_role_only = True  # your existing mixin flag

"""
class ActualSaleAdmin(admin.ModelAdmin):
    list_display  = ["client", 
        "period_type", "period_start", "period_end",
        "planning_location", "item", "planning_customer", "qty", "revenue",
    ]
    list_filter   = ["client", "period_type", "planning_location"]
    search_fields = ["item__name", "planning_customer__code"]
    date_hierarchy = "period_start"
    admin_role_only = True
"""