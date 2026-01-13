from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
#from django.utils.timezone import localtime, now
from django.utils.translation import get_language
from django.conf import settings
from django.shortcuts import get_object_or_404

from django.db.models import Prefetch
#from .models import Client, ClientLanguage, ClientTheme
#from .models import Client, ClientLanguage, ClientTheme, ClientNavbar
#, ClientLanguage, ClientTheme, TextStatic

from utils.common_functions import fetch_clientstatic
# update_list_of_dictionaries, fetch_translations, build_nested_hierarchy, build_nested_hierarchy_v2
project_base_language = settings.LANGUAGE_CODE   # 'en'


site_structure = [
   
    {
    'id': 16, 'parent': None, 'order': 1, 'level': 10, 'page': 'home', 'client': 'bahushira',
    'class': '', 'style': "background-image: url('https://via.placeholder.com/1920x1080');",
    'hidden': False 
    },
    {
    'id': 17, 'parent': 16, 'order': 1, 'level': 20, 'page': 'home', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    }, 
    {
    'id': 18,'parent': 17, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    },     
    {
    'id': 19,'parent': 18, 'order': 1, 'level': 40, 'type': 'hero', 'link_id': 2, 'page': 'home', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False 
    },                
    {
    'id': 20, 'parent': None, 'order': 1, 'level': 10, 'page': 'about', 'client': 'bahushira',
    'class': '', 'style': "background-image: url('https://via.placeholder.com/1920x1080');",
    'hidden': False 
    },
    {
    'id': 21, 'parent': 20, 'order': 1, 'level': 20, 'page': 'about', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    }, 
    {
    'id': 22,'parent': 21, 'order': 1, 'level': 30, 'type': '', 'page': 'about', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    },     
    {
    'id': 23,'parent': 22, 'order': 1, 'level': 40, 'type': 'hero', 'link_id': 3, 'page': 'about', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False 
    },   
    {
    'id': 24, 'parent': None, 'order': 1, 'level': 10, 'page': 'contact', 'client': 'bahushira',
    'class': '', 'style': "background-image: url('https://via.placeholder.com/1920x1080');",
    'hidden': False 
    },
    {
    'id': 25, 'parent': 24, 'order': 1, 'level': 20, 'page': 'contact', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    }, 
    {
    'id': 26,'parent': 25, 'order': 1, 'level': 30, 'type': '', 'page': 'contact', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False  
    },     
    {
    'id': 27,'parent': 26, 'order': 1, 'level': 40, 'type': 'hero', 'link_id': 4, 'page': 'contact', 'client': 'bahushira',
    'class': '', 'style': '',
    'hidden': False 
    },                      
]

site_cards = [
            {
            'id': 1, 'client': 'ABC123', 'page': 'home',
            'class': 'card-lg',
            'body_class': 'items-center text-center',
            'title': {'class': '', 'type': 'stb', 'ids': [1]},
            'contents': {'class': '', 'type': 'stb', 'ids': [2, 3] },
            'actions': {'class': '', 'position': 'end', 
                'buttons': [
                    {'class': '!btn-primary', 'type': 'stb', 'ids': [4]},
                    {'class': '!btn-warning', 'type': 'stb', 'ids': [5]}                    
                ],
            },
            'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'nike', 'class': 'rounded-xl'},
            },
]

site_heros = [
        
        {
            'id': 1, 'client': 'ABC123', 'page': 'home',
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': False, 'type': 'figure', 'order': 2, 
                    'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'spiderman', 'class': 'max-w-sm rounded-xl shadow-2xl'},  
                },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title':    {'class': '', 'type': 'stb', 'ids': [7]},
                    'contents': {'class': '', 'type': 'stb', 'ids': [8, 9]},
                    'actions':  {'class': '', 'position': 'end',                        
                        'buttons': [
                            {'class': '!btn-primary', 'type': 'stb', 'ids': [4]},
                            {'class': '!btn-warning', 'type': 'stb', 'ids': [5]}                    
                        ],
                    },                               
                },
                {'hidden': True, 'type': 'card',  'order': 3, 'link_id': 1 },
                
            ],
            'overlay': False,
            'overlay_style': ''

        },
        {
            'id': 2, 'client': 'bahushira', 'page': 'home',
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': False, 'type': 'figure', 'order': 2, 
                    'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'spiderman', 'class': 'max-w-sm rounded-xl shadow-2xl'},  
                },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title':    {'class': '', 'type': 'stb', 'ids': [10]},
                    'contents': {'class': '', 'type': 'stb', 'ids': []},
                    'actions':  {'class': '', 'position': 'end',                        
                        'buttons': [
                            {'class': '!btn-primary', 'type': 'stb', 'ids': []},
                            {'class': '!btn-warning', 'type': 'stb', 'ids': []}                    
                        ],
                    },                               
                },
                {'hidden': True, 'type': 'card',  'order': 3, 'link_id': 1 },
                
            ],
            'overlay': False,
            'overlay_style': ''
        },        
        {
            'id': 3, 'client': 'bahushira', 'page': 'home',
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': False, 'type': 'figure', 'order': 2, 
                    'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'nike', 'class': 'max-w-sm rounded-xl shadow-2xl'},  
                },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title':    {'class': '', 'type': 'stb', 'ids': [11]},
                    'contents': {'class': '', 'type': 'stb', 'ids': []},
                    'actions':  {'class': '', 'position': 'end',                        
                        'buttons': [
                            {'class': '!btn-primary', 'type': 'stb', 'ids': []},
                            {'class': '!btn-warning', 'type': 'stb', 'ids': []}                    
                        ],
                    },                               
                },
                {'hidden': True, 'type': 'card',  'order': 3, 'link_id': 1 },
                
            ],
            'overlay': False,
            'overlay_style': ''
        },  
        {
            'id': 4, 'client': 'bahushira', 'page': 'home',
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': False, 'type': 'figure', 'order': 2, 
                    'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'spiderman', 'class': 'max-w-sm rounded-xl shadow-2xl'},  
                },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title':    {'class': '', 'type': 'stb', 'ids': [12]},
                    'contents': {'class': '', 'type': 'stb', 'ids': []},
                    'actions':  {'class': '', 'position': 'end',                        
                        'buttons': [
                            {'class': '!btn-primary', 'type': 'stb', 'ids': []},
                            {'class': '!btn-warning', 'type': 'stb', 'ids': []}                    
                        ],
                    },                               
                },
                {'hidden': True, 'type': 'card',  'order': 3, 'link_id': 1 },
                
            ],
            'overlay': False,
            'overlay_style': ''
        },           
]

site_accordions = [
            {
            'id': 1, 'client': 'ABC123', 'page': 'home',
            'classjoin': 'join join-vertical bg-base-100',
            'class': 'collapse-plus join-item',
            'accordioncontents': [
                {
                    'order': 1,
                    'title': {'class': '', 'type': 'text', 'ids': ['acctit1']},
                    'contents': {'class': '', 'type': 'text', 'ids': ['acctxt1'] },
                },
                {
                    'order': 2,
                    'title': {'class': '', 'type': 'text', 'ids': ['acctit2']},
                    'contents': {'class': '', 'type': 'text', 'ids': ['acctxt2'] },
                },                
                {
                    'order': 3,
                    'title': {'class': '', 'type': 'text', 'ids': ['acctit3']},
                    'contents': {'class': '', 'type': 'text', 'ids': ['acctxt3'] },
                },                                
            ]
            },
]

site_carousals = [
            {
            'id': 1, 'client': 'ABC123', 'page': 'home',
            'class_carousal': 'w-full', 'class_item': '', 
            'prev_next': {
                'hidden': False,
                'class_anchor': '',
                'class_item': '',
                'prev' : {'class': '', 'mark': ''},
                'next' : {'class': '', 'mark': ''},
            },

            'carousalitems': [
                {
                    'order': 3,
                    'class': '',
                    'contents': {'class': '', 'type': 'img', 'link_id': 'nike' },
                },
                {
                    'order': 2,
                    'class': '',
                    'contents': {'class': '', 'type': 'img', 'link_id': 'spiderman' },
                },
                {
                    'order': 1,
                    'class': '',
                    'contents': {'class': '', 'type': 'img', 'link_id': 'daisy1' },
                },                
            ]
            },
]

# Options for accordions.class = collapse-plus/ collapse-arrow
# joinitem is not working as per daisyui

# Presently class in stbs is not used anywhere. To be evaluated for future use
site_stbs = [
    {'id': 1, 'client': 'ABC123', 
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycard' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 2, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},            
    {'id': 3, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 4, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'buynow' },
            ]},            
    {'id': 5, 'client': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},
    {'id': 6, 'client': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},     
    {'id': 7, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'myhero' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},     
    {'id': 8, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 9, 'client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},   
    {'id': 10, 'client': 'bahushira',
     'items': [
            {'order': 2, 'type': 'text', 'class': '', 'link_id': '01_01_01_01_title' },
            ]},                         
    {'id': 11, 'client': 'bahushira',
     'items': [
            {'order': 2, 'type': 'text', 'class': '', 'link_id': '01_01_01_01_title' },
            ]},                         
    {'id': 12, 'client': 'bahushira',
     'items': [
            {'order': 2, 'type': 'text', 'class': '', 'link_id': '01_01_01_01_title' },
            ]},                                     
]



raw_svgs = [
            {
            'id': 'like', 'client': 'ABC123', 'page': 'home',
            'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'
            },
]
raw_images = [
            {
            'id': 'nike', 'client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes',
            },
            {
            'id': 'spiderman', 'client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp', 'alt': 'spiderman',
            },
            {
            'id': 'daisy1', 'client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1625726411847-8cbb60cc71e6.webp', 'alt': 'daisy1',
            }                                    
]
 
# Assuming url of form path("<int:pk>/<str:page>/", ClientPageView.as_view(), name="client_page")
class ClientPageView(TemplateView):
    template_name = 'base.html'
    """
    def get(self, request, *args, **kwargs):
        lv_client_id = self.kwargs['pkey']
        lv_page_id = self.kwargs['page']
    """    
        
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add any common context data here that all views need
        lv_client_id = self.kwargs.get("pkey")   # <-- get it from URL
        lv_page_id = self.kwargs.get('page')
        
        if not lv_client_id:
            lv_client_id = 'bahushira'

        if not lv_page_id:
            lv_page_id = 'home'

        client_static = fetch_clientstatic(lv_client_id=lv_client_id)
        """
        # refactored to get all static data in one go and cache the sql call

        """
        #client_nb_items = client_static['client_nb_items']
        
        client_nb_items_nested = client_static['client_nb_items_nested']        
        nb = {}
        nb['items_nested'] = client_nb_items_nested
        nb['logo']="mylogo" 
        nb['title']={'class': '', 'type': 'text', 'ids': ['nb_title']} 
        context['texts_static_dict'] = client_static['texts_static_dict'] 

        context["client_id"] = lv_client_id
        context["client_hierarchy_list"] = client_static['client_hierarchy_list']
        context["client_hierarchy_str"] = ','.join(client_static['client_hierarchy_list'])        

        context["client_language_ids"] = client_static['client_language_ids']
        context["client_theme_ids"] = client_static['client_theme_ids']
        context['nb'] = nb
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        context['raw_svgs'] = raw_svgs
        context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs    
        context['site_accordions'] = site_accordions
        context['site_carousals'] = site_carousals

        site_structure_filtered = list(filter(lambda item: item.get('client') in client_static['client_hierarchy_list'] and not item.get('hidden'), site_structure))

        # filter page_structure based on lv_page_id
        context['page_structure'] = list(filter(lambda item: item.get('page')==lv_page_id, site_structure_filtered))

        return context


    

