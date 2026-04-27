
import nested_admin
from django.conf import settings
from django.contrib import admin
from modeltranslation.admin import TranslationBaseModelAdmin

from mysite.models import (GlobalVal)

class GlobalValInline(TranslationBaseModelAdmin, nested_admin.NestedTabularInline):
    model  = GlobalVal
    extra  = 1
    fields = ['key'] + [f'keyval_{code}' for code, _ in settings.LANGUAGES]
    # Renders as:
    # | key      | keyval_en | keyval_hi | keyval_fr | keyval_ta |
    # | logout   | Logout    | hiLogout  | frLogout  |           |



class GlobalValCatAdmin(nested_admin.NestedModelAdmin):
    inlines     = [GlobalValInline]
    list_display = ('globalvalcat_id',)
    search_fields = ('globalvalcat_id',)

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline

class ThemePresetAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    #fields = ["language_id", "label_obj"]
    search_fields = ("themepreset_id",)

