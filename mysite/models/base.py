from django.db import models
from django.core.exceptions import ValidationError
from html.parser import HTMLParser

"""
Client
    ├── name using modelTranslation #GentextBlock    
    ├── Page
        ├── name using modelTranslation #GentextBlock    
        ├── Layout @level 40
            ├── Component (onetoone at level=40, compl0_id = hero, card, accordion etc... + some fields at this level)
                     ├── ComponentSlot (foreign key compl1_id= figure, text + some fields that may be applicable for each of this)
                         └── ComptextBlock (only for compll1_id = text GenericRelation)
    ├── NavItem
    ├── Themes
        ├── themepreset
        └── name using modelTranslation #GentextBlock                        
           
GentextBlock Presently NOT USED (content_type) (name / nb_title / nb_logo) # used in Client, Page
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
                      
ComptextBlock (content_type) (title / content / actbut)  # used in HeroText, CardText, HeroCardText
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
           
           
TextstbItem (content_type) (text / svg / badge)
└── SvgtextbadgeValue (per language)
"""

def default_languages():
    return ['en']

def default_themes():
    return ['light']


class HTMLTagDetector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found_tags = False

    def handle_starttag(self, tag, attrs):
        self.found_tags = True

    def handle_endtag(self, tag):
        self.found_tags = True

def no_html_tags(value):
    if not value:
        return
    detector = HTMLTagDetector()
    detector.feed(value)
    if detector.found_tags:
        raise ValidationError("HTML tags are not allowed.")

def no_double_quotes(value):
    if value and '"' in value:
        raise ValidationError('Double quotes (") are not allowed. Use &quot; instead.')

# Combine both into one validator list for convenience
text_field_validators = [no_html_tags, no_double_quotes]

class LowercaseCharField(models.CharField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return value.lower()
        return value