# mysite/translation.py

from modeltranslation.translator import translator, TranslationOptions
# Import directly from the submodules — NOT from mysite.models (the package __init__)
# This avoids the circular import that occurs when modeltranslation autodiscovers
# translation.py before the models package __init__ has finished loading.
from mysite.models.global_config import GlobalVal
from mysite.models.client import Client, Theme
from mysite.models.page import Page, NavItem


class GlobalValTranslationOptions(TranslationOptions):
    fields = ('keyval',)
    required_languages = ('en',)

class ClientTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)
    required_languages = ('en',)

class ThemeTranslationOptions(TranslationOptions):
    fields = ('name',)
    required_languages = ('en',)

class PageTranslationOptions(TranslationOptions):
    fields = ('name',)
    required_languages = ('en',)

class NavItemTranslationOptions(TranslationOptions):
    fields = ('name',)
    required_languages = ('en',)

"""
# Register using get_model — avoids circular import during startup
# modeltranslation calls translation.py before models are fully loaded
GlobalVal = apps.get_model('mysite', 'GlobalVal')
Client    = apps.get_model('mysite', 'Client')
Theme     = apps.get_model('mysite', 'Theme')
Page      = apps.get_model('mysite', 'Page')
NavItem   = apps.get_model('mysite', 'NavItem')
"""

translator.register(GlobalVal, GlobalValTranslationOptions)
translator.register(Client,    ClientTranslationOptions)
translator.register(Theme,     ThemeTranslationOptions)
translator.register(Page,      PageTranslationOptions)
translator.register(NavItem,   NavItemTranslationOptions)

"""


from modeltranslation.translator import register, TranslationOptions
from mysite.models import GlobalVal, Client, Theme, Page, NavItem

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

@register(NavItem)
class NavItemTranslationOptions(TranslationOptions):
    fields = ('name', )
    # optional: set a required_languages constraint
    required_languages = ('en',)    

"""