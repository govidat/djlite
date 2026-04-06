from django import forms
from django.contrib import admin
import nested_admin
from modeltranslation.admin import TranslationAdmin, TranslationTabularInline, TranslationBaseModelAdmin
#from django.contrib.contenttypes.admin import GenericTabularInline
from .forms import ClientForm
# Register your models here.
#from .models import SUPPORTED_LANGUAGES   # your list of (code, label) tuples
from django.conf import settings
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2

from .models import GlobalValCat, GlobalVal, ThemePreset, Client, Theme, ComptextBlock, GentextBlock, TextstbItem, SvgtextbadgeValue

#from .models import Page, HeroCardText, HeroCardFigure, HeroCard, HeroText, HeroFigure, CardText, CardFigure, AccordionText, Card, Hero, Accordion, Layout

# Option 3 Common Component Model
from .models import Page, Layout, Component, ComponentSlot

# ── Reusable mixin ────────────────────────────────────────────────────
# Centralises the "climb up to Client and get language_list" logic
# so ThemeInline, PageInline (and any future inline) can reuse it.

class ClientLanguageMixin:
    """
    Mixin for any inline nested under Client.
    Resolves the parent client's language_list from:
      1. The inline object's own client FK (editing)
      2. The URL's object_id (adding)
      3. Fallback: all settings.LANGUAGES
    """
    TRANSLATED_FIELDS = ()   # override in each inline

    def _get_client_languages(self, request, obj=None):
        # Case 1: editing an existing inline object
        if obj and obj.pk:
            try:
                return obj.client.language_list or self._all_lang_codes()
            except AttributeError:
                pass

        # Case 2: adding — client_id is the object_id in the URL
        client_id = request.resolver_match.kwargs.get('object_id')
        if client_id:
            try:
                client = Client.objects.get(pk=client_id)
                return client.language_list or self._all_lang_codes()
            except Client.DoesNotExist:
                pass

        return self._all_lang_codes()

    def _all_lang_codes(self):
        return [code for code, _ in settings.LANGUAGES]

    def _build_language_fieldsets(self, lang_codes, extra_fields=()):
        """
        Builds fieldsets like:
          ('English', {'fields': ('name_en',)}),
          ('Tamil',   {'fields': ('name_ta',)}),
          ...
          ('Common',  {'fields': ('zip_code', ...)})
        """
        lang_dict = dict(settings.LANGUAGES)
        fieldsets = []
        for code in lang_codes:
            label = lang_dict.get(code, code.upper())
            fields = tuple(f"{field}_{code}" for field in self.TRANSLATED_FIELDS)
            fieldsets.append((label, {'fields': fields}))
        if extra_fields:
            fieldsets.append(('Common', {'fields': extra_fields}))
        return fieldsets

    def get_fieldsets(self, request, obj=None):
        lang_codes = self._get_client_languages(request, obj)
        return self._build_language_fieldsets(
            lang_codes,
            extra_fields=self.non_translated_fields
        )

    def get_fields(self, request, obj=None):
        lang_codes = self._get_client_languages(request, obj)
        fields = [
            f"{field}_{code}"
            for code in lang_codes
            for field in self.TRANSLATED_FIELDS
        ]
        return fields + list(self.non_translated_fields)


class GlobalValInline(TranslationBaseModelAdmin, nested_admin.NestedTabularInline):
    model  = GlobalVal
    extra  = 1
    fields = ['key'] + [f'keyval_{code}' for code, _ in settings.LANGUAGES]
    # Renders as:
    # | key      | keyval_en | keyval_hi | keyval_fr | keyval_ta |
    # | logout   | Logout    | hiLogout  | frLogout  |           |


@admin.register(GlobalValCat)
class GlobalValCatAdmin(nested_admin.NestedModelAdmin):
    inlines     = [GlobalValInline]
    list_display = ('globalvalcat_id',)
    search_fields = ('globalvalcat_id',)

# VERY IMPORTANT Any content_type model should be of NestedGenericTabularInline
"""
class LanguageAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    fields = ["language_id", "label_obj"]
    search_fields = ("language_id",)
"""
class ThemePresetAdmin(admin.ModelAdmin):
    #list_display = ("language_id", "label_obj")
    #fields = ["language_id", "label_obj"]
    search_fields = ("themepreset_id",)

"""
class SvgtextbadgeValueInline(nested_admin.NestedStackedInline):
    model = SvgtextbadgeValue
    extra = 1
    classes = ['collapse']
"""
class SvgtextbadgeValueInline(nested_admin.NestedTabularInline):
    model  = SvgtextbadgeValue
    extra  = 0
    fields = ('language_code', 'stext', 'ltext')

    def get_language_choices(self, request):
        """
        Resolve client's language_list from the URL's object_id.
        Caches result on the request object so Client is queried
        only once per page load, regardless of how many inline
        rows are rendered.
        """
        # Return cached result if already resolved this request
        if hasattr(request, '_cached_client_lang_choices'):
            return request._cached_client_lang_choices

        from django.conf import settings
        choices = list(settings.LANGUAGES)   # fallback

        client_id = request.resolver_match.kwargs.get('object_id')
        if client_id:
            try:
                client = Client.objects.get(pk=client_id)
                lang_codes = client.language_list or []
                lang_dict  = dict(settings.LANGUAGES)
                choices = [(code, lang_dict.get(code, code)) for code in lang_codes]
            except Client.DoesNotExist:
                pass

        # Cache on request — lives only for this request/response cycle
        request._cached_client_lang_choices = choices
        return choices

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'language_code':
            kwargs['widget'] = forms.Select(
                choices=self.get_language_choices(request)
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

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
"""
class ThemeInline(nested_admin.NestedStackedInline):
    model = Theme
    extra = 0
    classes = ['collapse']
    #list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [GentextBlockInline]
    classes = ['collapse']
    #inlines = []
"""
# ── ThemeInline ───────────────────────────────────────────────────────

class ThemeInline(
    ClientLanguageMixin,
    TranslationBaseModelAdmin,
    nested_admin.NestedStackedInline
):
    model = Theme
    extra = 0
    classes = ['collapse']
    #inlines = [GentextBlockInline]

    TRANSLATED_FIELDS = ('name',)
    non_translated_fields = ('theme_id', 'themepreset', 'ltext', 'order', 'hidden', 'is_default')   # adjust to your actual fields


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

"""
class PageInline(nested_admin.NestedStackedInline):
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [GentextBlockInline, LayoutInline]
"""
class PageInline(
    ClientLanguageMixin,
    TranslationBaseModelAdmin,
    nested_admin.NestedStackedInline
):
    model = Page
    extra = 0
    classes = ['collapse']
    inlines = [LayoutInline]                        # GentextBlockInline,  whatever Page's child inline is

    TRANSLATED_FIELDS = ('name',)                   # add more if Page has other translated fields
    non_translated_fields = ('page_id', 'ltext', 'order', 'parent', 'hidden')    # adjust to your actual fields


@admin.register(Client)
class ClientAdmin(TranslationBaseModelAdmin, nested_admin.NestedModelAdmin):
    form = ClientForm
    list_display = ('client_id', 'parent', 'nb_title_svg_pre', 'nb_title_svg_suf')
    inlines = [ThemeInline, PageInline]  # GentextBlockInline, 

    TRANSLATED_FIELDS = ('name', 'nb_title')   # add more here as needed

    
    def _language_fieldsets(self, lang_codes):
        lang_dict = dict(settings.LANGUAGES)       # ← from settings directly
        return [
            (lang_dict.get(code, code.upper()), {
                'fields': tuple(f"{field}_{code}" for field in self.TRANSLATED_FIELDS)
            })
            for code in lang_codes
        ]    

    def get_fieldsets(self, request, obj=None):
        # Determine which languages to show
        if obj and obj.language_list:
            lang_codes = obj.language_list          # editing: use saved list
        else:
            lang_codes = [code for code, _ in settings.LANGUAGES]  # adding: show all

        return [
            ('Identity', {
                'fields': ('client_id', 'parent', 'language_choices', 'nb_title_svg_pre', 'nb_title_svg_suf' )
            }),
            *self._language_fieldsets(lang_codes),
        ]

    class Media:
        js = ("admin/js/layout_admin.js", "admin/js/component_admin.js",)

"""
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
"""

#admin.site.register(Language, LanguageAdmin)
admin.site.register(ThemePreset, ThemePresetAdmin)

