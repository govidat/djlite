import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    GlobalValCat,
)

from scripts.helpers import clean


LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load GlobalValCat
# ═══════════════════════════════════════════════════════

def load_globalvalcats(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "00globalvalcat.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        globalvalcat_id = clean(
            row.get("globalvalcat_id"),
            lower=True,
        )

        if not globalvalcat_id:

            print(
                "Skipping empty globalvalcat_id"
            )

            skipped_count += 1
            continue

        if globalvalcat_id in seen:

            print(
                f"Duplicate CSV row: "
                f"{globalvalcat_id}"
            )

            skipped_count += 1
            continue

        seen.add(globalvalcat_id)

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{globalvalcat_id}"
            )

        else:

            obj, created = (
                GlobalValCat.objects.update_or_create(

                    globalvalcat_id=globalvalcat_id,
                )
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            if verbose:

                print(
                    f"{'Created' if created else 'Updated'} "
                    f"GlobalValCat: "
                    f"{globalvalcat_id}"
                )

    print()

    print(
        f"{'Dry-Run Completed -> Rollback' if dry_run else 'Loading Completed'}"
    )

    print(
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )

# ═══════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════

@transaction.atomic
def run(*args):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_globalvalcats(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

    if DRY_RUN:

        print()
        print(
            "DRY RUN COMPLETE → rollback"
        )

        transaction.set_rollback(True)

    print("Done")


"""
Normal Run
-----------
python manage.py runscript load_00Aglobalvalcat

Dry Run
--------
python manage.py runscript load_00Aglobalvalcat --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_00Aglobalvalcat --script-args dryrun verbose
"""