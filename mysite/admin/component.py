import nested_admin
from django.conf import settings
from django import forms
from mysite.models import (Client, SvgtextbadgeValue, TextstbItem, ComptextBlock, GentextBlock, ComponentSlot, Component)

class SvgtextbadgeValueInline(nested_admin.NestedTabularInline):
    model  = SvgtextbadgeValue
    extra  = 0
    fields = ('language_code', 'stext', 'ltext')

    def get_language_choices(self, request):
        """
        Resolve client's language_list from the URL's object_id.
        Caches result on the request object so Client is queried
        only once per page load, regardless of how many inline
        rows are rendered.
        """
        # Return cached result if already resolved this request
        if hasattr(request, '_cached_client_lang_choices'):
            return request._cached_client_lang_choices


        choices = list(settings.LANGUAGES)   # fallback

        client_id = request.resolver_match.kwargs.get('object_id')
        if client_id:
            try:
                client = Client.objects.get(pk=client_id)
                lang_codes = client.language_list or []
                lang_dict  = dict(settings.LANGUAGES)
                choices = [(code, lang_dict.get(code, code)) for code in lang_codes]
            except Client.DoesNotExist:
                pass

        # Cache on request — lives only for this request/response cycle
        request._cached_client_lang_choices = choices
        return choices

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'language_code':
            kwargs['widget'] = forms.Select(
                choices=self.get_language_choices(request)
            )
        return super().formfield_for_dbfield(db_field, request, **kwargs)

class TextstbItemInline(nested_admin.NestedGenericStackedInline):
    model = TextstbItem
    fields = ("item_id", "ltext", "hidden", "order", "css_class", "svg_text")
    extra = 0
    inlines = [SvgtextbadgeValueInline]
    classes = ['collapse']


class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    #fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']

class GentextBlockInline(nested_admin.NestedGenericStackedInline):
    model = GentextBlock
    fields = ("block_id", "ltext", "hidden", "order", "css_class")
    extra = 0
    inlines = [TextstbItemInline]
    classes = ['collapse']


class ComptextBlockInline(nested_admin.NestedGenericStackedInline):
    model = ComptextBlock
    extra = 0
    classes = ['collapse']
    inlines = [TextstbItemInline]

# Option 3 Common Component Model
# ── Component inlines ─────────────────────────────────────────

class ComponentSlotInline(nested_admin.NestedStackedInline):
    model = ComponentSlot
    fk_name = "component"
    extra = 0
    classes = ['collapse']
    fields = [
        "slot_type", "order", "hidden", "ltext", "css_class",
        "actions_class", # text for card, hero
        "image_url", "alt", "figure_class",   # figure
        "accordion_checked",                             # accordion text slot
    ]
    inlines = [ComptextBlockInline]

    class Media:
        js = ("admin/js/component_admin.js",)


class ComponentInline(nested_admin.NestedStackedInline):
    model = Component
    extra = 0
    classes = ['collapse']
    fields = [
        "comp_id", "order", "hidden", "ltext", "css_class",
        "card_body_class", # card
        "hero_content_class", "hero_overlay", "hero_overlay_style",            # hero
        "accordion_type", "accordion_name",    # accordion
        "config",
    ]
    inlines = [ComponentSlotInline]

    class Media:
        js = ("admin/js/component_admin.js",)
