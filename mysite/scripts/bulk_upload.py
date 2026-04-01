
import json
from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from mysite.models import (
    Client, Page, Layout, Component, ComponentSlot,
    GentextBlock, ComptextBlock, TextstbItem, SvgtextbadgeValue, Language
)
from django.db import models as django_models

# ── Helpers ───────────────────────────────────────────────────
def get_content_type(model):
    return ContentType.objects.get_for_model(model)


def upload_stb_items(items_data, parent_obj):
    ct = get_content_type(parent_obj.__class__)
    for item_data in items_data:
        defaults = {
            "ltext":     item_data.get("ltext", ""),
            "hidden":    item_data.get("hidden", False),
            "css_class": item_data.get("css_class", ""),
            "svg_text":  item_data.get("svg_text", ""),
        }
        item, created = TextstbItem.objects.update_or_create(
            content_type=ct,
            object_id=parent_obj.id,
            item_id=item_data["item_id"],
            order=item_data.get("order", 1),
            defaults=defaults
        )

        #print(f"  TextstbItem: item_id={item_data['item_id']} "
        #      f"parent={parent_obj.__class__.__name__}:{parent_obj.id} "
        #      f"created={created} id={item.id}")

        values = item_data.get("values", {})
        #print(f"    values in JSON: {list(values.keys())}")

        for lang_id, val in values.items():
            try:
                language = Language.objects.get(language_id=lang_id)
            except Language.DoesNotExist:
                print(f"    ⚠ Language '{lang_id}' not found — skipping")
                continue

            stb_val, stb_created = SvgtextbadgeValue.objects.update_or_create(
                textstbitem=item,
                language=language,
                defaults={
                    "stext": val.get("stext", ""),
                    "ltext": val.get("ltext", ""),
                }
            )
            #print(f"    SvgtextbadgeValue: lang={lang_id} "
            #      f"stext='{stb_val.stext}' "
            #      f"created={stb_created}")

def upload_comptextblocks(blocks_data, parent_obj):
    ct = get_content_type(parent_obj.__class__)
    #print(f"  ComptextBlock parent: {parent_obj.__class__.__name__} "
    #      f"id={parent_obj.id} ct_id={ct.id}")
    for block_data in blocks_data:
        defaults = {
            "ltext":     block_data.get("ltext", ""),
            "hidden":    block_data.get("hidden", False),
            "css_class": block_data.get("css_class", ""),
            "href_page": block_data.get("href_page", ""),
        }
        block, created = ComptextBlock.objects.update_or_create(
            content_type=ct,
            object_id=parent_obj.id,
            block_id=block_data["block_id"],
            order=block_data.get("order", 1),
            defaults=defaults
        )
        #print(f"  ComptextBlock: block_id={block_data['block_id']} "
        #      f"created={created} id={block.id}")
        upload_stb_items(block_data.get("items", []), block)

def upload_gentextblocks(blocks_data, parent_obj):
    """Create GentextBlock + items for Client, Page or Theme"""
    ct = get_content_type(parent_obj.__class__)
    for block_data in blocks_data:
        block, created = GentextBlock.objects.update_or_create(
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
    Returns a defaults dict ready for update_or_create.
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

    component, created = Component.objects.update_or_create(
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

        slot, created = ComponentSlot.objects.update_or_create(
            component=component,
            slot_type=slot_type,
            order=order,
            defaults=defaults
        )

        #print(f"  Slot: type={slot_type} order={order} "
        #      f"created={created} id={slot.id}")
        
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

        layout, created = Layout.objects.update_or_create(
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

        page, created = Page.objects.update_or_create(
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


