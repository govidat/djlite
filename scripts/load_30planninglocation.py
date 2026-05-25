import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    PlanningLocation,
)

from scripts.helpers import (
    clean,
    to_bool,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

# code,name,level_label,is_leaf,is_active,notes,
# client_id,parent_code,
# name_en,name_fr,name_hi,name_ta,
# level_label_en,level_label_fr,level_label_hi,level_label_ta

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "30planninglocation.csv"

    # =========================================================
    # READ CSV
    # =========================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =========================================================
    # COLLECT CLIENT IDS
    # =========================================================

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    # =========================================================
    # PREFETCH CLIENTS
    # =========================================================

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # =========================================================
    # PREFETCH EXISTING LOCATIONS
    # key = (client_id, code)
    # =========================================================

    location_cache = {}

    existing_locations = (
        PlanningLocation.objects
        .select_related("client")
        .filter(client__client_id__in=client_ids)
    )

    for loc in existing_locations:

        key = (
            loc.client.client_id,
            loc.code,
        )

        location_cache[key] = loc

    # =========================================================
    # PROCESS
    # =========================================================

    created_count = 0
    updated_count = 0
    skipped_count = 0

    pending_rows = rows.copy()

    pass_num = 1

    while pending_rows:

        print(f"\n--- PASS {pass_num} ---")

        next_pending = []

        progress_made = False

        for row in pending_rows:

            # =================================================
            # BASIC VALUES
            # =================================================

            client_id = clean(
                row.get("client_id"),
                lower=True,
            )

            code = clean(
                row.get("code"),
                lower=True,
            )

            parent_code = clean(
                row.get("parent_code"),
                lower=True,
            )

            if not client_id or not code:

                print(
                    "Skipping row with missing "
                    "client_id or code"
                )

                skipped_count += 1
                continue

            client = clients.get(client_id)

            if not client:

                print(
                    f"Missing client: {client_id}"
                )

                skipped_count += 1
                continue

            # =================================================
            # RESOLVE PARENT
            # =================================================

            parent = None

            if parent_code:

                parent = location_cache.get(
                    (
                        client_id,
                        parent_code,
                    )
                )

                if not parent:

                    next_pending.append(row)
                    continue

            # =================================================
            # DEFAULTS
            # =================================================

            defaults = {

                "parent": parent,

                "name":
                    clean(row.get("name")),

                "level_label":
                    clean(row.get("level_label")),

                "is_leaf":
                    to_bool(row.get("is_leaf")),

                "is_active":
                    to_bool(row.get("is_active")),

                "notes":
                    clean(row.get("notes")),
            }

            # =================================================
            # TRANSLATIONS
            # =================================================

            for lang in LANGS:

                defaults[f"name_{lang}"] = clean(
                    row.get(f"name_{lang}")
                )

                defaults[f"level_label_{lang}"] = clean(
                    row.get(f"level_label_{lang}")
                )

            # =================================================
            # DRY RUN
            # =================================================

            if dry_run:

                print(
                    f"[DRY RUN] "
                    f"{client_id} / {code}"
                )

                if verbose:
                    print(defaults)

                progress_made = True
                continue

            # =================================================
            # UPSERT
            # =================================================

            obj, created = (
                PlanningLocation.objects
                .update_or_create(

                    client=client,
                    code=code,

                    defaults=defaults,
                )
            )

            # =================================================
            # CACHE UPDATE
            # =================================================

            cache_key = (
                client_id,
                code,
            )

            location_cache[cache_key] = obj

            progress_made = True

            if created:
                created_count += 1
            else:
                updated_count += 1

            if verbose:

                print(
                    f"{'Created' if created else 'Updated'} "
                    f"PlanningLocation: "
                    f"{client_id} / {code}"
                )

        # =====================================================
        # NO PROGRESS
        # =====================================================

        if not progress_made:

            print("\nUNRESOLVED ROWS:")

            for row in next_pending:

                print(
                    f"Could not resolve parent "
                    f"[client="
                    f"{row.get('client_id')} "
                    f"code={row.get('code')} "
                    f"parent={row.get('parent_code')}]"
                )

            skipped_count += len(next_pending)
            break

        pending_rows = next_pending

        pass_num += 1

    # =========================================================
    # SUMMARY
    # =========================================================

    print()

    if dry_run:

        print("Dry-Run Completed -> Rollback")
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
python manage.py runscript load_20planninglocation

Dry Run:
python manage.py runscript load_20planninglocation --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_20planninglocation --script-args dryrun verbose
"""