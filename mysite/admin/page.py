import nested_admin
from mysite.models import (Layout, PageContent, Page, NavItem)
from modeltranslation.admin import TranslationBaseModelAdmin
from .base import ClientLanguageMixin

from mysite.admin.component import ComponentInline



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

