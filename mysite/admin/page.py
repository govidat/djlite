import nested_admin
from mysite.models import (Layout, PageContent, Page, NavItem)
from modeltranslation.admin import TranslationBaseModelAdmin
from .base import ClientLanguageMixin, BaseAdminInlinecss, ClientLanguageMixinV2

from mysite.admin.component import ComponentInline



class LayoutInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    model = Layout
    extra = 0
    classes = ['collapse']
    fields = ["level", "slug", "order", "hidden", "css_class", "style", "parent"]
    show_change_link = True
    inlines = [ComponentInline]

    class Media:
        js = ("admin/js/layout_admin.js",)

class PageContentInline(ClientLanguageMixinV2, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model   = PageContent
    classes = ['collapse']
    extra   = 0
    #fields  = ['language_code', 'html']

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
   

class PageInline(nested_admin.NestedStackedInline, BaseAdminInlinecss):
    #TranslationBaseModelAdmin, ClientLanguageMixinV2, 
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [LayoutInline, PageContentInline]                        # GentextBlockInline,  whatever Page's child inline is
    fields  = ['page_id', 'ltext', 'hidden']
    #TRANSLATED_FIELDS = ('name',)                   # add more if Page has other translated fields
    #non_translated_fields = ('page_id', 'ltext', 'order', 'parent', 'hidden')    # adjust to your actual fields
    """
    def get_fieldsets(self, request, obj=None):

        #main_ln_fields, other_ln_fields = self.get_translated_field_groups(
        #    request,
        #    ['name'],
        #    obj
        #)
        return (
            #('Main Language', {
            #    'fields': main_ln_fields,
            #    'classes': ('collapse',),
            #}),
            #('Other Languages', {
            #    'fields': other_ln_fields,
            #    'classes': ('collapse',),
            #}),            
            ('General', {
                'fields': ('page_id', 'ltext', 'hidden'),
                'classes': ('collapse',),
            })
            #'order', 'parent', 
        )
    """


class NavItemInline(ClientLanguageMixinV2, TranslationBaseModelAdmin, nested_admin.NestedStackedInline):
    model = NavItem
    extra = 0
    classes = ['collapse']
    #inlines = [LayoutInline, PageContentInline]                        # GentextBlockInline,  whatever Page's child inline is

    #TRANSLATED_FIELDS = ('name',)                   # add more if Page has other translated fields
    #non_translated_fields = ('location', 'nav_type', 'page', 'url', 'order', 'parent', 'hidden', 'open_in_new_tab')    # adjust to your actual fields

    def get_fieldsets(self, request, obj=None):

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