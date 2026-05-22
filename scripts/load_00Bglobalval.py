import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    GlobalValCat,
    GlobalVal,
)

from scripts.helpers import clean


LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load GlobalVal
# ═══════════════════════════════════════════════════════

def load_globalvals(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "01globalval.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── preload GlobalValCat ─────────────────────────

    globalvalcat_ids = {

        clean(
            r.get("globalvalcat_id"),
            lower=True,
        )

        for r in rows
    }

    globalvalcats = {

        c.globalvalcat_id: c

        for c in GlobalValCat.objects.filter(
            globalvalcat_id__in=globalvalcat_ids
        )
    }

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        globalvalcat_id = clean(
            row.get("globalvalcat_id"),
            lower=True,
        )

        key = clean(
            row.get("key"),
            lower=True,
        )

        if not globalvalcat_id or not key:

            print(
                "Skipping row with empty "
                "globalvalcat_id/key"
            )

            skipped_count += 1
            continue

        duplicate_key = (
            globalvalcat_id,
            key,
        )

        if duplicate_key in seen:

            print(
                f"Duplicate CSV row: "
                f"{duplicate_key}"
            )

            skipped_count += 1
            continue

        seen.add(duplicate_key)

        globalvalcat = globalvalcats.get(
            globalvalcat_id
        )

        if not globalvalcat:

            print(
                f"Missing GlobalValCat: "
                f"{globalvalcat_id}"
            )

            skipped_count += 1
            continue

        defaults = {}

        for lang in LANGS:

            defaults[f"keyval_{lang}"] = clean(
                row.get(f"keyval_{lang}")
            )

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{globalvalcat_id} / "
                f"{key}"
            )

            if verbose:
                print(defaults)

        else:

            obj, created = (
                GlobalVal.objects.update_or_create(

                    globalvalcat=globalvalcat,
                    key=key,

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
                    f"GlobalVal: "
                    f"{globalvalcat_id} / {key}"
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

    load_globalvals(
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
python manage.py runscript load_00Bglobalval

Dry Run
--------
python manage.py runscript load_00Bglobalval --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_00Bglobalval --script-args dryrun verbose
"""