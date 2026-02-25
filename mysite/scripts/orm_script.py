#from mysite.models import TokenType
#from mysite.models import Token
from mysite.models import Language
from mysite.models import ThemePreset


from mysite.models import Client
from mysite.models import Page
from mysite.models import Theme
from mysite.models import Layout
#from mysite.models import ClientLanguage
#from mysite.models import ClientTheme
#from mysite.models import ClientPage
#from mysite.models import TextStatic
#from mysite.models import Image
#from mysite.models import Svg

#from mysite.models import Position

from django.contrib.contenttypes.models import ContentType
from django.apps import apps

#from mysite.models import TextItemValue

#from django.db.models import F, Case, When
from django.utils import timezone
from django.db import connection
from django.db.models.functions import Lower

from pprint import pprint

def run():
    #lv_client_id = 'bahushira'
    #result = ClientLanguage.objects.filter(client_id="bahushira").order_by("-order").values_list('language_id', flat=True)
    #result = ClientLanguage.objects.filter(client_id='bahushira').values_list('language_id', flat=True).order_by('order')
    #print(connection.queries)    
    #result = ClientNavbar.objects.filter(client_id=lv_client_id).values('id', 'page_id', 'parent', 'order').order_by('order')
    #print(result)
    #print(result.exists())
    #print(client.first())
    #pprint(connection.queries)

    # print("Hello from runscript")
    """
        LANGUAGE_DATA = [
            {
            "language_id": "en",
            "label_obj": {"en": "English", "fr": "frEnglish", "hi": "hiEnglish"}
            },
            {
            "language_id": "fr",
            "label_obj": {"en": "French", "fr": "frFrench", "hi": "hiFrench"}
            },
            {
            "language_id": "hi",
            "label_obj": {"en": "Hindi", "fr": "frHindi", "hi": "hiHindi"}
            }
        ]
        for row in LANGUAGE_DATA:
            Language.objects.update_or_create(
                language_id=row["language_id"],
                label_obj= row["label_obj"]
            )    

        THEME_DATA = [
            {
            "theme_id": "light",
            "label_obj": {"en": "Light", "fr": "frLight", "hi": "hiLight"}
            },
            {
            "theme_id": "dark",
            "label_obj": {"en": "Dark", "fr": "frDark", "hi": "hiDark"}
            },
            {
            "theme_id": "aqua",
            "label_obj": {"en": "Aqua", "fr": "frAqua", "hi": "hiAqua"}
            }
        ]
        for row in THEME_DATA:
            Theme.objects.update_or_create(
                theme_id=row["theme_id"],
                label_obj= row["label_obj"]
            )    

        CLIENT_DATA = [
            {
            "client_id": "bahushira"
            }
        ]
        for row in CLIENT_DATA:
            Client.objects.update_or_create(
                client_id=row["client_id"]
            )    
    """
    """
        PAGE_DATA = [
            {
            "client_id": "bahushira",
            "page_id" : "home",
            "ltext": "Home",
            "parent_id": "",
            "order": 1, 
            "hidden": False
            },
            {
            "client_id": "bahushira",
            "page_id" : "about",
            "ltext": "About",
            "parent_id": "",
            "order": 2, 
            "hidden": False
            },        
            {
            "client_id": "bahushira",
            "page_id" : "team",
            "ltext": "Team",
            "parent_id": "",
            "order": 3, 
            "hidden": False
            },        
            {
            "client_id": "bahushira",
            "page_id" : "contact",
            "ltext": "Contact",
            "parent_id": "team",
            "order": 4,
            "hidden": False
            }
        ]

        clients = {c.client_id: c for c in Client.objects.all()}
        # this may not update the currently created page
        #pages = {c.page_id: c for c in Page.objects.all()}
        for row in PAGE_DATA:
            # Calculate the parent value using Python logic
            if row["parent_id"] != "":
                # Get the related Page2 object instance from the 'pages' dictionary
                #parent_value = pages[row["parent_id"]]
                parent_value = Page.objects.get(client.client_id = row["client_id"], page_id=row["parent_id"])
                
            else:
                # Set to None if there is no parent_id, which corresponds to the null value in the database
                parent_value = None

            client_value = clients[row["client_id"]]

            Page.objects.update_or_create(
                client = client_value,
                page_id=row["page_id"],
                ltext=row["ltext"],
                parent= parent_value,
                order=row["order"],
                hidden=row["hidden"],
            ) 

                    
    

        LAYOUT_DATA = [
        {
        "client_id": "bahushira",
        "page_id" : "home",
        "parent_slug": "",
        "order": 1, 
        "level": 10,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },        
        {
        "client_id": "bahushira",
        "page_id" : "home",
        "parent_slug": "a",
        "order": 1, 
        "level": 20,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },
        {
        "client_id": "bahushira",
        "page_id" : "home",
        "parent_slug": "a",
        "order": 1, 
        "level": 30,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },
        {
        "client_id": "bahushira",
        "page_id" : "home",
        "parent_slug": "a",
        "order": 1, 
        "level": 40,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "hero",
        }                
    ]
    """
    # Layout of Contact
    LAYOUT_DATA = [
        {
        "client_id": "bahushira",
        "page_id" : "contact",
        "parent_slug": "",
        "order": 1, 
        "level": 10,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },        
        {
        "client_id": "bahushira",
        "page_id" : "contact",
        "parent_slug": "a",
        "order": 1, 
        "level": 20,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },
        {
        "client_id": "bahushira",
        "page_id" : "contact",
        "parent_slug": "a",
        "order": 1, 
        "level": 30,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "",
        },
        {
        "client_id": "bahushira",
        "page_id" : "contact",
        "parent_slug": "a",
        "order": 1, 
        "level": 40,
        "css_class": "",
        "style": "",
        "hidden": False,
        "slug" : "a",
        "comp_id": "hero",
        }                
    ]    
    
    clients = {c.client_id: c for c in Client.objects.all()}
    pages = {(c.client.client_id, c.page_id): c for c in Page.objects.all()}
    #layouts = {(c.client.client_id, c.page.page_id, c.slug, c.level): c for c in Layout.objects.all()}

    for row in LAYOUT_DATA:

        client_value = clients[row["client_id"]]
        #page_value = pages.get((row["client_id"], row["page_id"]))
        page_value = pages[(row["client_id"], row["page_id"])]
        # Calculate the parent value using Python logic
        if row["parent_slug"] != "":
            # Get the related Layout object instance from the 'layouts' dictionary
            #parent_value = layouts.get((row["client_id"], row["page_id"], row["parent_slug"], row["level"]-10))
            # in the above code only the first row gets updated correctly. so we may have to update one row at a time
            parent_value = Layout.objects.get(client=client_value, page=page_value, slug= row["parent_slug"], level=row["level"]-10)
        else:
            # Set to None if there is no parent_id, which corresponds to the null value in the database
            parent_value = None



        Layout.objects.update_or_create(
            client = client_value,
            page = page_value,
            parent= parent_value,
            order=row["order"],
            level=row["level"],
            css_class=row["css_class"],
            style=row["style"],
            hidden=row["hidden"],
            slug=row["slug"],
            comp_id=row["comp_id"],
        ) 

    # Hero of Contact slug=a
    # DROPPING THIS . BELOW LAYOUT TO BE MAINTAINED DIRECTLY IN DJANGO ADMIN.
    # BUILDING THE LINKS LOOKS COMPLICATED AS IT IS MULTI LEVEL
    # POSTPONING THIS TYPE OF MASS UPLOAD 
    """
    HERO_DATA = [
        {
        "client_id": "bahushira",
        "page_id" : "contact",
        "layout_slug": "a",
        "layout_level": 40,
        "layout_comp_id": "hero",
        "css_class": "",
        "herocontent_class": "",
        "overlay": "",
        "overlay_style": "",
        "comp_id": "",
        }, 
    ]
    """
    """        
        THEMEPRESET_DATA = [
            {
            "themepreset_id": "light",
            "ltext": "a",
            "primary": "#570df8",
            "primary_content": "#ffffff",

            "secondary": "#f000b8",
            "secondary_content": "#ffffff",

            "accent": "#37cdbe",
            "accent_content": "#163835",

            "neutral": "#3d4451",
            "neutral_content": "#ffffff",

            "base_100": "#ffffff",
            "base_200": "#f2f2f2",
            "base_300": "#e5e6e6",
            "base_content": "#1f2937",

            "success": "#00c853",
            "success_content": "#ffffff",

            "warning": "#ff9800",
            "warning_content": "#ffffff",

            "error": "#ff5724",
            "error_content": "#ffffff",

            "info": "#2094f3",
            "info_content": "#ffffff"
            },   
            {
            "themepreset_id": "dark",
            "ltext": "b",
            "primary": "#661ae6",
            "primary_content": "#ffffff",

            "secondary": "#d926aa",
            "secondary_content": "#ffffff",

            "accent": "#1fb2a6",
            "accent_content": "#ffffff",

            "neutral": "#191d24",
            "neutral_content": "#a6adbb",

            "base_100": "#2a303c",
            "base_200": "#242933",
            "base_300": "#1d232a",
            "base_content": "#a6adbb",

            "success": "#36d399",
            "success_content": "#000000",

            "warning": "#fbbd23",
            "warning_content": "#000000",

            "error": "#f87272",
            "error_content": "#000000",

            "info": "#3abff8",
            "info_content": "#000000"
            },              
                
        ]


        for row in THEMEPRESET_DATA:

            ThemePreset.objects.update_or_create(
                themepreset_id=row["themepreset_id"],
                ltext=row["ltext"],
                primary=row["primary"],
                primary_content=row["primary_content"],

                secondary=row["secondary"],
                secondary_content=row["secondary_content"],

                accent=row["accent"],
                accent_content=row["accent_content"],

                neutral=row["neutral"],
                neutral_content=row["neutral_content"],

                base_100=row["base_100"],
                base_200=row["base_200"],
                base_300=row["base_300"],
                base_content=row["base_content"],

                success=row["success"],
                success_content=row["success_content"],

                warning=row["warning"],
                warning_content=row["warning_content"],

                error=row["error"],
                error_content=row["error_content"],

                info=row["info"],
                info_content=row["info_content"]
            ) 


        THEME_DATA = [
            {
            "client_id": "bahushira",
            "themepreset_id" : "light",
            "theme_id": "light",
            "is_default": False
            },        
            {
            "client_id": "bahushira",
            "themepreset_id" : "dark",
            "theme_id": "dark",
            "is_default": True
            },
        ]

        clients = {c.client_id: c for c in Client.objects.all()}
        themepresets = {c.themepreset_id: c for c in ThemePreset.objects.all()}
        #layouts = {(c.client.client_id, c.page.page_id, c.slug, c.level): c for c in Layout.objects.all()}

        for row in THEME_DATA:

            client_value = clients[row["client_id"]]
            themepreset_value = themepresets[row["themepreset_id"]]
    
            Theme.objects.update_or_create(
                client = client_value,
                themepreset = themepreset_value,
                theme_id=row["theme_id"],
                #overrides=row["overrides"],
                is_default=row["is_default"]
            ) 
    """