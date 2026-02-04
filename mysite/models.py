from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
import json
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey

# Create your models here

class LowercaseCharField(models.CharField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return value.lower()
        return value

class Language2(models.Model):
    # id = LowercaseCharField(max_length=2, primary_key=True)
    language_id = LowercaseCharField(max_length=2, unique=True)    
    label_obj = models.JSONField(null = True, blank = True, default=dict)

    def __str__(self):
        return f"{self.language_id} / {self.label_obj['en']}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-01 Project Language2"
        ordering = ["language_id"]    

class Theme2(models.Model):
    # id = LowercaseCharField(max_length=2, primary_key=True)
    theme_id = LowercaseCharField(max_length=2, unique=True)    
    label_obj = models.JSONField(null = True, blank = True, default=dict)

    def __str__(self):
        return f"{self.theme_id} / {self.label_obj['en']}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Project Theme2"
        ordering = ["theme_id"]

class TextItemValue2(models.Model):

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    language = models.ForeignKey(Language2, on_delete=models.CASCADE)    
    stext = models.CharField(max_length=255, null=True, blank=True)
    ltext = models.TextField(null=True, blank=True)
    def __str__(self):
        return f"{self.stext} / ({self.ltext})"
    class Meta:
        unique_together = ("content_type", "object_id", "language")


class Client2(models.Model):
    client_id = LowercaseCharField(max_length=25, unique=True)    

    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    language_list = models.JSONField(null = True, blank = True, default=list, help_text="A JSON array of selected values from Language.")
    theme_list = models.JSONField(null = True, blank = True, default=list)

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
        verbose_name = "00-03 Client2"
        ordering = ["client_id"]

class Page2(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    client = models.ForeignKey(
        Client2,
        on_delete=models.CASCADE,
        related_name='pages'
        )    
    page_id = LowercaseCharField(max_length=10, unique=True)  
    ltext = models.CharField(max_length=50, null=True)   # Optional
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children",
        on_delete=models.CASCADE
    )
    hidden = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.page_id} / {self.ltext}"
      
    # for usage in Admin Panel
    class Meta:
        #verbose_name = "00-04 Project Page"
        #verbose_name_plural = "My Custom Models"
        ordering = ["order"]

class TokenType(models.Model):
    
    # Categorizes tokens: global_text, local_text, language_name, theme_name, Country, State, City, Currency, etc.
    # id = LowercaseCharField(max_length=20, primary_key=True)   # e.g., "country"
    tokentype_id = LowercaseCharField(max_length=20, unique=True)   # e.g., "country"    
    # name = models.CharField(max_length=50, unique=True)   # e.g., "Country" 
    ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"     
    is_global = models.BooleanField(default=False)        # Global and it means it is centrally maintained? if True, then the Token name should be g_, else l_. g_ values can be part of the code itself.
    # for usage in Admin Panel
    class Meta:
        ordering = ["tokentype_id"]
        verbose_name = "00-01 Token Type2"
        #verbose_name_plural = "My Custom Models"

    def __str__(self):
        return f"{self.ltext} ({self.tokentype_id})"

class Token(models.Model):
    # id = LowercaseCharField(max_length=25, primary_key=True)   # user enters e.g. "g_india" or "l_client_name"

    #tokentype = models.ForeignKey(TokenType, on_delete=models.PROTECT)
    tokentype = models.ForeignKey(
        TokenType,
        on_delete=models.CASCADE,
        related_name='tokens'
    )    
    token_id = LowercaseCharField(max_length=20, unique=True)   # e.g., "country"    
    # name = models.CharField(max_length=50, unique=True)   # e.g., "Country" 
    ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"     

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Token"
        #verbose_name_plural = "My Custom Models"

    # Optional convenience helper:

    def resolve_value(self, client_id="default", language_id="en", page_id="global"):
        return TextStatic.objects.filter(
            client__client_id=client_id, token__token_id=self.token_id, language__language_id=language_id, page__page_id=page_id
        ).values_list("value", flat=True).first()        
    
    def resolve_all_values(self, client_id='default', page_id="global"):

        qs = TextStatic.objects.filter(client__client_id=client_id, token__token_id=self.token_id, page__page_id=page_id)
        values = {tr.language.language_id: tr.value for tr in qs}

        return values        


    def __str__(self):
        return self.token_id
    
class Language(models.Model):
    # id = LowercaseCharField(max_length=2, primary_key=True)
    language_id = LowercaseCharField(max_length=2, unique=True)    
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL)
    token = models.ForeignKey(
        Token,
        to_field='token_id', 
        on_delete=models.CASCADE,
        related_name='languages'
    )
    def __str__(self):
        return self.language_id

    # to get the name maintained for default client
    """
    def display_name(self):
        return self.token.resolve_value() if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values() if self.token else None
    """
    def display_name(self, client_id="default", language_id="en", page_id="global"):
        return self.token.resolve_value(client_id=client_id, language_id=language_id, page_id=page_id) if self.token else None

    def display_all_names(self, client_id="default", page_id="global"):
        return self.token.resolve_all_values(client_id=client_id, page_id=page_id) if self.token else None

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-03 Project Language"
        #verbose_name_plural = "My Custom Models"
        ordering = ["language_id"]    

class Theme(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    theme_id = LowercaseCharField(max_length=20, unique=True)    
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL)
    token = models.ForeignKey(
        Token,
        to_field='token_id', 
        on_delete=models.CASCADE,
        related_name='themes'
    )
    def __str__(self):
        return self.theme_id

    def display_name(self, client_id="default", language_id="en", page_id="global"):
        return self.token.resolve_value(client_id=client_id, language_id=language_id, page_id=page_id) if self.token else None

    def display_all_names(self, client_id="default", page_id="global"):
        return self.token.resolve_all_values(client_id=client_id, page_id=page_id) if self.token else None

        
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-04 Project Theme"
        #verbose_name_plural = "My Custom Models"
        ordering = ["theme_id"]

"""
default - TextItemValue for name
    language - TextItemValue for name
    theme - TextItemValue for name
Client - TextItemValue for name
      ├── Language 
      ├── Theme          
      ├── Page - TextItemValue for name
        ├── Layout
        │         ├── HeroText   (only if type=text)
        │             └── TextContent
        │         ├── HeroFigure (only if type=figure)
        │         └── HeroCard
        │              ├── HeroCardFigure
        │              └── HeroCardText
        │                 └── TextContent
        │
        └── Card
           ├── CardFigure
           └── CardText
                └── TextContent

TextContent
 └── TextBlock (title / content / actbut)
      └── TextItem (text / svg / badge)
           └── TextItemValue (per language)
                        
"""


class Page(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    page_id = LowercaseCharField(max_length=10, unique=True)  
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=False, blank=False, default='page_name')      
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL)
    token = models.ForeignKey(
        Token,
        to_field='token_id', 
        on_delete=models.CASCADE,
        default='page_name',
        related_name='pages'
        )

    def __str__(self):
        return self.page_id

    # to get the name maintained
    def display_name(self, client_id="default", language_id="en", page_id="global"):
        return self.token.resolve_value(client_id=client_id, language_id=language_id, page_id=page_id) if self.token else None

    def display_all_names(self, client_id="default", page_id="global"):
        return self.token.resolve_all_values(client_id=client_id, page_id=page_id) if self.token else None

        
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-04 Project Page"
        #verbose_name_plural = "My Custom Models"
        ordering = ["page_id"]
"""
class Position(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    position_id = LowercaseCharField(max_length=10, unique=True)  
    ltext = models.CharField(max_length=50, null=True)
""" 

class Client(models.Model):
    #id = LowercaseCharField(max_length=25, primary_key=True)
    client_id = LowercaseCharField(max_length=25, unique=True)    
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=False, blank=False, default='client_name')

    token = models.ForeignKey(
        Token,
        to_field='token_id', 
        on_delete=models.CASCADE,
        default='client_name',
        related_name='clients'
        )


    parent = models.ForeignKey(
        "self",
        to_field="client_id",
        db_column="parent_client_id",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    # ManyToMany with ordering
    client_languages = models.ManyToManyField(
        "Language", through="ClientLanguage", related_name="clients"
    )

    client_themes = models.ManyToManyField(
        "Theme", through="ClientTheme", related_name="clients"
    )

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
    

    # to get the name maintained
    def display_name(self):
        return self.token.resolve_value(client_id=self.client_id, language_id="en", page_id="global") if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values(client_id=self.client_id, page_id="global") if self.token else None



    def get_ordered_language_ids(self):
        
        return list(
            self.client_languages_rel.all()
            .order_by("order")
            .values_list("language__language_id", flat=True)
        )
        
      
    def get_ordered_theme_ids(self):
        """
        Return a list of id values in the order defined by ClientTheme.order
        """
        return list(
            self.client_themes_rel.all()
            .order_by("order")
            .values_list("theme__theme_id", flat=True)
        )

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-05 Client"
        #verbose_name_plural = "My Custom Models"
        ordering = ["client_id"]
        indexes = [
            models.Index(fields=["client_id"]),
        ]

class ClientLanguage(models.Model):
    # client = models.ForeignKey("Client", on_delete=models.CASCADE, related_name="client_languages_rel")
    # language = models.ForeignKey("Language", on_delete=models.CASCADE, related_name="language_clients_rel")

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_languages_rel'
        )
    language = models.ForeignKey(
        Language,
        to_field='language_id', 
        on_delete=models.CASCADE,
        related_name='language_clients_rel'
        )

    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("client", "language")
        ordering = ["client", "order"]
        verbose_name = "01-01 Client Language"

    def __str__(self):
        return f"{self.client} - {self.language} (order {self.order})"
        #return f"{self.language} ({self.order})"

class ClientTheme(models.Model):
    #client = models.ForeignKey("Client", on_delete=models.CASCADE, related_name="client_themes_rel")
    #theme = models.ForeignKey("Theme", on_delete=models.CASCADE, related_name="theme_clients_rel")

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_themes_rel'
        )
    theme = models.ForeignKey(
        Theme,
        to_field='theme_id', 
        on_delete=models.CASCADE,
        related_name='theme_clients_rel'
        )

    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("client", "theme")        
        ordering = ["client", "order"]
        verbose_name = "01-02 Client Theme"

    def __str__(self):
        return f"{self.client.client_id} - {self.theme.theme_id} (order {self.order})"
        #return f"{self.language} ({self.order})"

class ClientPage(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_page'
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='client_page'
        )
    
    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True, db_index=True,
        editable=False
        ) # Just for reference

    order = models.PositiveIntegerField(default=0)

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("client", "page")        
        ordering = ["client", "order"]
        verbose_name = "01-03 Client Pages"

    def __str__(self):
        # return {self.comp_unique}
        return f"{self.client.client_id} - {self.page.page_id} (order {self.order})"
    
    def save(self, *args, **kwargs):
        # Combine the fields. Adding a UUID can help ensure uniqueness if inputs are similar
        combined_value = f"{self.client.client_id}-{self.page.page_id}" 
        self.comp_unique = combined_value

        # The super().save() call will attempt to save to the database.
        # If the combined_field value is not unique, an IntegrityError will be raised.
        try:
            super().save(*args, **kwargs)
        except models.IntegrityError:
            # Handle the error if a duplicate is found
            # You might want to retry with a new UUID or raise a ValidationError
            # For simplicity, we just reraise here.
            from django.core.exceptions import ValidationError
            raise ValidationError("The combined comp_unique value already exists.")

# This may be dropped
class TextStatic(models.Model):
    #client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="translations") # default, bahushira... 
    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='translations'
        )
    #token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="translations") # g_en, g_fr, g_client_name, g_light...
    token = models.ForeignKey(
        Token,
        to_field='token_id', 
        on_delete=models.CASCADE,
        related_name='translations'
        )    
    #language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.
    language = models.ForeignKey(
        Language,
        to_field='language_id', 
        on_delete=models.CASCADE,
        related_name='translations'
        )        
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='translations'
        )        
    value = models.CharField(max_length=255)

    class Meta:
        unique_together = ("client", "token", "language", "page")
        verbose_name = "00-06 TextStatic"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} {self.token_id} {self.page_id} [{self.language_id}] = {self.value}"       
        # for usage in Admin Panel

# This may be dropped
class Image(models.Model):
    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='images',
        default='default'
        )

    image_id = LowercaseCharField(max_length=25, null=False)    
    #language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.

    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        default='global'
        )        

    image_url = models.URLField(max_length=500)
    # image_field = models.ImageField()    # pillow needs to e installed for this. to be revisited
    alt = models.CharField(max_length=100, null=False)

    class Meta:
        unique_together = ("client", "image_id", "page")
        verbose_name = "00-07 Image"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["image_id", "client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} {self.image_id} {self.page_id} {self.alt}"       
        # for usage in Admin Panel        
# This may be dropped
class Svg(models.Model):
    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='svgs',
        default='default'
        )

    svg_id = LowercaseCharField(max_length=25, null=False)    
    #language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.

    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        default='global'
        )        

    svg_text = models.CharField(max_length=500, null=False)

    class Meta:
        unique_together = ("client", "svg_id", "page")
        verbose_name = "00-08 Svg"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["svg_id", "client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} {self.svg_id} {self.page_id} {self.svg_text}"       
        # for usage in Admin Panel        

"""

Layout @level 40
      ├── Hero
      │         ├── HeroText   (only if type=text)
      │             └── TextContent
      │         ├── HeroFigure (only if type=figure)
      │         └── HeroCard
      │              ├── HeroCardFigure
      │              └── HeroCardText
      │                 └── TextContent
      │
      └── Card
           ├── CardFigure
           └── CardText
                └── TextContent  
TextContent
 └── TextBlock (title / content / actbut)
      └── TextBlockItem (text / svg / badge)
           └── TextBlockItemValue (per language)
                        
"""

class TextContent(models.Model):
    hidden = models.BooleanField(default=False)
    ltext = models.CharField(max_length=50, null=True)   # Optional
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()

    content_object = GenericForeignKey('content_type', 'object_id')
    def __str__(self):
        return f"{self.id} {self.ltext}" 

class TextBlock(models.Model):
    textcontent = models.ForeignKey(TextContent, related_name="blocks", on_delete=models.CASCADE)
    BLOCK_TYPES = (
        ("title", "Title"),
        ("content", "Content"),
        ("actbut", "ActionButtons"),
    )    
    block_id = models.CharField(max_length=20, choices=BLOCK_TYPES, blank=False, null=False)    
    ltext = models.CharField(max_length=50, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    css_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        unique_together = ("textcontent", "block_id")
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
    ltext = models.CharField(max_length=50, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField()
    css_class = models.CharField(max_length=255, blank=True, null=True)
    svg_text = models.CharField(max_length=500, blank=True, null=True)
    def clean(self):
        if self.svg_text and not self.item_id == 'svg':
            raise ValidationError("SVG text is relevanr only if item_id is SVG")
    def __str__(self):
        return f"{self.item_id} {self.ltext} ({self.block.block_id})"                
        
class TextBlockItemValue(models.Model):
    item = models.ForeignKey(TextBlockItem, related_name="values", on_delete=models.CASCADE)
    hidden = models.BooleanField(default=False)
    language = models.ForeignKey(Language, on_delete=models.CASCADE)
    value = models.TextField
    def clean(self):
        if self.item.item_id == 'svg' and self.value:
            raise ValidationError("Text values are not RELEVANT for parent type SVG")
    class Meta:
        unique_together = ("item", "language")
# This is for level 10 to 40  ...
# Components like card, accordion 

class Layout(models.Model):

    client = models.ForeignKey(Client, to_field='client_id', on_delete=models.CASCADE)
    page = models.ForeignKey(Page, to_field='page_id', on_delete=models.CASCADE)
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

    def __str__(self):
        return f"{self.client.client_id} / {self.page.page_id} / {self.level} / {self.slug}"

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
    hero = models.OneToOneField(
        Hero,
        on_delete=models.CASCADE,
        related_name="herotext"
    )
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
    textcontent = models.OneToOneField(
        TextContent,
        null=True, blank=True,
        on_delete=models.CASCADE
    )

    class Meta:
        verbose_name = "01-05a1 HeroText"
        unique_together = ("hero", "type_id")


class HeroFigure(models.Model):
    hero = models.OneToOneField(
        Hero,
        on_delete=models.CASCADE,
        related_name="herofigure"
    )
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
    """
    image = models.OneToOneField(
        Image,
        on_delete=models.CASCADE,
        related_name="herofigureimages"
    )
    """
    css_class = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        verbose_name = "01-05a2 HeroFigure"  
        unique_together = ("hero", "type_id")

class HeroCard(models.Model):
    hero = models.OneToOneField(
        Hero,
        on_delete=models.CASCADE,
        related_name="herocard"
    )
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
    herocard = models.OneToOneField(
        HeroCard,
        on_delete=models.CASCADE,
        related_name="herocardtext"
    )
    ltext = models.CharField(max_length=50, blank=True, null=True)   # Optional
    hidden = models.BooleanField(default=False)
    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)
    textcontent = models.OneToOneField(
        TextContent,
        null=True, blank=True,
        on_delete=models.CASCADE
    )
    class Meta:
        verbose_name = "01-05a3a HeroCard Text"  


class HeroCardFigure(models.Model):
    herocard = models.OneToOneField(
        HeroCard,
        on_delete=models.CASCADE,
        related_name="herocardfigure"
    )
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
    """
    image = models.OneToOneField(
        Image,
        on_delete=models.CASCADE,
        related_name="herocardfigureimages"
    )
    """
    css_class = models.CharField(max_length=255, blank=True, null=True)  
    class Meta:
        verbose_name = "01-05a3b HeroCard Figure"  


class Card(models.Model):
    layout = models.OneToOneField(
        Layout,
        on_delete=models.CASCADE,
        related_name="card"
    )
    ltext = models.CharField(max_length=50, blank=True, null=True)   # e.g., "Country"
    css_class = models.CharField(max_length=255, blank=True, null=True)
    body_class = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        verbose_name = "01-05b Card" 
        

class CardFigure(models.Model):
    card = models.OneToOneField(
        Card,
        on_delete=models.CASCADE,
        related_name="cardfigure"
    )
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
    """
    image = models.OneToOneField(
        Image,
        on_delete=models.CASCADE,
        related_name="cardfigureimages"
    )
    """    

    css_class = models.CharField(max_length=255, blank=True, null=True)  


class CardText(models.Model):
    card = models.OneToOneField(
        Card,
        on_delete=models.CASCADE,
        related_name="cardtext"
    )
    ltext = models.CharField(max_length=50, null=True)   # Optional
    hidden = models.BooleanField(default=False)

    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES, blank=True, null=True)

    textcontent = models.OneToOneField(
        TextContent,
        null=True, blank=True,
        on_delete=models.CASCADE
    )


# TBD Accordion and Carousal...
