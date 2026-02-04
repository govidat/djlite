# forms.py
from django import forms
from .models import Language2, Theme2, Client2

class ClientForm(forms.ModelForm):
    # This field fetches choices from Language
    language_choices = forms.ModelMultipleChoiceField(
        queryset=Language2.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'select-multiple'}),
        # Ensure 'required=False' if the JSON array can be empty
        required=False, 
        label="Select Source Languages"
    )

    # This field fetches choices from Theme
    theme_choices = forms.ModelMultipleChoiceField(
        queryset=Theme2.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'select-multiple'}),
        # Ensure 'required=False' if the JSON array can be empty
        required=False, 
        label="Select Source Themes"
    )

    class Meta:
        model = Client2
        fields = ['client_id', 'parent', 'language_list', 'theme_list'] # Include all fields

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If an instance already exists, populate the form field with current data
        if self.instance and self.instance.language_list:
            # Filter the queryset based on the values stored in the JSON field
            self.fields['language_choices'].initial = Language2.objects.filter(
                language_id__in=self.instance.language_list
            )
        if self.instance and self.instance.theme_list:
            # Filter the queryset based on the values stored in the JSON field
            self.fields['theme_choices'].initial = Theme2.objects.filter(
                theme_id__in=self.instance.theme_list
            )

    def save(self, commit=True):
        # Intercept the save process to populate the JSONField from the form field
        instance = super().save(commit=False)
        # Get the 'x_id' attribute from the selected Language objects
        selected_languages = self.cleaned_data['language_choices']
        instance.language_list = [obj.language_id for obj in selected_languages]

        selected_themes = self.cleaned_data['theme_choices']
        instance.theme_list = [obj.theme_id for obj in selected_themes]

        if commit:
            instance.save()
        return instance
