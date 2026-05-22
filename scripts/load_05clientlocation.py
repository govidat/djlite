import csv
from pathlib import Path

from django.db import transaction

from mysite.models import Client, ClientLocation

from scripts.helpers import (
    clean,
    to_bool,
)

# location_id,name,location_type,is_active,client_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "05clientlocation.csv"

    # ── Read CSV once ─────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect keys ──────────────────────────────────────

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    # ── Preload clients ───────────────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Load ClientLocation ───────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True
        )

        location_id = clean(
            row.get("location_id"),
            lower=True
        )

        if not client_id or not location_id:

            print(
                "Skipping row with empty "
                "client_id/location_id"
            )

            skipped_count += 1
            continue

        key = (client_id, location_id)

        if key in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_id} / {location_id}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── Client lookup ───────────────────────────────

        client = clients.get(client_id)

        if not client:

            print(
                f"Missing client: "
                f"{client_id}"
            )

            skipped_count += 1
            continue

        defaults = {

            "is_active": to_bool(
                row.get("is_active"),
                default=False
            ),

            "name": clean(
                row.get("name")
            ),

            "location_type": clean(
                row.get("location_type")
            ),
        }

        # ── Dry Run ─────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / {location_id}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Save ────────────────────────────────────────

        obj, created = (
            ClientLocation.objects.update_or_create(

                client=client,
                location_id=location_id,

                defaults=defaults
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"ClientLocation: "
                f"{client_id} / {location_id}"
            )

    # ── Summary ──────────────────────────────────────────

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
Normal Run:
python manage.py runscript load_05clientlocation

Dry Run:
python manage.py runscript load_05clientlocation --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_05clientlocation --script-args dryrun verbose
"""