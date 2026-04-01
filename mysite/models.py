from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
import json
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation
from html.parser import HTMLParser

# Create your models here

#Common component structrue:
"""
Client
    ├── GentextBlock    
    ├── Page
        ├── GentextBlock    
        ├── Layout @level 40
            ├── Component (onetoone at level=40, compl0_id = hero, card, accordion etc... + some fields at this level)
                     ├── ComponentSlot (foreign key compl1_id= figure, text + some fields that may be applicable for each of this)
                         └── ComptextBlock (only for compll1_id = text GenericRelation)

    ├── Themes
        ├── themepreset
        └── gentextblocks                        
           
GentextBlock (content_type) (name / nb_title / nb_logo) # used in Client, Page
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
                      
ComptextBlock (content_type) (title / content / actbut)  # used in HeroText, CardText, HeroCardText
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
           
           
TextstbItem (content_type) (text / svg / badge)
└── SvgtextbadgeValue (per language)
"""

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

class Language(models.Model):
    # id = LowercaseCharField(max_length=2, primary_key=True)
    language_id = LowercaseCharField(max_length=2, unique=True, db_index=True)    
    label_obj = models.JSONField(null = True, blank = True, default=dict)

    def __str__(self):
        return f"{self.language_id} / {self.label_obj['en']}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-01 Project Language"
        ordering = ["language_id"]    

class ThemePreset(models.Model):
    themepreset_id = LowercaseCharField(max_length=25, unique=True, db_index=True)
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional

    # === COLORS ===
    primary = models.CharField(max_length=20)
    secondary = models.CharField(max_length=20)
    accent = models.CharField(max_length=20)
    neutral = models.CharField(max_length=20)

    primary_content = models.CharField(max_length=20)
    secondary_content = models.CharField(max_length=20)
    accent_content = models.CharField(max_length=20)
    neutral_content = models.CharField(max_length=20)

    base_100 = models.CharField(max_length=20)
    base_200 = models.CharField(max_length=20)
    base_300 = models.CharField(max_length=20)
    base_content = models.CharField(max_length=20)

    success = models.CharField(max_length=20)
    warning = models.CharField(max_length=20)
    error = models.CharField(max_length=20)
    info = models.CharField(max_length=20)

    success_content = models.CharField(max_length=20)
    warning_content = models.CharField(max_length=20)
    error_content = models.CharField(max_length=20)
    info_content = models.CharField(max_length=20)

    # === TYPOGRAPHY ===
    font_body = models.CharField(max_length=100)
    font_heading = models.CharField(max_length=100)
    base_font_size = models.CharField(max_length=10, default="16px")
    scale_ratio = models.FloatField(default=1.2)

    # === SPACING ===
    section_gap = models.CharField(max_length=10, default="4rem")
    container_padding = models.CharField(max_length=10, default="1rem")

    # === RADIUS ===
    radius_btn = models.CharField(max_length=10, default="0.5rem")
    radius_card = models.CharField(max_length=10, default="1rem")
    radius_input = models.CharField(max_length=10, default="0.5rem")

    # === SHADOW ===
    shadow_sm = models.CharField(max_length=50, default="0 1px 2px 0 rgb(0 0 0 / 0.05)")
    shadow_md = models.CharField(max_length=50, default="0 4px 6px -1px rgb(0 0 0 / 0.1)")
    shadow_lg = models.CharField(max_length=50, default="0 10px 15px -3px rgb(0 0 0 / 0.1)")

    is_system = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.themepreset_id} / {self.ltext}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Project ThemePresets"
        ordering = ["themepreset_id"]    

class TextstbItem(models.Model):
    #block = models.ForeignKey(TextBlock, related_name="items", on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')    
    STB_ITEM_TYPES = (
        ("text", "Text"),
        ("svg", "SVG"),
        ("badge", "Badge"),
    )    
    item_id = models.CharField(max_length=20, choices=STB_ITEM_TYPES, blank=False, null=False) 
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)
    css_class = models.CharField(max_length=255, blank=True, null=True)
    svg_text = models.CharField(max_length=500, blank=True, null=True)
    #translations = GenericRelation(TextItemValue)
    
    def clean(self):
        if self.svg_text and not self.item_id == 'svg':
            raise ValidationError("SVG text is relevanr only if item_id is SVG")
        #if self.item_id == 'svg' and self.translations.exists():
        #    raise ValidationError("SVG items must not have translations")
    def __str__(self):
        return f"{self.item_id} {self.ltext}"   
    class Meta:
        unique_together = ("content_type", "object_id", "item_id", "order")
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]        
        verbose_name = "01-06b Text SVG/Text/Badge item"                

class SvgtextbadgeValue(models.Model):
    textstbitem = models.ForeignKey(TextstbItem, on_delete=models.CASCADE)
    language = models.ForeignKey(Language, on_delete=models.CASCADE)    
    stext = models.CharField(max_length=255, null=True, blank=True, validators=text_field_validators)
    ltext = models.TextField(null=True, blank=True, validators=text_field_validators)
    def __str__(self):
        return f"{self.stext} / ({self.ltext})"
    class Meta:
        unique_together = ("textstbitem", "language")
        verbose_name = "01-06c Svg Text Badge(STB) Item value"

class ComptextBlock(models.Model):
    #textcontent = models.ForeignKey(TextContent, related_name="blocks", on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')    

    BLOCK_TYPES = (
        ("title", "Title"),
        ("content", "Content"),
        ("actbut", "ActionButtons"),
    )    
    block_id = models.CharField(max_length=20, choices=BLOCK_TYPES, blank=False, null=False)    
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    textstbitems = GenericRelation(TextstbItem)
    # ideally this should be a dropdown of page of this client, but have kept it as a simple text for the timebeing. This value is passed as <a link in the Button component
    href_page=models.CharField(max_length=25, blank=True, null=True)
    class Meta:
        unique_together = ("content_type", "object_id", "block_id", "order")
        verbose_name = "01-06a Component Text Block" 
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["content_type", "object_id", "order"]),
        ]        
    def __str__(self):
        return f"{self.block_id} {self.ltext}"    
               
class GentextBlock(models.Model):
    #textcontent = models.ForeignKey(TextContent, related_name="blocks", on_delete=models.CASCADE)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')    
    BLOCK_TYPES = (
        ("name", "Name"),
        ("nb_title", "Navbar Title"),
        ("nb_subtitle", "Navbar SubTitle"),
    )    
    block_id = models.CharField(max_length=20, choices=BLOCK_TYPES, blank=False, null=False)    
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    textstbitems = GenericRelation(TextstbItem)
    class Meta:
        unique_together = ("content_type", "object_id", "block_id", "order")
        verbose_name = "01-06a General Text Block"  
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
            models.Index(fields=["content_type", "object_id", "order"]),
        ]        
    def __str__(self):
        return f"{self.block_id} {self.ltext}" 
    

class Client(models.Model):
    client_id = LowercaseCharField(max_length=25, unique=True, db_index=True)    

    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    language_list = models.JSONField(null = True, blank = True, default=lambda: ['en'], help_text="A JSON array of selected values from Language.")
    theme_list = models.JSONField(null = True, blank = True, default=lambda: ['light'])
    # Add this to allow: client_instance.translations.all()
    #translations = GenericRelation(TextItemValue)
    gentextblocks = GenericRelation(GentextBlock)

    def __str__(self):
        return self.client_id

    # if a Model has a recursive relationship and its parent is maintained in the same row
    def get_ancestors(self):
        #Return all ancestors (parent, grandparent, ...) as a list.#
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(str(current.client_id))
            current = current.parent
        return ancestors  
     
    def get_descendants(self):
        #Return all descendants (children, grandchildren, ...) as a list of clients.
        descendants = []

        def collect_children(node):
            for child in node.children.all():
                descendants.append(str(child.client_id))
                collect_children(child)

        collect_children(self)
        return descendants     
    class Meta:
        verbose_name = "00-03 Client"
        ordering = ["client_id"]


class Theme(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='themes')    
    theme_id = LowercaseCharField(max_length=10)  
    themepreset = models.ForeignKey(ThemePreset, on_delete=models.SET_NULL, null=True)
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False)
    # Add this to allow: client_instance.translations.all()
    gentextblocks = GenericRelation(GentextBlock)
    overrides = models.JSONField(blank=True, null=True)
    is_default = models.BooleanField(default=False)    

    def __str__(self):
        return f"{self.client.client_id} / {self.theme_id}"
      
    # for usage in Admin Panel
    class Meta:
        #verbose_name = "00-04 Project Page"
        #verbose_name_plural = "My Custom Models"
        unique_together = ("client", "theme_id")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["client", "order"]),
        ]

"""
class Page(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='pages'
        )    
    page_id = LowercaseCharField(max_length=10)  
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children",
        on_delete=models.CASCADE
    )
    hidden = models.BooleanField(default=False)
    # Add this to allow: client_instance.translations.all()
    #translations = GenericRelation(TextItemValue)    
    gentextblocks = GenericRelation(GentextBlock)

    def __str__(self):
        return f"{self.client.client_id} / {self.page_id}"
      
    # for usage in Admin Panel
    class Meta:
        #verbose_name = "00-04 Project Page"
        #verbose_name_plural = "My Custom Models"
        unique_together = ("client", "page_id")
        ordering = ["order"]
        indexes = [
            models.Index(fields=["client", "order"]),
        ]

class Layout(models.Model):
    # ideally layout can be an inline under page. but we are not able to brnach to a component inline from another inline.
    # client is kept, so that layout can be a separate admin tab. in that we are braching to component type admin.
    client = models.ForeignKey(Client, on_delete=models.CASCADE)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='layouts')
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="layoutchildren",
        on_delete=models.CASCADE
    )

    order = models.PositiveIntegerField(default=1)

    LEVEL_CHOICES = (
        (10, "Section"),
        (20, "Row"),
        (30, "Col"),
        (40, "Cell"),
    )
    level = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES)

    css_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    style = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    hidden = models.BooleanField(default=False)

    slug = models.SlugField()  # for bulk upload / human reference
    COMPONENT_TYPES = (
        ("hero", "Comp Hero"),
        ("card", "Comp Card"),
        ("accordion", "Comp Accordion"),
        ("carousel", "Comp Carousel"),
    )
    comp_id = models.CharField(max_length=30, choices=COMPONENT_TYPES, blank=True, null=True )
    class Meta:
        ordering = ("client", "page", "level", "order")
        unique_together = ("client", "page", "level", "slug")
        verbose_name = "01-04 Layout"

    def clean(self):
        if self.level != 40 and self.comp_id:
            raise ValidationError("Component has to be at Level = 40")
        
        if self.level != 10 and not self.parent:
            raise ValidationError("Non-root layouts must have a parent")

        if self.parent and self.parent.level != self.level - 10:
            raise ValidationError("Invalid parent level")

        if self.client.client_id != self.page.client.client_id:
            raise ValidationError("Page and Layout Clients need to be same !")

    def __str__(self):
        return f"{self.page.client.client_id} / {self.page.page_id} / {self.level} / {self.slug}"


class Hero(models.Model):
    layout = models.OneToOneField(
        Layout,
        on_delete=models.CASCADE,
        related_name="hero"
    )
    css_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    herocontent_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    overlay = models.BooleanField(default=False)
    overlay_style = models.CharField(max_length=255, blank=True, validators=text_field_validators)

    class Meta:
        verbose_name = "01-05a Hero"

class HeroText(models.Model):
    hero = models.OneToOneField(Hero, on_delete=models.CASCADE, related_name="herotext")
    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)
    type_id = models.CharField(max_length=10, default="text")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)

    class Meta:
        verbose_name = "01-05a1 HeroText"
        unique_together = ("hero", "type_id")


class HeroFigure(models.Model):
    hero = models.OneToOneField(Hero, on_delete=models.CASCADE, related_name="herofigure")
    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)
    type_id = models.CharField(max_length=10, default="figure")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    figure_class = models.CharField(max_length=255, blank=True, null=True)

    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)

    image_url = models.URLField(max_length=500)
    alt = models.CharField(max_length=100, null=False, default="Default")
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    class Meta:
        verbose_name = "01-05a2 HeroFigure"  
        unique_together = ("hero", "type_id")

class HeroCard(models.Model):
    hero = models.OneToOneField(Hero, on_delete=models.CASCADE, related_name="herocard")
    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)
    type_id = models.CharField(max_length=10, default="card")

    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    body_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    class Meta:
        verbose_name = "01-05a3 HeroCard"  
        unique_together = ("hero", "type_id")

class HeroCardText(models.Model):
    herocard = models.OneToOneField(HeroCard, on_delete=models.CASCADE, related_name="herocardtext")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=1)
    hidden = models.BooleanField(default=False)
    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    ) # this is redundant. ordering of comptextblocks defines the location of actions   
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)
    class Meta:
        verbose_name = "01-05a3a HeroCard Text"  


class HeroCardFigure(models.Model):
    herocard = models.OneToOneField(HeroCard, on_delete=models.CASCADE, related_name="herocardfigure")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=1) # position is redundant. order decindes the sequence
    figure_class = models.CharField(max_length=255, blank=True, null=True)
    hidden = models.BooleanField(default=False)
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    image_url = models.URLField(max_length=500)
    alt = models.CharField(max_length=100, null=False, default="Default")
    css_class = models.CharField(max_length=255, blank=True, null=True)  
    class Meta:
        verbose_name = "01-05a3b HeroCard Figure"  


class Card(models.Model):
    layout = models.OneToOneField(Layout, on_delete=models.CASCADE, related_name="card")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    body_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    class Meta:
        verbose_name = "01-05b Card" 

class CardFigure(models.Model):
    card = models.OneToOneField(Card, on_delete=models.CASCADE, related_name="cardfigure")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=1) # position is redundant. order decindes the sequence
    figure_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    hidden = models.BooleanField(default=False)
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    image_url = models.URLField(max_length=500)
    alt = models.CharField(max_length=100, null=False, default="Default")
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)  


class CardText(models.Model):
    card = models.OneToOneField(Card, on_delete=models.CASCADE, related_name="cardtext" )
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)
    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    # this is redundant. ordering of comptextblocks defines the location of actions
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)


class Accordion(models.Model):
    layout = models.OneToOneField(Layout, on_delete=models.CASCADE, related_name="accordion")
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    type = models.CharField(max_length=25, default="radio") # defaulted
    name = models.CharField(max_length=25, default="myaccordion_01") # deaulted
    #body_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = "01-05c Accordion" 
        unique_together = ("layout", "name")  # to ensure proper opening closing of accordions
   
class AccordionText(models.Model):
    # different from cardtext one accordion will have multiple accordiontext
    accordion = models.ForeignKey(Accordion, on_delete=models.CASCADE, related_name="accordiontext" )
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)
    checked = models.BooleanField(default=False) # if true then the accordion is kept open
    #actions_class = models.CharField(max_length=255, blank=True, null=True)        
    #POSITION_TYPES = (
    #    ("start", "Start"),
    #    ("end", "End"),
    #)    # this is redundant. ordering of comptextblocks defines the location of actions
    #actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)


# TBD Accordion and Carousal...
"""


class Page(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='pages'
        )    
    page_id = LowercaseCharField(max_length=10)  
    ltext = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children",
        on_delete=models.CASCADE
    )
    hidden = models.BooleanField(default=False)  
    gentextblocks = GenericRelation(GentextBlock)

    def __str__(self):
        return f"{self.client.client_id} / {self.page_id}"
      
    # for usage in Admin Panel
    class Meta:
        unique_together = ("client", "page_id")
        ordering = ["client", "order"]
        indexes = [
            models.Index(fields=["client", "order"]),
        ]
        verbose_name = "01-02 Page"

class Layout(models.Model):
    # ideally layout can be an inline under page. but we are not able to brnach to a component inline from another inline.
    # client is kept, so that layout can be a separate admin tab. in that we are braching to component type admin.
    #client = models.ForeignKey(Client, on_delete=models.CASCADE)
    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name='layouts')
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    order = models.PositiveIntegerField(default=1)

    LEVEL_CHOICES = (
        (10, "Section"),
        (20, "Row"),
        (30, "Col"),
        (40, "Cell"),
    )
    level = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES)

    css_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    style = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    hidden = models.BooleanField(default=False)

    slug = models.SlugField()  # for bulk upload / human reference
    #COMPONENT_TYPES = (
    #    ("hero", "Comp Hero"),
    #    ("card", "Comp Card"),
    #    ("accordion", "Comp Accordion"),
    #    ("carousel", "Comp Carousel"),
    #)
    #comp_id = models.CharField(max_length=30, choices=COMPONENT_TYPES, blank=True, null=True )
    class Meta:
        ordering = ("page", "level", "order")
        unique_together = ("page", "level", "slug")
        verbose_name = "01-03 Layout"

    def clean(self):
        #if self.level != 40 and self.comp_id:
        #    raise ValidationError("Component has to be at Level = 40")
        
        if self.level != 10 and not self.parent:
            raise ValidationError("Non-root layouts must have a parent")

        if self.parent and self.parent.level != self.level - 10:
            raise ValidationError("Invalid parent level")

        #if self.client.client_id != self.page.client.client_id:
        #    raise ValidationError("Page and Layout Clients need to be same !")

    def __str__(self):
        return f"{self.page.client.client_id} / {self.page.page_id} / {self.level} / {self.slug}"


class Component(models.Model):
    """L0 — one per Layout cell (level=40)"""
    layout = models.OneToOneField(
        Layout,
        on_delete=models.CASCADE,
        related_name="component"
    )

    COMP_TYPES = (
        ("hero",      "Hero"),
        ("card",      "Card"),
        ("accordion", "Accordion"),
        ("carousel",  "Carousel"),
    )
    comp_id       = models.CharField(max_length=30, choices=COMP_TYPES)
    ltext         = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)
    css_class     = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)
    card_body_class     = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)    # card    
    hero_content_class     = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)    # hero
    hero_overlay       = models.BooleanField(default=False)          # hero
    hero_overlay_style = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)  # hero
    accordion_type = models.CharField(max_length=25, blank=True, null=True)   # accordion
    accordion_name = models.CharField(max_length=25, blank=True, null=True)   # accordion
    config        = models.JSONField(default=dict, blank=True)
    hidden        = models.BooleanField(default=False)
    order         = models.PositiveIntegerField(default=1)  # This is not relevant and can be removed. As at cell lelvel there will be only one component

    def __str__(self):
        return f"{self.layout} / {self.comp_id}"

    class Meta:
        verbose_name = "01-04 Component L0"


class ComponentSlot(models.Model):
    """L1 — multiple slots per Component (figure or text)"""
    component = models.ForeignKey(
        Component,
        on_delete=models.CASCADE,
        related_name="slots"
    )

    SLOT_TYPES = (
        ("figure", "Figure"),
        ("text",   "Text"),
    )
    slot_type   = models.CharField(max_length=20, choices=SLOT_TYPES)
    order       = models.PositiveIntegerField(default=1)
    hidden      = models.BooleanField(default=False)
    ltext       = models.CharField(max_length=50, blank=True, null=True, validators=text_field_validators)
    css_class   = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)

    # Figure fields
    image_url   = models.URLField(max_length=500, blank=True, null=True)
    alt         = models.CharField(max_length=100, blank=True, null=True)
    figure_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)

    # Hero/Card slot specific
    actions_class = models.CharField(max_length=255, blank=True, null=True, validators=text_field_validators)

    # Accordion slot specific
    accordion_checked     = models.BooleanField(default=False)

    # Text slot — ComptextBlocks via GenericRelation
    comptextblocks = GenericRelation(ComptextBlock)

    def clean(self):
        if self.slot_type == 'figure' and not self.image_url:
            raise ValidationError("Figure slot requires an image_url.")

    def __str__(self):
        return f"{self.component} / {self.slot_type} / {self.order}"

    class Meta:
        ordering = ["component", "order"]
        unique_together = ("component", "slot_type", "order")
        verbose_name = "01-05 Component L1 Slot"

"""

"""