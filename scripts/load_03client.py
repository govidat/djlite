import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import Client

from scripts.helpers import (
    clean,
    to_json,
)


LANGS = [lang[0] for lang in settings.LANGUAGES]


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load Client
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03client.csv"

    # ── Read CSV once ───────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── Counters ────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load Clients ────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        # ── validation ────────────────────────────────

        if not client_id:

            print(
                "Skipping row with empty client_id"
            )

            skipped_count += 1
            continue

        if client_id in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_id}"
            )

            skipped_count += 1
            continue

        seen.add(client_id)

        # ── defaults ──────────────────────────────────

        defaults = {

            "language_list":
                to_json(row.get("language_list")),

            "theme_list":
                to_json(row.get("theme_list")),

            "nb_title_svg_pre":
                clean(row.get("nb_title_svg_pre")),

            "nb_title_svg_suf":
                clean(row.get("nb_title_svg_suf")),

            "default_language":
                clean(
                    row.get("default_language")
                ) or "en",
        }

        # ── multilingual fields ───────────────────────

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

            defaults[f"nb_title_{lang}"] = clean(
                row.get(f"nb_title_{lang}")
            )

        # ── DRY RUN ───────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id}"
            )

            if verbose:
                print(defaults)

        # ── SAVE ──────────────────────────────────────

        else:

            obj, created = (
                Client.objects.update_or_create(

                    client_id=client_id,

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
                    f"Client: "
                    f"{client_id}"
                )

    # ── Summary ────────────────────────────────────────

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
python manage.py runscript load_03client

Dry Run
--------
python manage.py runscript load_03client --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_03client --script-args dryrun verbose
"""