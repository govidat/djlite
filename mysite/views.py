from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
#from django.utils.timezone import localtime, now
from django.utils.translation import get_language
from django.conf import settings
from django.shortcuts import get_object_or_404

from .models import Client, ClientLanguage, ClientTheme

from utils.common_functions import build_nested_hierarchy, update_list_of_dictionaries, fetch_translations

project_base_language = settings.LANGUAGE_CODE   # 'en'


site_structure = [
    {
    'id':  1, 'parent': None, 'order': 1, 'level': 10, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': "background-image: url('https://via.placeholder.com/1920x1080');",
    'hidden': False 
    },
    {
    'id':  2, 'parent': 1, 'order': 3, 'level': 20, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id': 12,'parent': 2, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'client': 'ABC123',
    'class': 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3', 'style': '',
    'hidden': False  
    },    
    {
    'id':  3, 'parent': 1, 'order': 2, 'level': 20, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id': 13,'parent': 3, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id':  4, 'parent': 1, 'order': 1, 'level': 20, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id': 14,'parent': 4, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },        
    {
    'id': 10, 'parent': 1, 'order': 4, 'level': 20, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id': 15,'parent': 10, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    

    {
    'id':  5,'parent': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id':  6,'parent': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },
    {
    'id':  7,'parent': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    }, 
    {
    'id':  8,'parent': 13, 'order': 1, 'level': 40, 'type': 'hero', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },                        
    {
    'id':  9,'parent': 14, 'order': 1, 'level': 40, 'type': 'accordion', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },  
    {
    'id': 11,'parent': 15, 'order': 1, 'level': 40, 'type': 'carousal', 'link_id': 1, 'page': 'home', 'client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },     
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
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'l_home_title_01' },
            ]},                         
    {'id': 11, 'client': 'bahushira',
     'items': [
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'l_about_title_01' },
            ]},                         
    {'id': 12, 'client': 'bahushira',
     'items': [
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'l_contact_title_01' },
            ]},                                     
]
"""
raw_texts = [
            {'token': 'mycard', 'client': 'ZZZ999', 'text': {'en': 'BahCard', 'fr': 'frMy Card'}},
            {'token': 'mycard', 'client': 'ABC123', 'text': {'en': 'My Card', 'fr': 'frMy Card'}},
            {'token': 'mybadge', 'client': 'ABC123', 'text': {'en': 'My Badge2', 'fr': 'frMy Badge'}},
            {'token': 'mysubtitle', 'client': 'ABC123', 'text': {'en': 'My Subtitle', 'fr': 'frMy Subtitle'}},
            {'token': 'mycardtext', 'client': 'ABC123', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'}},
            {'token': 'buynow', 'client': 'ABC123', 'text': {'en': 'Buy Now', 'fr': 'frBuy'}},
            {'token': 'callus', 'client': 'ABC123', 'text': {'en': 'Call Us', 'fr': 'frCall'}},
            {'token': 'myhero', 'client': 'ABC123', 'text': {'en': 'My Hero', 'fr': 'frMy Hero'}},            
            {'token': 'acctit1', 'client': 'ABC123', 'text': {'en': 'How do I create an account?', 'fr': 'frHow do I create an account?'}},            
            {'token': 'acctxt1', 'client': 'ABC123', 'text': {'en': 'Click the "Sign Up" button in the top right corner and follow the registration process.', 'fr': 'frClick the "Sign Up" button in the top right corner and follow the registration process.'}},            
            {'token': 'acctit2', 'client': 'ABC123', 'text': {'en': 'I forgot my password. What should I do?', 'fr': 'frI forgot my password. What should I do?'}},            
            {'token': 'acctxt2', 'client': 'ABC123', 'text': {'en': 'Click on "Forgot Password" on the login page and follow the instructions sent to your email.', 'fr': 'frClick on "Forgot Password" on the login page and follow the instructions sent to your email.'}},            
            {'token': 'acctit3', 'client': 'ABC123', 'text': {'en': 'How do I update my profile information?', 'fr': 'frHow do I update my profile information?'}},            
            {'token': 'acctxt3', 'client': 'ABC123', 'text': {'en': 'Go to "My Account" settings and select "Edit Profile" to make changes.', 'fr': 'frGo to "My Account" settings and select "Edit Profile" to make changes.'}},            
            {'token': 'g_nb_title', 'client': 'ABC123', 'text': {'en': 'v2My Django Core Lite-Client', 'fr': 'frV2My Django Core Lite-Client'}},
            {'token': 'g_nb_title', 'client': 'default', 'text': {'en': 'Default', 'fr': 'frDefault'}},
            {'token': 'g_nb_title', 'client': 'bahushira', 'text': {'en': 'Bahushira', 'fr': 'frBahushira'}},
            {'token': 'l_home_title_01', 'client': 'bahushira', 'text': {'en': 'Welcome to Bahushira Home Page', 'fr': 'frWelcome to Bahushira Home Page'}},            
            {'token': 'l_about_title_01', 'client': 'bahushira', 'text': {'en': 'About Bahushira', 'fr': 'frAbout Bahushira'}},                        
            {'token': 'l_contact_title_01', 'client': 'bahushira', 'text': {'en': 'Contact Bahushira', 'fr': 'frContact Bahushira'}},                                    
            {'token': 'l_home_title_01', 'client': 'default', 'text': {'en': 'Welcome to Default Home Page', 'fr': 'frWelcome to Default Home Page'}},            
]
"""


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
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add any common context data here that both views need
        pkey = self.kwargs.get("pkey")   # <-- get it from URL
        page = self.kwargs.get('page')

        if pkey:
            client = pkey
        else:
            client = 'bahushira'  # Default root client
            # data = SomeModel.objects.filter(client=pkey)
            # context["data"] = data
        # else:
            # context["data"] = SomeModel.objects.all()

        if not page:
            page = 'home'

       # pk is the client from URL
        client = get_object_or_404(Client, pk=pkey)

        # Fetch related many-to-many values
        # ordered languages
        client_language_ids = client.get_ordered_language_ids()
        # ordered themes
        client_theme_ids = client.get_ordered_theme_ids()
        client_hierarchy_list = [client.id]
        client_hierarchy_list.append('default')


        client_nb_items = [
            {"id": "home", "parent": "",      "order": 1, 'text': {'en': 'Home', 'fr': 'frHome', 'hi': 'hiHome'}},
            {"id": "about", "parent": "",      "order": 2, 'text': {'en': 'About', 'fr': 'frAbout', 'hi': 'hiAbout'}},
            {"id": "contact", "parent": "team",      "order": 2, 'text': {'en': 'Contact', 'fr': 'frContact', 'hi': 'hiContact'}},
            {"id": "team", "parent": "",      "order": 3, 'text': {'en': 'Team', 'fr': 'frTeam', 'hi': 'hiTeam'}},    
            #{"id": "id4", "parent": "id3",   "order": 2},
            #{"id": "id5", "parent": "id3",   "order": 1},
            #{"id": "id6", "parent": "id5",   "order": 1},     
        ]
        # the url values and text are updated from Project Constant PC_NAVBAR_ITEMS
        #client_nb_items_updated = update_list_of_dictionaries(client_nb_items, settings.PC_NAVBAR_ITEMS,'id')
        client_nb_items_nested = build_nested_hierarchy(client_nb_items)
        nb = {}
        nb['items_nested']=client_nb_items_nested
        nb['logo']="mylogo" 
        nb['title']={'class': '', 'type': 'text', 'ids': ['g_nb_title']} 
        raw_texts_v0 = settings.ROOT_TRANSLATION
        raw_texts_v1 = fetch_translations(client_ids=client_hierarchy_list, as_dict=False)
        raw_texts = raw_texts_v0 + raw_texts_v1
        #context['raw_texts_v1'] = raw_texts_v1
        context['raw_texts'] = raw_texts
        context["client"] = client
        context["client_hierarchy_list"] = client_hierarchy_list
        context["client_hierarchy_str"] = ','.join(client_hierarchy_list)        

        context["client_language_ids"] = client_language_ids
        context["client_theme_ids"] = client_theme_ids
        context['nb'] = nb
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        context['raw_svgs'] = raw_svgs
        context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs    
        context['site_accordions'] = site_accordions
        context['site_carousals'] = site_carousals

        site_structure_filtered = list(filter(lambda item: item.get('client') in client_hierarchy_list and not item.get('hidden'), site_structure))

        if page == 'about':
            context['page_structure'] = list(filter(lambda item: item.get('page')=='about', site_structure_filtered))    
        elif page == 'contact':
            context['page_structure'] = list(filter(lambda item: item.get('page')=='contact', site_structure_filtered))
        else:
            context['page_structure'] = list(filter(lambda item: item.get('page')=='home', site_structure_filtered))

        return context


class ZClientBaseView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add any common context data here that both views need
        pkey = self.kwargs.get("pkey")   # <-- get it from URL

        if pkey:
            client = pkey
        else:
            client = 'bahushira'  # Default root client
        # let us get the client theme ids and client languages in this step
        client_language_ids = ['en', 'fr']
        client_theme_ids = ['light', 'aqua', 'dark']
        # client hierarchy place holder. presently using just the client
        client_hierarchy_list = [client]
        client_hierarchy_list.append('default')

        client_nb_items = [
            {"id": "home", "parent": "",      "order": 1, 'text': {'en': 'Home', 'fr': 'frHome', 'hi': 'hiHome'}},
            {"id": "about", "parent": "",      "order": 1, 'text': {'en': 'About', 'fr': 'frAbout', 'hi': 'hiAbout'}},
            {"id": "contact", "parent": "",      "order": 2, 'text': {'en': 'Contact', 'fr': 'frContact', 'hi': 'hiContact'}},
            #{"id": "team", "parent": "",      "order": 3, 'text': {'en': 'Team', 'fr': 'frTeam', 'hi': 'hiTeam'}},                
            #{"id": "id4", "parent": "id3",   "order": 2},
            #{"id": "id5", "parent": "id3",   "order": 1},
            #{"id": "id6", "parent": "id5",   "order": 1},     
        ]
        # the url values and text are updated from Project Constant PC_NAVBAR_ITEMS
        #client_nb_items_updated = update_list_of_dictionaries(client_nb_items, settings.PC_NAVBAR_ITEMS,'id')
        client_nb_items_nested = build_nested_hierarchy(client_nb_items)
        nb = {}
        nb['items_nested']=client_nb_items_nested
        nb['logo']="mylogo" 
        nb['title']={'class': '', 'type': 'text', 'ids': ['g_nb_title']} 


        context["client"] = client
        context["client_hierarchy_list"] = client_hierarchy_list
        context["client_hierarchy_str"] = ','.join(client_hierarchy_list)        
#        context["client_allowed_languages"] = client_allowed_languages
#        context["client_allowed_themes"] = client_allowed_themes
        context["client_language_ids"] = client_language_ids
        context["client_theme_ids"] = client_theme_ids        
        context['nb'] = nb
        context['site_structure'] = list(filter(lambda item: item.get('client') in client_hierarchy_list and not item.get('hidden'), site_structure))
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        context['raw_svgs'] = raw_svgs
        context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs    
        context['site_accordions'] = site_accordions
        context['site_carousals'] = site_carousals

        return context

class ZHomeView(ZClientBaseView):
    template_name = 'base.html'
    #model = YourModel # Replace with your actual model

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add specific context for the home page
        context['page_structure'] = list(filter(lambda item: item.get('page')=='home', context['site_structure']))
        return context

class ZAboutView(ZClientBaseView):
    template_name = 'base.html'
    #model = YourModel # Replace with your actual model

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add specific context for the home page
        context['page_structure'] = list(filter(lambda item: item.get('page')=='about', context['site_structure']))
        return context    
    
class ZContactView(ZClientBaseView):
    template_name = 'base.html'
    #model = YourModel # Replace with your actual model

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Add specific context for the home page
        context['page_structure'] = list(filter(lambda item: item.get('page')=='contact', context['site_structure']))
        return context        

