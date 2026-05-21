import csv
import json

from decimal import Decimal
from pathlib import Path

from django.conf import settings

from mysite.models import (
    Item,
    ItemVariant,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


LANGS = [
    code for code, _name in settings.LANGUAGES
]


# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def clean(value):

    return (value or "").strip()


def to_decimal(value):

    value = clean(value)

    if not value:
        return None

    try:
        return Decimal(value)

    except Exception:
        return None


def to_int(value, default=0):

    value = clean(value)

    if not value:
        return default

    try:
        return int(value)

    except Exception:
        return default


def to_bool(value):

    return clean(value) in ["1", "true", "True", "yes"]


def to_json(value):

    value = clean(value)

    if not value:
        return {}

    try:
        return json.loads(value)

    except Exception:
        return {}


# ─────────────────────────────────────────────
# loader
# ─────────────────────────────────────────────

def load_item_variants():

    file_path = DATA_DIR / "24itemvariant.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ─────────────────────────────────────────
    # preload keys
    # ─────────────────────────────────────────

    client_ids = {
        clean(r.get("client_id")).lower()
        for r in rows
    }

    item_ids = {
        clean(r.get("item_id")).lower()
        for r in rows
    }

    # ─────────────────────────────────────────
    # preload items
    # ─────────────────────────────────────────

    items = {

        (
            i.client.client_id.lower(),
            i.item_id.lower(),
        ): i

        for i in Item.objects.filter(
            client__client_id__in=client_ids,
            item_id__in=item_ids,
        ).select_related("client")
    }

    # ─────────────────────────────────────────
    # load
    # ─────────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id")
        ).lower()

        item_id = clean(
            row.get("item_id")
        ).lower()

        variant_id = clean(
            row.get("variant_id")
        ).lower()

        item = items.get(
            (client_id, item_id)
        )

        if not item:

            print(
                f"Missing Item: "
                f"{client_id} / {item_id}"
            )

            continue

        defaults = {

            "sku":
                clean(row.get("sku")),

            "gtin":
                clean(row.get("gtin")),

            "price":
                to_decimal(row.get("price")),

            "stock":
                to_int(row.get("stock"), 0),

            "is_active":
                to_bool(row.get("is_active")),
            "image_url": row.get("image_url","").strip(),
            "order": to_int(row.get("order")),

            "attributes":
                to_json(row.get("attributes")),
        }

        # ─────────────────────────────────────
        # multilingual fields
        # ─────────────────────────────────────

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

        obj, created = (
            ItemVariant.objects.update_or_create(

                item=item,
                variant_id=variant_id,

                defaults=defaults,
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"{client_id} / "
            f"{item_id} / "
            f"{variant_id}"
        )

    print("Loaded ItemVariant")


def run():

    load_item_variants()

    print("Done")