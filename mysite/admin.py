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
from .models import TokenType, Token, Language, Theme, Client, Translation, ClientLanguage, ClientTheme
#TypedTokenForeignKey

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
    list_display = ("id", "token", "display_name_en", "display_names_obj")
    search_fields = ("id", "token__id", "token__name")

    def display_name_en(self, obj):
        return obj.display_name()
    display_name_en.short_description = "Name (en)"

    def display_names_obj(self, obj):
        return obj.display_all_names()
    display_names_obj.short_description = "All Names"

class ThemeAdmin(admin.ModelAdmin):
    list_display = ("id", "token", "display_name_en", "display_names_obj")
    search_fields = ("id", "token__id", "token__name")

    def display_name_en(self, obj):
        return obj.display_name()
    display_name_en.short_description = "Name (en)"

    def display_names_obj(self, obj):
        return obj.display_all_names()
    display_names_obj.short_description = "All Names"

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

#class ClientThemeInline(admin.TabularInline):
#    model = ClientTheme
#    extra = 1


class ClientAdmin(SortableAdminBase, admin.ModelAdmin):
    list_display = ("id", "token", "parent", "get_languages", "get_themes", "get_parent_chain", "get_children_chain", "display_name_en", "display_names_obj")
    search_fields = ("id", "token__id")
    inlines = [ClientLanguageInline, ClientThemeInline]

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

admin.site.register(TokenType, TokenTypeAdmin)
admin.site.register(Token, TokenAdmin)
#admin.site.register(Maxlanguage)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
admin.site.register(Client, ClientAdmin)
admin.site.register(Translation, TranslationAdmin)