from django.db import models
from django.core.exceptions import ValidationError

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

"""
class ClientNavbar(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_navbar_rel'
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='page_navbar_rel'
        )
    order = models.PositiveIntegerField(default=0)

    parent = models.ForeignKey(
        "self",
        to_field="page_id",
        db_column="parent_page_id",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("client", "page")        
        ordering = ["client", "order"]
        verbose_name = "01-03 Client Navbar item"

    def __str__(self):
        #return f"{self.client_page} (order {self.order})"
        return f"{self.client.client_id} - {self.page.page_id} (order {self.order})"
"""

# A new auto filled field of client-page is created. parent child relationship is created on this field
class ClientNavbar(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_navbar_rel'
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='page_navbar_rel'
        )
    
    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # Needs to be nullable/blank if not generated on every save

    order = models.PositiveIntegerField(default=0)

    parent = models.ForeignKey(
        "self",
        to_field="comp_unique",
        db_column="parent_comp_unique",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("client", "page")        
        ordering = ["client", "order"]
        verbose_name = "01-03 Client Navbar item"

    def __str__(self):
        return f"{self.comp_unique} (order {self.order})"
        #return f"{self.client.client_id} - {self.page.page_id} (order {self.order})"
    
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
"""   
class ClientNavbar2(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_navbar_rel2'
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='page_navbar_rel2'
        )
    
    comp_unique = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # Needs to be nullable/blank if not generated on every save

    order = models.PositiveIntegerField(default=0)

    parent = models.ForeignKey(
        "self",
        to_field="comp_unique",
        db_column="parent_comp_unique",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("client", "page")        
        ordering = ["client", "order"]
        verbose_name = "01-03 Client Navbar2 item"

    def __str__(self):
        return f"{self.comp_unique} (order {self.order})"
        #return f"{self.client.client_id} - {self.page.page_id} (order {self.order})"
    
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
"""    
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


class ImageStatic(models.Model):
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
        verbose_name = "00-07 ImageStatic"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["image_id", "client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} {self.image_id} {self.page_id} {self.alt}"       
        # for usage in Admin Panel        

class SvgStatic(models.Model):
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
        verbose_name = "00-08 SvgStatic"
        #verbose_name_plural = "My Custom Models" 
        indexes = [
            models.Index(fields=["svg_id", "client"]),
        ]
    def __str__(self):
        return f"{self.client.client_id} {self.svg_id} {self.page_id} {self.svg_text}"       
        # for usage in Admin Panel        
"""
# A new auto filled field of client-page is created. parent child relationship is created on this field
class SiteStructure(models.Model):

    client = models.ForeignKey(
        Client,
        to_field='client_id', 
        on_delete=models.CASCADE,
        related_name='client_sitestructure_rel'
        )
    page = models.ForeignKey(
        Page,
        to_field='page_id', 
        on_delete=models.CASCADE,
        related_name='page_sitestructure_rel'
        )
    CHOICES = (
        (10, '10'),
        (20, '20'),
        (30, '30'),
        (40, '40'),
    )
    order = models.PositiveIntegerField(default=0)

    level = models.IntegerField(choices=CHOICES, default=10)
    
    calc_field = models.CharField(
        max_length=40, 
        unique=True, blank=True, null=True
        ) # Needs to be nullable/blank if not generated on every save

    parent = models.ForeignKey(
        "self",
        to_field="calc_field",
        db_column="parent_calc_field",
        null=True,
        blank=True,
        related_name="children",
        on_delete=models.CASCADE
    )

    class Meta:
        unique_together = ("client", "page")        
        ordering = ["client", "order"]
        verbose_name = "01-03 Client Navbar item"

    def __str__(self):
        return f"{self.client_page} (order {self.order})"
        #return f"{self.client.client_id} - {self.page.page_id} (order {self.order})"
    
    def save(self, *args, **kwargs):
        # Combine the fields. Adding a UUID can help ensure uniqueness if inputs are similar
        combined_value = f"{self.client.client_id}-{self.page.page_id}" 
        self.client_page = combined_value

        # The super().save() call will attempt to save to the database.
        # If the combined_field value is not unique, an IntegrityError will be raised.
        try:
            super().save(*args, **kwargs)
        except models.IntegrityError:
            # Handle the error if a duplicate is found
            # You might want to retry with a new UUID or raise a ValidationError
            # For simplicity, we just reraise here.
            from django.core.exceptions import ValidationError
            raise ValidationError("The combined client_page value already exists.")
    
"""