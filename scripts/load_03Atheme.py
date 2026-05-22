import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    ThemePreset,
    Theme,
)

from scripts.helpers import (
    clean,
    to_int,
    to_bool,
    to_json,
)


LANGS = [lang[0] for lang in settings.LANGUAGES]


# id,theme_id,order,hidden,overrides,is_default,
# client_id,themepreset_id,
# name,name_en,name_fr,name_hi,name_ta,ltext


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load Theme
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03Atheme.csv"

    # ── Read CSV once ───────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── Collect keys ────────────────────────────────────

    client_ids = {

        clean(
            r.get("client_id"),
            lower=True,
        )

        for r in rows
    }

    themepreset_ids = {

        clean(
            r.get("themepreset_id"),
            lower=True,
        )

        for r in rows
    }

    # ── Preload Clients ─────────────────────────────────

    clients = {

        c.client_id: c

        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Preload ThemePresets ────────────────────────────

    themepresets = {

        tp.themepreset_id: tp

        for tp in ThemePreset.objects.filter(
            themepreset_id__in=themepreset_ids
        )
    }

    # ── Counters ────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load Themes ─────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        theme_id = clean(
            row.get("theme_id"),
            lower=True,
        )

        themepreset_id = clean(
            row.get("themepreset_id"),
            lower=True,
        )

        # ── validation ────────────────────────────────

        if not client_id or not theme_id:

            print(
                "Skipping row with empty "
                "client_id/theme_id"
            )

            skipped_count += 1
            continue

        key = (
            client_id,
            theme_id,
        )

        if key in seen:

            print(
                f"Duplicate CSV row: {key}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── resolve client ────────────────────────────

        client = clients.get(client_id)

        if not client:

            print(
                f"Missing client: "
                f"{client_id}"
            )

            skipped_count += 1
            continue

        # ── resolve theme preset ──────────────────────

        themepreset = None

        if themepreset_id:

            themepreset = themepresets.get(
                themepreset_id
            )

            if not themepreset:

                print(
                    f"Missing ThemePreset: "
                    f"{themepreset_id}"
                )

                skipped_count += 1
                continue

        # ── defaults ──────────────────────────────────

        defaults = {

            "hidden":
                to_bool(row.get("hidden")),

            "order":
                to_int(row.get("order")) or 0,

            "overrides":
                to_json(row.get("overrides")),

            "is_default":
                to_bool(row.get("is_default")),

            "themepreset":
                themepreset,

            "ltext":
                clean(row.get("ltext")),
        }

        # ── multilingual fields ───────────────────────

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

        # ── DRY RUN ───────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / {theme_id}"
            )

            if verbose:
                print(defaults)

        # ── SAVE ──────────────────────────────────────

        else:

            obj, created = (
                Theme.objects.update_or_create(

                    client=client,
                    theme_id=theme_id,

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
                    f"Theme: "
                    f"{client_id} / {theme_id}"
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
python manage.py runscript load_03atheme

Dry Run
--------
python manage.py runscript load_03atheme --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_03atheme --script-args dryrun verbose
"""