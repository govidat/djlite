import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    Page,
    PageContent,
)

from scripts.helpers import clean

# client_id,page_id,
# htmlblob_en,htmlblob_hi,
# htmlblob_fr,htmlblob_ta

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LANGS = [lang[0] for lang in settings.LANGUAGES]


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03Dpagecontent.csv"

    # =====================================================
    # READ CSV
    # =====================================================

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =====================================================
    # COLLECT IDS
    # =====================================================

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    page_ids = {
        clean(row.get("page_id"), lower=True)
        for row in rows
        if clean(row.get("page_id"))
    }

    # =====================================================
    # PREFETCH CLIENTS
    # =====================================================

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # =====================================================
    # PREFETCH PAGES
    # =====================================================

    pages = {
        (
            p.client.client_id,
            p.page_id
        ): p

        for p in Page.objects.filter(
            client__client_id__in=client_ids,
            page_id__in=page_ids,
        ).select_related("client")
    }

    # =====================================================
    # LOAD
    # =====================================================

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        # -------------------------------------------------
        # BASIC VALUES
        # -------------------------------------------------

        client_id = clean(
            row.get("client_id"),
            lower=True
        )

        page_id = clean(
            row.get("page_id"),
            lower=True
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not client_id or not page_id:

            print(
                "Skipping row with missing "
                "client_id / page_id"
            )

            skipped_count += 1
            continue

        row_key = (
            client_id,
            page_id,
        )

        if row_key in seen:

            print(
                f"Duplicate CSV row: "
                f"{row_key}"
            )

            skipped_count += 1
            continue

        seen.add(row_key)

        # -------------------------------------------------
        # CLIENT
        # -------------------------------------------------

        client = clients.get(client_id)

        if not client:

            print(
                f"Missing client: "
                f"{client_id}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # PAGE
        # -------------------------------------------------

        page = pages.get(
            (client_id, page_id)
        )

        if not page:

            print(
                f"Missing page: "
                f"{client_id} / {page_id}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # DEFAULTS
        # -------------------------------------------------

        defaults = {}

        for lang in LANGS:

            defaults[
                f"htmlblob_{lang}"
            ] = clean(
                row.get(f"htmlblob_{lang}")
            )

        # -------------------------------------------------
        # DRY RUN
        # -------------------------------------------------

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / "
                f"{page_id}"
            )

            if verbose:
                print(defaults)

            continue

        # -------------------------------------------------
        # SAVE
        # -------------------------------------------------

        obj, created = (
            PageContent.objects.update_or_create(

                page=page,

                defaults=defaults
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"PageContent: "
                f"{client_id} / "
                f"{page_id}"
            )

    # =====================================================
    # SUMMARY
    # =====================================================

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
python manage.py runscript load_03dpagecontent

Dry Run:
python manage.py runscript load_03dpagecontent --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_03dpagecontent --script-args dryrun verbose
"""

"""

import csv
from pathlib import Path

from mysite.models import Client, Page, PageContent
#client_id, page_id, htmlblob_en, htmlblob_fr, htmlblob_hi
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "03Dpagecontent.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }


        page_ids = {
            (row.get("page_id") or "").strip().lower()
            for row in rows
            if (row.get("page_id") or "").strip()
        }

    # ── Fetch only required clients and pages ─────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    pages = {
        (p.client.client_id, p.page_id): p
        for p in Page.objects.filter(
            client__client_id__in=client_ids,
            page_id__in=page_ids,
        ).select_related("client")
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

        # ── page ───────────────────────────────────────

        page = None
        page_id = row.get("page_id")
        if page_id:
            page = pages.get((client_id, page_id))
            if not page:
                print(f"Missing page: {client_id} / {page_id}")
                continue


        obj, created = PageContent.objects.update_or_create(

            page=page,

            defaults={

                "htmlblob_en": row.get("htmlblob_en", ""),
                "htmlblob_hi": row.get("htmlblob_hi", ""),
                "htmlblob_fr": row.get("htmlblob_fr", ""),                    
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"PageContent: {client_id} / {page_id}"
        )

    print("Loaded PageContent")


def run():

    load_val01()

    print("Done")
"""