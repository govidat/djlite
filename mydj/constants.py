# These are Project Level Constants that can be pulled into settings.py and from there into any views

PC_NAVBAR_ITEMS = [
    {"level": 0, "parent_id": "", "id": "id1", "order": 3, "is_parent": False, "text": {"en": "Item1-en", "fr": "Item1-fr" }, "url": "url1"},
    {"level": 0, "parent_id": "", "id": "id2", "order": 2, "is_parent": False, "text": {"en": "Item2-en", "fr": "Item2-fr" }, "url": "url2"},
    {"level": 0, "parent_id": "", "id": "id3", "order": 1, "is_parent": True,  "text": {"en": "Item3-en", "fr": "Item3-fr" }, "url": "url3"},
    {"level": 1, "parent_id": "id3", "id": "id4", "order": 2, "is_parent": False, "text": {"en": "Item41-en", "fr": "Item41-fr" }, "url": "url41"},
    {"level": 1, "parent_id": "id3", "id": "id5", "order": 1, "is_parent": True, "text": {"en": "Item42-en", "fr": "Item42-fr" }, "url": "url42"},
    {"level": 2, "parent_id": "id5", "id": "id6", "order": 1, "is_parent": False, "text": {"en": "Item421-en", "fr": "Item421-fr" }, "url": "url421"},                        
    ]   

PC_THEMES = [
    {"id": "id1", "order": 3, "value": "light", "text": {"en": "Light", "fr": "Light-fr" }},
    {"id": "id2", "order": 2, "value": "dark",  "text": {"en": "Dark", "fr": "Dark-fr" }},
    {"id": "id3", "order": 1, "value": "aqua",  "text": {"en": "Aqua", "fr": "Aqua-fr"}},
    {"id": "id4", "order": 1, "value": "mytheme",  "text": {"en": "MyTheme", "fr": "MyTheme-fr"}},                
]

PC_LANGUAGES = [
    {"code": "en", "order": 3, "text": {"en": "English", "fr": "Anglais" }},
    {"code": "fr", "order": 2, "text": {"en": "French", "fr": "Francais" }},
#    {"code": "hi", "order": 1, "text": {"en": "Hindi", "fr": "Fr-Hindi" }},            
]

MY_ERROR_CODES = [
    {"code": "Z001", "text": {"en": "Value is not maintained"}},
    {"code": "Z002", "text": {"en": "Input is not a Dictionary Object"}},
]

SAMPLE_CARDS = {
    'class': 'flex flex-wrap gap-4',
    'cards': [
        {
            'order': 4,
            'class': 'card-lg',
            'body_class': 'items-center text-center',
            'title': {
                'class': '',
                'items':
            [
    {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
    {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'My Card', 'fr': 'frMy Card'} },
    {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'My Badge', 'fr': 'frMy Badge'} },
            ]
            },
            'contents': {
                'class': '', 
                'items': 
                    [
    [
    {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
    {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'SubTitle', 'fr': 'frSubTitle'} },
    {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'STB', 'fr': 'fSTB'} },
    ],
    [
    {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
    {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'} },
    {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'TxB', 'fr': 'fTxB'} },
    ],
                    ]
                },
            'actions': {
                'position': 'end', 
                'class': '', 
                'items': [
                    {'text': {'en': 'Buy Now', 'fr': 'frBuy'}, 'class': '!btn-primary'}, 
                    {'text': {'en': 'Call Us', 'fr': 'frCall'}, 'class': '!btn-warning'}
                    ]
                },
            'img': {'position': 'start', 'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes', 'class': 'rounded-xl'},
            'figure_class': 'px-0 pt-0',
        },
               
        ]
}

SAMPLE_HEROS = {
    'class': '',
    'heros': [
        {
            'order': 1,
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': True, 'type': 'image', 'order': 2, 'class': 'max-w-sm rounded-lg shadow-2xl', 'src': 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp' },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title': {
                        'class': '',
                        'items': [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'My Hero', 'fr': 'frMy Hero'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'My Badge', 'fr': 'frMy Badge'} },
                        ]
                    },
                    'contents': {
                        'class': '', 
                        'items': [
                            [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'SubTitle', 'fr': 'frSubTitle'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'STB', 'fr': 'fSTB'} },
                            ],
                            [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'A Hero Content has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA Hero content component has a figure, a body part, and inside body there are title and actions parts'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'TxB', 'fr': 'fTxB'} },
                            ],
                        ]
                    },
                    'buttons': {
                        'class':'', 
                        'items': [
                            {'order': 2, 'text': {'en': 'Buy Now'}, 'class': '!btn-primary',                  'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}, 
                            {'order': 1, 'text': {'en': 'Call Us'}, 'class': '!btn-warning flex-row-reverse', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}
                            ]                        
                    },
                                   
                },
                {'hidden': False, 'type': 'cards',  'order': 3, 
                    'cards': {
                        'class': '',
                        'cards': [
                            {
                                'order': 1,
                                'class': 'card-lg',
                                'body_class': 'items-center text-center',
                                'title': {
                                    'class': '',
                                    'items': [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'My Card', 'fr': 'frMy Card'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'My Badge', 'fr': 'frMy Badge'} },
                                    ]
                                },
                                'contents': {
                                    'class': '', 
                                    'items': [
                                        [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'SubTitle', 'fr': 'frSubTitle'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'STB', 'fr': 'fSTB'} },
                                        ],
                                        [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'TxB', 'fr': 'fTxB'} },
                                        ],
                                    ]
                                },
                                'actions': {
                                    'position': 'end', 
                                    'class': '', 
                                    'items': [
                                        {'text': {'en': 'Buy Now', 'fr': 'frBuy'}, 'class': '!btn-primary'}, 
                                        {'text': {'en': 'Call Us', 'fr': 'frCall'}, 'class': '!btn-warning'}
                                        ]
                                },
                                'img': {'position': 'start', 'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes', 'class': 'rounded-xl'},
                                'figure_class': 'px-0 pt-0',
                            },
                
                        ]
                    }
                },
                
            ],
            'overlay': False,
            'overlay_style': ''

        },
        {
            'order': 2,
            'class': '',
            'herocontent_class': '',
            'herocontents': [
                {'hidden': True, 'type': 'image', 'order': 2, 'class': 'max-w-sm rounded-lg shadow-2xl', 'src': 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp' },
                {'hidden': False, 'type': 'text',  'order': 1, 'class': '', 
                    'title': {
                        'class': '',
                        'items': [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'My Hero', 'fr': 'frMy Hero'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'My Badge', 'fr': 'frMy Badge'} },
                        ]
                    },
                    'contents': {
                        'class': '', 
                        'items': [
                            [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'SubTitle', 'fr': 'frSubTitle'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'STB', 'fr': 'fSTB'} },
                            ],
                            [
                            {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                            {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'A Hero Content has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA Hero content component has a figure, a body part, and inside body there are title and actions parts'} },
                            {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'TxB', 'fr': 'fTxB'} },
                            ],
                        ]
                    },
                    'buttons': {
                        'class':'', 
                        'items': [
                            {'order': 2, 'text': {'en': 'Buy Now'}, 'class': '!btn-primary',                  'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}, 
                            {'order': 1, 'text': {'en': 'Call Us'}, 'class': '!btn-warning flex-row-reverse', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}
                            ]                        
                    },
                                   
                },
                {'hidden': False, 'type': 'cards',  'order': 3, 
                    'cards': {
                        'class': '',
                        'cards': [
                            {
                                'order': 1,
                                'class': 'card-lg',
                                'body_class': 'items-center text-center',
                                'title': {
                                    'class': '',
                                    'items': [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'My Card', 'fr': 'frMy Card'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'My Badge', 'fr': 'frMy Badge'} },
                                    ]
                                },
                                'contents': {
                                    'class': '', 
                                    'items': [
                                        [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'SubTitle', 'fr': 'frSubTitle'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'STB', 'fr': 'fSTB'} },
                                        ],
                                        [
                                        {'order': 1, 'type': 'svg', 'class': '', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z' },
                                        {'order': 2, 'type': 'text', 'class': '', 'text': {'en': 'A card component has a figure, a body part, and inside body there are title and actions parts', 'fr': 'frA card component has a figure, a body part, and inside body there are title and actions parts'} },
                                        {'order': 3, 'type': 'badge', 'class': '', 'text': {'en': 'TxB', 'fr': 'fTxB'} },
                                        ],
                                    ]
                                },
                                'actions': {
                                    'position': 'end', 
                                    'class': '', 
                                    'items': [
                                        {'text': {'en': 'Buy Now', 'fr': 'frBuy'}, 'class': '!btn-primary'}, 
                                        {'text': {'en': 'Call Us', 'fr': 'frCall'}, 'class': '!btn-warning'}
                                        ]
                                },
                                'img': {'position': 'start', 'src': 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 'alt': 'shoes', 'class': 'rounded-xl'},
                                'figure_class': 'px-0 pt-0',
                            },
                
                        ]
                    }
                },
                
            ],
            'overlay': True,
            'overlay_style': 'background-image: url(https://img.daisyui.com/images/stock/photo-1507358522600-9f71e620c44e.webp);'

        },
    ]
}

"""
'buttons': {
                        'class':'', 
                        'items': [
                            {'order': 1, 'text': {'en': 'Buy Now'}, 'class': '!btn-primary',                  'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}, 
                            {'order': 2, 'text': {'en': 'Call Us'}, 'class': '!btn-warning flex-row-reverse', 'svg': 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z'}
                            ]
                    }  
"""                    