from django import forms
from django.contrib import admin
import nested_admin
#from django.contrib.contenttypes.admin import GenericTabularInline
from .forms import ClientForm
# Register your models here.

"""
# Register your models here.
from .models import Question, Choice

class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 3

class QuestionAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {"fields": ["question_text"]}),
        ("Date information", {"fields": ["pub_date"]}),
    ]
    inlines = [ChoiceInline]
    list_display = ["question_text", "pub_date", "was_published_recently"]
    list_filter = ["pub_date"]
    search_fields = ["question_text"]
    
admin.site.register(Question, QuestionAdmin)
"""
from adminsortable2.admin import SortableAdminBase, SortableInlineAdminMixin # admin-sortable2
#from .models import TokenType, Token, Language, Theme, Client, Translation, ClientLanguage, ClientTheme
from .models import TokenType, Token, Language, Theme, Client, TextStatic, ClientLanguage, ClientTheme, Page, ClientPage, Image, Svg, Layout, Hero, HeroText, HeroFigure, HeroCard, HeroCardText, HeroCardFigure, Card, CardText, CardFigure, TextContent, TextBlock, TextBlockItem, TextBlockItemValue, Language2, Theme2, Client2, TextItemValue2, Page2
# Component, TypedTokenForeignKey, HeroItem, 

class Language2Admin(admin.ModelAdmin):
    list_display = ("language_id", "label_obj")
    search_fields = ("language_id",)

class Theme2Admin(admin.ModelAdmin):
    list_display = ("theme_id", "label_obj")
    search_fields = ("theme_id",)

class TextItemValue2Inline(nested_admin.NestedGenericTabularInline):
    model = TextItemValue2
    extra = 1
    classes = ['collapse']

class Page2Inline(nested_admin.NestedStackedInline):
    model = Page2
    extra = 0
    classes = ['collapse']
    list_display = ('page_id', 'ltext', 'order', 'parent', 'hidden')
    inlines = [TextItemValue2Inline]

@admin.register(Client2)
class Client2Admin(nested_admin.NestedModelAdmin):
    #list_display = ("client_id", "parent")
    #search_fields = ("client_id",)
    form = ClientForm
    # Hide the raw JSON field in the admin display
    fields = ['client_id', 'parent', 'language_choices', 'theme_choices'] 
    list_display = ('client_id', 'parent')
    inlines = [TextItemValue2Inline, Page2Inline]
    

    

class TokenTypeAdmin(admin.ModelAdmin):
    list_display = ("tokentype_id", "ltext", "is_global")
    search_fields = ("tokentype_id", "ltext")
    list_filter = ("is_global",)

class TokenAdmin(admin.ModelAdmin):
    list_display = ("token_id", "tokentype_id", "ltext")
    list_filter = ("tokentype_id",)
    search_fields = ("token_id", "tokentype_id")
    #autocomplete_fields = ("tokentype_id")
 
    
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("language_id", "token_id")
    search_fields = ("language_id",)


class ThemeAdmin(admin.ModelAdmin):
    list_display = ("theme_id", "token_id")
    search_fields = ("theme_id",)

class PageAdmin(admin.ModelAdmin):
    list_display = ("page_id", "token_id")
    search_fields = ("page_id",)


class ClientAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ("client_id", "parent", "get_languages", "get_themes", "get_parent_chain", "get_children_chain", "display_name_en", "display_names_obj")
    search_fields = ("client_id", "token_id")
    #inlines = [ClientLanguageInline]

    #filter_horizontal = ("client_languages_old", "client_themes_old")  
    # 👆 makes a nice dual select box UI in admin    
    """
    def get_languages(self, obj):
        # join language values as comma separated string
        return ", ".join(str(lang.language) for lang in obj.client_languages.all())
    get_languages.short_description = "Languages"

    def get_themes(self, obj):
        # join theme values as comma separated string
        return ", ".join(str(theme.theme) for theme in obj.client_themes.all())
    get_themes.short_description = "Themes"
    """
    def get_languages(self, obj):
        return ", ".join(lang.language_id for lang in obj.client_languages.all())
    get_languages.short_description = "Languages"

    def get_themes(self, obj):
        return ", ".join(theme.theme_id for theme in obj.client_themes.all())
    get_themes.short_description = "Themes"
   
    def get_parent_chain(self, obj):
        #Show parent → grandparent → etc. as comma-separated IDs
        ancestors = obj.get_ancestors()
        return ", ".join(ancestors) if ancestors else "-"
    get_parent_chain.short_description = "Parent Chain"

    def get_children_chain(self, obj):
        descendants = obj.get_descendants()
        return ", ".join(descendants) if descendants else "-"
    get_children_chain.short_description = "Children Chain"   

    def display_name_en(self, obj):
        return obj.display_name()
    display_name_en.short_description = "Name (en)"

    def display_names_obj(self, obj):
        return obj.display_all_names()
    display_names_obj.short_description = "All Names"     


class TextStaticAdmin(admin.ModelAdmin):
    list_display = ("client_id", "token_id", "page_id", "language_id", "value")
    list_filter = ("client_id", "language_id", "token_id", "page_id")
    search_fields = ("token_id", "value")

class ClientLanguageAdmin(admin.ModelAdmin):
    list_display = ("client", "language", "order")
    search_fields = ("client__client_id",)

class ClientThemeAdmin(admin.ModelAdmin):
    list_display = ("client", "theme", "order")
    search_fields = ("client__client_id",)

class ClientPageAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "parent", "order")
    search_fields = ("client__client_id",)

class ImageAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "image_id", "image_url", "alt")
    search_fields = ("client__client_id",)

class SvgAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "svg_id", "svg_text")
    search_fields = ("client__client_id",)  

"""
Layout @level 40
      ├── Hero
      │         ├── HeroText   (only if type=text)
      │         ├── HeroFigure (only if type=figure)
      │         └── HeroCard
      │              ├── HeroCardText
      │              └── HeroCardFigure
      │
      └── Card
           ├── CardText
           └── CardFigure
     
"""
class TextBlockItemValueInline(nested_admin.NestedStackedInline):
    model = TextBlockItemValue
    extra = 0

class TextBlockItemInline(nested_admin.NestedStackedInline):
    model = TextBlockItem
    extra = 0
    inlines = [TextBlockItemValueInline]

class TextBlockInline(nested_admin.NestedStackedInline):
    model = TextBlock
    extra = 0
    inlines = [TextBlockItemInline]

class TextContentInline(nested_admin.NestedStackedInline):
    model = TextContent
    extra = 1
    inlines = [TextBlockInline]

class HeroCardTextInline(nested_admin.NestedStackedInline):
    model = HeroCardText
    extra = 0
    max_num = 1
    fields = ("ltext", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [TextContentInline]

class HeroCardFigureInline(nested_admin.NestedStackedInline):
    model = HeroCardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "figure_class", "position_id", "image_url", "alt", "css_class" )


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


class HeroTextInline(nested_admin.NestedStackedInline):
    model = HeroText
    extra = 0
    max_num = 1
#    fields = ("order", "hidden", "ltext", "title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "actions_class", "actions_position_id",
#                    "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    fieldsets = [
        (None, {"fields": ["order", "hidden", "ltext"]}),
        #("Title", {"fields": ["title_class", "title_stb_ids"]}),
        #("Contents", {"fields": ["contents_class", "contents_stb_ids"]}),
        ("Actions", {"fields": ["actions_class", "actions_position_id"]}), 
        #("Button 01", {"fields": ["button01_class", "button01_stb_ids"]}),
        #("Button 02", {"fields": ["button02_class", "button02_stb_ids"]}),
        #("Button 03", {"fields": ["button03_class", "button03_stb_ids"]}),                
        #("Button 04", {"fields": ["button04_class", "button04_stb_ids"]}),                                        
    ]    
    inlines = [TextContentInline]

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
class CardTextInline(nested_admin.NestedStackedInline):
    model = CardText
    extra = 0
    max_num = 1
    fields = ("ltext", "actions_class", "actions_position_id")
    #"title_class", "title_stb_ids", "contents_class", "contents_stb_ids", "button01_class", "button01_stb_ids", "button02_class", "button02_stb_ids", "button03_class", "button03_stb_ids", "button04_class", "button04_stb_ids")
    inlines = [TextContentInline]

class CardFigureInline(nested_admin.NestedStackedInline):
    model = CardFigure
    extra = 0
    max_num = 1
    fields = ("ltext", "figure_class", "position_id", "image_url", "alt", "css_class" )  
    
class HeroInline(nested_admin.NestedStackedInline):
    model = Hero
    extra = 0
    max_num = 1    
    fields = ("css_class", "herocontent_class", "overlay", "overlay_style")
    inlines = [HeroTextInline, HeroFigureInline, HeroCardInline]

class CardInline(nested_admin.NestedStackedInline):
    model = Card
    extra = 0
    max_num = 1
    fields = ("ltext", "css_class", "body_class")
    inlines = [CardTextInline, CardFigureInline]

@admin.register(Layout)
class LayoutAdmin(nested_admin.NestedModelAdmin):
    #list_display = ("client", "page", "parent", "order", "level", "css_class", "style", "hidden", "slug")
    fieldsets = [
        (None, {"fields": ["client", "page", "order", "level", "slug", "parent"]}),
        (None, {"fields": ["css_class", "style"]}),
        (None, {"fields": ["hidden"]}),
        (None, {"fields": ["comp_id"]}),
        
    ]    
    inlines = []
    def get_inline_instances(self, request, obj=None):
        if not obj:
            return []
        if obj.level == 40:
            if obj.comp_id == 'card':            
                return [CardInline(self.model, self.admin_site)]
            if obj.comp_id == 'hero':            
                return [HeroInline(self.model, self.admin_site)]
        return []

admin.site.register(Language2, Language2Admin)
admin.site.register(Theme2, Theme2Admin)

admin.site.register(TokenType, TokenTypeAdmin)
admin.site.register(Token, TokenAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
admin.site.register(Client, ClientAdmin)
admin.site.register(Page, PageAdmin)
admin.site.register(TextStatic, TextStaticAdmin)
admin.site.register(ClientLanguage, ClientLanguageAdmin)
admin.site.register(ClientTheme, ClientThemeAdmin)
admin.site.register(ClientPage, ClientPageAdmin)
admin.site.register(Image, ImageAdmin)
admin.site.register(Svg, SvgAdmin)
