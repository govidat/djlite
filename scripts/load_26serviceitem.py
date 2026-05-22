import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Item,
    ServiceItem,
)

from scripts.helpers import (
    clean,
    to_bool,
    to_int,
    to_decimal,
    to_json,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# =========================================================
# Loader
# =========================================================

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "26serviceitem.csv"

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
    # Collect keys
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
    # Process rows
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

        # -------------------------------------------------
        # Validation
        # -------------------------------------------------

        if not client_id or not item_id:

            print(
                "Skipping row with empty "
                "client_id/item_id"
            )

            skipped_count += 1
            continue

        key = (client_id, item_id)

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

        item = items.get(key)

        if not item:

            print(
                f"Missing Item: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # Defaults
        # -------------------------------------------------

        defaults = {

            "price": to_decimal(
                row.get("price")
            ),

            "currency": clean(
                row.get("currency", "INR")
            ),

            "duration_minutes": to_int(
                row.get("duration_minutes"),
                default=None,
            ),

            "is_location_based": to_bool(
                row.get("is_location_based")
            ),

            "service_area": clean(
                row.get("service_area")
            ),

            "fulfillment_type": clean(
                row.get("fulfillment_type")
            ),

            "attributes": to_json(
                row.get("attributes")
            ),
        }

        # -------------------------------------------------
        # Dry Run
        # -------------------------------------------------

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / {item_id}"
            )

            if verbose:
                print(defaults)

            continue

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        obj, created = (
            ServiceItem.objects.update_or_create(

                item=item,

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
                f"ServiceItem: "
                f"{client_id} / {item_id}"
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