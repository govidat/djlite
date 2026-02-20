from django import forms
from django.contrib import admin
import nested_admin
#from django.contrib.contenttypes.admin import GenericTabularInline
from .forms import ClientForm
# Register your models here.

from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2

from .models import Language, Theme, Client, Page, HeroCardText, HeroCardFigure, HeroCard, HeroText, HeroFigure, CardText, CardFigure, Card, Hero, Layout, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue
# TextItemValue, TextBlockItem, TextBlock, TextContent,

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline
class LanguageAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    fields = ["language_id", "label_obj"]
    search_fields = ("language_id",)

class ThemeAdmin(admin.ModelAdmin):
    #list_display = ("theme_id", "label_obj")
    fields = ["theme_id", "label_obj"]    
    search_fields = ("theme_id",)
"""
class TextItemValueInline(nested_admin.NestedGenericTabularInline):
    model = TextItemValue
    extra = 1
    classes = ['collapse']
"""
class SvgtextbadgeValueInline(nested_admin.NestedStackedInline):
    model = SvgtextbadgeValue
    extra = 1
    classes = ['collapse']
"""
class TextBlockItemInline(nested_admin.NestedStackedInline):
    model = TextBlockItem
    extra = 0
    inlines = [TextItemValueInline]
    classes = ['collapse']
"""
class TextstbItemInline(nested_admin.NestedGenericTabularInline):
    model = TextstbItem
    fields = ("item_id", "ltext", "hidden", "order", "css_class", "svg_text")
    extra = 0
    inlines = [SvgtextbadgeValueInline]
    classes = ['collapse']

"""
class TextBlockInline(nested_admin.NestedStackedInline):
    model = TextBlock
    extra = 0
    inlines = [TextBlockItemInline]
    classes = ['collapse']
"""
class ComptextBlockInline(nested_admin.NestedGenericTabularInline):
    model = ComptextBlock
    fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

class GentextBlockInline(nested_admin.NestedGenericTabularInline):
    model = GentextBlock
    fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']
"""
class TextContentInline(nested_admin.NestedGenericTabularInline):
    model = TextContent
    extra = 1
    inlines = [TextBlockInline]
    classes = ['collapse']
"""
class HeroCardTextInline(nested_admin.NestedStackedInline):
    model = HeroCardText
    extra = 0
    max_num = 1
    fields = ("ltext", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroCardFigureInline(nested_admin.NestedStackedInline):
    model = HeroCardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "figure_class", "position_id", "image_url", "alt", "css_class" )
    classes = ['collapse']

class HeroCardInline(nested_admin.NestedStackedInline):
    model = HeroCard
    extra = 0
    max_num = 1
    #fields = ("order", "hidden", "ltext", "css_class", "body_class")
    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        (None, {"fields": ["css_class", "body_class"]}),
    ]        
    inlines = [HeroCardTextInline, HeroCardFigureInline]
    classes = ['collapse']

class HeroTextInline(nested_admin.NestedStackedInline):
    model = HeroText
    extra = 0
    max_num = 1
    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        ("Actions", {"fields": ["actions_class", "actions_position_id"]}), 
    ]    
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroFigureInline(nested_admin.NestedStackedInline):
    model = HeroFigure
    extra = 0
    max_num = 1    
    #fields = ("order", "hidden", "ltext", "figure_class", "position_id", "image", "css_class" )

    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        (None, {"fields": ["figure_class", "position_id"]}),
        (None, {"fields": ["image_url", "alt"]}),
        (None, {"fields": ["css_class"]}), 
    ]    
    classes = ['collapse']

class CardTextInline(nested_admin.NestedStackedInline):
    model = CardText
    extra = 0
    max_num = 1
    fields = ("ltext", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class CardFigureInline(nested_admin.NestedStackedInline):
    model = CardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "figure_class", "position_id", "image_url", "alt", "css_class" )
    classes = ['collapse'] 
    
class HeroInline(nested_admin.NestedStackedInline):
    model = Hero
    extra = 0
    max_num = 1    
    fields = ("css_class", "herocontent_class", "overlay", "overlay_style")
    inlines = [HeroTextInline, HeroFigureInline, HeroCardInline]
    classes = ['collapse']

class CardInline(nested_admin.NestedStackedInline):
    model = Card
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "body_class")
    inlines = [CardTextInline, CardFigureInline]
    classes = ['collapse']
"""
class Hero2Inline(nested_admin.NestedStackedInline):
    model = Hero2
    extra = 0
    max_num = 1    
    fields = ("css_class", "herocontent_class", "overlay", "overlay_style")
    #inlines = [HeroTextInline, HeroFigureInline, HeroCardInline]
    #classes = ['collapse']
    classes = ['layer3-hero-inline', 'dynamic-inline']
class Card2Inline(nested_admin.NestedStackedInline):
    model = Card2
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "body_class")
    #inlines = [CardTextInline, CardFigureInline]
    #classes = ['collapse']
    # Add a custom CSS class for JS targeting
    classes = ['layer3-card-inline', 'dynamic-inline']

class Layout2Inline(nested_admin.NestedStackedInline):
    model = Layout2
    extra = 0
    max_num = 1
    #fields = ("ltext", "css_class", "body_class")
    inlines = [Card2Inline, Hero2Inline]
    classes = ['collapse']
    class Media:
        js = ('js/dynamic_inlines.js',) # Path to your JS file
    #def get_inlines(self, request, obj=None):
    #    if obj and obj.some_field == 'value_a':
    #        return [OptionAInline]
    #    elif obj and obj.some_field == 'value_b':
    #        return [OptionBInline]
    #    return self.inlines  # Default if no condition met
"""

@admin.register(Layout)
class LayoutAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client", "page", "parent", "order", "level", "css_class", "style", "hidden", "slug")
    fieldsets = [
        (None, {"fields": ["client", "page", "order", "level", "slug", "parent"]}),
        (None, {"fields": ["css_class", "style"]}),
        (None, {"fields": ["hidden"]}),
        (None, {"fields": ["comp_id"]}),       
    ]    
    # ideally layout can be an inline under page. but we are not able to brnach to a component inline from another inline.
    # client is kept, so that layout can be a separate admin tab. in that we are braching to component type admin.
    inlines = []
    classes = ['collapse']
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        if obj.level == 40:
            if obj.comp_id == 'card':            
                return [CardInline(self.model, self.admin_site)]
            if obj.comp_id == 'hero':            
                return [HeroInline(self.model, self.admin_site)]
        return []

class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []


@admin.register(Client)
class ClientAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client_id", "parent")
    #search_fields = ("client_id",)
    form = ClientForm
    # Hide the raw JSON field in the admin display
    fields = ['client_id', 'parent', 'language_choices', 'theme_choices'] 
    list_display = ('client_id', 'parent')
    inlines = [GentextBlockInline, PageInline]
    
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
