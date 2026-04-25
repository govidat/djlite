from django.db import models
from .base import (
    LowercaseCharField, text_field_validators
)
#from .global_config import (ThemePreset)

#from .page import (Layout)
from django.core.exceptions import ValidationError

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.fields import GenericRelation

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
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
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
    #zzlanguage = models.ForeignKey(Language, on_delete=models.CASCADE) 
    language_code = LowercaseCharField(max_length=2, blank=True)   # stores 'en', 'fr', 'hi' etc.
    stext = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    ltext = models.TextField(blank=True, validators=text_field_validators)
    def __str__(self):
        return f"{self.stext} / ({self.ltext})"
    class Meta:
        unique_together = ("textstbitem", "language_code" )
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
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
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
    # This is to be deprecated. Initially planned to use this for Page Name, Client name etc. Now modelTranslation is being used.
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
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=1)  # same block_id can be repeated
    css_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)
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
    
class Component(models.Model):
    """L0 — one per Layout cell (level=40)"""
    layout = models.OneToOneField(
        'mysite.Layout',
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
    ltext         = models.CharField(max_length=50, blank=True, validators=text_field_validators)
    css_class     = models.CharField(max_length=255, blank=True, validators=text_field_validators)
    card_body_class     = models.CharField(max_length=255, blank=True, validators=text_field_validators)    # card    
    hero_content_class     = models.CharField(max_length=255, blank=True, validators=text_field_validators)    # hero
    hero_overlay       = models.BooleanField(default=False)          # hero
    hero_overlay_style = models.CharField(max_length=255, blank=True, validators=text_field_validators)  # hero
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
    ltext       = models.CharField(max_length=50, blank=True, validators=text_field_validators)
    css_class   = models.CharField(max_length=255, blank=True, validators=text_field_validators)

    # Figure fields
    image_url   = models.URLField(max_length=500, blank=True, null=True)
    alt         = models.CharField(max_length=100, blank=True, null=True)
    figure_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)

    # Hero/Card slot specific
    actions_class = models.CharField(max_length=255, blank=True, validators=text_field_validators)

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

