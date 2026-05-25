# mysite/translation.py

from modeltranslation.translator import translator, TranslationOptions
# Import directly from the submodules — NOT from mysite.models (the package __init__)
# This avoids the circular import that occurs when modeltranslation autodiscovers
# translation.py before the models package __init__ has finished loading.
from mysite.models.global_config import GlobalVal
from mysite.models.client import Client, Theme, ClientTemplate
from mysite.models.admin_proxies import ClientContentStructured, ClientContentHtml, ClientStaff, ClientTemplatewrapper
from mysite.models.page import NavItem, PageContent #Page, 
from mysite.models.catalogue import (
    Taxonomy, TaxonomyNode, NodeAttributeType, NodeAttributeValue, 
    GlobalItem, GlobalItemMedia, Item, ItemMedia, ProductItem, SongItem, ItemVariant
)
from mysite.models.component import SvgtextbadgeValue
from mysite.models.demand import PlanningLocation, PlanningCustomer, SalesNode

class GlobalValTranslationOptions(TranslationOptions):
    fields = ('keyval',)
    required_languages = ('en',)

class ClientTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)
    required_languages = ('en',)

class ClientContentStructuredTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)  # same as Client

class ClientContentHtmlTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)  # same as Client

class ClientStaffTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)  # same as Client

class ClientTemplatewrapperTranslationOptions(TranslationOptions):
    fields = ('name', 'nb_title',)  # same as Client

class ThemeTranslationOptions(TranslationOptions):
    fields = ('name',)
    required_languages = ('en',)

#class PageTranslationOptions(TranslationOptions):
#    fields = ('name',)
#    required_languages = ('en',)
class PageContentTranslationOptions(TranslationOptions):
    fields = ('htmlblob',)
    required_languages = ('en',)

class ClientTemplateTranslationOptions(TranslationOptions):
    fields = ('htmlblob',)
    required_languages = ('en',)    

class NavItemTranslationOptions(TranslationOptions):
    fields = ('name',)
    required_languages = ('en',)

class TaxonomyTranslationOptions(TranslationOptions):
    fields = ('name', 'description')

class TaxonomyNodeTranslationOptions(TranslationOptions):
    fields = ('name',)

class NodeAttributeTypeTranslationOptions(TranslationOptions):
    fields = ('name',)

class NodeAttributeValueTranslationOptions(TranslationOptions):
    fields = ('name',)

class GlobalItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description', 'care_instructions')

class GlobalItemMediaTranslationOptions(TranslationOptions):
    fields = ('text_content',)

class ItemTranslationOptions(TranslationOptions):
    fields = ('name', 'description', 'care_instructions')    

#class ProductItemTranslationOptions(TranslationOptions):
#    fields = ('short_description', 'care_instructions',)    

class SongItemTranslationOptions(TranslationOptions):
    fields = ('artist', 'album',) 

class ItemMediaTranslationOptions(TranslationOptions):
    fields = ('text_content',)

class ItemVariantTranslationOptions(TranslationOptions):
    fields = ('name', )     

class SvgtextbadgeValueTranslationOptions(TranslationOptions):
    fields = ('text',)

class PlanningLocationTranslationOptions(TranslationOptions):
    fields = ('name', 'level_label',)    

class PlanningCustomerTranslationOptions(TranslationOptions):
    fields = ('name', 'level_label',)  

class SalesNodeTranslationOptions(TranslationOptions):
    fields = ('name', 'level_label',)  
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
translator.register(ClientContentStructured,    ClientContentStructuredTranslationOptions)
translator.register(ClientContentHtml,    ClientContentHtmlTranslationOptions)
translator.register(ClientStaff,    ClientStaffTranslationOptions)
translator.register(ClientTemplatewrapper,    ClientTemplatewrapperTranslationOptions)

translator.register(Theme,     ThemeTranslationOptions)
#translator.register(Page,      PageTranslationOptions)
translator.register(PageContent,      PageContentTranslationOptions)
translator.register(ClientTemplate,      ClientTemplateTranslationOptions)
translator.register(NavItem,   NavItemTranslationOptions)

translator.register(Taxonomy,      TaxonomyTranslationOptions)
translator.register(TaxonomyNode,  TaxonomyNodeTranslationOptions)
translator.register(NodeAttributeType,   NodeAttributeTypeTranslationOptions)
translator.register(NodeAttributeValue,  NodeAttributeValueTranslationOptions)
translator.register(GlobalItem,          GlobalItemTranslationOptions)
translator.register(GlobalItemMedia,          GlobalItemMediaTranslationOptions)
translator.register(Item,          ItemTranslationOptions)
translator.register(ItemMedia,          ItemMediaTranslationOptions)
#translator.register(ProductItem,   ProductItemTranslationOptions)
translator.register(SongItem,      SongItemTranslationOptions)
translator.register(ItemVariant,      ItemVariantTranslationOptions)
translator.register(SvgtextbadgeValue,      SvgtextbadgeValueTranslationOptions)

translator.register(PlanningLocation,      PlanningLocationTranslationOptions)
translator.register(PlanningCustomer,      PlanningCustomerTranslationOptions)
translator.register(SalesNode,      SalesNodeTranslationOptions)


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