# forms.py
from django import forms
from django.conf import settings

from django.contrib.auth.models import User
from allauth.account.forms import SignupForm
from .models import CustomerProfile, ClientUserProfile, Client, CustomerAddress


class ClientForm(forms.ModelForm):

    # This field fetches choices from settings
    language_choices = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,               # ← from settings
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Select Source Languages",
        initial=['en'],
    )    
 
    class Meta:
        model = Client
        fields = ['client_id', 'parent', 'language_list', 'name', 'nb_title', 'nb_title_svg_pre', 'nb_title_svg_suf'] # Include all fields
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If an instance already exists, populate the form field with current data
        if self.instance and self.instance.pk and self.instance.language_list:
            # language_list is already a list of codes e.g. ['en', 'ta']
            # MultipleChoiceField just needs that list directly
            self.fields['language_choices'].initial = self.instance.language_list

    def save(self, commit=True):
        instance = super().save(commit=False)
        # cleaned_data returns e.g. ['en', 'ta'] directly — no queryset to iterate
        instance.language_list = self.cleaned_data['language_choices']
        if commit:
            instance.save()
        return instance
    
# ── Type 2: Customer signup form ──────────────────────────────────────

class CustomerSignupForm(SignupForm):
    """
    Extended allauth signup form for Type 2 customers.
    Captures extra profile fields at registration time.
    """

    first_name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            'placeholder': 'First Name',
            'class': 'input input-bordered w-full'
        })
    )
    last_name = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Last Name',
            'class': 'input input-bordered w-full'
        })
    )
    mobile = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Mobile Number',
            'class': 'input input-bordered w-full'
        })
    )
    preferred_language = forms.ChoiceField(
        choices=[],
        required=False,
        widget=forms.Select(attrs={
            'class': 'select select-bordered w-full'
        })
    )

    def __init__(self, *args, **kwargs):
        self.client = kwargs.pop('client', None)
        super().__init__(*args, **kwargs)
        if self.client and self.client.language_list:
            lang_dict = dict(settings.LANGUAGES)
            self.fields['preferred_language'].choices = [
                (code, lang_dict.get(code, code))
                for code in self.client.language_list
            ]
        else:
            self.fields['preferred_language'].choices = list(settings.LANGUAGES)

    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name  = self.cleaned_data.get('last_name', '')
        user.save(update_fields=['first_name', 'last_name'])
        return user
    
# ── Type 1: Staff user creation form (admin only) ────────────────────

class ClientUserProfileForm(forms.ModelForm):
    """
    Used in Django admin to create/edit Type 1 staff profiles.
    """
    class Meta:
        model  = ClientUserProfile
        fields = ['user', 'client', 'mobile', 'is_active']

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Scope client dropdown to permitted clients
        if self.request and not self.request.user.is_superuser:
            from guardian.shortcuts import get_objects_for_user
            self.fields['client'].queryset = get_objects_for_user(
                self.request.user,
                f'{Client._meta.app_label}.view_client_data',
                klass=Client,
            )

        # Only show users without a staff profile (unassigned users)
        assigned_user_ids = ClientUserProfile.objects.values_list('user_id', flat=True)
        self.fields['user'].queryset = User.objects.filter(
            is_superuser=False,
            is_staff=False,
        ).exclude(id__in=assigned_user_ids)


# ── Customer profile edit form (customer-facing, not admin) ──────────

class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model  = CustomerProfile
        fields = ['mobile', 'preferred_language', 'preferred_theme']
        widgets = {
            'mobile': forms.TextInput(attrs={
                'class': 'input input-bordered w-full',
                'placeholder': 'Mobile Number'
            }),
            'preferred_language': forms.Select(attrs={
                'class': 'select select-bordered w-full'
            }),
            'preferred_theme': forms.Select(attrs={
                'class': 'select select-bordered w-full'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.client = kwargs.pop('client', None)
        super().__init__(*args, **kwargs)
        if self.client:
            self.fields['preferred_theme'].queryset = \
                self.client.themes.filter(hidden=False)
            self.fields['preferred_theme'].empty_label = 'Default Theme'
            if self.client.language_list:
                lang_dict = dict(settings.LANGUAGES)
                self.fields['preferred_language'] = forms.ChoiceField(
                    choices=[
                        (code, lang_dict.get(code, code))
                        for code in self.client.language_list
                    ],
                    required=False,
                    widget=forms.Select(attrs={
                        'class': 'select select-bordered w-full'
                    })
                )

class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model  = CustomerAddress
        fields = ['street', 'city', 'zip_code', 'country_code']
        widgets = {
            'street': forms.TextInput(attrs={
                'class': 'input input-bordered w-full',
                'placeholder': 'Street Address'
            }),
            'city': forms.TextInput(attrs={
                'class': 'input input-bordered w-full',
                'placeholder': 'City'
            }),
            'zip_code': forms.TextInput(attrs={
                'class': 'input input-bordered w-full',
                'placeholder': 'ZIP / PIN Code'
            }),
            'country_code': forms.TextInput(attrs={
                'class': 'input input-bordered w-full',
                'placeholder': 'e.g. IN, US, FR'
            }),
        }