# mysite/admin/__init__.py

from django.contrib import admin
from django.contrib.auth.models import User

from mysite.admin.global_config import (
    ThemePresetAdmin, GlobalValCatAdmin, GlobalValInline
)
from mysite.admin.client import ClientAdmin  

#from mysite.admin.page import PageInline, LayoutInline, PageContentInline, NavItemInline

#from mysite.admin.component import SvgtextbadgeValueInline, TextstbItemInline, ComptextBlockInline, GentextBlockInline, ComptextBlockInline, ComponentSlotInline

from mysite.admin.users import (
    ClientUserProfileInline, CustomUserAdmin, ClientGroupPermissionInline, 
    ClientUserMembershipInline, ClientGroupAdmin, ClientLocationAdmin, 
)
from mysite.admin.catalogue import GlobalItemAdmin, TaxonomyAdmin, ItemAdmin, TaxonomyNodeAdmin, NodeAttributeTypeAdmin, NodeAttributeValueAdmin

from mysite.models import (
    ThemePreset, GlobalValCat, GlobalVal,
    Client, Theme, ClientLocation,
    NavItem, Page, 
    ClientGroup, 
    Layout, Component,
    ClientUserProfile, CustomerProfile, ClientUserMembership,
    GlobalItem, Taxonomy, Item,
    TaxonomyNode, NodeAttributeType, NodeAttributeValue

)


# All registrations in one place — easy to see what's registered
admin.site.register(ThemePreset,          ThemePresetAdmin)
admin.site.register(GlobalValCat,         GlobalValCatAdmin)
admin.site.register(Client,               ClientAdmin)
admin.site.register(ClientLocation,       ClientLocationAdmin)
admin.site.register(ClientGroup,          ClientGroupAdmin)
admin.site.register(User,                 CustomUserAdmin)
admin.site.register(Taxonomy,             TaxonomyAdmin)
admin.site.register(GlobalItem,           GlobalItemAdmin)
admin.site.register(Item,                 ItemAdmin)
admin.site.register(TaxonomyNode,         TaxonomyNodeAdmin)
admin.site.register(NodeAttributeType,    NodeAttributeTypeAdmin)
admin.site.register( NodeAttributeValue,  NodeAttributeValueAdmin)
