#from mysite.models import TokenType
#from mysite.models import Token
#from mysite.models import Language
from mysite.models import ThemePreset


from mysite.models import Theme
from mysite.models import Layout


#from mysite.models import Position

# from django.contrib.contenttypes.models import ContentType
from django.apps import apps

#from mysite.models import TextItemValue

#from django.db.models import F, Case, When
from django.utils import timezone
from django.db import connection
from django.db.models.functions import Lower

from pprint import pprint

import json
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from mysite.models import (
    Client, Page, Layout, Component, ComponentSlot,
    GentextBlock, ComptextBlock, TextstbItem, SvgtextbadgeValue
)
from django.db import models as django_models

def run():
    #lv_client_id = 'bahushira'
    #result = ClientLanguage.objects.filter(client_id="bahushira").order_by("-order").values_list('language_id', flat=True)
    #result = ClientLanguage.objects.filter(client_id='bahushira').values_list('language_id', flat=True).order_by('order')
    #print(connection.queries)    
    #result = ClientNavbar.objects.filter(client_id=lv_client_id).values('id', 'page_id', 'parent', 'order').order_by('order')
    #print(result)
    #print(result.exists())
    #print(client.first())
    #pprint(connection.queries)

    # print("Hello from runscript")
    """ Step 1

    THEMEPRESET_DATA = [
        {
        "themepreset_id": "light",
        "ltext": "a",
        "primary": "#570df8",
        "primary_content": "#ffffff",

        "secondary": "#f000b8",
        "secondary_content": "#ffffff",

        "accent": "#37cdbe",
        "accent_content": "#163835",

        "neutral": "#3d4451",
        "neutral_content": "#ffffff",

        "base_100": "#ffffff",
        "base_200": "#f2f2f2",
        "base_300": "#e5e6e6",
        "base_content": "#1f2937",

        "success": "#00c853",
        "success_content": "#ffffff",

        "warning": "#ff9800",
        "warning_content": "#ffffff",

        "error": "#ff5724",
        "error_content": "#ffffff",

        "info": "#2094f3",
        "info_content": "#ffffff"
        },   
        {
        "themepreset_id": "dark",
        "ltext": "b",
        "primary": "#661ae6",
        "primary_content": "#ffffff",

        "secondary": "#d926aa",
        "secondary_content": "#ffffff",

        "accent": "#1fb2a6",
        "accent_content": "#ffffff",

        "neutral": "#191d24",
        "neutral_content": "#a6adbb",

        "base_100": "#2a303c",
        "base_200": "#242933",
        "base_300": "#1d232a",
        "base_content": "#a6adbb",

        "success": "#36d399",
        "success_content": "#000000",

        "warning": "#fbbd23",
        "warning_content": "#000000",

        "error": "#f87272",
        "error_content": "#000000",

        "info": "#3abff8",
        "info_content": "#000000"
        },              
            
    ]
    for row in THEMEPRESET_DATA:

        ThemePreset.objects.update_or_create(
            themepreset_id=row["themepreset_id"],
            ltext=row["ltext"],
            primary=row["primary"],
            primary_content=row["primary_content"],

            secondary=row["secondary"],
            secondary_content=row["secondary_content"],

            accent=row["accent"],
            accent_content=row["accent_content"],

            neutral=row["neutral"],
            neutral_content=row["neutral_content"],

            base_100=row["base_100"],
            base_200=row["base_200"],
            base_300=row["base_300"],
            base_content=row["base_content"],

            success=row["success"],
            success_content=row["success_content"],

            warning=row["warning"],
            warning_content=row["warning_content"],

            error=row["error"],
            error_content=row["error_content"],

            info=row["info"],
            info_content=row["info_content"]
        ) 
    """
    """ Step 2
    
    CLIENT_DATA = [
        {
        "client_id": "bahushira"
        }
    ]
    for row in CLIENT_DATA:
        Client.objects.update_or_create(
            client_id=row["client_id"]
        )    

    THEME_DATA = [
        {
        "client_id": "bahushira",
        "themepreset_id" : "light",
        "theme_id": "light",
        "is_default": False
        },        
        {
        "client_id": "bahushira",
        "themepreset_id" : "dark",
        "theme_id": "dark",
        "is_default": True
        },
    ]

    clients = {c.client_id: c for c in Client.objects.all()}
    themepresets = {c.themepreset_id: c for c in ThemePreset.objects.all()}
    #layouts = {(c.client.client_id, c.page.page_id, c.slug, c.level): c for c in Layout.objects.all()}

    for row in THEME_DATA:

        client_value = clients[row["client_id"]]
        themepreset_value = themepresets[row["themepreset_id"]]

        Theme.objects.update_or_create(
            client = client_value,
            themepreset = themepreset_value,
            theme_id=row["theme_id"],
            #overrides=row["overrides"],
            is_default=row["is_default"]
        )   
    
    """
    """ Step 3 Mass upload """

    # ── Helpers ───────────────────────────────────────────────────

def get_content_type(model):
    return ContentType.objects.get_for_model(model)


def upload_stb_items(items_data, parent_obj):
    """Create TextstbItem + SvgtextbadgeValue for any parent (GentextBlock or ComptextBlock)"""
    ct = get_content_type(parent_obj.__class__)
    for item_data in items_data:
        item, created = TextstbItem.objects.get_or_create(
            content_type=ct,
            object_id=parent_obj.id,
            item_id=item_data["item_id"],
            order=item_data.get("order", 1),
            defaults={
                "ltext":     item_data.get("ltext", ""),
                "hidden":    item_data.get("hidden", False),
                "css_class": item_data.get("css_class", ""),
                "svg_text":  item_data.get("svg_text", ""),
            }
        )
        # Upload language values
        for lang_id, val in item_data.get("values", {}).items():
            try:
                language = Language.objects.get(language_id=lang_id)
            except Language.DoesNotExist:
                print(f"  ⚠ Language '{lang_id}' not found — skipping")
                continue
            SvgtextbadgeValue.objects.get_or_create(
                textstbitem=item,
                language=language,
                defaults={
                    "stext": val.get("stext", ""),
                    "ltext": val.get("ltext", ""),
                }
            )


def upload_comptextblocks(blocks_data, parent_obj):
    """Create ComptextBlock + items for any parent (ComponentSlot etc)"""
    ct = get_content_type(parent_obj.__class__)
    for block_data in blocks_data:
        block, created = ComptextBlock.objects.get_or_create(
            content_type=ct,
            object_id=parent_obj.id,
            block_id=block_data["block_id"],
            order=block_data.get("order", 1),
            defaults={
                "ltext":     block_data.get("ltext", ""),
                "hidden":    block_data.get("hidden", False),
                "css_class": block_data.get("css_class", ""),
                "href_page": block_data.get("href_page", ""),
            }
        )
        upload_stb_items(block_data.get("items", []), block)


def upload_gentextblocks(blocks_data, parent_obj):
    """Create GentextBlock + items for Client, Page or Theme"""
    ct = get_content_type(parent_obj.__class__)
    for block_data in blocks_data:
        block, created = GentextBlock.objects.get_or_create(
            content_type=ct,
            object_id=parent_obj.id,
            block_id=block_data["block_id"],
            order=block_data.get("order", 1),
            defaults={
                "ltext":     block_data.get("ltext", ""),
                "hidden":    block_data.get("hidden", False),
                "css_class": block_data.get("css_class", ""),
            }
        )
        upload_stb_items(block_data.get("items", []), block)

# ── Generic field extractor ───────────────────────────────────

def extract_fields(model_class, data, exclude=None):
    """
    Introspects model fields and extracts matching values from data dict.
    Skips excluded fields, FK fields, and fields not present in data.
    Returns a defaults dict ready for get_or_create.
    """
    exclude = set(exclude or [])
    defaults = {}

    for field in model_class._meta.fields:
        name = field.name

        # Skip excluded and FK fields (handled separately)
        if name in exclude:
            continue
        if isinstance(field, django_models.ForeignKey):
            continue

        # Only include if key exists in data
        if name not in data:
            continue

        value = data[name]

        # Use field default if value is None
        if value is None:
            if field.has_default():
                defaults[name] = field.default() if callable(field.default) else field.default
        else:
            defaults[name] = value

    return defaults


# ── Upload functions ──────────────────────────────────────────

def upload_component(component_data, layout):
    """Create Component + slots — generic, no hardcoded field names"""

    # Extract all non-FK fields except layout and id
    defaults = extract_fields(
        Component,
        component_data,
        exclude={"id", "layout"}
    )

    component, created = Component.objects.get_or_create(
        layout=layout,
        defaults=defaults
    )

    upload_slots(component_data.get("slots", []), component)
    return component


def upload_slots(slots_data, component):
    """Create ComponentSlot + comptextblocks — generic, no hardcoded field names"""

    for slot_data in slots_data:

        # Extract lookup fields separately
        slot_type = slot_data["slot_type"]
        order     = slot_data.get("order", 1)

        # Extract remaining fields generically
        defaults = extract_fields(
            ComponentSlot,
            slot_data,
            exclude={"id", "component", "slot_type", "order"}
        )

        slot, created = ComponentSlot.objects.get_or_create(
            component=component,
            slot_type=slot_type,
            order=order,
            defaults=defaults
        )

        # Only text slots have comptextblocks
        if slot_type == "text":
            upload_comptextblocks(slot_data.get("comptextblocks", []), slot)


def upload_layouts(layouts_data, page, slug_map=None):
    """
    Recursively create Layout records — generic field extraction.
    slug_map is keyed by (page_id, slug) to ensure uniqueness per page
    not across the whole client.
    """
    if slug_map is None:
        slug_map = {}

    for layout_data in layouts_data:

        # Resolve parent using (page, slug) as key
        parent_slug = layout_data.get("parent_slug")
        parent_layout = slug_map.get((page.page_id, parent_slug)) if parent_slug else None

        # Extract lookup fields
        level = layout_data["level"]
        slug  = layout_data["slug"]

        # Extract remaining fields generically
        defaults = extract_fields(
            Layout,
            layout_data,
            exclude={"id", "page", "level", "slug", "parent",
                     "parent_slug", "component", "children"}
        )
        defaults["parent"] = parent_layout

        layout, created = Layout.objects.get_or_create(
            page=page,
            level=level,
            slug=slug,
            defaults=defaults
        )

        # Register using (page_id, slug) as key — unique per page not client
        slug_map[(page.page_id, slug)] = layout

        # Upload component if level=40 and component data present
        if level == 40 and layout_data.get("component"):
            upload_component(layout_data["component"], layout)

        # Recurse into children
        if layout_data.get("children"):
            upload_layouts(layout_data["children"], page, slug_map)

    return slug_map

def upload_pages(pages_data, client):
    """Create Page records + their layouts"""
    # Build page slug map for parent resolution
    page_map = {}

    for page_data in pages_data:
        parent_page_id = page_data.get("parent_page_id")
        parent_page = page_map.get(parent_page_id) if parent_page_id else None

        page, created = Page.objects.get_or_create(
            client=client,
            page_id=page_data["page_id"],
            defaults={
                "ltext":  page_data.get("ltext", ""),
                "order":  page_data.get("order", 0),
                "hidden": page_data.get("hidden", False),
                "parent": parent_page,
            }
        )
        page_map[page_data["page_id"]] = page

        upload_gentextblocks(page_data.get("gentextblocks", []), page)
        upload_layouts(page_data.get("layouts", []), page)

    return page_map


# ── Main entry point ──────────────────────────────────────────

@transaction.atomic
def bulk_upload(json_data):
    """
    Main entry point. Pass either a dict or a JSON string.
    Wrapped in transaction.atomic so everything rolls back on error.
    """
    if isinstance(json_data, str):
        json_data = json.loads(json_data)

    client_id = json_data["client_id"]

    try:
        client = Client.objects.get(client_id=client_id)
    except Client.DoesNotExist:
        raise ValueError(f"Client '{client_id}' does not exist. Create it first.")

    print(f"Uploading data for client: {client_id}")

    # Client level gentextblocks
    upload_gentextblocks(json_data.get("gentextblocks", []), client)

    # Pages + layouts + components
    upload_pages(json_data.get("pages", []), client)

    print(f"Upload complete for client: {client_id}")


# ── Management command wrapper ────────────────────────────────

# mysite/management/commands/bulk_upload.py
# Usage: python manage.py bulk_upload path/to/data.json

from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = "Bulk upload client page/layout/component data from JSON file"

    def add_arguments(self, parser):
        parser.add_argument("json_file", type=str, help="Path to JSON file")

    def handle(self, *args, **options):
        with open(options["json_file"], "r") as f:
            json_data = json.load(f)
        try:
            bulk_upload(json_data)
            self.stdout.write(self.style.SUCCESS("Bulk upload successful"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Bulk upload failed: {e}"))
            raise