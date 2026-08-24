"""
Admin registration for Item Lifecycle models (substitution / discontinuation / introduction).
Mirrors the structure of demand_schemes.py.
"""
from django.contrib import admin
from mysite.models.demand.lifecycle import (
    ItemSubstitution, ItemDiscontinuation, ItemIntroduction,
)


class ItemSubstitutionAdmin(admin.ModelAdmin):
    list_display = ['client', 'old_item', 'new_item', 'conversion_factor',
                    'effective_from', 'updated_at']
    list_filter = ['client']
    search_fields = ['old_item__item_id', 'new_item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ItemDiscontinuationAdmin(admin.ModelAdmin):
    list_display = ['client', 'item', 'effective_from', 'updated_at']
    list_filter = ['client']
    search_fields = ['item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class ItemIntroductionAdmin(admin.ModelAdmin):
    list_display = ['client', 'new_item', 'reference_item', 'ratio',
                    'copy_from', 'copy_to', 'updated_at']
    list_filter = ['client']
    search_fields = ['new_item__item_id', 'reference_item__item_id']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    raw_id_fields = ['new_item', 'reference_item']

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
