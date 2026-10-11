import csv
from pathlib import Path

from django.db import transaction

from mysite.models import (
    Client,
    Page,
)

from scripts.helpers import (
    clean,
    to_bool,
)


# id,page_code,ltext,hidden,client_code


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load Page
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03Bpage.csv"

    # ── Read CSV once ───────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── Collect keys ────────────────────────────────────

    client_codes = {

        clean(
            r.get("client_code"),
            lower=True,
        )

        for r in rows
    }

    # ── Preload Clients ─────────────────────────────────

    clients = {

        c.client_code: c

        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # ── Counters ────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load Pages ──────────────────────────────────────

    for row in rows:

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        page_code = clean(
            row.get("page_code"),
            lower=True,
        )

        # ── validation ────────────────────────────────

        if not client_code or not page_code:

            print(
                "Skipping row with empty "
                "client_code/page_code"
            )

            skipped_count += 1
            continue

        key = (
            client_code,
            page_code,
        )

        if key in seen:

            print(
                f"Duplicate CSV row: {key}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── resolve client ────────────────────────────

        client = clients.get(client_code)

        if not client:

            print(
                f"Missing client: "
                f"{client_code}"
            )

            skipped_count += 1
            continue

        # ── defaults ──────────────────────────────────

        defaults = {

            "hidden":
                to_bool(row.get("hidden")),

            "ltext":
                clean(row.get("ltext")),
        }

        # ── DRY RUN ───────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code} / {page_code}"
            )

            if verbose:
                print(defaults)

        # ── SAVE ──────────────────────────────────────

        else:

            obj, created = (
                Page.objects.update_or_create(

                    client=client,
                    page_code=page_code,

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
                    f"Page: "
                    f"{client_code} / {page_code}"
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
python manage.py runscript load_03bpage

Dry Run
--------
python manage.py runscript load_03bpage --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_03bpage --script-args dryrun verbose
"""