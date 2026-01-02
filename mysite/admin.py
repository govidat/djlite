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
from .models import TokenType2, Token2, Language2, Theme2, Client2, TextStatic2, ClientLanguage2, ClientTheme2, Page2

#TypedTokenForeignKey
"""
class TokenTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_global")
    search_fields = ("id", "name")
    list_filter = ("is_global",)

class TokenAdmin(admin.ModelAdmin):
    list_display = ("id", "tokentype", "parent")
    list_filter = ("tokentype",)
    search_fields = ("id", "tokentype__id", "tokentype__name")
    autocomplete_fields = ("tokentype", "parent")
 
    
class LanguageAdmin(admin.ModelAdmin):
    list_display = ("id",)
    search_fields = ("id",)
    
    #list_display = ("id", "token", "display_name_en", "display_names_obj")
    #search_fields = ("id", "token__id", "token__name")

    #def display_name_en(self, obj):
    #    return obj.display_name()
    #display_name_en.short_description = "Name (en)"

    #def display_names_obj(self, obj):
    #    return obj.display_all_names()
    #display_names_obj.short_description = "All Names"
    

class ThemeAdmin(admin.ModelAdmin):
    list_display = ("id",)
    search_fields = ("id",)
        
    #list_display = ("id", "token", "display_name_en", "display_names_obj")
    #search_fields = ("id", "token__id", "token__name")

    #def display_name_en(self, obj):
    #    return obj.display_name()
    #display_name_en.short_description = "Name (en)"

    #def display_names_obj(self, obj):
    #    return obj.display_all_names()
    #display_names_obj.short_description = "All Names"
    

class ClientLanguageInline(SortableInlineAdminMixin, admin.TabularInline):  # or StackedInline if you prefer
    model = ClientLanguage
    extra = 1  # number of blank rows to show
    fields = ("language", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["language"]  # optional: adds search for large language sets
    #ordering = ["order"]

class ClientThemeInline(SortableInlineAdminMixin, admin.TabularInline):
    model = ClientTheme
    extra = 1
    fields = ("theme", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["theme"]
    #ordering = ["order"]



class ClientAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ("id", "token", "parent", "get_languages", "get_themes", "get_parent_chain", "get_children_chain", "display_name_en", "display_names_obj")
    search_fields = ("id", "token__id")
    inlines = [ClientLanguageInline, ClientThemeInline]

    #filter_horizontal = ("client_languages_old", "client_themes_old")  
    # 👆 makes a nice dual select box UI in admin    
    
    #def get_languages(self, obj):
    #    # join language values as comma separated string
    #    return ", ".join(str(lang.language) for lang in obj.client_languages.all())
    #get_languages.short_description = "Languages"

    #def get_themes(self, obj):
    #    # join theme values as comma separated string
    #    return ", ".join(str(theme.theme) for theme in obj.client_themes.all())
    #get_themes.short_description = "Themes"
    
    def get_languages(self, obj):
        return ", ".join(lang.id for lang in obj.client_languages.all())
    get_languages.short_description = "Languages"

    def get_themes(self, obj):
        return ", ".join(theme.id for theme in obj.client_themes.all())
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


class TranslationAdmin(admin.ModelAdmin):
    list_display = ("client", "token", "language", "value")
    list_filter = ("client", "language", "token")
    search_fields = ("token__id", "value")
"""

class TokenType2Admin(admin.ModelAdmin):
    list_display = ("tokentype_id", "ltext", "is_global")
    search_fields = ("tokentype_id", "ltext")
    list_filter = ("is_global",)

class Token2Admin(admin.ModelAdmin):
    list_display = ("token_id", "tokentype_id", "ltext")
    list_filter = ("tokentype_id",)
    search_fields = ("token_id", "tokentype_id")
    #autocomplete_fields = ("tokentype_id")
 
    
class Language2Admin(admin.ModelAdmin):
    list_display = ("language_id", "token_id")
    search_fields = ("language_id",)


class Theme2Admin(admin.ModelAdmin):
    list_display = ("theme_id", "token_id")
    search_fields = ("theme_id",)

class Page2Admin(admin.ModelAdmin):
    list_display = ("page_id", "token_id")
    search_fields = ("page_id",)

class ClientLanguage2Inline(SortableInlineAdminMixin, admin.TabularInline):  # or StackedInline if you prefer
    model = ClientLanguage2
    extra = 1  # number of blank rows to show
    fields = ("language_id", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["language"]  # optional: adds search for large language sets
    #ordering = ["order"]

class ClientTheme2Inline(SortableInlineAdminMixin, admin.TabularInline):
    model = ClientTheme2
    extra = 1
    fields = ("theme_id", ) #admin-sortable2 , "order"
    #autocomplete_fields = ["theme"]
    #ordering = ["order"]



class Client2Admin(SortableAdminBase, admin.ModelAdmin):
    list_display = ("client_id", "parent", "get_languages", "get_themes", "get_parent_chain", "get_children_chain", "display_name_en", "display_names_obj")
    search_fields = ("client_id", "token_id")
    inlines = [ClientLanguage2Inline, ClientTheme2Inline]

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
        return ", ".join(lang.language_id for lang in obj.client_languages2.all())
    get_languages.short_description = "Languages"

    def get_themes(self, obj):
        return ", ".join(theme.theme_id for theme in obj.client_themes2.all())
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


class TextStatic2Admin(admin.ModelAdmin):
    list_display = ("client_id", "token_id", "page_id", "language_id", "value")
    list_filter = ("client_id", "language_id", "token_id", "page_id")
    search_fields = ("token_id", "value")

"""
admin.site.register(TokenType, TokenTypeAdmin)
admin.site.register(Token, TokenAdmin)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
admin.site.register(Client, ClientAdmin)
admin.site.register(Translation, TranslationAdmin)
"""

admin.site.register(TokenType2, TokenType2Admin)
admin.site.register(Token2, Token2Admin)
admin.site.register(Language2, Language2Admin)
admin.site.register(Theme2, Theme2Admin)
admin.site.register(Client2, Client2Admin)
admin.site.register(Page2, Page2Admin)
admin.site.register(TextStatic2, TextStatic2Admin)