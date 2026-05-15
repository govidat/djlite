from django.db import models
from .base import (
    LowercaseCharField, default_languages, default_themes, text_field_validators
)
#from .global_config import (ThemePreset)
from django.conf import settings

class Client(models.Model):
    client_id = LowercaseCharField(max_length=25, unique=True, db_index=True)    

    parent = models.ForeignKey("self", null=True, blank=True, related_name="children", on_delete=models.CASCADE)
    language_list = models.JSONField(null = True, blank = True, default=default_languages, help_text="A JSON array of selected values from Language.")
    default_language = models.CharField(max_length=10, choices=settings.LANGUAGES, default=settings.LANGUAGE_CODE)
    theme_list = models.JSONField(null = True, blank = True, default=default_themes)
    # Add this to allow: client_instance.translations.all()
    #translations = GenericRelation(TextItemValue)
    #gentextblocks = GenericRelation(GentextBlock)
    # Translatable fields
    name = models.CharField(max_length=100, blank=True, null=True) # modeltranslation blank=True to be present 
    nb_title = models.CharField(max_length=100, blank=True, null=True) # modeltranslation blank=True to be present

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

    overrides = models.JSONField(blank=True, null=True)
    is_default = models.BooleanField(default=False)    

    # Translatable fields
    name = models.CharField(max_length=40, blank=True, null=True) # modeltranslation blank=True to be present

    def __str__(self):
        client_id = getattr(self.client, 'client_id', '?')
        return f"{client_id} / {self.theme_id}"        
        #return f"{self.client.client_id} / {self.theme_id}"
      
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

class ClientTemplate(models.Model):
    """
    Client-specific template fragments stored in DB.
    Overrides filesystem templates for catalogue components.
    Works exactly like PageContent but for reusable partials,
    not full pages.
    Which templates genuinely need client override
    High value — clients will actually want to customise these:
    Template key                Where to replace                                    What clients customise 
    catalogue_item_card         items_list.html — in the {% for item %} loop        Different fields shown, different layout per domain
    catalogue_filter_sidebar    page_catalogue_html.html and page_catalogue.html    Hide certain filter sections, reorder filterscatalogue_item_detail
    item_detail view            item_detail_wrapper                                 Completely different detail layout per domain

    Low value — leave as filesystem includes:
    Template                Why skip DB override
    catalogue_items_list    Just a grid wrapper + loop + pagination. Rarely needs client customisation. The card inside it is already overridable.
    catalogue_pagination    Pure navigation — no business logic. Same for all clients.
    navbar                  
    footer    

    """
    TEMPLATE_CHOICES = [
        ('catalogue_filter_sidebar', 'Catalogue: Filter Sidebar'),
        ('catalogue_item_card',      'Catalogue: Item Card'),
        ('catalogue_item_detail',    'Catalogue: Item Detail'),        
        ('catalogue_items_list',     'Catalogue: Items List'),
        ('catalogue_pagination',     'Catalogue: Pagination'),
        ('navbar',                   'Navbar'),
        ('footer',                   'Footer'),
    ]

    client          = models.ForeignKey(
        'mysite.Client', on_delete=models.CASCADE,
        related_name='templates'
    )
    template_key    = models.CharField(
        max_length=50, choices=TEMPLATE_CHOICES,
        help_text="Which template this overrides"
    )
    """
    language_code   = LowercaseCharField(
        max_length=10, default='en',
        help_text="Language this template variant serves. "
                  "Use 'all' to apply regardless of language."
    )
    html            = models.TextField(
        help_text="Django template HTML. Has access to all context variables."
    )
    """
    htmlblob      = models.TextField(blank=True, help_text="Django template HTML. Has access to all context variables.") # modeltranslation blank=True to be present    
    is_active       = models.BooleanField(default=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('client', 'template_key')
        ordering        = ['client', 'template_key']
        verbose_name = "00-03E Client Templates"
        verbose_name_plural = "00-03E Client Templates"
    def __str__(self):
        client_id = getattr(self.client, 'client_id', '?')
        return f"{client_id} / {self.template_key}"

# models/client_block.py

class ClientBlock(models.Model):

    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='blocks',
        null=True,
        blank=True,
        help_text="Leave empty to block ALL clients."
    )

    from_date = models.DateTimeField()
    to_date   = models.DateTimeField()

    remarks = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-from_date']
        verbose_name = "00-00 Client Block"
        verbose_name_plural = "00-00 Client Blocks"
        indexes = [
            models.Index(fields=['is_active', 'from_date', 'to_date']),
            models.Index(fields=['client']),
        ]        

    def __str__(self):

        target = (
            self.client.client_id
            if self.client else
            "ALL CLIENTS"
        )

        return (
            f"{target} "
            f"({self.from_date} → {self.to_date})"
        )