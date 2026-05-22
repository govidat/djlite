import csv
from pathlib import Path

from django.db import transaction

from mysite.models import Client, ClientGroup

from scripts.helpers import (
    clean,
    to_bool,
)

# group_id,name,role,description,is_active,client_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "04clientgroup.csv"

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

    # ── Load ClientGroup ──────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True
        )

        group_id = clean(
            row.get("group_id"),
            lower=True
        )

        if not client_id or not group_id:

            print(
                "Skipping row with empty "
                "client_id/group_id"
            )

            skipped_count += 1
            continue

        key = (client_id, group_id)

        if key in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_id} / {group_id}"
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

            "role": clean(
                row.get("role")
            ),

            "description": clean(
                row.get("description")
            ),
        }

        # ── Dry Run ─────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / {group_id}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Save ────────────────────────────────────────

        obj, created = (
            ClientGroup.objects.update_or_create(

                client=client,
                group_id=group_id,

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
                f"ClientGroup: "
                f"{client_id} / {group_id}"
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
python manage.py runscript load_04clientgroup

Dry Run:
python manage.py runscript load_04clientgroup --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_04clientgroup --script-args dryrun verbose
"""