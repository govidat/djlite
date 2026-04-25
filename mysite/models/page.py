from django.db import models
from .base import (
    LowercaseCharField, text_field_validators
)
#from .global_config import (ThemePreset)
#from .client import (Client)
from django.core.exceptions import ValidationError

class Page(models.Model):
    #id = LowercaseCharField(max_length=20, primary_key=True)
    client = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='pages'
        )    
    page_id = LowercaseCharField(max_length=10)  
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
    order = models.PositiveIntegerField(default=0)
    parent = models.ForeignKey("self", null=True, blank=True, related_name="children",
        on_delete=models.CASCADE
    )
    hidden = models.BooleanField(default=False)  
    #gentextblocks = GenericRelation(GentextBlock)
    # Translatable fields
    name = models.CharField(max_length=40, blank=True, null=True)

    def __str__(self):
        return f"{self.client.client_id} / {self.page_id}"
      
    # for usage in Admin Panel
    class Meta:
        unique_together = ("client", "page_id")
        ordering = ["client", "order"]
        indexes = [
            models.Index(fields=["client", "order"]),
        ]
        verbose_name = "00-03-02 Page"

class NavItem(models.Model):
    NAV_TYPES = [
        ('page',     'Internal Page'),
        ('url',      'External URL'),
        ('anchor',   'Anchor (#section)'),
        ('label',    'Label only (no link)'),  # dropdown header
    ]
    LOCATION_CHOICES = [
        ('header', 'Header / Appbar'),
        ('footer', 'Footer'),
        ('sidebar', 'Sidebar'),
    ]

    client      = models.ForeignKey('mysite.Client', on_delete=models.CASCADE,
                                    related_name='nav_items')
    parent      = models.ForeignKey('self', null=True, blank=True,
                                    on_delete=models.CASCADE,
                                    related_name='children')
    location    = models.CharField(max_length=20, choices=LOCATION_CHOICES,
                                   default='header')
    nav_type    = models.CharField(max_length=10, choices=NAV_TYPES,
                                   default='page')

    # If nav_type = 'page'
    page        = models.ForeignKey(Page, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name='nav_items')

    # If nav_type = 'url' or 'anchor'
    url         = models.CharField(max_length=500, blank=True)

    # Display
    name       = LowercaseCharField(max_length=100)   # modeltranslation expands this
    order       = models.PositiveIntegerField(default=0)
    hidden      = models.BooleanField(default=False)
    open_in_new_tab = models.BooleanField(default=False)
    svg_pre = models.CharField(max_length=500, blank=True, null=True)
    svg_suf = models.CharField(max_length=500, blank=True, null=True)    

    class Meta:
        ordering        = ['client', 'location', 'order']
        unique_together = ('client', 'location', 'parent', 'order')
        verbose_name = "00-03-03 NavItem"

    def get_url(self, client_id):
        if self.nav_type == 'page' and self.page:
            return self.page.page_id
        if self.nav_type in ('url', 'anchor'):
            return self.url
        return '#'   # label-only — no navigation

    def __str__(self):
        return f"{self.client.client_id} / {self.location} / {self.name}"

class PageContent(models.Model):
    """
    Track A — raw HTML page authoring.
    One row per page per language. Rendered directly via |safe.
    Checked before the component tree in ClientPageView.
    """
    page          = models.ForeignKey(
        Page,
        on_delete=models.CASCADE,
        related_name='contents'
    )
    language_code = LowercaseCharField(max_length=2, blank=False, null=False, default='en')   # stores 'en', 'fr', 'hi' etc.
    html          = models.TextField()

    class Meta:
        unique_together = ('page', 'language_code')
        ordering        = ['page', 'language_code']
        verbose_name    = '01-02 Page Content (HTML)'

    def __str__(self):
        return f"{self.page} / {self.language_code}"
    
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

