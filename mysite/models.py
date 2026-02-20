from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
import json
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation

# Create your models here
"""
Language
Theme
Client
    ├── TextItemValue to replaced by GentextBlock    
    ├── Page
        ├── TextItemValue to replaced by GentextBlock    
        ├── Layout @level 40
            ├── Hero
            │         ├── HeroText   (only if type=text)
            │             └── TextContent to replaced by ComptextBlock
            │         ├── HeroFigure (only if type=figure)
            │         └── HeroCard
            │              ├── HeroCardFigure
            │              └── HeroCardText
            │                 └── TextContent to replaced by ComptextBlock
            │
            └── Card
                ├── CardFigure
                └── CardText
                        └── TextContent to replaced by ComptextBlock 

                        TextContent (content_type) To be depreacted
 └── TextBlock (title / content / actbut)
      └── TextBlockItem (text / svg / badge)
           └── TextItemValue (per language)

           
GentextBlock (content_type) (name / nb_title / nb_logo) # used in Client, Page
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)

                      
ComptextBlock (content_type) (title / content / actbut)  # used in HeroText, CardText, HeroCardText
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
           
           
TextstbItem (content_type) (text / svg / badge)
└── SvgtextbadgeValue (per language)
                      

TextItemValue (content_type) - To be deprecated                                   
"""
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

class Theme(models.Model):
    # id = LowercaseCharField(max_length=2, primary_key=True)
    theme_id = LowercaseCharField(max_length=50, unique=True, db_index=True)    
    label_obj = models.JSONField(null = True, blank = True, default=dict)

    def __str__(self):
        return f"{self.theme_id} / {self.label_obj['en']}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Project Theme"
        ordering = ["theme_id"]

"""
class TextItemValue(models.Model):

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    language = models.ForeignKey(Language, on_delete=models.CASCADE)    
    stext = models.CharField(max_length=255, null=True, blank=True)
    ltext = models.TextField(null=True, blank=True)
    def __str__(self):
        return f"{self.stext} / ({self.ltext})"
    class Meta:
        unique_together = ("content_type", "object_id", "language")
        verbose_name = "01-06d Text Item value"    


class TextContent(models.Model):
    hidden = models.BooleanField(default=False)
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()

    content_object = GenericForeignKey('content_type', 'object_id')
    def __str__(self):
        return f"{self.id} {self.ltext}" 
    class Meta:
        verbose_name = "01-06a Text Content"    

class TextBlock(models.Model):
    textcontent = models.ForeignKey(TextContent, related_name="blocks", on_delete=models.CASCADE)
    BLOCK_TYPES = (
        ("title", "Title"),
        ("content", "Content"),
        ("actbut", "ActionButtons"),
    )    
    block_id = models.CharField(max_length=20, choices=BLOCK_TYPES, blank=False, null=False)    
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    css_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        unique_together = ("textcontent", "block_id")
        verbose_name = "01-06b Text Block"        
    def __str__(self):
        return f"{self.block_id} {self.ltext}"        

class TextBlockItem(models.Model):
    block = models.ForeignKey(TextBlock, related_name="items", on_delete=models.CASCADE)
    BLOCK_ITEM_TYPES = (
        ("text", "Text"),
        ("svg", "SVG"),
        ("badge", "Badge"),
    )    
    item_id = models.CharField(max_length=20, choices=BLOCK_ITEM_TYPES, blank=False, null=False) 
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField()
    css_class = models.CharField(max_length=255, blank=True, null=True)
    svg_text = models.CharField(max_length=500, blank=True, null=True)
    translations = GenericRelation(TextItemValue)
    def clean(self):
        if self.svg_text and not self.item_id == 'svg':
            raise ValidationError("SVG text is relevanr only if item_id is SVG")
        if self.item_id == 'svg' and self.translations.exists():
            raise ValidationError("SVG items must not have translations")
    def __str__(self):
        return f"{self.item_id} {self.ltext} ({self.block.block_id})"       
    class Meta:
        verbose_name = "01-06c Text Block Item"              
"""
# below two are new tries
"""           
GentextBlock (content_type) (name / nb_title / nb_logo) # used in Client, Page
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)

                      
ComptextBlock (content_type) (title / content / actbut)  # used in HeroText, CardText, HeroCardText
└──TextstbItem (content_type) (text / svg / badge)
    └── SvgtextbadgeValue (per language)
           
           
TextstbItem (content_type) (text / svg / badge)
└── SvgtextbadgeValue (per language)
"""

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
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
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
    stext = models.CharField(max_length=255, null=True, blank=True)
    ltext = models.TextField(null=True, blank=True)
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
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, null=True)
    textstbitems = GenericRelation(TextstbItem)
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
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, null=True)
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
    language_list = models.JSONField(null = True, blank = True, default=list, help_text="A JSON array of selected values from Language.")
    theme_list = models.JSONField(null = True, blank = True, default=list)
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

class Page(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    client = models.ForeignKey(
        Client,
        on_delete=models.CASCADE,
        related_name='pages'
        )    
    page_id = LowercaseCharField(max_length=10, unique=True)  
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
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

    css_class = models.CharField(max_length=255, blank=True)
    style = models.CharField(max_length=255, blank=True)
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
        ordering = ("page", "level", "order")
        unique_together = ("page", "level", "slug")
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
    css_class = models.CharField(max_length=255, blank=True)
    herocontent_class = models.CharField(max_length=255, blank=True)
    overlay = models.BooleanField(default=False)
    overlay_style = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "01-05a Hero"

class HeroText(models.Model):
    hero = models.OneToOneField(Hero, on_delete=models.CASCADE, related_name="herotext")
    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)
    type_id = models.CharField(max_length=10, default="text")
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
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
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    figure_class = models.CharField(max_length=255, blank=True, null=True)

    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)

    image_url = models.URLField(max_length=500)
    alt = models.CharField(max_length=100, null=False, default="Default")
    css_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = "01-05a2 HeroFigure"  
        unique_together = ("hero", "type_id")

class HeroCard(models.Model):
    hero = models.OneToOneField(Hero, on_delete=models.CASCADE, related_name="herocard")
    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)
    type_id = models.CharField(max_length=10, default="card")

    ltext = models.CharField(max_length=50, blank=True, null=True)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True)
    body_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = "01-05a3 HeroCard"  
        unique_together = ("hero", "type_id")

class HeroCardText(models.Model):
    herocard = models.OneToOneField(HeroCard, on_delete=models.CASCADE, related_name="herocardtext")
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)
    class Meta:
        verbose_name = "01-05a3a HeroCard Text"  


class HeroCardFigure(models.Model):
    herocard = models.OneToOneField(HeroCard, on_delete=models.CASCADE, related_name="herocardfigure")
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
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
    ltext = models.CharField(max_length=50, blank=True, null=True)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True)
    body_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = "01-05b Card" 

class CardFigure(models.Model):
    card = models.OneToOneField(Card, on_delete=models.CASCADE, related_name="cardfigure")
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
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


class CardText(models.Model):
    card = models.OneToOneField(Card, on_delete=models.CASCADE, related_name="cardtext" )
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)

    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    #textcontents = GenericRelation(TextContent)
    comptextblocks = GenericRelation(ComptextBlock)

   


# TBD Accordion and Carousal...
