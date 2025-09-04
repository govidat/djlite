from django.db import models
from django.core.exceptions import ValidationError

# Create your models here

class LowercaseCharField(models.CharField):
    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is not None:
            return value.lower()
        return value
    
class Tokentype(models.Model):
    
    # Categorizes tokens: global_text, local_text, language_name, theme_name, Country, State, City, Currency, etc.
    id_tokentype = LowercaseCharField(max_length=20, primary_key=True)   # e.g., "country"
    name = models.CharField(max_length=50, unique=True)   # e.g., "Country" 
    is_global = models.BooleanField(default=False)        # Global and it means it is centrally maintained? if True, then the Token name should be g_, else l_. g_ values can be part of the code itself.
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-01 Token Type"
        #verbose_name_plural = "My Custom Models"

    def __str__(self):
        return self.name
    
class Token(models.Model):
    id_token = LowercaseCharField(max_length=25, primary_key=True)   # user enters e.g. "g_india" or "l_client_name"
    id_tokentype = models.ForeignKey(Tokentype, on_delete=models.PROTECT)
    # tokens can have a parent relationship like Chennai > Tamilnadu > India
    id_parent = models.ForeignKey(
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
        if self.id_tokentype.is_global and not self.id_token.startswith("g_"):
            raise ValidationError("Global tokens must start with 'g_'.")
        if not self.id_tokentype.is_global and not self.id_token.startswith("l_"):
            raise ValidationError("Local tokens must start with 'l_'.")

    def save(self, *args, **kwargs):
        # Ensure validation runs also when saving programmatically
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.id_token

class Maxlanguage(models.Model):
    id_language = LowercaseCharField(max_length=2, primary_key=True)
    name = models.CharField(max_length=50)
    def __str__(self):
        return f"{self.name} ({self.id_language})"
    
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-00 Maximum Project Language"
        #verbose_name_plural = "My Custom Models"
        
"""
class TypedTokenForeignKey(models.ForeignKey):
    
    #A ForeignKey to Token that also stores which TokenType it should allow.

    def __init__(self, to="Token", *args, id_tokentype=None, **kwargs):
        self.id_tokentype = id_tokentype
        # Always point to Token model
        super().__init__(to, *args, **kwargs)


class TypedTokenForeignKey(models.ForeignKey):
    
    #Custom ForeignKey to Token that remembers which TokenType it belongs to.
    #This makes the Django admin dropdown automatically filter tokens.
    
    def __init__(self, to="Token", *args, id_tokentype=None, **kwargs):
        self.id_tokentype = id_tokentype
        # always point to Token
        super().__init__(to, *args, **kwargs)

    def deconstruct(self):
        
        #Needed so Django migrations know how to serialize this field.
        
        name, path, args, kwargs = super().deconstruct()
        if self.id_tokentype is not None:
            kwargs["id_tokentype"] = self.id_tokentype
        return name, path, args, kwargs
"""
class Language(models.Model):
    id_language = LowercaseCharField(max_length=2, primary_key=True)
    language_name_token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True)

    #language_name_token = TypedTokenForeignKey(
    #    on_delete=models.SET_NULL,
    #    null=True, blank=True,
    #    related_name="language_name",
    #    id_tokentype="language_name"
    #)    
    def __str__(self):
        return self.id_language
    
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-03 Project Language"
        #verbose_name_plural = "My Custom Models"

class Theme(models.Model):
    id_theme = LowercaseCharField(max_length=20, primary_key=True)
    theme_name_token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.id_theme
    
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-04 Project Theme"
        #verbose_name_plural = "My Custom Models"

class Client(models.Model):
    id_client = LowercaseCharField(max_length=25, primary_key=True)

    #Client model with tokenized name and location.
    client_name_token = models.ForeignKey(Token, on_delete=models.SET_NULL, null=True, blank=True, default='g_client_name')
    id_parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children"
    )
    # Many-to-many fields (admin will show multi-select box)
    client_languages = models.ManyToManyField("Language", related_name="clients", blank=True)
    client_themes = models.ManyToManyField("Theme", related_name="clients", blank=True)    

    def __str__(self):
        return self.id_client

    # if a Model has a recursive relationship and its id_parent is maintained in the same row
    def get_ancestors(self):
        #Return all ancestors (parent, grandparent, ...) as a list.#
        ancestors = []
        current = self.id_parent
        while current is not None:
            ancestors.append(str(current.id_client))
            current = current.id_parent
        return ancestors  
     
    def get_descendants(self):
        #Return all descendants (children, grandchildren, ...) as a list of id_clients.
        descendants = []

        def collect_children(node):
            for child in node.children.all():
                descendants.append(str(child.id_client))
                collect_children(child)

        collect_children(self)
        return descendants     
    
    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-05 Client"
        #verbose_name_plural = "My Custom Models"

"""
class Translation(models.Model):
    
    #Stores translations of token values in different languages.
    id_client = 
    id_token = models.ForeignKey(Token, on_delete=models.CASCADE, related_name="translations") # g_en, g_fr, g_client_name, g_light...
    id_language = models.ForeignKey(Language, on_delete=models.CASCADE)  # "en", "fr", etc.
    value = models.CharField(max_length=255)

    class Meta:
        unique_together = ("token", "language_code")

    def __str__(self):
        return f"{self.token.key} [{self.language_code}] = {self.value}"       
        # for usage in Admin Panel
    class Meta:
        verbose_name = "00-04 Translation"
        #verbose_name_plural = "My Custom Models"     
"""        