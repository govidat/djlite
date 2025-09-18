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
    id = LowercaseCharField(max_length=20, primary_key=True)   # e.g., "country"
    name = models.CharField(max_length=50, unique=True)   # e.g., "Country" 
    is_global = models.BooleanField(default=False)        # Global and it means it is centrally maintained? if True, then the Token name should be g_, else l_. g_ values can be part of the code itself.
    # for usage in Admin Panel
    class Meta:
        ordering = ["id"]
        verbose_name = "00-01 Token Type"
        #verbose_name_plural = "My Custom Models"

    def __str__(self):
        return f"{self.name} ({self.id})"
   
 
class Token(models.Model):
    id = LowercaseCharField(max_length=25, primary_key=True)   # user enters e.g. "g_india" or "l_client_name"
    tokentype = models.ForeignKey(TokenType, on_delete=models.PROTECT)
    # tokens can have a parent relationship like Chennai > Tamilnadu > India
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children"
    )
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Token"
        #verbose_name_plural = "My Custom Models"

    def clean(self):
        #Validate prefix based on type.is_global
        if self.tokentype.is_global and not self.id.startswith("g_"):
            raise ValidationError("Global tokens must start with 'g_'.")
        if not self.tokentype.is_global and not self.id.startswith("l_"):
            raise ValidationError("Local tokens must start with 'l_'.")

    def save(self, *args, **kwargs):
        # Ensure validation runs also when saving programmatically
        self.full_clean()
        super().save(*args, **kwargs)

    # Optional convenience helper:

    def resolve_value(self, client="default", language="en"):
        if isinstance(client, str):
            client = Client.objects.get(pk=client)
        if isinstance(language, str):
            language = Language.objects.get(pk=language)

        return Translation.objects.filter(
            client=client, token=self, language=language
        ).values_list("value", flat=True).first()        
    
    """ alternative way 
    def resolve_value(self, client_id="default", lang_id="en"):
        try:
            return self.translations.get(client__id=client_id, language__id=lang_id).value
        except Translation.DoesNotExist:
            return None   # or fallback to default client/lang    
    """    
    def resolve_all_values(self, client='default'):
        if isinstance(client, str):
            client = Client.objects.get(pk=client)
        #Return a dict {language_code: value} for this token for the given client,
        #only including languages that actually have translations.
        
        qs = Translation.objects.filter(client=client, token=self)
        values = {tr.language.pk: tr.value for tr in qs}

        return values        


    def __str__(self):
        return self.id
     
"""
class TypedTokenForeignKey(models.ForeignKey):
    
    #A ForeignKey to Token that also stores which TokenType it should allow.

    def __init__(self, to="Token", *args, tokentype=None, **kwargs):
        self.tokentype = tokentype
        # Always point to Token model
        super().__init__(to, *args, **kwargs)


class TypedTokenForeignKey(models.ForeignKey):
    
    #Custom ForeignKey to Token that remembers which TokenType it belongs to.
    #This makes the Django admin dropdown automatically filter tokens.
    
    def __init__(self, to="Token", *args, tokentype=None, **kwargs):
        self.tokentype = tokentype
        # always point to Token
        super().__init__(to, *args, **kwargs)

    def deconstruct(self):
        
        #Needed so Django migrations know how to serialize this field.
        
        name, path, args, kwargs = super().deconstruct()
        if self.tokentype is not None:
            kwargs["tokentype"] = self.tokentype
        return name, path, args, kwargs
"""
class Language(models.Model):
    id = LowercaseCharField(max_length=2, primary_key=True)
    token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.id

    # to get the name maintained for default client
    """
    def display_name(self):
        return self.token.resolve_value() if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values() if self.token else None
    """
    def display_name(self, client="default", language="en"):
        return self.token.resolve_value(client=client, language=language) if self.token else None

    def display_all_names(self, client="default"):
        return self.token.resolve_all_values(client=client) if self.token else None

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-03 Project Language"
        #verbose_name_plural = "My Custom Models"
        ordering = ["id"]

class Theme(models.Model):
    id = LowercaseCharField(max_length=20, primary_key=True)
    token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.id

    # to get the name maintained for default client
    """
    def display_name(self):
        return self.token.resolve_value() if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values() if self.token else None
    """
    def display_name(self, client="default", language="en"):
        return self.token.resolve_value(client=client, language=language) if self.token else None

    def display_all_names(self, client="default"):
        return self.token.resolve_all_values(client=client) if self.token else None    
        
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-04 Project Theme"
        #verbose_name_plural = "My Custom Models"
        ordering = ["id"]

class Client(models.Model):
    id = LowercaseCharField(max_length=25, primary_key=True)

    #Client model with tokenized name and location.
    token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True, default='g_client_name')
    
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children"
    )

    # ManyToMany with ordering
    client_languages = models.ManyToManyField(
        "Language", through="ClientLanguage", related_name="clients"
    )

    client_themes = models.ManyToManyField(
        "Theme", through="ClientTheme", related_name="clients"
    )

    def __str__(self):
        return self.id

    # if a Model has a recursive relationship and its parent is maintained in the same row
    def get_ancestors(self):
        #Return all ancestors (parent, grandparent, ...) as a list.#
        ancestors = []
        current = self.parent
        while current is not None:
            ancestors.append(str(current.id))
            current = current.parent
        return ancestors  
     
    def get_descendants(self):
        #Return all descendants (children, grandchildren, ...) as a list of clients.
        descendants = []

        def collect_children(node):
            for child in node.children.all():
                descendants.append(str(child.id))
                collect_children(child)

        collect_children(self)
        return descendants     
    
    # to get the name maintained 

    def display_name(self):
        return self.token.resolve_value(self.id, "en") if self.token else None

    def display_all_names(self):
        return self.token.resolve_all_values(self.id) if self.token else None

    def get_ordered_language_ids(self):
        """
        Return a list of id values in the order defined by ClientLanguage.order
        """
        return list(
            self.client_languages_rel.all()
            .order_by("order")
            .values_list("language__id", flat=True)
        )
        
      
    def get_ordered_theme_ids(self):
        """
        Return a list of id values in the order defined by ClientTheme.order
        """
        return list(
            self.client_themes_rel.all()
            .order_by("order")
            .values_list("theme__id", flat=True)
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
        ordering = ["id"]

class ClientLanguage(models.Model):
    client = models.ForeignKey("Client", on_delete=models.CASCADE, related_name="client_languages_rel")
    language = models.ForeignKey("Language", on_delete=models.CASCADE, related_name="language_clients_rel")
    
    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("client", "language")
        ordering = ["order"]

    def __str__(self):
        return f"{self.client.id} - {self.language.id} (order {self.order})"
        #return f"{self.language} ({self.order})"

class ClientTheme(models.Model):
    client = models.ForeignKey("Client", on_delete=models.CASCADE, related_name="client_themes_rel")
    theme = models.ForeignKey("Theme", on_delete=models.CASCADE, related_name="theme_clients_rel")

    order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("client", "theme")        
        ordering = ["order"]

    def __str__(self):
        return f"{self.client.id} - {self.theme.id} (order {self.order})"
        #return f"{self.language} ({self.order})"


class Translation(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="translations") # default, bahushira... 
    token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="translations") # g_en, g_fr, g_client_name, g_light...
    language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.
    value = models.CharField(max_length=255)

    class Meta:
        unique_together = ("client", "token", "language")
        verbose_name = "00-06 Translation"
        #verbose_name_plural = "My Custom Models" 

    def __str__(self):
        return f"{self.client.id} {self.token.id} [{self.language.id}] = {self.value}"       
        # for usage in Admin Panel
