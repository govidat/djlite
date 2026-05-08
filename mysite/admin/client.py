import nested_admin
from django.conf import settings
from django.contrib import admin
from modeltranslation.admin import TranslationBaseModelAdmin

from .base import ClientScopedMixin, _user_has_admin_role, ClientLanguageMixinV2, BaseAdminInlinecss
from mysite.models import (Theme)
from mysite.forms import ClientForm

from mysite.admin.page import PageInline, NavItemInline
from mysite.admin.users import ClientUserProfileInline

# ── ThemeInline ───────────────────────────────────────────────────────

class ThemeInline(TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2):
    model = Theme
    extra = 0
    classes = ['collapse']
    #inlines = [GentextBlockInline]

    #TRANSLATED_FIELDS = ('name',)
    #non_translated_fields = ('theme_id', 'themepreset', 'ltext', 'order', 'hidden', 'is_default')   # adjust to your actual fields
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('theme_id', 'themepreset', 'ltext', 'order', 'hidden', 'is_default'),
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

class ClientAdmin(ClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss):
    form         = ClientForm
    #list_display = ('client_id', 'parent', 'nb_title_svg_pre', 'nb_title_svg_suf')
    inlines      = [ThemeInline, PageInline, NavItemInline, ClientUserProfileInline]
    #TRANSLATED_FIELDS = ('name', 'nb_title')
    admin_role_only = True
    """
    def _language_fieldsets(self, lang_codes):
        lang_dict = dict(settings.LANGUAGES)
        return [
            (lang_dict.get(code, code.upper()), {
                'fields': tuple(f"{field}_{code}" for field in self.TRANSLATED_FIELDS)
            })
            for code in lang_codes
        ]
    """
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'nb_title'],
            obj
        )
        return (
            ('General', {
                'fields': ('client_id', 'parent', 'language_choices', 'default_language', 'nb_title_svg_pre', 'nb_title_svg_suf'),
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

