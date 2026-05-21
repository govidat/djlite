import csv
from decimal import Decimal
from pathlib import Path

from mysite.models import (
    GlobalItem,
    NodeAttributeType,
    NodeAttributeValue,
    GlobalItemAttributeValue,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def to_decimal(value):

    value = (value or "").strip()

    if not value:
        return None

    try:
        return Decimal(value)
    except:
        return None


def load_val01():

    file_path = DATA_DIR / "11Bglobalitemattributevalue.csv"

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── collect keys ─────────────────────────────────────

    global_item_ids = {
        (r.get("global_item_id") or "").strip().lower()
        for r in rows
    }

    attribute_slugs = {
        (r.get("attribute_slug") or "").strip().lower()
        for r in rows
    }

    predefined_slugs = {
        (r.get("predefined_value_slug") or "").strip().lower()
        for r in rows
        if (r.get("predefined_value_slug") or "").strip()
    }

    # ── preload global items ─────────────────────────────

    global_items = {
        gi.global_item_id: gi
        for gi in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── preload attribute types ──────────────────────────

    attribute_types = {

        (
            at.node.taxonomy.slug,
            at.node.slug,
            at.slug
        ): at

        for at in NodeAttributeType.objects.select_related(
            "node",
            "node__taxonomy"
        ).filter(
            slug__in=attribute_slugs
        )
    }

    # ── preload predefined values ────────────────────────

    predefined_values = {

        (
            pv.attribute_type.node.taxonomy.slug,
            pv.attribute_type.node.slug,
            pv.attribute_type.slug,
            pv.slug
        ): pv

        for pv in NodeAttributeValue.objects.select_related(
            "attribute_type",
            "attribute_type__node",
            "attribute_type__node__taxonomy",
        ).filter(
            slug__in=predefined_slugs
        )
    }

    # ── load values ──────────────────────────────────────

    for row in rows:

        global_item_id = (
            row.get("global_item_id") or ""
        ).strip().lower()

        taxonomy_slug = (
            row.get("taxonomy_slug") or ""
        ).strip().lower()

        node_slug = (
            row.get("node_slug") or ""
        ).strip().lower()

        attribute_slug = (
            row.get("attribute_slug") or ""
        ).strip().lower()

        predefined_value_slug = (
            row.get("predefined_value_slug") or ""
        ).strip().lower()

        global_item = global_items.get(global_item_id)

        if not global_item:

            print(
                f"Missing GlobalItem: {global_item_id}"
            )
            continue

        attribute_type = attribute_types.get(
            (
                taxonomy_slug,
                node_slug,
                attribute_slug,
            )
        )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{attribute_slug}"
            )
            continue

        predefined_value = None

        if predefined_value_slug:

            predefined_value = predefined_values.get(
                (
                    taxonomy_slug,
                    node_slug,
                    attribute_slug,
                    predefined_value_slug,
                )
            )

            if not predefined_value:

                print(
                    f"Missing predefined value: "
                    f"{predefined_value_slug}"
                )
                continue

        obj, created = (
            GlobalItemAttributeValue.objects.update_or_create(

                global_item=global_item,
                attribute_type=attribute_type,

                defaults={

                    "predefined_value":
                        predefined_value,

                    "value_text":
                        row.get("value_text", ""),

                    "value_number":
                        to_decimal(
                            row.get("value_number")
                        ),
                }
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"GlobalItemAttributeValue: "
            f"{global_item_id} / "
            f"{attribute_slug}"
        )

    print("Loaded GlobalItemAttributeValue")


def run():

    load_val01()

    print("Done")