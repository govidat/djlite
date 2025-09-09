from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
from django.utils.timezone import localtime, now
from django.utils.translation import get_language
from django.conf import settings

from utils.common_functions import build_nested_hierarchy, update_list_of_dictionaries

project_base_language = settings.LANGUAGE_CODE   # 'en'


site_structure = [
    {
    'id':  1, 'parent_id': None, 'order': 1, 'level': 10, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': "background-image: url('https://via.placeholder.com/1920x1080');",
    'hidden': False 
    },
    {
    'id':  2, 'parent_id': 1, 'order': 3, 'level': 20, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id': 12,'parent_id': 2, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'id_client': 'ABC123',
    'class': 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3', 'style': '',
    'hidden': False  
    },    
    {
    'id':  3, 'parent_id': 1, 'order': 2, 'level': 20, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id': 13,'parent_id': 3, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id':  4, 'parent_id': 1, 'order': 1, 'level': 20, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id': 14,'parent_id': 4, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },        
    {
    'id': 10, 'parent_id': 1, 'order': 4, 'level': 20, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    
    {
    'id': 15,'parent_id': 10, 'order': 1, 'level': 30, 'type': '', 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },    

    {
    'id':  5,'parent_id': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False  
    },
    {
    'id':  6,'parent_id': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },
    {
    'id':  7,'parent_id': 12, 'order': 1, 'level': 40, 'type': 'card', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    }, 
    {
    'id':  8,'parent_id': 13, 'order': 1, 'level': 40, 'type': 'hero', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },                        
    {
    'id':  9,'parent_id': 14, 'order': 1, 'level': 40, 'type': 'accordion', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },  
    {
    'id': 11,'parent_id': 15, 'order': 1, 'level': 40, 'type': 'carousal', 'link_id': 1, 'page': 'home', 'id_client': 'ABC123',
    'class': '', 'style': '',
    'hidden': False 
    },         
]

site_cards = [
            {
            'id': 1, 'id_client': 'ABC123', 'page': 'home',
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
            'id': 1, 'id_client': 'ABC123', 'page': 'home',
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
 
]

site_accordions = [
            {
            'id': 1, 'id_client': 'ABC123', 'page': 'home',
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
            'id': 1, 'id_client': 'ABC123', 'page': 'home',
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
    {'id': 1, 'id_client': 'ABC123', 
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycard' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 2, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},            
    {'id': 3, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 4, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'buynow' },
            ]},            
    {'id': 5, 'id_client': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},
    {'id': 6, 'id_client': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},     
    {'id': 7, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'myhero' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},     
    {'id': 8, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 9, 'id_client': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},            

]
raw_texts = [
            {'id': 'mycard', 'id_client': 'ZZZ999', 'text': {'en': 'BahCard', 'fr': 'frMy Card'}},
            {'id': 'mycard', 'id_client': 'ABC123', 'text': {'en': 'My Card', 'fr': 'frMy Card'}},
            {'id': 'mybadge', 'id_client': 'ABC123', 'text': {'en': 'My Badge2', 'fr': 'frMy Badge'}},
            {'id': 'mysubtitle', 'id_client': 'ABC123', 'text': {'en': 'My Subtitle', 'fr': 'frMy Subtitle'}},
            {'id': 'mycardtext', 'id_client': 'ABC123', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'}},
            {'id': 'buynow', 'id_client': 'ABC123', 'text': {'en': 'Buy Now', 'fr': 'frBuy'}},
            {'id': 'callus', 'id_client': 'ABC123', 'text': {'en': 'Call Us', 'fr': 'frCall'}},
            {'id': 'myhero', 'id_client': 'ABC123', 'text': {'en': 'My Hero', 'fr': 'frMy Hero'}},            
            {'id': 'acctit1', 'id_client': 'ABC123', 'text': {'en': 'How do I create an account?', 'fr': 'frHow do I create an account?'}},            
            {'id': 'acctxt1', 'id_client': 'ABC123', 'text': {'en': 'Click the "Sign Up" button in the top right corner and follow the registration process.', 'fr': 'frClick the "Sign Up" button in the top right corner and follow the registration process.'}},            
            {'id': 'acctit2', 'id_client': 'ABC123', 'text': {'en': 'I forgot my password. What should I do?', 'fr': 'frI forgot my password. What should I do?'}},            
            {'id': 'acctxt2', 'id_client': 'ABC123', 'text': {'en': 'Click on "Forgot Password" on the login page and follow the instructions sent to your email.', 'fr': 'frClick on "Forgot Password" on the login page and follow the instructions sent to your email.'}},            
            {'id': 'acctit3', 'id_client': 'ABC123', 'text': {'en': 'How do I update my profile information?', 'fr': 'frHow do I update my profile information?'}},            
            {'id': 'acctxt3', 'id_client': 'ABC123', 'text': {'en': 'Go to "My Account" settings and select "Edit Profile" to make changes.', 'fr': 'frGo to "My Account" settings and select "Edit Profile" to make changes.'}},            
            {'id': 'nb_title', 'id_client': 'ABC123', 'text': {'en': 'v2My Django Core Lite-Client', 'fr': 'frV2My Django Core Lite-Client'}},
]

# we can have texts of mother site like bahushira with a client id of ZZZ999 and that of ABC123. 
# Then sort the teaxt in ascending order. If a text is available for ABC123, then it will be picked first. 
# If not ZZZ999 text will be picked.
#sorted_by_age = sorted(data, key=lambda x: x['age']) ; max-w-sm rounded-lg shadow-2xl


raw_svgs = [
            {
            'id': 'like', 'id_client': 'ABC123', 'page': 'home',
            'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'
            },
]
raw_images = [
            {
            'id': 'nike', 'id_client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes',
            },
            {
            'id': 'spiderman', 'id_client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp', 'alt': 'spiderman',
            },
            {
            'id': 'daisy1', 'id_client': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1625726411847-8cbb60cc71e6.webp', 'alt': 'daisy1',
            }                                    
]


zroot = {}


#zroot['current_language'] = get_language()
zroot['counts'] = [1,4]
zroot['current_time'] = localtime(now())

# zclient['allowed_themes']=allowed_themes
# get the client
# zclient['allowed_languages']=allowed_languages

class HomeZappView(TemplateView):
    template_name = 'base.html'    
    # We are using the base in theme/base.html
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        pkey = self.kwargs.get("pkey")   # <-- get it from URL

        if pkey:
            id_client = pkey
        else:
            id_client = 'ZZZ999'  # Default root client
            # data = SomeModel.objects.filter(id_client=pkey)
            # context["data"] = data
        # else:
            # context["data"] = SomeModel.objects.all()
        # let us get the client theme ids and client languages in this step
        client_language_ids = ['en', 'fr']
        client_theme_ids = ['light', 'aqua', 'dark']
        zclient = {}
        zclient['allowed_languages'] = [d for d in settings.PC_LANGUAGES if d.get("id") in client_language_ids]
        zclient['allowed_themes'] = [d for d in settings.PC_THEMES if d.get("id") in client_theme_ids]

        client_nb_items = [
            {"id": "id1", "parent_id": "",      "order": 3},
            {"id": "id2", "parent_id": "",      "order": 2},
            {"id": "id3", "parent_id": "",      "order": 1},
            {"id": "id4", "parent_id": "id3",   "order": 2},
            {"id": "id5", "parent_id": "id3",   "order": 1},
            {"id": "id6", "parent_id": "id5",   "order": 1},     
        ]
        # the url values and text are updated from Project Constant PC_NAVBAR_ITEMS
        client_nb_items_updated = update_list_of_dictionaries(client_nb_items, settings.PC_NAVBAR_ITEMS,'id')
        client_nb_items_nested = build_nested_hierarchy(client_nb_items_updated)
        nb = {}
        nb['items_nested']=client_nb_items_nested
        nb['logo']="mylogo" 
        nb['title']={'class': '', 'type': 'text', 'ids': ['nb_title']} 



        context["id_client"] = id_client
        context['nb'] = nb
        context['zroot'] = zroot
        context['zclient'] = zclient
        # context['cards'] = cards
        # context['heros'] = heros
        # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
        context['page_structure'] = list(filter(lambda item: item.get('page')=='home' and not item.get('hidden'), site_structure))
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        context['raw_texts'] = sorted(raw_texts, key=lambda x: x['id_client'])
        context['raw_svgs'] = raw_svgs
        context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs    
        context['site_accordions'] = site_accordions
        context['site_carousals'] = site_carousals

        return context

def home_zapp_fbv(request, pkey=None): # new
    client = None
    # data = None

    if pkey:
        id_client = pkey
    else:
        id_client = 'ZZZ999'  # Default root client        
        # client = get_object_or_404(Client, pk=pkey)
        # data = SomeModel.objects.filter(id_client=pkey)
    #else:
        # fallback: maybe show default data or all data
        #data = SomeModel.objects.all()
    context = {}
    context['id_client'] = id_client
    context['nb'] = nb
    context['zroot'] = zroot
    #context['zclient'] = zclient
    # context['cards'] = cards
    # context['heros'] = heros
    return render(request, 'zapp/homezapp.html', context)
