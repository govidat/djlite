from mysite.models import TokenType
from mysite.models import Token
from mysite.models import Language
from mysite.models import Theme
from mysite.models import Page
from mysite.models import Client
from mysite.models import ClientLanguage
from mysite.models import ClientTheme
#from mysite.models import ClientPage
from mysite.models import TextStatic
from mysite.models import Image
from mysite.models import Svg

#from mysite.models import Position

from django.contrib.contenttypes.models import ContentType
from django.apps import apps

from mysite.models import Language2
from mysite.models import Theme2
from mysite.models import Client2
from mysite.models import Page2
from mysite.models import TextItemValue2

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
    LANGUAGE2_DATA = [
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
    for row in LANGUAGE2_DATA:
        Language2.objects.update_or_create(
            language_id=row["language_id"],
            label_obj= row["label_obj"]
        )    

    THEME2_DATA = [
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
    for row in THEME2_DATA:
        Theme2.objects.update_or_create(
            theme_id=row["theme_id"],
            label_obj= row["label_obj"]
        )    

    CLIENT2_DATA = [
        {
        "client_id": "bahushira"
        }
    ]
    for row in CLIENT2_DATA:
        Client2.objects.update_or_create(
            client_id=row["client_id"]
        )    
    PAGE2_DATA = [
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
        "parent_id": "team"
        "order": 5, 
        "hidden": False
        }
    ]
 

    PAGE2_DATA = [
        {
        "client_id": "bahushira",
        "page_id" : "test",
        "ltext": "Test",
        "parent_id": "",
        "order": 7, 
        "hidden": False
        },
    ]    
    clients = {c.client_id: c for c in Client2.objects.all()}
    pages = {c.page_id: c for c in Page2.objects.all()}
    for row in PAGE2_DATA:
        # Calculate the parent value using Python logic
        if row["parent_id"] != "":
            # Get the related Page2 object instance from the 'pages' dictionary
            parent_value = pages[row["parent_id"]]
        else:
            # Set to None if there is no parent_id, which corresponds to the null value in the database
            parent_value = None

        client_value = clients[row["client_id"]]

        Page2.objects.update_or_create(
            client = client_value,
            page_id=row["page_id"],
            ltext=row["ltext"],
            parent= parent_value,
            order=row["order"],
            hidden=row["hidden"],
        ) 

                         
    """
    TEXTITEMVALUE2_DATA = [
        {
        "language_id": "en",
        "stext": "Bahushira",
        "ltext": "Bahushira Technologies LLP v2",
        "source_model": "Client2",
        "source_field": "client_id",
        "row_value": "bahushira"
        },
        {
        "language_id": "fr",
        "stext": "Bahushira",
        "ltext": "frBahushira Technologies LLP v2",
        "source_model": "Client2",
        "source_field": "client_id",
        "row_value": "bahushira"
        },        
        {
        "language_id": "hi",
        "stext": "Bahushira",
        "ltext": "Bahushira Technologies LLP v2",
        "source_model": "Client2",
        "source_field": "client_id",
        "row_value": "bahushira"
        },        
        {
        "language_id": "en",
        "stext": "Home",
        "ltext": "Homev2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "fr",
        "stext": "frHome",
        "ltext": "frHomev2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "hi",
        "stext": "hiHome",
        "ltext": "hiHomev2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "home"
        },        
        {
        "language_id": "en",
        "stext": "About",
        "ltext": "Aboutv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "fr",
        "stext": "frAbout",
        "ltext": "frAboutv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "hi",
        "stext": "hiAbout",
        "ltext": "hiAboutv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "about"
        },                                
        {
        "language_id": "en",
        "stext": "Team",
        "ltext": "Teamv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "team"
        },                                                        
        {
        "language_id": "fr",
        "stext": "frTeam",
        "ltext": "frTeamv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "team"
        },                                                        
        {
        "language_id": "hi",
        "stext": "hiTeam",
        "ltext": "hiTeamv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "team"
        },
        {
        "language_id": "en",
        "stext": "Contact",
        "ltext": "Contactv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "contact"
        },                                                        
        {
        "language_id": "fr",
        "stext": "frContact",
        "ltext": "frContactv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "contact"
        },
        {
        "language_id": "hi",
        "stext": "hiContact",
        "ltext": "hiContactv2",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "contact"
        },        
        {
        "language_id": "en",
        "stext": "test short text",
        "ltext": "Test Long Text",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "test"
        },
        {
        "language_id": "fr",
        "stext": "frtest short text",
        "ltext": "frTest Long Text",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "test"
        },
        {
        "language_id": "hi",
        "stext": "hitest short text",
        "ltext": "hiTest Long Text",
        "source_model": "Page2",
        "source_field": "page_id",
        "row_value": "test"
        }           
    ]    

    languages = {c.language_id: c for c in Language2.objects.all()}

    for row in TEXTITEMVALUE2_DATA:
        #lv_source_model_lower = row["source_model"].lower()
        #lv_content_type_id = ContentType.objects.filter(app_label = "my_site", model=lv_source_model_lower).first()['id']
        lv_source_model_lower = row["source_model"].lower()

        try:
            content_type_obj = ContentType.objects.get(app_label="mysite", model=lv_source_model_lower)
            lv_content_type_id = content_type_obj.id
            # or simply:
            # lv_content_type_id = ContentType.objects.get(app_label="my_site", model=lv_source_model_lower).id
        except ContentType.DoesNotExist:
            # Handle the case where the content type is not found
            print(f"Content type for model {lv_source_model_lower} in app my_site not found.")
            lv_content_type_id = None # Or handle the error as appropriate for your application

            #print(f"content_type_id - {lv_content_type_id}")
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

        TextItemValue2.objects.update_or_create(
            language = language_value,
            stext=row["stext"],
            ltext=row["ltext"],
            object_id=lv_object_id,
            content_type_id=lv_content_type_id            
        )    


    """    
    # tokentype = TokenType()
    TOKENTYPE_DATA = [
        {
        "tokentype_id" : "text_page", 
        "ltext": "Text Page",
        "is_global" : False
        },
        {
        "tokentype_id" : "text_global", 
        "ltext": "Text Global",
        "is_global" : True
        },        
    ]

    for row in TOKENTYPE_DATA:
        TokenType.objects.update_or_create(
            tokentype_id=row["tokentype_id"],
            ltext= row["ltext"],
            is_global= row["is_global"]
        )
    #TokenType.objects.create(
    #    tokentype_id = 'text_page', 
    #    ltext = 'Text Page',
    #    is_global = False)

    #TokenType.objects.create(
    #    tokentype_id = 'text_global',
    #    ltext = 'Text Global',
    #    is_global = True)
    
    tokentypes = {c.tokentype_id: c for c in TokenType.objects.all()}
    TOKEN_DATA = [
        {
            "token_id": "client_name",
            "tokentype_id": "text_global",
            "ltext": "Client Name"
        },
        {
            "token_id": "nb_title",
            "tokentype_id": "text_global",
            "ltext": "NavBar Title"
        },        
    ]
    for row in TOKEN_DATA:
        Token.objects.update_or_create(
            tokentype=tokentypes[row["tokentype_id"]],
            token_id= row["token_id"],
            ltext= row["ltext"]
        )
    """
"""    
    Token.objects.create(
        token_id = 'client_name',
        tokentype_id = 'text_global', 
        ltext = 'Client Name')

    Token.objects.create(
        token_id = 'nb_title',
        tokentype_id = 'text_global',
        ltext = 'NavBar Title')

    Token.objects.create(
        token_id = '01_01_01_01_title',
        ltext = 'Title at 4th level',
        tokentype_id = 'text_page')

    Token.objects.create(
        token_id = 'global',
        ltext = 'Global Usage',
        tokentype_id = 'text_global')
    
    Token.objects.create(
        token_id = 'page_name',
        ltext = 'Page Name',
        tokentype_id = 'text_global')

    Token.objects.create(
        token_id = 'err001',
        ltext = 'Error Code 001',
        tokentype_id = 'text_global')        
    Token.objects.create(
        token_id = 'err002',
        ltext = 'Error Code 002',
        tokentype_id = 'text_global')            

    Token.objects.create(
        token_id = 'en',
        ltext = 'English',
        tokentype_id = 'text_global')        
    Token.objects.create(
        token_id = 'hi',
        ltext = 'Hindi',
        tokentype_id = 'text_global')
    Token.objects.create(
        token_id = 'fr',
        ltext = 'French',
        tokentype_id = 'text_global')
    
    Token.objects.create(
        token_id = 'home',
        ltext = 'Home',
        tokentype_id = 'text_global')
    Token.objects.create(
        token_id = 'about',
        ltext = 'About',
        tokentype_id = 'text_global')
    Token.objects.create(
        token_id = 'contact',
        ltext = 'Contact',
        tokentype_id = 'text_global')
    Token.objects.create(
        token_id = 'team',
        ltext = 'Team',
        tokentype_id = 'text_global')

    Token.objects.create(
        token_id = 'light',
        ltext = 'Light',
        tokentype_id = 'text_global')
    Token.objects.create(
        token_id = 'aqua',
        ltext = 'Aqua',
        tokentype_id = 'text_global')
        
  
    Token.objects.create(
        token_id = 'dark',
        ltext = 'Dark',
        tokentype_id = 'text_global')        
   
    
      
    Language.objects.create(
        language_id = 'en',
        token_id = 'en')
    Language.objects.create(
        language_id = 'hi',
        token_id = 'hi')
    Language.objects.create(
        language_id = 'fr',
        token_id = 'fr')

    Theme.objects.create(
        theme_id = 'light',
        token_id = 'light')
    Theme.objects.create(
        theme_id = 'aqua',
        token_id = 'aqua')
    Theme.objects.create(
        theme_id = 'dark',
        token_id = 'dark')
   
    Page.objects.create(
        page_id = 'global',
        token_id = 'global')  
    Page.objects.create(
        page_id = 'home',
        token_id = 'home')
    Page.objects.create(
        page_id = 'about',
        token_id = 'about')
    Page.objects.create(
        page_id = 'team',
        token_id = 'team')
    Page.objects.create(
        page_id = 'contact',
        token_id = 'contact')
    
    Position.objects.create(
        position_id = 'start',
        ltext = 'Start')
    Position.objects.create(
        position_id = 'end',
        ltext = 'End')
    

    Client.objects.create(
        client_id = 'default',
        token_id = 'client_name')
 
    Client.objects.create(
        client_id = 'bahushira')
 
    ClientLanguage.objects.create(
        client_id = 'bahushira',
        language_id = 'en',
        order = 1)

    ClientLanguage.objects.create(
        client_id = 'bahushira',
        language_id = 'hi',
        order = 2)        

    ClientTheme.objects.create(
        client_id = 'bahushira',
        theme_id = 'light',
        order = 1)        
    ClientTheme.objects.create(
        client_id = 'bahushira',
        theme_id = 'dark',
        order = 2)        
      

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'en',
        page_id = 'global',
        value = 'Bahushira Technologies LLP'
        ) 

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiBahushira Technologies LLP'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'fr',
        page_id = 'global',
        value = 'frBahushira Technologies LLP'
        ) 


    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'en',
        page_id = 'global',
        value = 'Default Client'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiDefault Client'
        )
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'fr',
        page_id = 'global',
        value = 'frDefault Client'
        )        
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'en',
        page_id = 'global',
        value = 'Value is not maintained'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiValue is not maintained'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'fr',
        page_id = 'global',
        value = 'frValue is not maintained'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'en',
        page_id = 'global',
        value = 'Input is not a Dictionary Object'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiInput is not a Dictionary Object'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'fr',
        page_id = 'global',
        value = 'frInput is not a Dictionary Object'
        )     
   

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'en',
        page_id = 'global',
        value = 'English'
        )     
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiEnglish'
        )     
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'fr',
        page_id = 'global',
        value = 'frEnglish'
        )     
    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'en',
        page_id = 'global',
        value = 'Hindi'
        )     
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiHindi'
        )     
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'fr',
        page_id = 'global',
        value = 'frHindi'
        )         
    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'en',
        page_id = 'global',
        value = 'French'
        )         
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiFrench'
        )         
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'fr',
        page_id = 'global',
        value = 'frFrench'
        )         

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'en',
        page_id = 'global',
        value = 'Light'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiLight'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'fr',
        page_id = 'global',
        value = 'frLight'
        )        
    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'en',
        page_id = 'global',
        value = 'Dark'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiDark'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'fr',
        page_id = 'global',
        value = 'frDark'
        )    
    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'en',
        page_id = 'global',
        value = 'Aqua'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiAqua'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'fr',
        page_id = 'global',
        value = 'frAqua'
        )    

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'en',
        page_id = 'global',
        value = 'Home'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiHome'
        )
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'fr',
        page_id = 'global',
        value = 'frHome'
        )  

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'en',
        page_id = 'global',
        value = 'About'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiAbout'
        )    
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'fr',
        page_id = 'global',
        value = 'frAbout'
        )    

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'en',
        page_id = 'global',
        value = 'Contact'
        )              
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiContact'
        )              
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'fr',
        page_id = 'global',
        value = 'frContact'
        )      

    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'en',
        page_id = 'global',
        value = 'Team'
        ) 
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiTeam'
        )
    TextStatic.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'fr',
        page_id = 'global',
        value = 'frTeam'
        )

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'en',
        page_id = 'global',
        value = 'Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiBahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'fr',
        page_id = 'global',
        value = 'frBahushira'
        ) 

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'home',
        value = 'Welcome to Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'home',
        value = 'hiWelcome to Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'home',
        value = 'frWelcome to Bahushira'
        ) 

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'about',
        value = 'About Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'about',
        value = 'hiAbout Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'about',
        value = 'frAbout Bahushira'
        ) 

    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'contact',
        value = 'Contact Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'contact',
        value = 'hiContact Bahushira'
        ) 
    TextStatic.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'contact',
        value = 'frContact Bahushira'
        ) 

    Image.objects.create(
        client_id = 'default',
        page_id = 'global',        
        image_id = 'nike',
        image_url = 'https://img.daisyui.com/images/stock/photo-1606107557195-0e29a4b5b4aa.webp', 
        alt = 'shoes'
        )         
    Image.objects.create(
        client_id = 'default',
        page_id = 'global',
        image_id = 'spiderman',
        image_url = 'https://img.daisyui.com/images/stock/photo-1635805737707-575885ab0820.webp', 
        alt = 'spiderman'
        )
    Image.objects.create(
        client_id = 'default',
        page_id = 'global',
        image_id = 'daisy1',
        image_url = 'https://img.daisyui.com/images/stock/photo-1625726411847-8cbb60cc71e6.webp', 
        alt = 'daisy1'
        )        

    Svg.objects.create(
        client_id = 'default',
        page_id = 'global',
        svg_id = 'like',
        svg_text = 'M21 8.25c0-2.485-2.099-4.5-4.688-4.5-1.935 0-3.597 1.126-4.312 2.733-.715-1.607-2.377-2.733-4.313-2.733C5.1 3.75 3 5.765 3 8.25c0 7.22 9 12 9 12s9-4.78 9-12Z', 
        )                


"""