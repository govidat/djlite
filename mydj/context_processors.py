

# my_app/context_processors.py

# ADD this to project/settings.py TEMPLATES . then these are available in all templates 
from django.conf import settings

def settings_constants(request):
    """
    Context processor to make settings constants available in templates.
    """
    return {
        'LANGUAGE_CODE': settings.LANGUAGE_CODE,
        # Add any other settings you want to access in templates
        # 'PC_THEMES': settings.PC_THEMES,
        #'PC_LANGUAGES': settings.PC_LANGUAGES,
    }