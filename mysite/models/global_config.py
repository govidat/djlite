from django.db import models
from .base import (
    LowercaseCharField,
    text_field_validators,
)
from django.utils.translation import gettext_lazy as _

class ThemePreset(models.Model):
    themepreset_id = LowercaseCharField(max_length=25, unique=True, db_index=True)
    ltext = models.CharField(max_length=50, blank=True, validators=text_field_validators)   # Optional

    # === COLORS ===
    primary = models.CharField(max_length=20)
    secondary = models.CharField(max_length=20)
    accent = models.CharField(max_length=20)
    neutral = models.CharField(max_length=20)

    primary_content = models.CharField(max_length=20)
    secondary_content = models.CharField(max_length=20)
    accent_content = models.CharField(max_length=20)
    neutral_content = models.CharField(max_length=20)

    base_100 = models.CharField(max_length=20)
    base_200 = models.CharField(max_length=20)
    base_300 = models.CharField(max_length=20)
    base_content = models.CharField(max_length=20)

    success = models.CharField(max_length=20)
    warning = models.CharField(max_length=20)
    error = models.CharField(max_length=20)
    info = models.CharField(max_length=20)

    success_content = models.CharField(max_length=20)
    warning_content = models.CharField(max_length=20)
    error_content = models.CharField(max_length=20)
    info_content = models.CharField(max_length=20)

    # === TYPOGRAPHY ===
    font_body = models.CharField(max_length=100)
    font_heading = models.CharField(max_length=100)
    base_font_size = models.CharField(max_length=10, default="16px")
    scale_ratio = models.FloatField(default=1.2)

    # === SPACING ===
    section_gap = models.CharField(max_length=10, default="4rem")
    container_padding = models.CharField(max_length=10, default="1rem")

    # === RADIUS ===
    radius_btn = models.CharField(max_length=10, default="0.5rem")
    radius_card = models.CharField(max_length=10, default="1rem")
    radius_input = models.CharField(max_length=10, default="0.5rem")

    # === SHADOW ===
    shadow_sm = models.CharField(max_length=50, default="0 1px 2px 0 rgb(0 0 0 / 0.05)")
    shadow_md = models.CharField(max_length=50, default="0 4px 6px -1px rgb(0 0 0 / 0.1)")
    shadow_lg = models.CharField(max_length=50, default="0 10px 15px -3px rgb(0 0 0 / 0.1)")

    is_system = models.BooleanField(default=True)
    def __str__(self):
        return f"{self.themepreset_id} / {self.ltext}"

    # for usage in Admin Panel
    class Meta:
        verbose_name = "00-02 Project ThemePreset"
        ordering = ["themepreset_id"]    

class GlobalValCat(models.Model):
    globalvalcat_id = LowercaseCharField(max_length=25, primary_key=True)

    class Meta:
        verbose_name        = "00-01 Project Global Value Category"
        verbose_name_plural = "00-01 Project Global Value Categories"
        ordering            = ['globalvalcat_id']

    def __str__(self):
        return self.globalvalcat_id

class GlobalVal(models.Model):
    globalvalcat = models.ForeignKey(
        GlobalValCat,
        on_delete=models.CASCADE,
        related_name='globalvals'
    )
    key    = models.CharField(max_length=100)
    keyval = models.CharField(max_length=500, blank=True, null=True) # modeltranslation blank=True to be present

    class Meta:
        unique_together = ('globalvalcat', 'key')
        ordering        = ['globalvalcat__globalvalcat_id', 'key']

    def __str__(self):
        cat_id = getattr(self.globalvalcat, 'globalvalcat_id', '?')
        return f"{cat_id}.{self.key}"
    
class Country(models.Model):
    """
    Global list of countries the platform supports.
    Superadmin-managed (ADMIN_VIEW_ONLY_MODELS).
    Client selects which countries its site serves via Client.allowed_countries.
    """
    code        = models.CharField(
        _('code'), max_length=2, primary_key=True,
        help_text="ISO 3166-1 alpha-2 country code"
    )
    name        = models.CharField(_('name'), max_length=100, blank=True) # modeltranslation
    description = models.TextField(_('description'), blank=True) # modeltranslation
    flag_emoji  = models.CharField(
        _('flag emoji'), max_length=10, blank=True,
        help_text="Unicode flag emoji e.g. \U0001f1ee\U0001f1f3 for India"
    )
    order       = models.PositiveIntegerField(default=0)
    is_active   = models.BooleanField(default=True)

    class Meta:
        app_label = 'mysite'
        verbose_name = _('00-00B Country')
        verbose_name_plural = _('00-00B Countries')
        ordering = ['order', 'code']

    def __str__(self):
        return f'{self.flag_emoji} {self.code} - {self.name}'

class DistributionChannel(models.Model):
    code = models.CharField(_('code'), max_length=2, primary_key=True)
    label = models.CharField(_('label'), max_length=64, blank=True) # modeltranslation
    is_active = models.BooleanField(default=True)

    class Meta:
        app_label = 'mysite'
        verbose_name = _('00-02B Distribution Channel')
        verbose_name_plural = _('00-02B Distribution Channels')
        ordering = ['code']

    def __str__(self):
        return f'{self.code} - {self.label}'

    #@classmethod
    #def seed_defaults(cls):
    #    for code, label in [('00', 'Common'), ('01', 'Retail'), ('02', 'Institutional')]:
    #        cls.objects.get_or_create(code=code, defaults={'label': label})