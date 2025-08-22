from django.shortcuts import render

# Create your views here.
# Create your views here.
from django.shortcuts import render # new
from django.views.generic import TemplateView
from django.utils.timezone import localtime, now
from django.utils.translation import get_language
from django.conf import settings

project_base_language = settings.LANGUAGE_CODE   # 'en'

def build_nested_hierarchy(flat_list):
    # Create a dictionary for quick lookup of items by their ID
    item_map = {item['id']: item for item in flat_list}

    # Initialize a list to store the top-level items (roots)
    nested_list = []

    # Iterate through each item to build the hierarchy
    for item in flat_list:
        parent_id = item.get('parent_id')

        # If the item has a parent, add it to the parent's children list
        if parent_id is not None and parent_id in item_map:
            parent_item = item_map[parent_id]
            if 'children' not in parent_item:
                parent_item['children'] = []
            parent_item['children'].append(item)
        # If the item has no parent, it's a top-level item
        else:
            nested_list.append(item)

    return nested_list

nb_items = settings.PC_NAVBAR_ITEMS

items_nested = build_nested_hierarchy(nb_items)

allowed_themes = settings.PC_THEMES

allowed_languages = settings.PC_LANGUAGES

cards = settings.SAMPLE_CARDS
# filtered_data = list(filter(lambda item: not item.get('is_active'), data))
heros = settings.SAMPLE_HEROS
site_structure = [
    {
    'id': 1,'parent_id': None, 'type': 'Full', 'page': 'home', 'client_id': 'ABC123',
    'class10': '', 'style10': "background-image: url('https://via.placeholder.com/1920x1080');",
    'children': [2, 3, 4] 
    },
    {
    'id': 2,'parent_id': 1, 'order': 1, 'type': 'FullScreen', 'page': 'home', 'client_id': 'ABC123',
    'class20': '', 'style20': '',
    'class30': 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3', 'style30': '',
    'children': [5, 6, 7] 
    },
    {
    'id': 3,'parent_id': 1, 'order': 2, 'type': 'FullScreen', 'page': 'home', 'client_id': 'ABC123',
    'class20': '', 'style20': '',
    'class30': '', 'style30': '',
    'children': [8] 
    },
    {
    'id': 4,'parent_id': 1, 'order': 3, 'type': 'FullScreen', 'page': 'home', 'client_id': 'ABC123',
    'class20': '', 'style20': '',
    'class30': '', 'style30': '',
    'children': [] 
    },    
    {
    'id': 5,'parent_id': 2, 'order': 1, 'type': 'Card', 'link_id': 1, 'page': 'home', 'client_id': 'ABC123',
    'class40': '', 'style40': '',
    'children': [] 
    },
    {
    'id': 6,'parent_id': 2, 'order': 1, 'type': 'Card', 'link_id': 1, 'page': 'home', 'client_id': 'ABC123',
    'class40': '', 'style40': '',
    'children': [] 
    },
    {
    'id': 7,'parent_id': 2, 'order': 1, 'type': 'Card', 'link_id': 1, 'page': 'home', 'client_id': 'ABC123',
    'class40': '', 'style40': '',
    'children': [] 
    }, 
    {
    'id': 8,'parent_id': 3, 'order': 1, 'type': 'Hero', 'link_id': 1, 'page': 'home', 'client_id': 'ABC123',
    'class40': '', 'style40': '',
    'children': [] 
    },                        
]

site_cards = [
            {
            'id': 1, 'client_id': 'ABC123', 'page': 'home',
            'class': 'card-lg',
            'body_class': 'items-center text-center',
            'title': {'class': '', 'stb_ids': [1]},
            'contents': {'class': '', 'stb_ids': [2, 3] },
            'actions': {'class': '', 'position': 'end', 
                'buttons': [
                    {'class': '!btn-primary', 'stb_ids': [4]},
                    {'class': '!btn-warning', 'stb_ids': [5]}                    
                ],
            },
            'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'nike', 'class': 'rounded-xl'},
            },
]

site_heros = [
        
        {
            'id': 1, 'client_id': 'ABC123', 'page': 'home',
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': True, 'type': 'figure', 'order': 2, 
                    'figure': {'figure_class': 'px-0 pt-0', 'position': 'start', 'link_id': 'spiderman', 'class': 'max-w-sm rounded-xl shadow-2xl'},  
                },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title':    {'class': '', 'stb_ids': [7]},
                    'contents': {'class': '', 'stb_ids': [8, 9]},
                    'actions':  {'class': '', 'position': 'end',                        
                        'buttons': [
                            {'class': '!btn-primary', 'stb_ids': [4]},
                            {'class': '!btn-warning', 'stb_ids': [5]}                    
                        ],
                    },                               
                },
                {'hidden': False, 'type': 'card',  'order': 3, 'link_id': 1 },
                
            ],
            'overlay': False,
            'overlay_style': ''

        },
 
]

site_stbs = [
    {'id': 1, 'client_id': 'ABC123', 
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycard' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 2, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},            
    {'id': 3, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 4, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'buynow' },
            ]},            
    {'id': 5, 'client_id': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},
    {'id': 6, 'client_id': 'ABC123',
     'items': [
            {'order': 2, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 1, 'type': 'text', 'class': '', 'link_id': 'callus' },
            ]},     
    {'id': 7, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'myhero' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},     
    {'id': 8, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mysubtitle' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},
    {'id': 9, 'client_id': 'ABC123',
     'items': [
            {'order': 1, 'type': 'svg', 'class': '', 'link_id': 'like' },
            {'order': 2, 'type': 'text', 'class': '', 'link_id': 'mycardtext' },
            {'order': 3, 'type': 'badge', 'class': '', 'link_id': 'mybadge' },
            ]},            

]
raw_texts = [
            {'id': 'mycard', 'client_id': 'ZZZ999', 'text': {'en': 'BahCard', 'fr': 'frMy Card'}},
            {'id': 'mycard', 'client_id': 'ABC123', 'text': {'en': 'My Card', 'fr': 'frMy Card'}},
            {'id': 'mybadge', 'client_id': 'ABC123', 'text': {'en': 'My Badge2', 'fr': 'frMy Badge'}},
            {'id': 'mysubtitle', 'client_id': 'ABC123', 'text': {'en': 'My Subtitle', 'fr': 'frMy Subtitle'}},
            {'id': 'mycardtext', 'client_id': 'ABC123', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'}},
            {'id': 'buynow', 'client_id': 'ABC123', 'text': {'en': 'Buy Now', 'fr': 'frBuy'}},
            {'id': 'callus', 'client_id': 'ABC123', 'text': {'en': 'Call Us', 'fr': 'frCall'}},
            {'id': 'myhero', 'client_id': 'ABC123', 'text': {'en': 'My Hero', 'fr': 'frMy Hero'}},            
]

# we can have texts of mother site like bahushira with a client id of ZZZ999 and that of ABC123. 
# Then sort the teaxt in ascending order. If a text is available for ABC123, then it will be picked first. 
# If not ZZZ999 text will be picked.
#sorted_by_age = sorted(data, key=lambda x: x['age']) ; max-w-sm rounded-lg shadow-2xl


raw_svgs = [
            {
            'id': 'like', 'client_id': 'ABC123', 'page': 'home',
            'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'
            },
]
raw_images = [
            {
            'id': 'nike', 'client_id': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes',
            },
            {
            'id': 'spiderman', 'client_id': 'ABC123', 'page': 'home',
            'src': 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp', 'alt': 'spiderman',
            }            
]

nb = {}
nb['items_nested']=items_nested
nb['logo']="mylogo" 
nb['title']="My Django Core Lite"

zroot = {}
zclient = {}

#zroot['current_language'] = get_language()
zroot['counts'] = [1,4]
zroot['current_time'] = localtime(now())

zclient['allowed_themes']=allowed_themes
zclient['allowed_languages']=allowed_languages

class HomeZappView(TemplateView):
    template_name = 'zapp/homezappv2.html'
# for adding some additional context
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context['nb'] = nb
        context['zroot'] = zroot
        context['zclient'] = zclient
        context['cards'] = cards
        context['heros'] = heros
        # filtered_data = list(filter(lambda item: not item.get('is_active'), data))
        context['page_structure'] = list(filter(lambda item: item.get('page')=='home', site_structure))
        context['site_cards'] = site_cards
        context['site_heros'] = site_heros        
        context['raw_texts'] = sorted(raw_texts, key=lambda x: x['client_id'])
        context['raw_svgs'] = raw_svgs
        context['raw_images'] = raw_images  
        context['site_stbs'] = site_stbs              
        return context

def home_zapp_fbv(request): # new
    context = {}
    context['nb'] = nb
    context['zroot'] = zroot
    context['zclient'] = zclient
    context['cards'] = cards
    context['heros'] = heros
    return render(request, 'zapp/homezapp.html', context)
