# mysite>admin>demand.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _


from modeltranslation.admin import TranslationBaseModelAdmin
from .base import _user_has_admin_role, ClientLanguageMixinV2, BaseAdminInlinecss, ClientScopedMixin
#from mysite.models import (DistributionChannel)
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
            request, ['name', 'level_label'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'parent', 'code', 'is_leaf', 'is_active', 'notes', 'path', 'depth'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
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
            request, ['name', 'level_label'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'parent', 'code', 'customer_type', 'external_id', 'is_active', 'notes', 'path', 'depth' ),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
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
            request, ['name', 'level_label'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'parent', 'code', 'planning_location', 'is_active'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
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
    """
    def has_add_permission(self, request):
        return _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)
    """
"""
class ZZCustomerSalesAssignmentAdmin(admin.ModelAdmin):
    list_display  = ["client", "planning_customer", "sales_node", "valid_from", "valid_to"]
    list_filter   = ["client", "sales_node__client"]
    search_fields = ["planning_customer__code", "sales_node__code"]
    admin_role_only = True
    autocomplete_fields = (
        'client',
        'planning_customer',
        'sales_node'
    )
"""
class SalesForecastLinkAdmin(admin.ModelAdmin):

    list_display = [
        "client", "planning_location", "distribution_channel", "planning_customer",
        "sales_node", "link_type_display", "valid_from", "valid_to", "is_active_display",
    ]
    list_filter = ["client", "distribution_channel", "valid_to"]  # valid_to filter: NULL = active, quick eyeball
    search_fields = [
        "planning_location__code", "planning_location__name",
        "planning_customer__code", "planning_customer__name",
        "sales_node__code", "sales_node__name",
    ]
    date_hierarchy = "valid_from"
    autocomplete_fields = ["planning_location", "planning_customer", "sales_node"]

    def link_type_display(self, obj):
        return obj.link_type
    link_type_display.short_description = "shape"

    def is_active_display(self, obj):
        return obj.is_active
    is_active_display.short_description = "active"
    is_active_display.boolean = True

    def get_form(self, request, obj=None, **kwargs):
        """Client-scope planning_location, planning_customer, sales_node —
        same pattern as ActualSaleAdmin."""
        from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer, SalesNode

        form = super().get_form(request, obj, **kwargs)

        if obj and obj.client_id:
            if "planning_location" in form.base_fields:
                form.base_fields["planning_location"].queryset = (
                    PlanningLocation.objects.filter(client=obj.client, is_active=True, is_leaf=True)
                    .order_by("path")
                )
            if "planning_customer" in form.base_fields:
                form.base_fields["planning_customer"].queryset = (
                    PlanningCustomer.objects.filter(client=obj.client, is_active=True)
                    .order_by("path")
                )
            if "sales_node" in form.base_fields:
                form.base_fields["sales_node"].queryset = (
                    SalesNode.objects.filter(client=obj.client, is_active=True, children__isnull=True)
                    .order_by("path")
                )
        return form

    def save_model(self, request, obj, form, change):
        obj.full_clean()  # enforce clean() (overlap/shape checks) from the admin too
        super().save_model(request, obj, form, change)

    admin_role_only = True
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
        "distribution_channel",
        "qty", "revenue",
    ]
    list_filter    = ["client", "period_type", "planning_location", "distribution_channel"]
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

    # ── NEW: hide/restrict distribution_channel based on the client ────────────
    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        # Only reachable when a client is already known (existing object).
        # For a brand-new record the client isn't chosen yet, so we can't
        # evaluate the flag at render time — see get_form comment below for
        # how that residual case is handled.
        if obj and obj.client_id and not obj.client.is_distribution_channel_enabled():
            fields = [f for f in fields if f != "distribution_channel"]
        return fields

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        # New record, client unknown yet: don't let anyone hand-pick a channel
        # before we know whether it's even a meaningful dimension for this
        # client. Model.save() would silently coerce to '00' anyway if the
        # client turns out to be DC-disabled, but showing an editable field
        # that might get silently overridden is confusing — lock it instead.
        if obj is None:
            readonly.append("distribution_channel")
        return readonly

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        initial.setdefault("distribution_channel", "00")
        return initial
    
    # ── Client-scope the item queryset ────────────────────────────────────────
    def get_form(self, request, obj=None, **kwargs):
        """
        Restrict the item, planning_location, planning_customer, and
        distribution_channel dropdowns to the client already set on the
        ActualSale being edited. For new records the full querysets are
        shown (client not yet chosen) — distribution_channel is additionally
        locked read-only in that case (see get_readonly_fields).
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
            # NEW — only reachable when the field wasn't already stripped by
            # get_fields (i.e. this client has DC enabled), so this just
            # narrows it to the client's *allowed* codes rather than every
            # active DistributionChannel globally.
            if "distribution_channel" in form.base_fields:
                from mysite.models import DistributionChannel
                allowed = obj.client.get_allowed_distribution_channel_codes()
                form.base_fields["distribution_channel"].queryset = (
                    DistributionChannel.objects.filter(code__in=allowed, is_active=True)
                    .order_by("code")
                )

        return form

    admin_role_only = True  # your existing mixin flag

    # ── Deletion guard: warn when deleting actuals drops outlier adjustments ──
    def _warn_if_outlier_adjustments(self, request, actual_sales):
        from django.contrib import messages
        from mysite.models import ActualSaleOutlierAdjustment
        if isinstance(actual_sales, list):
            row_count = len(actual_sales)
            pks = [s.pk for s in actual_sales]
        else:
            row_count = actual_sales.count()
            pks = actual_sales.values_list('pk', flat=True)
        outlier_count = (
            ActualSaleOutlierAdjustment.objects
            .filter(actual_sale_id__in=pks)
            .count()
        )
        if outlier_count:
            messages.warning(
                request,
                _(
                    "Deleting %(rows)s actual sale row(s) will also permanently "
                    "delete %(outliers)s outlier adjustment record(s) linked to them."
                ) % {
                    'rows': row_count,
                    'outliers': outlier_count,
                },
            )

    def delete_view(self, request, object_id, extra_context=None):
        obj = self.get_object(request, object_id)
        if obj is not None:
            self._warn_if_outlier_adjustments(request, [obj])
        return super().delete_view(request, object_id, extra_context)

    def delete_queryset(self, request, queryset):
        self._warn_if_outlier_adjustments(request, queryset)
        return super().delete_queryset(request, queryset)



# ═════════════════════════════════════════════════════════════════════════════
# 1. ItemPlanningProfile
# ═════════════════════════════════════════════════════════════════════════════

#@admin.register(ItemPlanningProfile)
class ItemPlanningProfileAdmin(admin.ModelAdmin):
    """
    Planners maintain standard_price here for every active item.
    weighted_avg_price and price_updated_at are read-only — set by the
    compute_series_profiles Celery task from ActualSale revenue data.

    Price resolution used by the forecast engine:
        1. weighted_avg_price  (preferred — actuals-derived)
        2. standard_price      (fallback — planner-set)

    Planners should review items where:
        - standard_price is set but weighted_avg_price is null
          (item has no revenue history — price is a pure estimate)
        - weighted_avg_price diverges significantly from standard_price
          (price has shifted — consider updating standard_price)
    """

    list_display = [
        'item_code',
        'client',
        'standard_price',
        'weighted_avg_price',
        'effective_price_display',
        'price_divergence_flag',
        'price_updated_at',
        'updated_at',
    ]
    list_filter  = ['client']
    search_fields = [
        'item__item_id',
        'item__name',
        'client__client_id',
    ]
    ordering = ['client', 'item__item_id']

    # ── Field layout ──────────────────────────────────────────────────────────
    readonly_fields = [
        'client',                   # set at creation, never changed
        'item',                     # set at creation, never changed
        'weighted_avg_price',       # Celery-managed — never hand-edit
        'price_updated_at',         # Celery-managed
        'updated_at',               # auto
        'effective_price_display',
        'price_divergence_flag',
        'actuals_revenue_note',
    ]

    fieldsets = [
        (_('Item'), {
            'fields': [('client', 'item')],
        }),
        (_('Planning Price'), {
            'fields': [
                'standard_price',
                'notes',
            ],
            'description': _(
                'Set the standard_price for every item before running a forecast. '
                'This is the transfer/selling price used to convert qty forecasts '
                'to value (₹) at all aggregate levels.'
            ),
        }),
        (_('Actuals-Derived Price (read-only)'), {
            'fields': [
                'weighted_avg_price',
                'price_updated_at',
                'effective_price_display',
                'price_divergence_flag',
                'actuals_revenue_note',
            ],
            'description': _(
                'weighted_avg_price is computed automatically by the '
                'compute_series_profiles task from sum(revenue)/sum(qty) '
                'over recent actuals. Do not edit manually.'
            ),
            'classes': ['collapse'],
        }),
        (_('Audit'), {
            'fields': ['updated_at'],
            'classes': ['collapse'],
        }),
    ]

    # ── Custom columns ────────────────────────────────────────────────────────

    @admin.display(description='Item ID', ordering='item__item_id')
    def item_code(self, obj):
        return obj.item.item_id

    @admin.display(description='Effective Price')
    def effective_price_display(self, obj):
        ep = obj.effective_price
        source = (
            'actuals-derived'
            if obj.weighted_avg_price
            else 'standard (no actuals revenue)'
        )
        return format_html(
            '<strong>₹{}</strong> <span style="color:#6c757d;font-size:11px">({})</span>',
            ep, source,
        )

    @admin.display(description='Price Check')
    def price_divergence_flag(self, obj):
        """
        Warn when weighted_avg_price diverges > 20% from standard_price.
        Helps planners spot stale standard prices.
        """
        if not obj.weighted_avg_price or not obj.standard_price:
            return '—'

        wap = float(obj.weighted_avg_price)
        sp  = float(obj.standard_price)
        if sp == 0:
            return '—'

        divergence_pct = abs(wap - sp) / sp * 100

        if divergence_pct > 30:
            return format_html(
                '<span style="color:#dc3545;font-weight:bold">'
                '⚠ {:.1f}% divergence — review standard_price'
                '</span>',
                divergence_pct,
            )
        if divergence_pct > 15:
            return format_html(
                '<span style="color:#fd7e14">'
                '△ {:.1f}% divergence'
                '</span>',
                divergence_pct,
            )
        return format_html(
            '<span style="color:#198754">✓ {:.1f}%</span>',
            divergence_pct,
        )

    @admin.display(description='Actuals Note')
    def actuals_revenue_note(self, obj):
        """
        Show how many ActualSale rows with revenue exist for this item,
        so planners know whether weighted_avg_price is well-supported.
        """
        from mysite.models.demand.actuals import ActualSale
        count = ActualSale.objects.filter(
            client=obj.client,
            item=obj.item,
            revenue__isnull=False,
        ).count()
        if count == 0:
            return format_html(
                '<span style="color:#dc3545">'
                'No actuals revenue rows — standard_price is the only source.'
                '</span>'
            )
        return format_html(
            '<span style="color:#198754">'
            '{} actuals rows with revenue data.'
            '</span>',
            count,
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related('client', 'item')
        )

    admin_role_only = True


