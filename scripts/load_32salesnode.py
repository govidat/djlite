import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    PlanningLocation,
    SalesNode,
)

from scripts.helpers import (
    clean,
    to_bool,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

# ============================================================
# CSV FORMAT
# ============================================================

# code,is_active,client_id,parent_code,planning_location_code,
# level_label_en,level_label_fr,level_label_hi,level_label_ta,
# name_en,name_fr,name_hi,name_ta

# ============================================================
# SAMPLE CSV
# ============================================================

"""
code,is_active,client_id,parent_code,planning_location_code,level_label_en,level_label_fr,level_label_hi,level_label_ta,name_en,name_fr,name_hi,name_ta
aism,1,bahushira,,,National Manager,,,,All India Sales Manager,,,
rmchennai,1,bahushira,aism,chennai,Regional Manager,,,,Regional Manager Chennai,,,
amadyar,1,bahushira,rmchennai,adyar,Area Manager,,,,Area Manager Adyar,,,
sr001,1,bahushira,amadyar,adyar,Sales Rep,,,,Sales Representative 001,,,
"""

# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

# ============================================================
# LOADER
# ============================================================


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "32salesnode.csv"

    # ========================================================
    # READ CSV
    # ========================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ========================================================
    # COLLECT IDS
    # ========================================================

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    planning_location_codes = {
        clean(row.get("planning_location_code"), lower=True)
        for row in rows
        if clean(row.get("planning_location_code"))
    }

    # ========================================================
    # PREFETCH CLIENTS
    # ========================================================

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ========================================================
    # PREFETCH PLANNING LOCATIONS
    # key = (client_id, code)
    # ========================================================

    planning_locations = {}

    for loc in (
        PlanningLocation.objects
        .filter(code__in=planning_location_codes)
        .select_related("client")
    ):

        key = (
            loc.client.client_id,
            loc.code,
        )

        planning_locations[key] = loc

    # ========================================================
    # PREFETCH EXISTING SALES NODES
    # key = (client_id, code)
    # ========================================================

    salesnode_cache = {}

    existing_nodes = (
        SalesNode.objects
        .select_related(
            "client",
            "parent",
            "planning_location",
        )
    )

    for n in existing_nodes:

        key = (
            n.client.client_id,
            n.code,
        )

        salesnode_cache[key] = n

    # ========================================================
    # PROCESS
    # ========================================================

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

            planning_location_code = clean(
                row.get("planning_location_code"),
                lower=True,
            )

            # =================================================
            # VALIDATION
            # =================================================

            if not client_id or not code:

                print(
                    "Skipping row with missing "
                    "client_id or code"
                )

                skipped_count += 1
                continue

            # =================================================
            # CLIENT
            # =================================================

            client = clients.get(client_id)

            if not client:

                print(
                    f"Missing client: {client_id}"
                )

                skipped_count += 1
                continue

            # =================================================
            # PARENT
            # =================================================

            parent = None

            if parent_code:

                parent = salesnode_cache.get(
                    (
                        client_id,
                        parent_code,
                    )
                )

                # unresolved parent
                if not parent:

                    next_pending.append(row)
                    continue

            # =================================================
            # PLANNING LOCATION
            # =================================================

            planning_location = None

            if planning_location_code:

                planning_location = planning_locations.get(
                    (
                        client_id,
                        planning_location_code,
                    )
                )

                if not planning_location:

                    print(
                        f"Missing PlanningLocation: "
                        f"{client_id} / "
                        f"{planning_location_code}"
                    )

                    skipped_count += 1
                    continue

            # =================================================
            # DEFAULTS
            # =================================================

            defaults = {

                "parent":
                    parent,

                "planning_location":
                    planning_location,

                "is_active":
                    to_bool(row.get("is_active")),
            }

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
                    f"{client_id} / "
                    f"{code}"
                )

                if verbose:
                    print(defaults)

                progress_made = True
                continue

            # =================================================
            # UPSERT
            # =================================================

            obj, created = (
                SalesNode.objects
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

            salesnode_cache[cache_key] = obj

            progress_made = True

            if created:
                created_count += 1
            else:
                updated_count += 1

            if verbose:

                print(
                    f"{'Created' if created else 'Updated'} "
                    f"SalesNode: "
                    f"{client_id} / "
                    f"{code}"
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

    # ========================================================
    # SUMMARY
    # ========================================================

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


# ============================================================
# RUN
# ============================================================

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
python manage.py runscript load_32salesnode

Dry Run:
python manage.py runscript load_32salesnode --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_32salesnode --script-args dryrun verbose
"""