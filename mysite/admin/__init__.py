# mysite/admin/__init__.py

from django.contrib import admin
from django.contrib.auth.models import User

from mysite.admin.global_config import (
    ThemePresetAdmin, GlobalValCatAdmin, GlobalValInline, DistributionChannelAdmin
)
from mysite.admin.client import ClientAdmin, ClientBlockAdmin, ClientFeatureControlAdmin, ClientContentStructuredAdmin, ClientContentHtmlAdmin, ClientStaffAdmin, ClientTemplatewrapperAdmin, SectorTemplateAdmin #ClientTemplateAdmin

from mysite.admin.users import (
    ClientUserProfileInline, CustomUserAdmin, ClientGroupPermissionInline, 
    ClientUserMembershipInline, ClientGroupAdmin, ClientLocationAdmin, 
)
from mysite.admin.catalogue import GlobalItemAdmin, TaxonomyAdmin, ItemAdmin, TaxonomyNodeAdmin, NodeAttributeTypeAdmin, NodeAttributeValueAdmin

from mysite.admin.demand import PlanningLocationAdmin, PlanningCustomerAdmin, SalesNodeAdmin, SalesForecastLinkAdmin, ActualSaleAdmin, ItemPlanningProfileAdmin

from mysite.admin.demand_forecast import ( 
    ForecastVersionAdmin, ForecastLineAdmin, ForecastAccuracyAdmin, 
    AbcClassDefinitionAdmin, ForecastingConfigAdmin, SeriesLevelEvaluationAdmin, SeriesProfileAdmin, 
    ForecastAggregateAdmin, ForecastOverrideAdmin
)

from mysite.admin.demand_schemes import (
    SalesSchemeAdmin, ResolvedSalesSchemePeriodAdmin,
)

from mysite.admin.demand_lifecycle import (
    ItemSubstitutionAdmin, ItemDiscontinuationAdmin, ItemIntroductionAdmin,
)

from mysite.models import (
    ThemePreset, GlobalValCat, GlobalVal, DistributionChannel,
    Client, ClientBlock, ClientFeatureControl, 
    ClientContentStructured, ClientContentHtml, ClientStaff, ClientTemplatewrapper,
    Theme, ClientLocation,
    NavItem, Page, ClientTemplate,
    SectorTemplate,
    ClientGroup, 
    Layout, Component,
    ClientUserProfile, CustomerProfile, ClientUserMembership,
    GlobalItem, Taxonomy, Item,
    TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    # Demand Planning
    PlanningLocation, PlanningCustomer, SalesNode, SalesForecastLink, ActualSaleImport, ActualSale, ItemPlanningProfile,
    ForecastVersion, ForecastLine, ForecastAccuracy, 
    AbcClassDefinition, ForecastingConfig, SeriesLevelEvaluation, SeriesProfile,
    ForecastAggregate, ForecastOverride
)

from mysite.models.demand.schemes import (
    SalesScheme, ResolvedSalesSchemePeriod,
)

from mysite.models.demand.lifecycle import (
    ItemSubstitution, ItemDiscontinuation, ItemIntroduction,
)



# All registrations in one place — easy to see what's registered
admin.site.register(ClientBlock,          ClientBlockAdmin)
admin.site.register(ClientFeatureControl,          ClientFeatureControlAdmin)


admin.site.register(ThemePreset,          ThemePresetAdmin)
admin.site.register(DistributionChannel,          DistributionChannelAdmin)


admin.site.register(GlobalValCat,         GlobalValCatAdmin)
admin.site.register(Client,               ClientAdmin)
admin.site.register(ClientContentStructured,  ClientContentStructuredAdmin)
admin.site.register(ClientContentHtml,  ClientContentHtmlAdmin)
admin.site.register(ClientStaff,  ClientStaffAdmin)
admin.site.register(ClientTemplatewrapper,  ClientTemplatewrapperAdmin)

#admin.site.register(ClientTemplate,  ClientTemplateAdmin)
admin.site.register(SectorTemplate,       SectorTemplateAdmin)
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
admin.site.register( SalesForecastLink,  SalesForecastLinkAdmin)
admin.site.register( ActualSale,  ActualSaleAdmin)
admin.site.register( ItemPlanningProfile,  ItemPlanningProfileAdmin)
# Forecasting
admin.site.register( ForecastVersion,  ForecastVersionAdmin)
admin.site.register( ForecastLine,  ForecastLineAdmin)
admin.site.register( ForecastAccuracy,  ForecastAccuracyAdmin)


admin.site.register( AbcClassDefinition,  AbcClassDefinitionAdmin)
admin.site.register( ForecastingConfig,  ForecastingConfigAdmin)
admin.site.register( SeriesLevelEvaluation,  SeriesLevelEvaluationAdmin)
admin.site.register( SeriesProfile,  SeriesProfileAdmin)
admin.site.register( ForecastAggregate,  ForecastAggregateAdmin)
admin.site.register( ForecastOverride,  ForecastOverrideAdmin)

# Sales Promotion Schemes
admin.site.register( SalesScheme,  SalesSchemeAdmin)
admin.site.register( ResolvedSalesSchemePeriod,  ResolvedSalesSchemePeriodAdmin)

# Item Lifecycle
admin.site.register( ItemSubstitution,  ItemSubstitutionAdmin)
admin.site.register( ItemDiscontinuation,  ItemDiscontinuationAdmin)
admin.site.register( ItemIntroduction,  ItemIntroductionAdmin)
