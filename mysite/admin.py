from django.contrib import admin

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
from .models import TokenType, Token, Language, Theme, Client, TextStatic, ClientLanguage, ClientTheme, Page, ClientPage, Image, Svg
#, SiteStructure, Hero, HeroContent, HeroText, HeroFigure

#TypedTokenForeignKey


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
class HeroInline(admin.StackedInline):
    model = Hero
    extra = 0
    max_num = 1
    can_delete = True
    show_change_link = True

@admin.register(SiteStructure)
class SiteStructureAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "page",
        "shell_id",
        "parent",
        "type_id",
        "order",
        "hidden",
    )
    list_filter = ("client", "page", "type_id")
    search_fields = ("shell_id", "comp_unique")
    ordering = ("client", "page", "shell_id", "order")

    inlines = [HeroInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("parent", "client", "page")

class HeroContentInline(admin.TabularInline):
    model = HeroContent
    extra = 0
    ordering = ("order",)
    show_change_link = True

@admin.register(Hero)
class HeroAdmin(admin.ModelAdmin):
    list_display = (
        "sitestructure",
        "overlay",
    )
    inlines = [HeroContentInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "sitestructure",
                "sitestructure__client",
                "sitestructure__page",
            )
        )

class HeroTextInline(admin.StackedInline):
    model = HeroText
    extra = 0
    max_num = 1

class HeroFigureInline(admin.StackedInline):
    model = HeroFigure
    extra = 0
    max_num = 1

@admin.register(HeroContent)
class HeroContentAdmin(admin.ModelAdmin):
    list_display = (
        "hero",
        "type_id",
        "order",
        "hidden",
    )
    list_filter = ("type_id", "hidden")
    ordering = ("hero", "order")

    inlines = [HeroTextInline, HeroFigureInline]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "hero",
                "hero__sitestructure",
            )
        )
"""

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
