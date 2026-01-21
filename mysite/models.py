from django.db import models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
import json

# Create your models here

class LowercaseCharField(models.CharField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return value.lower()
        return value
        
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
        to_field='tokentype_id', 
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
        verbose_name = "00-04 Project Theme"
        #verbose_name_plural = "My Custom Models"
        ordering = ["theme_id"]

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


    #Client model with tokenized name and location.
    #token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True, default='g_client_name')
    """    
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children"
    )
    """
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
    """
    def display_name(self):
        return self.token.resolve_value(self.client_id, "en", "global") if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values(self.client_id, "global" ) if self.token else None
    """
    # to get the name maintained
    def display_name(self):
        return self.token.resolve_value(client_id=self.client_id, language_id="en", page_id="global") if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values(client_id=self.client_id, page_id="global") if self.token else None



    def get_ordered_language_ids(self):
        """
        Return a list of id values in the order defined by ClientLanguage.order
        """
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
        """
        return list(
            self.client_themes.through.objects.filter(client=self)
            .order_by("order")
            .values_list("theme__id", flat=True)
        )  
        """      
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


# This is for level 10 to 40 captured as shell_id eg a, aa, aaa, aaaa, ...
# Components like card, accordion to have a foreign key link to SiteStructure
""" This is deprecated
class SiteStructure(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='sitestructures',
        blank=False, null=False
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='sitestructures',
        blank=False, null=False
        )
        
    # plan is 1 alpha for level 10, 20, 30 each and 2 alpha for 40    
    shell_id = models.CharField(max_length=5,blank=False, null=False)

    order = models.PositiveIntegerField(default=1,
        blank=False, null=False)
     
    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # for reference and programmatic upload of data

    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    # type_id is used at level 40
    TYPE_CHOICES = (
        ('hero', 'hero'),
        ('card', 'card'),
        ('accordion', 'accordion' ),
    )    
    
    type_id = models.CharField(
        max_length=30,choices=TYPE_CHOICES, 
        blank=True, null=True
    )  # hero / card / accordion / etc

    css_class = models.CharField(max_length=255,blank=True, null=True)
    style = models.CharField(max_length=255,blank=True, null=True)
    hidden = models.BooleanField(default=False)

    class Meta:
        unique_together = ("client", "page", "shell_id")        
        ordering = ["client", "page", "shell_id", "order"]
        verbose_name = "01-04 Client Site Structure"

    def __str__(self):
        return f"{self.client.client_id} - {self.page.page_id} - {self.shell_id}"

    def clean(self):
        if self.type_id and len(self.shell_id) < 4:
            raise ValidationError("Only level 40 nodes can have type")

        if len(self.shell_id) > 3 and not self.type_id:
            raise ValidationError("Level 40 nodes must have a type")

    def save(self, *args, **kwargs):
        # Combine the fields. Adding a UUID can help ensure uniqueness if inputs are similar
        combined_value = f"{self.client.client_id}-{self.page.page_id} - {self.shell_id}" 
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

class Hero(models.Model):
    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='heros',
        blank=False, null=False
        )
    sitestructure = models.OneToOneField(
        SiteStructure,
        on_delete=models.CASCADE,
        related_name="heros"
    )

    css_class = models.CharField(max_length=255,blank=True, null=True)
    herocontent_css_class = models.CharField(max_length=255,blank=True, null=True)

    overlay = models.BooleanField(default=False)
    overlay_style = models.CharField(max_length=255,blank=True, null=True)

    class Meta:
        unique_together = ("client", "sitestructure")        
        ordering = ["client", "sitestructure"]
        verbose_name = "01-05 Hero Structure"
   
    def __str__(self):
        return f"{self.sitestructure.comp_unique}"

    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # for reference and programmatic upload of data    

    @property
    def level(self):
        lv_length = len(self.shell_id)
        if lv_length == 1:
            return 10
        if lv_length == 2:
            return 20
        if lv_length == 3:
            return 30
        return 40
    
    def clean(self):
        if self.level != 40:
            raise ValidationError("Can have a foreign key relationship only with Level 40 SiteStructure")

        if self.client_id != self.sitestructure.client_id:
            raise ValidationError("SiteStructure Foreign key to be of same Client")    

    def save(self, *args, **kwargs):
        self.comp_unique = self.sitestructure.comp_unique

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
        
class HeroContent(models.Model):
    client = models.ForeignKey(
        Client,
        to_field="client_id",
        on_delete=models.CASCADE,
        related_name="herocontents"
    )    

    hero = models.ForeignKey(
        Hero,
        on_delete=models.CASCADE,
        related_name="herocontents"
    )
    CONTENT_TYPES = (
        ("text", "Text"),
        ("figure", "Figure"),
        ("card", "Card"),
    )
    type_id = models.CharField(max_length=10, choices=CONTENT_TYPES)
    order = models.PositiveIntegerField(default=1,
        blank=False, null=False)
    hidden = models.BooleanField(default=False)

    css_class = models.CharField(max_length=255, blank=True, null=True)
    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # for reference and programmatic upload of data 

    # If type is Card, then only additional piece of info required is card_id. hence including this field here itself    \
    # TBD Whether this should be a foreign key on Card Model is a decision point
    card_id = models.PositiveIntegerField(blank=True, null=True)
        
        
    class Meta:
        ordering = ["client", "hero"]
        verbose_name = "01-05b Hero Content"
   
    def __str__(self):
        return f"{self.client.client_id} - {self.hero.sitestructure.shell_id} - {self.type_id} - {self.order}" 

    def clean(self):
        if self.client_id != self.hero.client_id:
            raise ValidationError("Hero Foreign key to be of same Client")   
        if self.type_id == 'card' and not self.card_id:
           raise ValidationError("Card Type needs to have a card_id value")

    def save(self, *args, **kwargs):
        # Combine the fields. 
        combined_value = f"{self.hero.comp_unique} - {self.hidden} - {self.order}" 
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
                    
class HeroFigure(models.Model):
    client = models.ForeignKey(
        Client,
        to_field="client_id",
        on_delete=models.CASCADE,
        related_name="herofigures"
    )    
    herocontent = models.OneToOneField(
        HeroContent,
        on_delete=models.CASCADE,
        related_name="herofigures"
    )

    figure_class = models.CharField(max_length=255, blank=True, null=True)
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES)
    
    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        related_name="heroimages"
    )
    
    css_class = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        ordering = ["client", "herocontent"]
        verbose_name = "01-05ba Hero Content Figure"

    def __str__(self):
        return f"{self.client.client_id} - {self.herocontent.hero.sitestructure.shell_id} - {self.image.image_id}" 

    def clean(self):
        if self.client_id != self.herocontent.client_id:
            raise ValidationError("HeroContent Foreign key to be of same Client")        
        if self.client_id != self.image.client_id:
            raise ValidationError("Image Foreign key to be of same Client")        

class HeroText(models.Model):
    client = models.ForeignKey(
        Client,
        to_field="client_id",
        on_delete=models.CASCADE,
        related_name="herotexts"
    )    
    herocontent = models.OneToOneField(
        HeroContent,
        on_delete=models.CASCADE,
        related_name="herotexts"
    )

    title_class = models.CharField(max_length=255, blank=True, null=True)
    title_stb_ids = models.JSONField(default=list)
    contents_class = models.CharField(max_length=255, blank=True, null=True)
    contents_stb_ids = models.JSONField(default=list)

    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES)

    # a max of 4 buttons possible
    button01_class = models.CharField(max_length=255, blank=True, null=True)
    button01_stb_ids = models.JSONField(default=list)
    button02_class = models.CharField(max_length=255, blank=True, null=True)
    button02_stb_ids = models.JSONField(default=list)
    button03_class = models.CharField(max_length=255, blank=True, null=True)
    button03_stb_ids = models.JSONField(default=list)
    button04_class = models.CharField(max_length=255, blank=True, null=True)
    button04_stb_ids = models.JSONField(default=list)

    class Meta:
        ordering = ["client", "herocontent"]
        verbose_name = "01-05bc Hero Content Text"

    def __str__(self):
        return f"{self.client.client_id} - {self.herocontent.hero.sitestructure.shell_id}" 
        
    def clean(self):
        if self.client_id != self.herocontent.client_id:
            raise ValidationError("HeroContent Foreign key to be of same Client")  

"""
"""
class ComposedText(models.Model):
    #ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"

    title_class = models.CharField(max_length=255, blank=True, null=True)
    title_stb_ids = models.JSONField(default=list)
    contents_class = models.CharField(max_length=255, blank=True, null=True)
    contents_stb_ids = models.JSONField(default=list)

    actions_class = models.CharField(max_length=255, blank=True, null=True)        
    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    actions_position_id = models.CharField(max_length=20, choices=POSITION_TYPES)

    # a max of 4 buttons possible
    button01_class = models.CharField(max_length=255, blank=True, null=True)
    button01_stb_ids = models.JSONField(default=list)
    button02_class = models.CharField(max_length=255, blank=True, null=True)
    button02_stb_ids = models.JSONField(default=list)
    button03_class = models.CharField(max_length=255, blank=True, null=True)
    button03_stb_ids = models.JSONField(default=list)
    button04_class = models.CharField(max_length=255, blank=True, null=True)
    button04_stb_ids = models.JSONField(default=list)

class ComposedFigure(models.Model):
    #ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"
    figure_class = models.CharField(max_length=255, blank=True, null=True)

    POSITION_TYPES = (
        ("start", "Start"),
        ("end", "End"),
    )    
    position_id = models.CharField(max_length=20, choices=POSITION_TYPES)
    
    image = models.ForeignKey(
        Image,
        on_delete=models.CASCADE,
        related_name="heroimages"
    )
    
    css_class = models.CharField(max_length=255, blank=True, null=True)

class Card(models.Model):
    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='cardststics'
        )

    card_id = LowercaseCharField(max_length=25, null=False)    
    #language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.

    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        default='global'
        )        
    ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"

    class Meta:
        unique_together = ("client", "page", "card_id")
        verbose_name = "00-08 Card"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["card_id", "client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} / {self.page_id} / {self.card_id} / {self.ltext}"       
        # for usage in Admin Panel   

class CardText(models.Model):
    card = models.OneToOneField(
        Card,
        on_delete=models.CASCADE,
        related_name="cardtexts"
    )
    composedtext = models.OneToOneField(
        ComposedText,
        on_delete=models.CASCADE,
        related_name="cardtexts"
    )    
    #ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"

class CardFigure(models.Model):
    card = models.OneToOneField(
        Card,
        on_delete=models.CASCADE,
        related_name="cardfigures"
    )
    composedfigure = models.OneToOneField(
        ComposedFigure,
        on_delete=models.CASCADE,
        related_name="cardfigures"
    )    

    #ltext = models.CharField(max_length=50, null=True)   # e.g., "Country"

class LayoutNode(models.Model):

    client = models.ForeignKey(Client, to_field='client_id', on_delete=models.CASCADE)
    page = models.ForeignKey(Page, to_field='page_id', on_delete=models.CASCADE)
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

    css_class = models.CharField(max_length=255, blank=True)
    style = models.CharField(max_length=255, blank=True)
    hidden = models.BooleanField(default=False)

    slug = models.SlugField()  # for bulk upload / human reference

    class Meta:
        ordering = ("client", "page", "level", "order")
        unique_together = ("client", "page", "level", "slug")

    def __str__(self):
        return f"{self.client.client_id} / {self.page.page_id} / {self.level} / {self.slug}"
    
class Component(models.Model):
    layoutnode = models.OneToOneField(
        LayoutNode,
        on_delete=models.CASCADE,
        related_name="component"
    )

    COMPONENT_TYPES = (
        ("hero", "Hero"),
        ("card", "Card"),
        ("accordion", "Accordion"),
        ("carousel", "Carousel"),
    )
    type = models.CharField(max_length=30, choices=COMPONENT_TYPES)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(layout__level=40),
                name="component_only_on_level_40",
            )
        ]

    def __str__(self):
        return f"{self.type} @ {self.layout.slug}"
    
class Hero(models.Model):
    component = models.OneToOneField(
        Component,
        on_delete=models.CASCADE,
        related_name="hero"
    )

    css_class = models.CharField(max_length=255, blank=True)
    overlay = models.BooleanField(default=False)
    overlay_style = models.CharField(max_length=255, blank=True)

class HeroContent(models.Model):
    hero = models.ForeignKey(
        Hero,
        on_delete=models.CASCADE,
        related_name="herocontents"
    )

    order = models.PositiveIntegerField()
    hidden = models.BooleanField(default=False)

    CONTENT_TYPES = (
        ("text", "Text"),
        ("figure", "Figure"),
        ("card", "Card"),
    )
    type = models.CharField(max_length=10, choices=CONTENT_TYPES)
    # TBD Whether this should be a foreign key on Card Model is a decision point
    #card_id = models.PositiveIntegerField(blank=True, null=True)

    card = models.ForeignKey(
        Card,
        on_delete=models.CASCADE,
        related_name="herocards"
    )

    def clean(self):
        if self.type_id == 'card' and not self.card:
           raise ValidationError("Card Type needs to have a Card value")

        if self.hero.component.layoutnode.client.client_id != self.card.client.client_id:
            raise ValidationError("Card Foreign key to be of same Client")  

    class Meta:
        ordering = ("order",)

class HeroText(models.Model):
    herocontent = models.OneToOneField(
        HeroContent,
        on_delete=models.CASCADE,
        related_name="herotexts"
    )
    composedtext = models.OneToOneField(
        ComposedText,
        on_delete=models.CASCADE,
        related_name="herotexts"
    )    


class HeroFigure(models.Model):
    herocontent = models.OneToOneField(
        HeroContent,
        on_delete=models.CASCADE,
        related_name="herofigures"
    )
    composedfigure = models.OneToOneField(
        ComposedFigure,
        on_delete=models.CASCADE,
        related_name="herofigures"
    )  
"""      
