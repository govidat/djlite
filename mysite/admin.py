from django import forms
from django.contrib import admin
import nested_admin
#from django.contrib.contenttypes.admin import GenericTabularInline
from .forms import ClientForm
# Register your models here.

from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2

from .models import Language, ThemePreset, Client, Theme, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue

#from .models import Page, HeroCardText, HeroCardFigure, HeroCard, HeroText, HeroFigure, CardText, CardFigure, AccordionText, Card, Hero, Accordion, Layout

# Option 3 Common Component Model
from .models import Page, Layout, Component, ComponentSlot

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline
class LanguageAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    fields = ["language_id", "label_obj"]
    search_fields = ("language_id",)

class ThemePresetAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    #fields = ["language_id", "label_obj"]
    search_fields = ("themepreset_id",)


class SvgtextbadgeValueInline(nested_admin.NestedStackedInline):
    model = SvgtextbadgeValue
    extra = 1
    classes = ['collapse']

class TextstbItemInline(nested_admin.NestedGenericStackedInline):
    model = TextstbItem
    fields = ("item_id", "ltext", "hidden", "order", "css_class", "svg_text")
    extra = 0
    inlines = [SvgtextbadgeValueInline]
    classes = ['collapse']


class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    #fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

class GentextBlockInline(nested_admin.NestedGenericStackedInline):
    model = GentextBlock
    fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

"""
class HeroCardTextInline(nested_admin.NestedStackedInline):
    model = HeroCardText
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class HeroCardFigureInline(nested_admin.NestedStackedInline):
    model = HeroCardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "figure_class", "position_id", "image_url", "alt", "css_class" )
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
    fields = ("ltext", "order", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
    classes = ['collapse']

class CardFigureInline(nested_admin.NestedStackedInline):
    model = CardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "order", "figure_class", "position_id", "image_url", "alt", "css_class" )
    classes = ['collapse'] 

class AccordionTextInline(nested_admin.NestedStackedInline):
    model = AccordionText
    extra = 0
    max_num = 5
    fields = ("ltext", "order", "checked", "hidden")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [ComptextBlockInline]
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

class AccordionInline(nested_admin.NestedStackedInline):
    model = Accordion
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "type", "name")
    inlines = [AccordionTextInline]
    classes = ['collapse']

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
            if obj.comp_id == 'accordion':            
                return [AccordionInline(self.model, self.admin_site)]            
        return []


class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []
"""
class ThemeInline(nested_admin.NestedStackedInline):
    model = Theme
    extra = 0
    classes = ['collapse']
    #list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []

class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    extra = 0
    classes = ['collapse']
    inlines = [TextstbItemInline]

# Option 3 Common Component Model
# ── Component inlines ─────────────────────────────────────────

class ComponentSlotInline(nested_admin.NestedStackedInline):
    model = ComponentSlot
    fk_name = "component"
    extra = 0
    classes = ['collapse']
    fields = [
        "slot_type", "order", "hidden", "ltext", "css_class",
        "actions_class", # text for card, hero
        "image_url", "alt", "figure_class",   # figure
        "accordion_checked",                             # accordion text slot
    ]
    inlines = [ComptextBlockInline]

    class Media:
        js = ("admin/js/component_admin.js",)


class ComponentInline(nested_admin.NestedStackedInline):
    model = Component
    extra = 0
    classes = ['collapse']
    fields = [
        "comp_id", "order", "hidden", "ltext", "css_class",
        "card_body_class", # card
        "hero_content_class", "hero_overlay", "hero_overlay_style",            # hero
        "accordion_type", "accordion_name",    # accordion
        "config",
    ]
    inlines = [ComponentSlotInline]

    class Media:
        js = ("admin/js/component_admin.js",)


class LayoutInline(nested_admin.NestedStackedInline):
    model = Layout
    extra = 0
    classes = ['collapse']
    fields = ["level", "slug", "order", "hidden", "css_class", "style", "parent"]
    show_change_link = True
    inlines = [ComponentInline]

    class Media:
        js = ("admin/js/layout_admin.js",)


class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [GentextBlockInline, LayoutInline]


@admin.register(Client)
class ClientAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client_id", "parent")
    #search_fields = ("client_id",)
    form = ClientForm
    # Hide the raw JSON field in the admin display
    fields = ['client_id', 'parent', 'language_choices'] 
    list_display = ('client_id', 'parent')
    inlines = [GentextBlockInline, ThemeInline, PageInline]
    class Media:
        js = ("admin/js/layout_admin.js", "admin/js/component_admin.js",)
        
admin.site.register(Language, LanguageAdmin)
admin.site.register(ThemePreset, ThemePresetAdmin)

