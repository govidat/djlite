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
from .models import Tokentype, Token, Language, Theme, Client
#TypedTokenForeignKey, Maxlanguage, 

class TokentypeAdmin(admin.ModelAdmin):
    list_display = ("id_tokentype", "name", "is_global")
    search_fields = ("id_tokentype", "name")

class TokenAdmin(admin.ModelAdmin):
    list_display = ("id_token", "id_tokentype", "id_parent")
#    list_filter = ("id_tokentype" )
#    search_fields = ("id_token")   

#class MaxlanguageAdmin(admin.ModelAdmin):
#    list_display = ("id_language", "name")
#    list_filter = ("name")
#    search_fields = ("id_language")

class LanguageAdmin(admin.ModelAdmin):
    list_display = ("id_language", "language_name_token")
#    list_filter = ("id_language")
#    search_fields = ("id_language")

class ThemeAdmin(admin.ModelAdmin):
    list_display = ("id_theme", "theme_name_token")
#    list_filter = ("id_theme")
#    search_fields = ("id_theme")

    #def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #    if isinstance(db_field, TypedTokenForeignKey) and db_field.id_tokentype:
    #        kwargs["queryset"] = Token.objects.filter(type__code=db_field.id_tokentype)
    #    return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    #def formfield_for_dbfield(self, db_field, request, **kwargs):
    #    if isinstance(db_field, TypedTokenForeignKey) and db_field.id_tokentype:
    #        kwargs["queryset"] = Token.objects.filter(type__code=db_field.id_tokentype)
    #    return super().formfield_for_dbfield(db_field, request, **kwargs)

class ClientAdmin(admin.ModelAdmin):
    list_display = ("id_client", "client_name_token", "id_parent", "get_languages", "get_themes", "get_parent_chain", "get_children_chain")
    search_fields = ("id_client", "client_name_token")
    filter_horizontal = ("client_languages", "client_themes")  
    # 👆 makes a nice dual select box UI in admin    
    def get_languages(self, obj):
        # join id_language values as comma separated string
        return ", ".join(str(lang.id_language) for lang in obj.client_languages.all())
    get_languages.short_description = "Languages"

    def get_themes(self, obj):
        # join id_theme values as comma separated string
        return ", ".join(str(theme.id_theme) for theme in obj.client_themes.all())
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

admin.site.register(Tokentype, TokentypeAdmin)
admin.site.register(Token, TokenAdmin)
#admin.site.register(Maxlanguage)
admin.site.register(Language, LanguageAdmin)
admin.site.register(Theme, ThemeAdmin)
admin.site.register(Client, ClientAdmin)