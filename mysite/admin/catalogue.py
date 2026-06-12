# mysite/admin/_catalogue.py
import nested_admin
from modeltranslation.admin import TranslationBaseModelAdmin
from .base import _user_has_admin_role, ClientLanguageMixinV2, BaseAdminInlinecss, SharedOrClientScopedMixin, ClientScopedMixin
#from modeltranslation.translator import translator
from django.conf import settings

from django.contrib import admin
from mysite.models.catalogue import (
    TaxonomyNode, NodeAttributeType, NodeAttributeValue,
    GlobalItemTaxonomyNode, GlobalItemAttributeValue, GlobalItemMedia,
    ItemTaxonomyNode, ItemAttributeValue, ItemMedia, ItemVariant,
    ProductItem, SongItem, DocumentItem, ServiceItem,
)
"""
Client admins should:

Model	            Global rows	        Client rows
GlobalItem	        View only	        N/A
Taxonomy	        View	            CRUD
TaxonomyNode	    View	            CRUD
NodeAttributeType	View	            CRUD
NodeAttributeValue	View	            CRUD
Item* models	    N/A	                CRUD

ClientScopedMixin
    ↓
SharedOrClientScopedMixin
    ↓
Catalogue Admins

ClientScopedMixin
Handles:
    guardian permission checks
    tenant permission logic

SharedOrClientScopedMixin
Handles:
    global/shared row visibility
    queryset filtering
    dropdown filtering
    protection of shared rows

This is a very clean separation.
"""   
# ── Taxonomy Admin ────────────────────────────────────────────────────



class NodeAttributeValueInline(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2):
    model  = NodeAttributeValue
    extra  = 0
    classes = ['collapse']
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'slug', 'order', 'gpc_value_code')    # adjust to your actual fields    
    show_change_link = True
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'slug', 'order', 'gpc_value_code'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )

        return (
            ('General', {
                'fields': ('client', 'slug', 'order', 'gpc_value_code'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    #fieldsets = ()       
    """
class NodeAttributeValueAdmin(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2):
    list_select_related = ('client', 'attribute_type')
    search_fields = ('slug', 'name', 'gpc_value_code')
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'slug', 'order', 'gpc_value_code')    # adjust to your actual fields
    list_filter   = ('client', 'attribute_type')
    def get_fieldsets(self, request, obj=None):
            main_ln_fields, other_ln_fields = self.get_translated_field_groups(
                request, ['name'], obj
            )
            fieldsets = [
                ('General', {
                    'fields': ('client', 'slug', 'order', 'gpc_value_code'),
                    'classes': ('collapse',),
                }),            
                ('Main Language', {
                    'fields': main_ln_fields,
                    'classes': ('collapse',),
                }),
            ]
            # Only add Other Languages section if client has more than one language
            if other_ln_fields:
                fieldsets.append((
                    'Other Languages', {
                        'fields': other_ln_fields,
                        'classes': ('collapse',),
                    }
                ))
            return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('client', 'slug', 'order', 'gpc_value_code'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    #fieldsets = () 
    """
    def has_module_perms(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)
    
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)
        
class NodeAttributeTypeInline(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2):
    model  = NodeAttributeType
    extra  = 0
    classes = ['collapse']
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code')    # adjust to your actual fields    
    show_change_link = True
    inlines         = [NodeAttributeValueInline]
    def get_fieldsets(self, request, obj=None):
                main_ln_fields, other_ln_fields = self.get_translated_field_groups(
                    request, ['name'], obj
                )
                fieldsets = [
                    ('General', {
                        'fields': ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code'),
                        'classes': ('collapse',),
                    }),            
                    ('Main Language', {
                        'fields': main_ln_fields,
                        'classes': ('collapse',),
                    }),
                ]
                # Only add Other Languages section if client has more than one language
                if other_ln_fields:
                    fieldsets.append((
                        'Other Languages', {
                            'fields': other_ln_fields,
                            'classes': ('collapse',),
                        }
                    ))
                return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    #fieldsets = ()   
    """ 

class NodeAttributeTypeAdmin(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss):
    list_select_related = ('client', 'node')
    search_fields = ('slug', 'name', 'gpc_attribute_code')
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code'                       )    # adjust to your actual fields  
    list_filter   = ('client', 'field_type', 'is_filterable')
    inlines       = [NodeAttributeValueInline]
    def get_fieldsets(self, request, obj=None):
                main_ln_fields, other_ln_fields = self.get_translated_field_groups(
                    request, ['name'], obj
                )
                fieldsets = [
                    ('General', {
                        'fields': ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code'),
                        'classes': ('collapse',),
                    }),            
                    ('Main Language', {
                        'fields': main_ln_fields,
                        'classes': ('collapse',),
                    }),
                ]
                # Only add Other Languages section if client has more than one language
                if other_ln_fields:
                    fieldsets.append((
                        'Other Languages', {
                            'fields': other_ln_fields,
                            'classes': ('collapse',),
                        }
                    ))
                return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('client', 'slug', 'field_type', 'is_required', 'is_filterable', 'order', 'gpc_attribute_code'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
        #fieldsets = () 
    """
    def has_module_perms(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)
    
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)
    
class TaxonomyNodeInline(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2, BaseAdminInlinecss):
    model = TaxonomyNode
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'taxonomy',
            'client',
        )
    #def get_queryset(self, request):
    #    return super().get_queryset(request).select_related(
    #        'node', 'node__taxonomy', 'node__client'
    #    )    
    extra = 0
    classes = ['collapse']
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active')    # adjust to your actual fields
    show_change_link = True
    readonly_fields = ('path', 'depth')
    raw_id_fields = ['parent', 'global_node']
    inlines         = [NodeAttributeTypeInline]
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('client', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )    
    """

class TaxonomyNodeAdmin(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss):
    list_select_related = ('taxonomy', 'client', 'parent', 'global_node')
    search_fields   = ('slug', 'name', 'path', 'gpc_code')
    #TRANSLATED_FIELDS = ('name',)                   # add more if you have translated fields
    #non_translated_fields = ('client', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active')    # adjust to your actual fields
    list_filter     = ('taxonomy', 'client', 'is_active', 'depth')
    readonly_fields = ('path', 'depth')
    autocomplete_fields = ['parent', 'global_node']
    # Note: no autocomplete_fields on parent/global_node here
    # since those also reference TaxonomyNode — handled via raw_id_fields instead
    raw_id_fields   = ('parent', 'global_node')
    inlines         = [NodeAttributeTypeInline]
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('client', 'taxonomy', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('client', 'taxonomy', 'parent', 'slug', 'path', 'depth', 'order', 'metadata', 'gpc_code', 'global_node', 'is_active'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        ) 
    """
    def has_module_perms(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)
    
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_add_permission(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)
     
class TaxonomyAdmin(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss):
    inlines      = [TaxonomyNodeInline]
    admin_role_only = True
    search_fields = ('slug', 'name')
    raw_id_fields = ('client',)
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name', 'description'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('slug', 'client', 'taxonomy_type', 'order', 'is_active', 'gpc_segment_code'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'description'],
            obj
        )
        return (
            ('General', {
                'fields': ('slug', 'client', 'taxonomy_type', 'order', 'is_active', 'gpc_segment_code'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )   
    """
    """
    def has_add_permission(self, request):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)

    def has_module_perms(self, request):        # chatgpt
        return request.user.is_superuser or _user_has_admin_role(request.user)
    """

# ── Global Item Admin ─────────────────────────────────────────────────
class GlobalItemMediaInline(TranslationBaseModelAdmin, ClientLanguageMixinV2, nested_admin.NestedStackedInline):
    model  = GlobalItemMedia
    extra               = 0
    classes             = ['collapse']
    #fields = ('media_type', 'media_url', 'alt', 'order', 'is_primary')
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['text_content'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('media_type', 'media_url', 'alt', 'order', 'is_primary'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['text_content'],
            obj
        )
        return (
            ('General', {
                'fields': ('media_type', 'media_url', 'alt', 'order', 'is_primary'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    """

class GlobalItemAttributeValueInline(nested_admin.NestedStackedInline):
    model       = GlobalItemAttributeValue
    extra       = 0
    classes     = ['collapse']
    fields      = ('attribute_type', 'predefined_value', 'value_text', 'value_number')
    autocomplete_fields = ['attribute_type', 'predefined_value']


class GlobalItemTaxonomyNodeInline(nested_admin.NestedStackedInline):
    model       = GlobalItemTaxonomyNode
    extra       = 0
    classes = ['collapse']
    fields      = ('node', 'is_primary')
    autocomplete_fields = ['node']
    #inlines         = [GlobalItemAttributeValueInline]  -- moved to GlobalItemAdmin


class GlobalItemAdmin(TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss):
    #TRANSLATED_FIELDS = ('name', 'description', 'care_instructions',)
    #non_translated_fields = ('global_item_id', 'domain', 'brand', 'gtin',
    #                   'barcode', 'weight_g', 'length_mm', 'width_mm', 'height_mm',
    #                   'gpc_brick_code', 'status', 'manufacturer', 'country_of_origin', 'image_url', 'image_alt', 'attributes')    # adjust to your actual fields        
    list_select_related = True   # select_related on all FK fields
    admin_role_only = True    
    list_filter     = ('domain', 'status')
    search_fields   = ('global_item_id', 'name', 'gtin', 'gpc_brick_code')
    readonly_fields = ('created_at', 'updated_at')
    inlines         = [GlobalItemTaxonomyNodeInline, GlobalItemAttributeValueInline, GlobalItemMediaInline]

    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name', 'description', 'care_instructions'], obj
        )
        fieldsets = [
            ('GS1 Identification', {
                'fields': ('gtin', 'gpc_brick_code', 'global_item_id', 'domain', 'status'),
                'classes': ('collapse',),
                'description': 'GTIN: 8/12/13/14 digit GS1 identifier. '
                            'GPC Brick Code: 8-digit GS1 GPC code.'
                
            }),          
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Image Content', {
                'fields': ('image_url', 'image_alt'),
                'classes': ('collapse',),
            }),
            ('Basics', {
                'fields': ('barcode', 'weight_g', 'length_mm', 'width_mm', 'height_mm'),
                'classes': ('collapse',),
            }),        
            ('Overflow Attributes', {
                'fields': ('attributes',),
                'classes': ('collapse',),
                'description': 'JSON overflow for attributes not in typed sub-models'
            }),
            ('Audit', {
                'fields': ('created_by', 'created_at', 'updated_at'),
                'classes': ('collapse',)
            }),     

        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.insert(2, (
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """ 
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'description', 'care_instructions'],
            obj
        )

        return (
            ('GS1 Identification', {
                'fields': ('gtin', 'gpc_brick_code', 'global_item_id', 'domain', 'status'),
                'classes': ('collapse',),
                'description': 'GTIN: 8/12/13/14 digit GS1 identifier. '
                            'GPC Brick Code: 8-digit GS1 GPC code.'
                
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
            #('Brand / Manufacturer', {
            #    'fields': ('brand', 'subbrand', 'manufacturer', 'country_of_origin'),
            #    'classes': ('collapse',),
            #}),
            ('Image Content', {
                'fields': ('image_url', 'image_alt'),
                'classes': ('collapse',),
            }),
            ('Basics', {
                'fields': ('barcode', 'weight_g', 'length_mm', 'width_mm', 'height_mm'),
                'classes': ('collapse',),
            }),        
            ('Overflow Attributes', {
                'fields': ('attributes',),
                'classes': ('collapse',),
                'description': 'JSON overflow for attributes not in typed sub-models'
            }),
            ('Audit', {
                'fields': ('created_by', 'created_at', 'updated_at'),
                'classes': ('collapse',)
            }),            
        )
    #fieldsets = ()
    """
    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or _user_has_admin_role(request.user)


# ── Client Item Admin ─────────────────────────────────────────────────

class ItemAttributeValueInline(nested_admin.NestedStackedInline):
    model               = ItemAttributeValue
    extra               = 0
    classes             = ['collapse']
    fields              = ('attribute_type', 'predefined_value', 'value_text', 'value_number')
    autocomplete_fields = ['attribute_type', 'predefined_value']

class ItemTaxonomyNodeInline(nested_admin.NestedStackedInline):
    model               = ItemTaxonomyNode
    extra               = 0
    classes             = ['collapse']
    fields              = ('node', 'is_primary', 'order')
    autocomplete_fields = ['node']
    #inlines         = [ItemAttributeValueInline] -- part of ItemAdmin

class ItemMediaInline(TranslationBaseModelAdmin, ClientLanguageMixinV2, nested_admin.NestedStackedInline):
    model  = ItemMedia
    extra               = 0
    classes             = ['collapse']
    #fields = ('media_type', 'media_url', 'alt', 'order', 'is_primary')
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['text_content'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('media_type', 'media_url', 'alt', 'order', 'is_primary'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['text_content'],
            obj
        )
        return (
            ('General', {
                'fields': ('media_type', 'media_url', 'alt', 'order', 'is_primary'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    """
class ItemVariantInline(TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2):
    model  = ItemVariant
    extra               = 0
    classes             = ['collapse']
    #TRANSLATED_FIELDS = ('name', )
    #fields = ('variant_id', 'sku', 'gtin', 'price', 'stock', 'is_active', 'attributes')
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('variant_id', 'sku', 'gtin', 'price', 'stock', 'is_active', 'attributes'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name'],
            obj
        )
        return (
            ('General', {
                'fields': ('variant_id', 'sku', 'gtin', 'price', 'stock', 'is_active', 'attributes'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )   
    """
class ProductItemInline(nested_admin.NestedStackedInline):
    model  = ProductItem
    extra               = 0
    classes             = ['collapse']
    #TRANSLATED_FIELDS = ('short_description', 'care_instructions', )    
    fields = ('price', 'compare_price', 'currency', 'sku',  'barcode', 'track_inventory', 'stock_quantity', 
              'attributes')


class SongItemInline(TranslationBaseModelAdmin, nested_admin.NestedStackedInline, ClientLanguageMixinV2):
    model  = SongItem
    extra               = 0
    classes             = ['collapse']
    #TRANSLATED_FIELDS = ('artist', 'album', )      
    #fields = ('duration_s', 'bpm', 'genre', 'musical_key', 'audio_url', 'preview_url', 'isrc', 'attributes')
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['artist', 'album'], obj
        )
        fieldsets = [
            ('General', {
                'fields': ('duration_s', 'bpm', 'genre', 'musical_key', 'audio_url', 'preview_url', 'isrc', 'attributes'),
                'classes': ('collapse',),
            }),            
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.append((
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['artist', 'album'],
            obj
        )
        return (
            ('General', {
                'fields': ('duration_s', 'bpm', 'genre', 'musical_key', 'audio_url', 'preview_url', 'isrc', 'attributes'),
                'classes': ('collapse',),
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
        )
    """
class DocumentItemInline(nested_admin.NestedStackedInline):
    model  = DocumentItem
    extra               = 0
    classes             = ['collapse']
    fields = ('file_url', 'format', 'page_count', 'file_size_kb',
              'version', 'language', 'is_free', 'price', 'currency', 'attributes')


class ServiceItemInline(nested_admin.NestedStackedInline):
    model  = ServiceItem
    extra               = 0
    classes             = ['collapse']
    fields = ('price', 'currency', 'duration_minutes', 'is_location_based',
              'service_area', 'fulfillment_type', 'attributes')


class ItemAdmin(SharedOrClientScopedMixin, TranslationBaseModelAdmin, nested_admin.NestedModelAdmin, ClientLanguageMixinV2, BaseAdminInlinecss ):
    list_select_related = ('client', 'global_item', 'product_detail', 'song_detail', 'document_detail', 'service_detail')
    admin_role_only = True    
    list_filter     = ('client', 'domain', 'status')
    search_fields   = ('item_id', 'name', 'gtin')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ['global_item']
    raw_id_fields = ('client', 'global_item')

    """
    inlines         = [
        ItemTaxonomyNodeInline,
        ItemAttributeValueInline,
        ItemMediaInline,
        ItemVariantInline,
        ProductItemInline,
        SongItemInline,
        DocumentItemInline,
        ServiceItemInline,
    ]

    # for Inline Header to be in a Single Line    
    class Media:
        css = {
            'all': ('admin/css/custom_inline.css',)
        }    
    """  
    """ 
    def get_queryset(self, request):
        qs = super().get_queryset(request)

        if request.user.is_superuser:
            return qs

        return qs.filter(
            client__in=self._permitted_clients(request)
        )    
    """
    def get_fieldsets(self, request, obj=None):
        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request, ['name', 'description', 'care_instructions'], obj
        )
        fieldsets = [
            ('Client', {
                'fields': ('client',),
                'classes': ('collapse',),
            }),              
            ('GS1 Identification', {
                'fields': ('gtin', 'gpc_brick_code', 'item_id', 'global_item', 'inherit_global_media', 'domain', 'status', 'order'),
                'classes': ('collapse',),
                'description': 'GTIN: 8/12/13/14 digit GS1 identifier. '
                            'GPC Brick Code: 8-digit GS1 GPC code.'
                
            }),          
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Image Content', {
                'fields': ('image_url', 'image_alt'),
                'classes': ('collapse',),
            }),
            ('Basics', {
                'fields': ('barcode', 'weight_g', 'length_mm', 'width_mm', 'height_mm'),
                'classes': ('collapse',),
            }),        
            ('Overflow Attributes', {
                'fields': ('attributes',),
                'classes': ('collapse',),
                'description': 'JSON overflow for attributes not in typed sub-models'
            }),
            ('Audit', {
                'fields': ('created_by', 'created_at', 'updated_at'),
                'classes': ('collapse',)
            }),     

        ]
        # Only add Other Languages section if client has more than one language
        if other_ln_fields:
            fieldsets.insert(3, (
                'Other Languages', {
                    'fields': other_ln_fields,
                    'classes': ('collapse',),
                }
            ))
        return tuple(fieldsets)
    """
    def get_fieldsets(self, request, obj=None):

        main_ln_fields, other_ln_fields = self.get_translated_field_groups(
            request,
            ['name', 'description', 'care_instructions'],
            obj
        )

        return (
            ('Client', {
                'fields': ('client',),
                'classes': ('collapse',),
            }),            
            ('GS1 Identification', {
                'fields': ('gtin', 'gpc_brick_code', 'item_id', 'global_item', 'inherit_global_media', 'domain', 'status', 'order'),
                'classes': ('collapse',),
                'description': 'GTIN: 8/12/13/14 digit GS1 identifier. '
                            'GPC Brick Code: 8-digit GS1 GPC code.'              
            }),
            ('Main Language', {
                'fields': main_ln_fields,
                'classes': ('collapse',),
            }),
            ('Other Languages', {
                'fields': other_ln_fields,
                'classes': ('collapse',),
            }),
            #('Brand / Manufacturer', {
            #    'fields': ('brand', 'subbrand', 'manufacturer', 'country_of_origin'),
            #    'classes': ('collapse',),
            #}),
            ('Image Content', {
                'fields': ('image_url', 'image_alt'),
                'classes': ('collapse',),
            }),
            ('Basics', {
                'fields': ('barcode', 'weight_g', 'length_mm', 'width_mm', 'height_mm'),
                'classes': ('collapse',),
            }),        
            ('Overflow Attributes', {
                'fields': ('attributes',),
                'classes': ('collapse',),
                'description': 'JSON overflow for attributes not in typed sub-models'
            }),
            ('Audit', {
                'fields': ('created_by', 'created_at', 'updated_at'),
                'classes': ('collapse',)
            }),            
        )
    """
    def get_inline_instances(self, request, obj=None):
        inline_instances = []

        common_inlines = [
            ItemTaxonomyNodeInline,
            ItemAttributeValueInline,
            ItemMediaInline,
            ItemVariantInline,
        ]

        domain_inlines_map = {
            'product': [ProductItemInline],
            'song': [SongItemInline],
            'document': [DocumentItemInline],
            'service': [ServiceItemInline],
        }

        # 1. Add common inlines (always)
        for inline in common_inlines:
            inline_instances.append(inline(self.model, self.admin_site))

        # 2. ADD PAGE → include ALL domain inlines (collapsed)
        if obj is None:
            for inline_list in domain_inlines_map.values():
                for inline in inline_list:
                    inline_instances.append(inline(self.model, self.admin_site))

        # 3. EDIT PAGE → include ONLY selected domain inline
        else:
            domain_inlines = domain_inlines_map.get(obj.domain, [])
            for inline in domain_inlines:
                inline_instances.append(inline(self.model, self.admin_site))

        return inline_instances

    def resolved_name_display(self, obj):
        return obj.resolved_name()
    resolved_name_display.short_description = 'Resolved Name'

    def has_add_permission(self, request):
        return _user_has_admin_role(request.user)

    def has_delete_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

    def has_change_permission(self, request, obj=None):
        return _user_has_admin_role(request.user)

