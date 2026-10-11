import csv
from pathlib import Path

from django.db import transaction

from mysite.models import ThemePreset

from scripts.helpers import clean


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load ThemePreset
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "02themepreset.csv"

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

        themepreset_code = clean(
            row.get("themepreset_code"),
            lower=True,
        )

        if not themepreset_code:

            print(
                "Skipping empty themepreset_code"
            )

            skipped_count += 1
            continue

        if themepreset_code in seen:

            print(
                f"Duplicate CSV row: "
                f"{themepreset_code}"
            )

            skipped_count += 1
            continue

        seen.add(themepreset_code)

        defaults = {

            "ltext": clean(row.get("ltext")),

            "primary": clean(row.get("primary")),
            "primary_content": clean(row.get("primary_content")),

            "secondary": clean(row.get("secondary")),
            "secondary_content": clean(row.get("secondary_content")),

            "accent": clean(row.get("accent")),
            "accent_content": clean(row.get("accent_content")),

            "neutral": clean(row.get("neutral")),
            "neutral_content": clean(row.get("neutral_content")),

            "base_100": clean(row.get("base_100")),
            "base_200": clean(row.get("base_200")),
            "base_300": clean(row.get("base_300")),
            "base_content": clean(row.get("base_content")),

            "success": clean(row.get("success")),
            "success_content": clean(row.get("success_content")),

            "warning": clean(row.get("warning")),
            "warning_content": clean(row.get("warning_content")),

            "error": clean(row.get("error")),
            "error_content": clean(row.get("error_content")),

            "info": clean(row.get("info")),
            "info_content": clean(row.get("info_content")),
        }

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{themepreset_code}"
            )

            if verbose:
                print(defaults)

        else:

            obj, created = (
                ThemePreset.objects.update_or_create(

                    themepreset_code=themepreset_code,

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
                    f"ThemePreset: "
                    f"{themepreset_code}"
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

    load_val01(
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
python manage.py runscript load_02themepreset

Dry Run
--------
python manage.py runscript load_02themepreset --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_02themepreset --script-args dryrun verbose
"""