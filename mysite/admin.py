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
from .models import TokenType, Token, Language, Theme, Client, TextStatic, ClientLanguage, ClientTheme, Page, ClientNavbar, ImageStatic, SvgStatic

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


"""
class ClientLanguageInline(SortableInlineAdminMixin, admin.TabularInline):  # or StackedInline if you prefer
    model = ClientLanguage
    extra = 1  # number of blank rows to show
    fields = ("language_id", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["language"]  # optional: adds search for large language sets
    #ordering = ["order"]

class ClientThemeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ClientTheme
    extra = 1
    fields = ("theme_id", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["theme"]
    #ordering = ["order"]

class ClientNavbarInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ClientNavbar
    extra = 1
    fields = ("page_id", "parent", "order" ) #admin-sortable2 , "order"
"""


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

class ClientNavbarAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "parent", "order")
    search_fields = ("client__client_id",)

class ImageStaticAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "image_id", "image_url", "alt")
    search_fields = ("client__client_id",)

class SvgStaticAdmin(admin.ModelAdmin):
    list_display = ("client", "page", "svg_id", "svg_text")
    search_fields = ("client__client_id",)    
"""
admin.site.register(TokenType, TokenTypeAdmin)
admin.site.register(Token, TokenAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
admin.site.register(Client, ClientAdmin)
admin.site.register(Translation, TranslationAdmin)
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
admin.site.register(ClientNavbar, ClientNavbarAdmin)
admin.site.register(ImageStatic, ImageStaticAdmin)
admin.site.register(SvgStatic, SvgStaticAdmin)