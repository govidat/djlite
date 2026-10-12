import csv
from pathlib import Path

from django.db import transaction

from mysite.models import (
    Client,
    ClientLocation,
)

from scripts.helpers import (
    clean,
    to_bool,
)

# =========================================================
# CSV FORMAT
# =========================================================
# location_code,name,location_type,is_active,
# client_code,parent_location_code
#
# Example:
#
# location_code,name,location_type,is_active,client_code,parent_location_code
# india,India,office,1,bahushira,
# south,South Region,branch,1,bahushira,india
# blr,Bangalore Branch,branch,1,bahushira,south
# wh1,Warehouse 1,warehouse,1,bahushira,blr

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# =========================================================
# Loader
# =========================================================

def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = (
        data_dir /
        "05clientlocation.csv"
    )

    # =====================================================
    # READ CSV
    # =====================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =====================================================
    # COLLECT CLIENT IDS
    # =====================================================

    client_codes = {

        clean(
            row.get("client_code"),
            lower=True,
        )

        for row in rows

        if clean(row.get("client_code"))
    }

    # =====================================================
    # PREFETCH CLIENTS
    # =====================================================

    clients = {

        c.client_code: c

        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # =====================================================
    # PREFETCH EXISTING LOCATIONS
    # key = (client_code, location_code)
    # =====================================================

    location_cache = {}

    existing_locations = (
        ClientLocation.objects
        .filter(
            client__client_code__in=client_codes
        )
        .select_related("client")
    )

    for loc in existing_locations:

        key = (
            loc.client.client_code,
            loc.location_code,
        )

        location_cache[key] = loc

    # =====================================================
    # PROCESS
    # =====================================================

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

            client_code = clean(
                row.get("client_code"),
                lower=True,
            )

            location_code = clean(
                row.get("location_code"),
                lower=True,
            )

            parent_location_code = clean(
                row.get("parent_location_code"),
                lower=True,
            )

            if not client_code or not location_code:

                print(
                    "Skipping row with missing "
                    "client_code or location_code"
                )

                skipped_count += 1
                continue

            # =================================================
            # CLIENT
            # =================================================

            client = clients.get(client_code)

            if not client:

                print(
                    f"Missing client: "
                    f"{client_code}"
                )

                skipped_count += 1
                continue

            # =================================================
            # PARENT LOCATION
            # =================================================

            parent = None

            if parent_location_code:

                parent = location_cache.get(
                    (
                        client_code,
                        parent_location_code,
                    )
                )

                # unresolved parent
                if not parent:

                    next_pending.append(row)
                    continue

            # =================================================
            # DEFAULTS
            # =================================================

            defaults = {

                "name": clean(
                    row.get("name")
                ),

                "location_type": clean(
                    row.get("location_type")
                ),

                "is_active": to_bool(
                    row.get("is_active")
                ),

                "parent": parent,
            }

            # =================================================
            # DRY RUN
            # =================================================

            if dry_run:

                print(
                    f"[DRY RUN] "
                    f"{client_code} / "
                    f"{location_code}"
                )

                if verbose:
                    print(defaults)

                progress_made = True
                continue

            # =================================================
            # UPSERT
            # =================================================

            obj, created = (
                ClientLocation.objects
                .update_or_create(

                    client=client,
                    location_code=location_code,

                    defaults=defaults,
                )
            )

            # =================================================
            # CACHE UPDATE
            # =================================================

            cache_key = (
                client_code,
                location_code,
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
                    f"ClientLocation: "
                    f"{client_code} / "
                    f"{location_code}"
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
                    f"{row.get('client_code')} "
                    f"location="
                    f"{row.get('location_code')} "
                    f"parent="
                    f"{row.get('parent_location_code')}]"
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
# RUNNER
# =========================================================

@transaction.atomic
def run(*args, data_dir=None):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
        data_dir=data_dir,
    )

    print("Done")


"""
Normal Run
----------
python manage.py runscript load_05clientlocation

Dry Run
--------
python manage.py runscript load_05clientlocation --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_05clientlocation --script-args dryrun verbose
"""
"""

import csv
from pathlib import Path

from mysite.models import Client, ClientLocation
#location_code,name,location_type,is_active,client_code
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "05clientlocation.csv"

    # ── First pass: collect client_codes from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_codes = {
            (row.get("client_code") or "").strip().lower()
            for row in rows
            if (row.get("client_code") or "").strip()
        }


    # ── Fetch only required clients  ─────────────────────────

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }



    # ── Second pass: load navs ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

    #    reader = csv.DictReader(f)

    for row in rows:

        client_code = row["client_code"]
        client = clients.get(client_code)
        if not client:
            print(f"Missing client: {client_code}")
            continue
        
        location_code= row.get("location_code", "")

        obj, created = ClientLocation.objects.update_or_create(

            client=client,
            location_code= location_code,

            defaults={
                
                "is_active": row.get("is_active", "0") == "1",

                "name": row.get("name", ""),
                "location_type": row.get("location_type", ""),                  
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"ClientLocation: {client_code} / {location_code}"
        )

    print("Loaded ClientLocation")


def run():

    load_val01()

    print("Done")

"""