# forms.py
from django import forms
from .models import Client
from django.conf import settings

class ClientForm(forms.ModelForm):
    # This field fetches choices from settings
    language_choices = forms.MultipleChoiceField(
        choices=settings.LANGUAGES,               # ← from settings
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Select Source Languages",
        initial=['en'],
    )    
    """    
    # This field fetches choices from Language
    language_choices = forms.ModelMultipleChoiceField(
        queryset=Language.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        #widget=forms.SelectMultiple(attrs={'class': 'select-multiple'}),
        # Ensure 'required=False' if the JSON array can be empty
        required=True, 
        label="Select Source Languages",
        initial=['en']   # safety net for unbound forms
    )
    """
    """
    # This field fetches choices from Theme
    theme_choices = forms.ModelMultipleChoiceField(
        queryset=Theme.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'select-multiple'}),
        # Ensure 'required=False' if the JSON array can be empty
        required=False, 
        label="Select Source Themes"
    )
    """
    class Meta:
        model = Client
        fields = ['client_id', 'parent', 'language_list', 'name', 'nb_title', 'nb_title_svg_pre', 'nb_title_svg_suf'] # Include all fields
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If an instance already exists, populate the form field with current data
        if self.instance and self.instance.language_list:
            # Filter the queryset based on the values stored in the JSON field
            self.fields['language_choices'].initial = Language.objects.filter(
                language_id__in=self.instance.language_list
            )
    """        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If an instance already exists, populate the form field with current data
        if self.instance and self.instance.pk and self.instance.language_list:
            # language_list is already a list of codes e.g. ['en', 'ta']
            # MultipleChoiceField just needs that list directly
            self.fields['language_choices'].initial = self.instance.language_list

        """    
        if self.instance and self.instance.theme_list:
            # Filter the queryset based on the values stored in the JSON field
            self.fields['theme_choices'].initial = Theme.objects.filter(
                theme_id__in=self.instance.theme_list
            )
        """
    """    
    def save(self, commit=True):
        # Intercept the save process to populate the JSONField from the form field
        instance = super().save(commit=False)
        # Get the 'x_id' attribute from the selected Language objects
        selected_languages = self.cleaned_data['language_choices']
        instance.language_list = [obj.language_id for obj in selected_languages]
        
        #selected_themes = self.cleaned_data['theme_choices']
        #instance.theme_list = [obj.theme_id for obj in selected_themes]
        
        if commit:
            instance.save()
        return instance
    """
    def save(self, commit=True):
        instance = super().save(commit=False)
        # cleaned_data returns e.g. ['en', 'ta'] directly — no queryset to iterate
        instance.language_list = self.cleaned_data['language_choices']
        if commit:
            instance.save()
        return instance