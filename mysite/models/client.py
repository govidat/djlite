from django.db import models
from .base import (
    LowercaseCharField, default_languages, default_themes, text_field_validators
)
#from .global_config import (ThemePreset)

class Client(models.Model):
    client_id = LowercaseCharField(max_length=25, unique=True, db_index=True)    

    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    language_list = models.JSONField(null = True, blank = True, default=default_languages, help_text="A JSON array of selected values from Language.")
    theme_list = models.JSONField(null = True, blank = True, default=default_themes)
    # Add this to allow: client_instance.translations.all()
    #translations = GenericRelation(TextItemValue)
    #gentextblocks = GenericRelation(GentextBlock)
    # Translatable fields
    name = models.CharField(max_length=100, blank=True, null=True)
    nb_title = models.CharField(max_length=100, blank=True, null=True) 

    nb_title_svg_pre = models.CharField(max_length=500, blank=True, null=True)
    nb_title_svg_suf = models.CharField(max_length=500, blank=True, null=True)

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
        permissions = [
            ('view_client_data',   'Can view client data'),
            ('edit_client_data',   'Can edit client data'),
            ('create_client_data', 'Can create client data'),
            ('admin_client_data',  'Can admin client — manage users'),
        ]

class Theme(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='themes')    
    theme_id = LowercaseCharField(max_length=10)  
    themepreset = models.ForeignKey('mysite.ThemePreset', on_delete=models.SET_NULL, null=True)
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    hidden = models.BooleanField(default=False)
    # Add this to allow: client_instance.translations.all()
    #gentextblocks = GenericRelation(GentextBlock)
    overrides = models.JSONField(blank=True, null=True)
    is_default = models.BooleanField(default=False)    

    # Translatable fields
    name = models.CharField(max_length=40, blank=True, null=True)


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
        verbose_name = "00-03-01 Theme"
