import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    AttributeType,
)

from scripts.helpers import (
    clean,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

# client_code,slug,
# name_en,name_hi,name_fr,name_ta,
# field_type,gpc_code

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


@transaction.atomic
def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = data_dir / "08Aattributetype.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect lookup keys ─────────────────────────────────

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if clean(row.get("client_code"))
    }

    # ── Prefetch Clients ────────────────────────────────────

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # ── Counters ────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Process Rows ────────────────────────────────────────

    for row in rows:

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        slug = clean(
            row.get("slug"),
            lower=True,
        )

        if not slug:

            print("Skipping row with missing slug")

            skipped_count += 1
            continue

        # ── Duplicate Detection ────────────────────────────

        key = (
            client_code or None,
            slug,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve Client ─────────────────────────────────

        client = (
            clients.get(client_code)
            if client_code else None
        )

        if client_code and not client:

            print(f"Missing Client: {client_code}")

            skipped_count += 1
            continue

        # ── Defaults ────────────────────────────────────────

        defaults = {
            "field_type": clean(row.get("field_type")) or "text",
            "gpc_code": clean(row.get("gpc_code")) or "",
        }

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

        # ── Dry Run ─────────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code or 'GLOBAL'} / {slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ─────────────────────────────────

        obj, created = (
            AttributeType.objects.update_or_create(

                client=client,
                slug=slug,

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
                f"AttributeType: "
                f"{client_code or 'GLOBAL'} / {slug}"
            )

    # ── Summary ─────────────────────────────────────────────

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
Normal Run:
python manage.py runscript load_08Aattributetype

Dry Run:
python manage.py runscript load_08Aattributetype --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_08Aattributetype --script-args dryrun verbose
"""
