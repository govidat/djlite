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
from .models import Tokentype, Token, Maxlanguage, Language, Theme
#TypedTokenForeignKey, 

class TokentypeAdmin(admin.ModelAdmin):
    list_display = ("id_tokentype", "name", "is_global")
    search_fields = ("id_tokentype", "name")

class TokenAdmin(admin.ModelAdmin):
    list_display = ("id_token", "id_tokentype", "id_parent")
    list_filter = ("id_tokentype" )
    search_fields = ("id_token")   

class MaxlanguageAdmin(admin.ModelAdmin):
    list_display = ("id_language", "name")
    list_filter = ("name")
    search_fields = ("id_language")

class LanguageAdmin(admin.ModelAdmin):
    list_display = ("id_language", "language_name_token")
    list_filter = ("id_language")
    search_fields = ("id_language")

class ThemeAdmin(admin.ModelAdmin):
    list_display = ("id_theme", "theme_name_token")
    list_filter = ("id_theme")
    search_fields = ("id_theme")

    #def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #    if isinstance(db_field, TypedTokenForeignKey) and db_field.id_tokentype:
    #        kwargs["queryset"] = Token.objects.filter(type__code=db_field.id_tokentype)
    #    return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    #def formfield_for_dbfield(self, db_field, request, **kwargs):
    #    if isinstance(db_field, TypedTokenForeignKey) and db_field.id_tokentype:
    #        kwargs["queryset"] = Token.objects.filter(type__code=db_field.id_tokentype)
    #    return super().formfield_for_dbfield(db_field, request, **kwargs)

admin.site.register(Tokentype)
admin.site.register(Token)
admin.site.register(Maxlanguage)
admin.site.register(Language)
admin.site.register(Theme)