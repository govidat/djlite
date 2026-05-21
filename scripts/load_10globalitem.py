import csv
import json
from pathlib import Path

from django.contrib.auth import get_user_model

from mysite.models import GlobalItem
from django.conf import settings

LANGS = [lang[0] for lang in settings.LANGUAGES]


# global_item_id,gtin,gpc_brick_code,domain,status,
# name_en,name_hi,name_fr,name_ta,
# description_en,description_hi,description_fr,description_ta,
# country_of_origin,image_url,image_alt,
# barcode,weight_g,length_mm,width_mm,height_mm,
# care_instructions_en,care_instructions_hi,
# care_instructions_fr,care_instructions_ta,
# attributes

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

User = get_user_model()


def to_int(value):

    value = (value or "").strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def to_json(value):

    value = (value or "").strip()

    if not value:
        return {}

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {value}")
        return {}


def load_val01():

    file_path = DATA_DIR / "10globalitem.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Load GlobalItem ─────────────────────────────────────

    for row in rows:

        global_item_id = (
            row.get("global_item_id") or ""
        ).strip().lower()

        if not global_item_id:

            print("Skipping row with empty global_item_id")
            continue

        defaults = {

            "gtin": row.get("gtin", "").strip(),
            "gpc_brick_code": row.get("gpc_brick_code", "").strip(),
            "domain": row.get("domain", "generic").strip(),
            "status": row.get("status", "draft").strip(),
            # ── media / identity ───────────────

            "country_of_origin": row.get("country_of_origin", "").strip(),
            "image_url": row.get("image_url", "").strip(),
            "image_alt": row.get("image_alt", "").strip(),
            "barcode": row.get("barcode", "").strip(),

            # ── dimensions ─────────────────────

            "weight_g": to_int(row.get("weight_g")),
            "length_mm": to_int(row.get("length_mm")),
            "width_mm": to_int(row.get("width_mm")),
            "height_mm": to_int(row.get("height_mm")),
            # ── JSON attributes ────────────────

            "attributes": json.loads(row.get("attributes", "{}")),
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


        obj, created = (
            GlobalItem.objects.update_or_create(

                global_item_id=global_item_id,
                defaults=defaults
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"GlobalItem: {global_item_id}"
        )

    print("Loaded GlobalItem")


def run():

    load_val01()

    print("Done")