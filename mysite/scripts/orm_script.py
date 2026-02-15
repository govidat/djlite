#from mysite.models import TokenType
#from mysite.models import Token
from mysite.models import Language
from mysite.models import Theme
from mysite.models import Page
from mysite.models import Client
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

from mysite.models import TextItemValue

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

          
                    

    TEXTITEMVALUE_DATA = [
        {
        "language_id": "en",
        "stext": "Bahushira",
        "ltext": "Bahushira Technologies LLP",
        "source_model": "Client",
        "source_field": "client_id",
        "row_value": "bahushira"
        },
        
        {
        "language_id": "fr",
        "stext": "Bahushira",
        "ltext": "frBahushira Technologies LLP",
        "source_model": "Client",
        "source_field": "client_id",
        "row_value": "bahushira"
        },        
        {
        "language_id": "hi",
        "stext": "Bahushira",
        "ltext": "Bahushira Technologies LLP",
        "source_model": "Client",
        "source_field": "client_id",
        "row_value": "bahushira"
        },        
        {
        "language_id": "en",
        "stext": "Home",
        "ltext": "Home",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "fr",
        "stext": "frHome",
        "ltext": "frHome",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "hi",
        "stext": "hiHome",
        "ltext": "hiHome",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "en",
        "stext": "About",
        "ltext": "About",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "fr",
        "stext": "frAbout",
        "ltext": "frAbout",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "hi",
        "stext": "hiAbout",
        "ltext": "hiAbout",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "en",
        "stext": "Team",
        "ltext": "Team",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "team"
        },                                                        
        {
        "language_id": "fr",
        "stext": "frTeam",
        "ltext": "frTeam",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "team"
        },                                                        
        {
        "language_id": "hi",
        "stext": "hiTeam",
        "ltext": "hiTeam",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "team"
        },
        {
        "language_id": "en",
        "stext": "Contact",
        "ltext": "Contact",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "contact"
        },                                                        
        {
        "language_id": "fr",
        "stext": "frContact",
        "ltext": "frContact",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "contact"
        },
        {
        "language_id": "hi",
        "stext": "hiContact",
        "ltext": "hiContact",
        "source_model": "Page",
        "source_field": "page_id",
        "row_value": "contact"
        }         
    ]    

    languages = {c.language_id: c for c in Language.objects.all()}
    content_types = {c.model: c for c in ContentType.objects.filter(app_label="mysite")}

    for row in TEXTITEMVALUE_DATA:
        lv_source_model_lower = row["source_model"].lower()
        
        # Define the model name and app label as variables
        app_label = 'mysite' # Replace with the actual name of your app
        model_name = row["source_model"] # Replace with the actual name of your model

        # Get the model class dynamically
        ModelClass = apps.get_model(app_label, model_name)

        # Now you can use the ModelClass just like a normal model
        try:
            lv_content_type_obj = ModelClass.objects.get(**{row["source_field"]: row["row_value"]})
            lv_object_id = lv_content_type_obj.id
            # or simply:
            # lv_content_type_id = ContentType.objects.get(app_label="my_site", model=lv_source_model_lower).id
        except ModelClass.DoesNotExist:
            # Handle the case where the content type is not found
            print(f"content_type_id not found.")
            lv_object_id = None # Or handle the error as appropriate for your application
        

        language_value = languages[row["language_id"]]
        content_type_value = content_types.get(lv_source_model_lower)
        #content_type_value = content_types[row[lv_source_model_lower]]

        TextItemValue.objects.update_or_create(
            language = language_value,
            stext=row["stext"],
            ltext=row["ltext"],
            object_id=lv_object_id,
            content_type = content_type_value            
        )    

        
    """ 

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

          