import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import Client, Taxonomy

from scripts.helpers import (
    clean,
    to_int,
    to_bool,
)

# slug,order,is_active,client_id,
# name_en,name_fr,name_hi,name_ta,
# description_en,description_fr,description_hi,description_ta,
# gpc_segment_code,taxonomy_type

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "06taxonomy.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect required client_ids ─────────────────────────

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    # ── Prefetch clients ────────────────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Counters ────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load Taxonomy ───────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True
        )

        slug = clean(
            row.get("slug"),
            lower=True
        )

        # ── validations ──────────────────────────────────

        if not slug:

            print("Skipping row with empty slug")

            skipped_count += 1
            continue

        key = (
            client_id,
            slug,
        )

        if key in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_id or 'GLOBAL'} / {slug}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── resolve client ───────────────────────────────

        client = None

        if client_id:

            client = clients.get(client_id)

            if not client:

                print(
                    f"Missing client: {client_id}"
                )

                skipped_count += 1
                continue

        # ── defaults ─────────────────────────────────────

        defaults = {

            "is_active":
                to_bool(row.get("is_active")),

            "order":
                to_int(row.get("order")) or 0,

            "gpc_segment_code":
                clean(row.get("gpc_segment_code")),

            "taxonomy_type":
                clean(row.get("taxonomy_type")),
        }

        # ── multilingual fields ──────────────────────────

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

            defaults[f"description_{lang}"] = clean(
                row.get(f"description_{lang}")
            )

        # ── DRY RUN ──────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id or 'GLOBAL'} / "
                f"{slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ──────────────────────────────

        obj, created = (
            Taxonomy.objects.update_or_create(

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
                f"Taxonomy: "
                f"{client_id or 'GLOBAL'} / "
                f"{slug}"
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
python manage.py runscript load_06taxonomy

Dry Run:
python manage.py runscript load_06taxonomy --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_06taxonomy --script-args dryrun verbose
"""

"""

import csv
from pathlib import Path

from mysite.models import Client, Taxonomy
#slug,order,is_active,client_id,name_en,name_fr,name_hi,name_ta,description_en,description_fr,description_hi,description_ta,gpc_segment_code,taxonomy_type
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "06taxonomy.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }


    # ── Fetch only required clients  ─────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }



    # ── Second pass: load navs ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

    #    reader = csv.DictReader(f)

    for row in rows:
        client_id = (row.get("client_id") or "").strip().lower()
        client = clients.get(client_id) if client_id else None    # None is expected for Global Values
        
        slug= row.get("slug", "")

        obj, created = Taxonomy.objects.update_or_create(

            client=client,
            slug= slug,

            defaults={
                
                "is_active": row.get("is_active", "0") == "1",
                "order": int(row.get("order", 0)),                
                "name_en": row.get("name_en", ""),                
                "name_hi": row.get("name_hi", ""),
                "name_fr": row.get("name_fr", ""),
                "name_ta": row.get("name_ta", ""),

                "description_en": row.get("description_en", ""),                
                "description_hi": row.get("description_hi", ""),
                "description_fr": row.get("description_fr", ""),
                "description_ta": row.get("description_ta", ""),

                "gpc_segment_code": row.get("gpc_segment_code", ""),
                "taxonomy_type": row.get("taxonomy_type", ""),

            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"Taxonomy: {client_id if client_id else 'Global'} / {slug}"
        )

    print("Loaded Taxonomy")


def run():

    load_val01()

    print("Done")
"""