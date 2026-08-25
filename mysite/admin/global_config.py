
import nested_admin
from django.conf import settings
from django.contrib import admin
from modeltranslation.admin import TranslationBaseModelAdmin
from .base import BaseAdminInlinecss, ClientLanguageMixinV2
from mysite.models import (GlobalVal, Country)

class GlobalValInline(TranslationBaseModelAdmin, nested_admin.NestedTabularInline):
    model  = GlobalVal
    extra  = 1
    fields = ['key'] + [f'keyval_{code}' for code, _ in settings.LANGUAGES]
    # Renders as:
    # | key      | keyval_en | keyval_hi | keyval_fr | keyval_ta |
    # | logout   | Logout    | hiLogout  | frLogout  |           |



class GlobalValCatAdmin(nested_admin.NestedModelAdmin, BaseAdminInlinecss):
    inlines     = [GlobalValInline]
    list_display = ('globalvalcat_id',)
    search_fields = ('globalvalcat_id',)

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline

class ThemePresetAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    #fields = ["language_id", "label_obj"]
    search_fields = ("themepreset_id",)

class CountryAdmin(TranslationBaseModelAdmin, admin.ModelAdmin, ClientLanguageMixinV2):
    list_display = ('code', 'flag_emoji', 'name', 'order', 'is_active')
    list_filter = ('is_active',)
    ordering = ('order', 'code')

    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name', 'description'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('code', 'flag_emoji', 'order', 'is_active'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)

class DistributionChannelAdmin(TranslationBaseModelAdmin, admin.ModelAdmin, ClientLanguageMixinV2):
    list_display = ('code', 'label', 'is_active')
    list_filter = ('is_active',)
    search_fields = ("code",)

    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['label'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('code', 'is_active'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)