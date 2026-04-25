from django.db import models
from .base import (LowercaseCharField)
#from .global_config import (ThemePreset)
#from .client import (Client, Theme)
#from .page import (Layout)
from django.contrib.auth.models import User  # this is for ClientUser to have client level authorization

from django.core.exceptions import ValidationError

#from django.contrib.contenttypes.models import ContentType
#from django.contrib.contenttypes.fields import GenericForeignKey
#from django.contrib.contenttypes.fields import GenericRelation
# ── Type 1: Client Staff ──────────────────────────────────────────────

class ClientUserProfile(models.Model):
    """
    Staff user anchored to exactly ONE client.
    OneToOneField — one Django User = one client staff role.
    """
    user      = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='client_profile'
    )
    client    = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='staff_profiles'
    )
    mobile    = models.CharField(max_length=20, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "00-03-04 Client Staff Profile"


    def __str__(self):
        return f"{self.user.email} @ {self.client.client_id} [staff]"


# ── Type 2: Customer ──────────────────────────────────────────────────

class CustomerProfile(models.Model):
    """
    Customer registered with a specific client.
    ForeignKey (not OneToOne) — same User can be a customer
    of multiple clients in the same SaaS.
    """
    user               = models.ForeignKey(        # ← ForeignKey not OneToOne
        User,
        on_delete=models.CASCADE,
        related_name='customer_profiles'
    )
    client             = models.ForeignKey(
        'mysite.Client',
        on_delete=models.CASCADE,
        related_name='customer_profiles'
    )
    mobile             = models.CharField(max_length=20, blank=True)
    preferred_language = models.CharField(max_length=10, blank=True)
    preferred_theme    = models.ForeignKey(
        'Theme', null=True, blank=True, on_delete=models.SET_NULL
    )
    default_address    = models.ForeignKey(
        'CustomerAddress', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+'
    )
    is_active          = models.BooleanField(default=True)
    #created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'client')    # one profile per user per client
        verbose_name    = 'Customer Profile'

    def __str__(self):
        return f"{self.user.email} @ {self.client.client_id} [customer]"


class CustomerAddress(models.Model):
    customer     = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name='addresses'
    )
    street       = models.CharField(max_length=200)
    city         = models.CharField(max_length=100)
    zip_code     = models.CharField(max_length=20)
    country_code = models.CharField(max_length=2)
    is_default   = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_default', 'city']

    def __str__(self):
        return f"{self.street}, {self.city}"

    def save(self, *args, **kwargs):
        # Only run default clearing if is_default is True
        if self.is_default:
            CustomerAddress.objects.filter(
                customer=self.customer,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
# ── Location (Store / Branch) ─────────────────────────────────────────

class ClientLocation(models.Model):
    LOCATION_TYPE_CHOICES = [
        ('store',      'Store'),
        ('branch',     'Branch'),
        ('warehouse',  'Warehouse'),
        ('office',     'Office'),
    ]

    client        = models.ForeignKey('mysite.Client', on_delete=models.CASCADE, related_name='locations')
    location_id   = LowercaseCharField(max_length=50)
    name          = models.CharField(max_length=100)
    location_type = models.CharField(max_length=20, choices=LOCATION_TYPE_CHOICES, default='store')
    is_active     = models.BooleanField(default=True)

    class Meta:
        unique_together = ('client', 'location_id')
        ordering        = ['client', 'location_id']
        verbose_name = "00-05 Client Location"
    def __str__(self):
        return f"{self.client.client_id} / {self.location_id} ({self.location_type})"

# ── Client Group ──────────────────────────────────────────────────────

class ClientGroup(models.Model):
    
    #A named group within a client — like Django's Group but client-scoped.
    #e.g. 'Warehouse Staff', 'Billing Team', 'Store A Managers'
    #Multiple users can be assigned to one group.
    
    ROLE_CHOICES = [
        ('admin',  'Client Admin'),   # manage users/groups, full access
        ('staff',  'Client Staff'),   # access controlled per module
        ('viewer', 'Client Viewer'),  # read-only on permitted modules
    ]

    client      = models.ForeignKey('mysite.Client', on_delete=models.CASCADE, related_name='groups')
    group_id    = LowercaseCharField(max_length=50)
    name        = models.CharField(max_length=100)
    role        = models.CharField(max_length=20, choices=ROLE_CHOICES, default='staff')
    description = models.CharField(max_length=300, blank=True)
    is_active   = models.BooleanField(default=True)

    # Location scope — empty means access to ALL locations
    locations   = models.ManyToManyField(
        ClientLocation,
        blank=True,
        related_name='groups',
        help_text='Leave empty to grant access to all locations'
    )

    class Meta:
        unique_together = ('client', 'group_id')
        ordering        = ['client', 'group_id']
        verbose_name = "00-04 Client Group"
    def __str__(self):
        return f"{self.client.client_id} / {self.name} ({self.role})"

    def has_location_access(self, location):
        #Empty locations = all access. Otherwise check membership.
        if not self.locations.exists():
            return True
        return self.locations.filter(pk=location.pk).exists()

# ── Module Permissions per Group ──────────────────────────────────────

class ClientGroupPermission(models.Model):
    MODULE_CHOICES = [
        # CMS
        ('cms',       'CMS (Pages, Themes)'),
        # Commerce
        ('cart',      'Shopping Cart'),
        ('quotation', 'Quotations'),
        ('order',     'Orders'),
        ('delivery',  'Delivery'),
        ('shipment',  'Shipments'),
        ('billing',   'Billing'),
    ]

    ACTION_CHOICES = [
        ('view',   'View'),
        ('create', 'Create'),
        ('edit',   'Edit'),
        ('delete', 'Delete'),
    ]

    group  = models.ForeignKey(ClientGroup, on_delete=models.CASCADE, related_name='permissions')
    module = models.CharField(max_length=30, choices=MODULE_CHOICES)
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)

    class Meta:
        unique_together = ('group', 'module', 'action')
        ordering        = ['group', 'module', 'action']

    def __str__(self):
        return f"{self.group} | {self.module}.{self.action}"

# ── User → Group assignment ───────────────────────────────────────────

class ClientUserMembership(models.Model):
    user  = models.ForeignKey(User, on_delete=models.CASCADE, related_name='client_memberships')
    group = models.ForeignKey(ClientGroup, on_delete=models.CASCADE, related_name='memberships')

    class Meta:
        unique_together = ('user', 'group')

    def clean(self):
        """Ensure user belongs to the same client as the group."""
        from django.core.exceptions import ValidationError
        try:
            profile = self.user.client_profile
            if profile.client != self.group.client:
                raise ValidationError(
                    f"User {self.user.username} belongs to "
                    f"{profile.client.client_id}, not {self.group.client.client_id}"
                )

        except ClientUserProfile.DoesNotExist:
            pass
            #raise ValidationError(
            #    f"User {self.user.username} has no client profile. "
            #    f"Register them under a client first."
            #)


    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

