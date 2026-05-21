
import csv
import json
from pathlib import Path

from mysite.models import (
    Client,
    GlobalItem,
    Item,
)

from django.conf import settings

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_items():

    file_path = DATA_DIR / "20item.csv"

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    client_ids = {
        (r.get("client_id") or "").strip().lower()
        for r in rows
        if (r.get("client_id") or "").strip()
    }

    global_item_ids = {
        (r.get("global_item_id") or "").strip().lower()
        for r in rows
        if (r.get("global_item_id") or "").strip()
    }

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    global_items = {
        g.global_item_id: g
        for g in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    for row in rows:

        client_id = (row.get("client_id") or "").strip().lower()
        client = clients.get(client_id)

        if not client:
            print(f"Missing client: {client_id}")
            continue

        global_item = None

        global_item_id = (
            row.get("global_item_id") or ""
        ).strip().lower()

        if global_item_id:
            global_item = global_items.get(global_item_id)

            if not global_item:
                print(
                    f"Missing global item: "
                    f"{global_item_id}"
                )
                continue

        item_id = (
            row.get("item_id") or ""
        ).strip().lower()

        defaults = {

            "global_item": global_item,

            "inherit_global_media":
                row.get(
                    "inherit_global_media",
                    "1"
                ) == "1",

            "gtin":
                row.get("gtin", ""),

            "gpc_brick_code":
                row.get("gpc_brick_code", ""),

            "domain":
                row.get("domain", "generic"),

            "status":
                row.get("status", "draft"),

            "order":
                int(row.get("order", 0)),

            "country_of_origin":
                row.get("country_of_origin", ""),

            "image_url":
                row.get("image_url", ""),

            "image_alt":
                row.get("image_alt", ""),

            "barcode":
                row.get("barcode", ""),

            "weight_g":
                int(row["weight_g"])
                if row.get("weight_g")
                else None,

            "length_mm":
                int(row["length_mm"])
                if row.get("length_mm")
                else None,

            "width_mm":
                int(row["width_mm"])
                if row.get("width_mm")
                else None,

            "height_mm":
                int(row["height_mm"])
                if row.get("height_mm")
                else None,

            "attributes":
                json.loads(
                    row.get("attributes", "{}")
                ),
        }

        for lang in LANGS:

            defaults[f"name_{lang}"] = \
                row.get(f"name_{lang}", "")

            defaults[f"description_{lang}"] = \
                row.get(f"description_{lang}", "")

            defaults[
                f"care_instructions_{lang}"
            ] = row.get(
                f"care_instructions_{lang}",
                ""
            )

        obj, created = Item.objects.update_or_create(

            client=client,
            item_id=item_id,

            defaults=defaults
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"Item: {client_id} / {item_id}"
        )

    print("Loaded Items")


def run():

    load_items()

    print("Done")
