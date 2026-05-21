import csv
import json

from decimal import Decimal
from pathlib import Path

from django.db import transaction

from mysite.models import (
    Item,
    ProductItem,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def clean(value):
    return (value or "").strip()


def clean_lower(value):
    return clean(value).lower()


def bool01(value):
    return clean(value) == "1"


def to_decimal(value):

    value = clean(value)

    if value == "":
        return None

    return Decimal(value)


def to_int(value):

    value = clean(value)

    if value == "":
        return 0

    return int(value)


# ─────────────────────────────────────────────
# loader
# ─────────────────────────────────────────────

@transaction.atomic
def load_val01():

    file_path = DATA_DIR / "22productitem.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── collect keys ─────────────────────────

    client_ids = {
        clean_lower(r.get("client_id"))
        for r in rows
    }

    item_ids = {
        clean_lower(r.get("item_id"))
        for r in rows
    }

    # ── preload items ───────────────────────

    items = {

        (
            i.client.client_id,
            i.item_id
        ): i

        for i in Item.objects.filter(

            client__client_id__in=client_ids,
            item_id__in=item_ids,

        ).select_related("client")
    }

    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ── load rows ───────────────────────────

    for row in rows:

        client_id = clean_lower(
            row.get("client_id")
        )

        item_id = clean_lower(
            row.get("item_id")
        )

        item = items.get(
            (client_id, item_id)
        )

        if not item:

            print(
                f"Missing item: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        defaults = {

            "price":
                to_decimal(row.get("price")),

            "compare_price":
                to_decimal(
                    row.get("compare_price")
                ),

            "currency":
                clean(row.get("currency"))
                or "INR",

            "sku":
                clean(row.get("sku")),

            "barcode":
                clean(row.get("barcode")),

            "track_inventory":
                bool01(
                    row.get("track_inventory", "0")
                ),

            "stock_quantity":
                to_int(
                    row.get("stock_quantity")
                ),

            "attributes":
                json.loads(
                    row.get("attributes", "{}")
                ),
        }

        obj, created = \
            ProductItem.objects.update_or_create(

                item=item,

                defaults=defaults
            )

        if created:
            created_count += 1
        else:
            updated_count += 1

        print(
            f"{'Created' if created else 'Updated'} "
            f"{client_id} → {item_id}"
        )

    print()

    print(
        f"Loaded ProductItem "
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )


def run():

    load_val01()

    print("Done")

