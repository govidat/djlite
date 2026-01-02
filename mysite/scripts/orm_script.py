from mysite.models import TokenType2
from mysite.models import Token2
from mysite.models import Language2
from mysite.models import Theme2
from mysite.models import Page2
from mysite.models import Client2
from mysite.models import ClientLanguage2
from mysite.models import ClientTheme2
from mysite.models import TextStatic2


from django.utils import timezone
from django.db import connection
from pprint import pprint

def run():
    """
    tokens = Token.objects.all()
    print(tokens)

    pprint(connection.queries)

    # print("Hello from runscript")
    """
    
    """
    # tokentype = TokenType2()
    TokenType2.objects.create(
        tokentype_id = 'text_page', 
        ltext = 'Text Page',
        is_global = False)

    TokenType2.objects.create(
        tokentype_id = 'text_global',
        ltext = 'Text Global',
        is_global = True)
    """    
    """
    Token2.objects.create(
        token_id = 'client_name',
        tokentype_id = 'text_global', 
        ltext = 'Client Name')

    Token2.objects.create(
        token_id = 'nb_title',
        tokentype_id = 'text_global',
        ltext = "NavBar Title')

    Token2.objects.create(
        token_id = '01_01_01_01_title',
        ltext = 'Title at 4th level',
        tokentype_id = 'text_page')

    Token2.objects.create(
        token_id = 'global',
        ltext = 'Global Usage',
        tokentype_id = 'text_global')
    
    Token2.objects.create(
        token_id = 'page_name',
        ltext = 'Page Name',
        tokentype_id = 'text_global')

    Token2.objects.create(
        token_id = 'err001',
        ltext = 'Error Code 001',
        tokentype_id = 'text_global')        
    Token2.objects.create(
        token_id = 'err002',
        ltext = 'Error Code 002',
        tokentype_id = 'text_global')            

    Token2.objects.create(
        token_id = 'en',
        ltext = 'English',
        tokentype_id = 'text_global')        
    Token2.objects.create(
        token_id = 'hi',
        ltext = 'Hindi',
        tokentype_id = 'text_global')
    Token2.objects.create(
        token_id = 'fr',
        ltext = 'French',
        tokentype_id = 'text_global')
    
    Token2.objects.create(
        token_id = 'home',
        ltext = 'Home',
        tokentype_id = 'text_global')
    Token2.objects.create(
        token_id = 'about',
        ltext = 'About',
        tokentype_id = 'text_global')
    Token2.objects.create(
        token_id = 'contact',
        ltext = 'Contact',
        tokentype_id = 'text_global')
    Token2.objects.create(
        token_id = 'team',
        ltext = 'Team',
        tokentype_id = 'text_global')

    Token2.objects.create(
        token_id = 'light',
        ltext = 'Light',
        tokentype_id = 'text_global')
    Token2.objects.create(
        token_id = 'aqua',
        ltext = 'Aqua',
        tokentype_id = 'text_global')
        
  
    Token2.objects.create(
        token_id = 'dark',
        ltext = 'Dark',
        tokentype_id = 'text_global')        

    
      
    Language2.objects.create(
        language_id = 'en',
        token_id = 'en')
    Language2.objects.create(
        language_id = 'hi',
        token_id = 'hi')
    Language2.objects.create(
        language_id = 'fr',
        token_id = 'fr')

    Theme2.objects.create(
        theme_id = 'light',
        token_id = 'light')
    Theme2.objects.create(
        theme_id = 'aqua',
        token_id = 'aqua')
    Theme2.objects.create(
        theme_id = 'dark',
        token_id = 'dark')
   
    Page2.objects.create(
        page_id = 'global',
        token_id = 'global')  
    Page2.objects.create(
        page_id = 'home',
        token_id = 'home')
    Page2.objects.create(
        page_id = 'about',
        token_id = 'about')
    Page2.objects.create(
        page_id = 'team',
        token_id = 'team')
    Page2.objects.create(
        page_id = 'contact',
        token_id = 'contact')


    Client2.objects.create(
        client_id = 'default',
        token_id = 'client_name')
 
    Client2.objects.create(
        client_id = 'bahushira')
 
    ClientLanguage2.objects.create(
        client_id = 'bahushira',
        language_id = 'en',
        order = 1)

    ClientLanguage2.objects.create(
        client_id = 'bahushira',
        language_id = 'hi',
        order = 2)        

    ClientTheme2.objects.create(
        client_id = 'bahushira',
        theme_id = 'light',
        order = 1)        
    ClientTheme2.objects.create(
        client_id = 'bahushira',
        theme_id = 'dark',
        order = 2)        


    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'en',
        page_id = 'global',
        value = 'Bahushira Technologies LLP'
        ) 

    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiBahushira Technologies LLP'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'client_name',
        language_id = 'fr',
        page_id = 'global',
        value = 'frBahushira Technologies LLP'
        ) 


    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'en',
        page_id = 'global',
        value = 'Default Client'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiDefault Client'
        )
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'client_name',
        language_id = 'fr',
        page_id = 'global',
        value = 'frDefault Client'
        )        
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'en',
        page_id = 'global',
        value = 'Value is not maintained'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiValue is not maintained'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err001',
        language_id = 'fr',
        page_id = 'global',
        value = 'frValue is not maintained'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'en',
        page_id = 'global',
        value = 'Input is not a Dictionary Object'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiInput is not a Dictionary Object'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'err002',
        language_id = 'fr',
        page_id = 'global',
        value = 'frInput is not a Dictionary Object'
        )     
   

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'en',
        page_id = 'global',
        value = 'English'
        )     
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiEnglish'
        )     
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'en',
        language_id = 'fr',
        page_id = 'global',
        value = 'frEnglish'
        )     
    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'en',
        page_id = 'global',
        value = 'Hindi'
        )     
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiHindi'
        )     
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'hi',
        language_id = 'fr',
        page_id = 'global',
        value = 'frHindi'
        )         
    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'en',
        page_id = 'global',
        value = 'French'
        )         
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiFrench'
        )         
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'fr',
        language_id = 'fr',
        page_id = 'global',
        value = 'frFrench'
        )         

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'en',
        page_id = 'global',
        value = 'Light'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiLight'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'light',
        language_id = 'fr',
        page_id = 'global',
        value = 'frLight'
        )        
    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'en',
        page_id = 'global',
        value = 'Dark'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiDark'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'dark',
        language_id = 'fr',
        page_id = 'global',
        value = 'frDark'
        )    
    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'en',
        page_id = 'global',
        value = 'Aqua'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiAqua'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'aqua',
        language_id = 'fr',
        page_id = 'global',
        value = 'frAqua'
        )    

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'en',
        page_id = 'global',
        value = 'Home'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiHome'
        )
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'home',
        language_id = 'fr',
        page_id = 'global',
        value = 'frHome'
        )  

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'en',
        page_id = 'global',
        value = 'About'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiAbout'
        )    
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'about',
        language_id = 'fr',
        page_id = 'global',
        value = 'frAbout'
        )    

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'en',
        page_id = 'global',
        value = 'Contact'
        )              
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiContact'
        )              
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'contact',
        language_id = 'fr',
        page_id = 'global',
        value = 'frContact'
        )      

    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'en',
        page_id = 'global',
        value = 'Team'
        ) 
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiTeam'
        )
    TextStatic2.objects.create(
        client_id = 'default',
        token_id = 'team',
        language_id = 'fr',
        page_id = 'global',
        value = 'frTeam'
        )

    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'en',
        page_id = 'global',
        value = 'Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'hi',
        page_id = 'global',
        value = 'hiBahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = 'nb_title',
        language_id = 'fr',
        page_id = 'global',
        value = 'frBahushira'
        ) 

    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'home',
        value = 'Welcome to Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'home',
        value = 'hiWelcome to Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'home',
        value = 'frWelcome to Bahushira'
        ) 

    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'about',
        value = 'About Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'about',
        value = 'hiAbout Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'about',
        value = 'frAbout Bahushira'
        ) 

    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'en',
        page_id = 'contact',
        value = 'Contact Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'hi',
        page_id = 'contact',
        value = 'hiContact Bahushira'
        ) 
    TextStatic2.objects.create(
        client_id = 'bahushira',
        token_id = '01_01_01_01_title',
        language_id = 'fr',
        page_id = 'contact',
        value = 'frContact Bahushira'
        ) 

    """

