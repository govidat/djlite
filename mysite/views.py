from django.shortcuts import render

# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
#from django.utils.timezone import localtime, now
#from django.utils.translation import get_language
from django.conf import settings
#from django.shortcuts import get_object_or_404

#from collections import defaultdict

from utils.common_functions import fetch_clientstatic
#, build_nested_hierarchy, build_layout_tree
# update_list_of_dictionaries, fetch_translations, build_nested_hierarchy, build_nested_hierarchy_v2
project_base_language = settings.LANGUAGE_CODE   # 'en'

 
# Assuming url of form path("<int:pk>/<str:page>/", ClientPageView.as_view(), name="client_page")
class ClientPageView(TemplateView):
    template_name = 'base.html'
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add any common context data here that all views need
        lv_client_id = self.kwargs.get("pkey", 'bahushira')   # <-- get it from URL
        lv_page_id = self.kwargs.get('page', 'home')

        client_dict = fetch_clientstatic(lv_client_id=lv_client_id)

        client_dict.setdefault("pages", [])

        context["client"] = client_dict
        context["page"] = next(
            (p for p in client_dict["pages"] if p.get("page_id") == lv_page_id),
            {}
        )

        """       
        #lv_client_dict = fetch_clientstatic(lv_client_id=lv_client_id)
        context["client"] = fetch_clientstatic(lv_client_id=lv_client_id)
        #lv_pages_list = lv_client_dict.pages
        context["page"] = next(
            (item for item in context["client"]["pages"] if item.get("page_id") == lv_page_id),
            {}
        )
        """
        #context["page"] = list(filter(lambda item: item.get('page_id')==lv_page_id, lv_pages_list))[0]
        #context["page"] = [item for item in lv_client_dict pages if item['page)id'] == lv_page_id]
        #context["page"] = list(filter(lambda item: item.get('page_id')==lv_page_id, lv_client_dict))[0]        
        """
        #client_nb_items = client_static['client_nb_items']
        
        #client_nb_items_nested = client_static['client_nb_items_nested']        
        nb = {}
        nb['items_nested'] = client_static.get('nb_items_nested', [])
        nb['logo']="mylogo" 
        nb['title']={'class': '', 'type': 'text', 'ids': ['nb_title']} 
        context['texts_static_dict'] = client_static.get('texts_static_dict') 
        context['images_static_dict'] = client_static.get('images_static_dict')
        context['svgs_static_dict'] = client_static.get('svgs_static_dict')

        context["client_id"] = lv_client_id
        context["client_hierarchy_list"] = client_static.get('client_hierarchy_list')
        context["client_hierarchy_str"] = ','.join(client_static.get('client_hierarchy_list', []))        

        context["client_language_ids"] = client_static.get('client_language_ids')
        context["client_theme_ids"] = client_static.get('client_theme_ids')
        context['nb'] = nb
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        #context['raw_svgs'] = raw_svgs
        #context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs    
        context['site_accordions'] = site_accordions
        context['site_carousals'] = site_carousals

        site_structure_filtered = list(filter(lambda item: item.get('client') in client_static.get('client_hierarchy_list', []) and not item.get('hidden'), site_structure))

        # filter page_structure based on lv_page_id
        context['page_structure'] = list(filter(lambda item: item.get('page')==lv_page_id, site_structure_filtered))

        # code to get the required layout data from context['layout']
        #layouts = client_static.get('layouts', [])
        #page_layouts = [l for l in layouts if l.page_id == lv_page_id]
        #context['page_tree'] = page_layouts
        #context['page_tree'] = build_layout_tree(page_layouts)    
        context['clientv2'] = client_static.get('clientv2')
        """
        return context


    
"""
The golden rule

select_related → OneToOneField, ForeignKey

prefetch_related → ForeignKey(many), reverse relations


"""