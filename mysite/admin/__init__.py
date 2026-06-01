# mysite/admin/__init__.py

from django.contrib import admin
from django.contrib.auth.models import User

from mysite.admin.global_config import (
    ThemePresetAdmin, GlobalValCatAdmin, GlobalValInline
)
from mysite.admin.client import ClientAdmin, ClientBlockAdmin, ClientFeatureControlAdmin, ClientContentStructuredAdmin, ClientContentHtmlAdmin, ClientStaffAdmin, ClientTemplatewrapperAdmin #ClientTemplateAdmin

from mysite.admin.users import (
    ClientUserProfileInline, CustomUserAdmin, ClientGroupPermissionInline, 
    ClientUserMembershipInline, ClientGroupAdmin, ClientLocationAdmin, 
)
from mysite.admin.catalogue import GlobalItemAdmin, TaxonomyAdmin, ItemAdmin, TaxonomyNodeAdmin, NodeAttributeTypeAdmin, NodeAttributeValueAdmin

from mysite.admin.demand import PlanningLocationAdmin, PlanningCustomerAdmin, SalesNodeAdmin, CustomerSalesAssignmentAdmin, ActualSaleAdmin

from mysite.admin.demand_forecast import ( 
    ForecastVersionAdmin, ForecastLineAdmin, ForecastAccuracyAdmin, 
    AbcClassDefinitionAdmin, ForecastingConfigAdmin, SeriesLevelEvaluationAdmin, SeriesProfileAdmin
)

from mysite.models import (
    ThemePreset, GlobalValCat, GlobalVal,
    Client, ClientBlock, ClientFeatureControl, 
    ClientContentStructured, ClientContentHtml, ClientStaff, ClientTemplatewrapper,
    Theme, ClientLocation,
    NavItem, Page, ClientTemplate,
    ClientGroup, 
    Layout, Component,
    ClientUserProfile, CustomerProfile, ClientUserMembership,
    GlobalItem, Taxonomy, Item,
    TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    # Demand Planning
    PlanningLocation, PlanningCustomer, SalesNode, CustomerSalesAssignment, ActualSaleImport, ActualSale, 
    ForecastVersion, ForecastLine, ForecastAccuracy, 
    AbcClassDefinition, ForecastingConfig, SeriesLevelEvaluation, SeriesProfile
)



# All registrations in one place — easy to see what's registered
admin.site.register(ClientBlock,          ClientBlockAdmin)
admin.site.register(ClientFeatureControl,          ClientFeatureControlAdmin)


admin.site.register(ThemePreset,          ThemePresetAdmin)
admin.site.register(GlobalValCat,         GlobalValCatAdmin)
admin.site.register(Client,               ClientAdmin)
admin.site.register(ClientContentStructured,  ClientContentStructuredAdmin)
admin.site.register(ClientContentHtml,  ClientContentHtmlAdmin)
admin.site.register(ClientStaff,  ClientStaffAdmin)
admin.site.register(ClientTemplatewrapper,  ClientTemplatewrapperAdmin)

#admin.site.register(ClientTemplate,  ClientTemplateAdmin)
admin.site.register(ClientLocation,       ClientLocationAdmin)
admin.site.register(ClientGroup,          ClientGroupAdmin)
admin.site.register(User,                 CustomUserAdmin)
admin.site.register(Taxonomy,             TaxonomyAdmin)
admin.site.register(GlobalItem,           GlobalItemAdmin)
admin.site.register(Item,                 ItemAdmin)
admin.site.register(TaxonomyNode,         TaxonomyNodeAdmin)
admin.site.register(NodeAttributeType,    NodeAttributeTypeAdmin)
admin.site.register( NodeAttributeValue,  NodeAttributeValueAdmin)

# Demand Planning PlanningLocationAdmin, PlanningCustomerAdmin, SalesNodeAdmin, CustomerSalesAssignmentAdmin, ActualSaleAdmin
admin.site.register( PlanningLocation,  PlanningLocationAdmin)
admin.site.register( PlanningCustomer,  PlanningCustomerAdmin)
admin.site.register( SalesNode,  SalesNodeAdmin)
admin.site.register( CustomerSalesAssignment,  CustomerSalesAssignmentAdmin)
admin.site.register( ActualSale,  ActualSaleAdmin)

# Forecasting
admin.site.register( ForecastVersion,  ForecastVersionAdmin)
admin.site.register( ForecastLine,  ForecastLineAdmin)
admin.site.register( ForecastAccuracy,  ForecastAccuracyAdmin)


admin.site.register( AbcClassDefinition,  AbcClassDefinitionAdmin)
admin.site.register( ForecastingConfig,  ForecastingConfigAdmin)
admin.site.register( SeriesLevelEvaluation,  SeriesLevelEvaluationAdmin)
admin.site.register( SeriesProfile,  SeriesProfileAdmin)

