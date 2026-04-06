from modeltranslation.translator import register, TranslationOptions
from .models import GlobalVal, Client, Theme, Page

@register(GlobalVal)
class GlobalValTranslationOptions(TranslationOptions):
    fields = ('keyval',)
    required_languages = ('en',)

@register(Client)
class ClientTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title')
    # optional: set a required_languages constraint
    required_languages = ('en',)

@register(Theme)
class ThemeTranslationOptions(TranslationOptions):
    fields = ('name', )
    # optional: set a required_languages constraint
    required_languages = ('en',)    

@register(Page)
class PageTranslationOptions(TranslationOptions):
    fields = ('name', )
    # optional: set a required_languages constraint
    required_languages = ('en',)    
