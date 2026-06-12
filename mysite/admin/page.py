import nested_admin
from mysite.models import (Layout, PageContent, Page, NavItem)
from modeltranslation.admin import TranslationBaseModelAdmin
from .base import ClientScopedMixin, ClientLanguageMixin, BaseAdminInlinecss, ClientLanguageMixinV2

from mysite.admin.component import ComponentInline



class LayoutInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    model = Layout
    extra = 0
    classes = ['collapse']
    fields = ["level", "slug", "order", "hidden", "css_class", "style", "parent"]
    show_change_link = True
    inlines = [ComponentInline]
    raw_id_fields = ('page',)
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related(
            'page',
            'page__client',
        )    
    class Media:
        js = ("admin/js/layout_admin.js",)

class PageContentInline(ClientLanguageMixinV2, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model   = PageContent
    classes = ['collapse']
    extra   = 0
    #fields  = ['language_code', 'html']
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['htmlblob'], obj
        )
        fieldsets = [
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
            ['htmlblob'],
            obj
        )
        return (
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),            
            #('General', {
            #    'fields': ('language_code', 'html'),
            #    'classes': ('collapse',),
            #})
        )
    
    """
        
""" With Inlines    
class PageInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    #TranslationBaseModelAdmin, ClientLanguageMixinV2, 
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [LayoutInline, PageContentInline]                        
    fields  = ['page_id', 'ltext', 'hidden']
"""


class PageInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    #TranslationBaseModelAdmin, ClientLanguageMixinV2, 
    model = Page
    extra = 0
    classes = ['collapse']
    #inlines = [LayoutInline, PageContentInline]                       
    fields  = ['page_id', 'ltext', 'hidden']
    show_change_link = True

class PageplusLayoutInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    #TranslationBaseModelAdmin, ClientLanguageMixinV2, 
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [LayoutInline]                        
    fields  = ['page_id', ]
    show_change_link = True

class PageplusPageContentInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    #TranslationBaseModelAdmin, ClientLanguageMixinV2, 
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [PageContentInline]                        
    fields  = ['page_id', ]
    show_change_link = True    


class NavItemInline(ClientLanguageMixinV2, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model = NavItem
    extra = 0
    classes = ['collapse']
    #raw_id_fields = ('page',)
    # to limit the pages to this client
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "page":

            object_id = request.resolver_match.kwargs.get("object_id")

            if object_id:
                kwargs["queryset"] = Page.objects.filter(
                    client_id=object_id
                ).order_by("page_id")

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs
        )

    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name'], obj
        )
        fieldsets = [
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('General', {
                'fields': ('location', 'nav_type', 'page', 'url',
                           'order', 'parent', 'hidden', 'open_in_new_tab'),
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.insert(1, (
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)

        """
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),            
            ('General', {
                'fields': ('location', 'nav_type', 'page', 'url', 'order', 'parent', 'hidden', 'open_in_new_tab'),
                'classes': ('collapse',),
            })
        )
        """