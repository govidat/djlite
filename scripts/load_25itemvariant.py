import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Item,
    ItemVariant,
)

from scripts.helpers import (
    clean,
    to_int,
    to_bool,
    to_json,
    to_decimal,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LANGS = [lang[0] for lang in settings.LANGUAGES]


# item_id,variant_id,sku,gtin,
# name_en,name_hi,name_fr,name_ta,
# price,stock,is_active,image_url,
# order,attributes,client_id


# =========================================================
# Loader
# =========================================================

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "24itemvariant.csv"

    # -----------------------------------------------------
    # Read CSV
    # -----------------------------------------------------

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    # -----------------------------------------------------
    # Collect Keys
    # -----------------------------------------------------

    client_ids = {

        clean(
            row.get("client_id"),
            lower=True,
        )

        for row in rows

        if row.get("client_id")
    }

    item_ids = {

        clean(
            row.get("item_id"),
            lower=True,
        )

        for row in rows

        if row.get("item_id")
    }

    # -----------------------------------------------------
    # Prefetch Items
    # -----------------------------------------------------

    items = {

        (
            item.client.client_id,
            item.item_id,
        ): item

        for item in Item.objects.filter(

            client__client_id__in=client_ids,
            item_id__in=item_ids,

        ).select_related("client")
    }

    # -----------------------------------------------------
    # Stats
    # -----------------------------------------------------

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # -----------------------------------------------------
    # Process Rows
    # -----------------------------------------------------

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        item_id = clean(
            row.get("item_id"),
            lower=True,
        )

        variant_id = clean(
            row.get("variant_id"),
            lower=True,
        )

        # -------------------------------------------------
        # Validation
        # -------------------------------------------------

        if not client_id:

            print(
                "Skipping row with empty client_id"
            )

            skipped_count += 1
            continue

        if not item_id:

            print(
                "Skipping row with empty item_id"
            )

            skipped_count += 1
            continue

        if not variant_id:

            print(
                "Skipping row with empty variant_id"
            )

            skipped_count += 1
            continue

        key = (
            client_id,
            item_id,
            variant_id,
        )

        if key in seen:

            print(
                f"Duplicate CSV row: {key}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # -------------------------------------------------
        # Resolve Item
        # -------------------------------------------------

        item = items.get(
            (
                client_id,
                item_id,
            )
        )

        if not item:

            print(
                f"Missing Item: "
                f"{client_id} / "
                f"{item_id}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # Defaults
        # -------------------------------------------------

        defaults = {

            "sku": clean(
                row.get("sku")
            ),

            "gtin": clean(
                row.get("gtin")
            ),

            "price": to_decimal(
                row.get("price")
            ),

            "stock": to_int(
                row.get("stock"),
                default=0,
            ),

            "is_active": to_bool(
                row.get("is_active")
            ),

            "image_url": clean(
                row.get("image_url")
            ),

            "order": to_int(
                row.get("order"),
                default=0,
            ),

            "attributes": to_json(
                row.get("attributes")
            ),
        }

        # -------------------------------------------------
        # Multilingual Fields
        # -------------------------------------------------

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

        # -------------------------------------------------
        # Dry Run
        # -------------------------------------------------

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / "
                f"{item_id} / "
                f"{variant_id}"
            )

            if verbose:
                print(defaults)

            continue

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        obj, created = (
            ItemVariant.objects.update_or_create(

                item=item,
                variant_id=variant_id,

                defaults=defaults,
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"ItemVariant: "
                f"{client_id} / "
                f"{item_id} / "
                f"{variant_id}"
            )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()

    if dry_run:

        print(
            "Dry-Run Completed -> Rollback"
        )

        transaction.set_rollback(True)

    else:

        print("Loading Completed")

        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )


# =========================================================
# Runner
# =========================================================

@transaction.atomic
def run(*args):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

    print("Done")


"""
Normal Run
----------
python manage.py runscript ...

Dry Run + Verbose
-----------------
python manage.py runscript ... --script-args dryrun verbose
"""

"""


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

"""