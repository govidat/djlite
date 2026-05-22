import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import Client, ClientTemplate
from scripts.helpers import clean, to_bool


# client_id,template_key,is_active,
# htmlblob_en,htmlblob_hi,htmlblob_fr,htmlblob_ta

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03Eclienttemplate.csv"

    # ── Read CSV once ─────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect required client_ids ──────────────────────

    client_ids = {

        clean(row.get("client_id"), lower=True)

        for row in rows

        if clean(row.get("client_id"), lower=True)
    }

    # ── Prefetch clients ──────────────────────────────────

    clients = {

        c.client_id: c

        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Counters ──────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load ClientTemplate ───────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        template_key = clean(
            row.get("template_key")
        )

        if not client_id or not template_key:

            print(
                "Skipping row with empty "
                "client_id/template_key"
            )

            skipped_count += 1
            continue

        key = (client_id, template_key)

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve client ──────────────────────────────

        client = clients.get(client_id)

        if not client:

            print(f"Missing client: {client_id}")

            skipped_count += 1
            continue

        # ── Defaults ────────────────────────────────────

        defaults = {

            "is_active":
                to_bool(row.get("is_active")),
        }

        # ── Multi-language fields ───────────────────────

        for lang in LANGS:

            defaults[f"htmlblob_{lang}"] = clean(
                row.get(f"htmlblob_{lang}")
            )

        # ── Dry Run ──────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / "
                f"{template_key}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ─────────────────────────────

        obj, created = (
            ClientTemplate.objects.update_or_create(

                client=client,
                template_key=template_key,

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
                f"ClientTemplate: "
                f"{client_id} / "
                f"{template_key}"
            )

    # ── Summary ───────────────────────────────────────────

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
python manage.py runscript load_03eclienttemplate

Dry Run:
python manage.py runscript load_03eclienttemplate --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_03eclienttemplate --script-args dryrun verbose
"""
"""

import csv
from pathlib import Path

from mysite.models import Client, ClientTemplate
#client_id, page_id, htmlblob_en, htmlblob_fr, htmlblob_hi
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "03Eclienttemplate.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }


    # ── Fetch only required clients and pages ─────────────────────────

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

        client_id = row["client_id"]
        client = clients.get(client_id)
        if not client:
            print(f"Missing client: {client_id}")
            continue
        
        template_key= row.get("template_key", "")

        obj, created = ClientTemplate.objects.update_or_create(

            client=client,
            template_key= template_key,

            defaults={
                "is_active": row.get("is_active", "0") == "1",

                "htmlblob_en": row.get("htmlblob_en", ""),
                "htmlblob_hi": row.get("htmlblob_hi", ""),
                "htmlblob_fr": row.get("htmlblob_fr", ""),                    
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"ClientTemplate: {client_id} / {template_key}"
        )

    print("Loaded ClientTemplate")


def run():

    load_val01()

    print("Done")
"""