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

# client_code,page_code,
# htmlblob_en,htmlblob_hi,
# htmlblob_fr,htmlblob_ta

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LANGS = [lang[0] for lang in settings.LANGUAGES]


def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = data_dir / "03Dpagecontent.csv"

    # =====================================================
    # READ CSV
    # =====================================================

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =====================================================
    # COLLECT IDS
    # =====================================================

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if clean(row.get("client_code"))
    }

    page_codes = {
        clean(row.get("page_code"), lower=True)
        for row in rows
        if clean(row.get("page_code"))
    }

    # =====================================================
    # PREFETCH CLIENTS
    # =====================================================

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # =====================================================
    # PREFETCH PAGES
    # =====================================================

    pages = {
        (
            p.client.client_code,
            p.page_code
        ): p

        for p in Page.objects.filter(
            client__client_code__in=client_codes,
            page_code__in=page_codes,
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

        client_code = clean(
            row.get("client_code"),
            lower=True
        )

        page_code = clean(
            row.get("page_code"),
            lower=True
        )

        # -------------------------------------------------
        # VALIDATION
        # -------------------------------------------------

        if not client_code or not page_code:

            print(
                "Skipping row with missing "
                "client_code / page_code"
            )

            skipped_count += 1
            continue

        row_key = (
            client_code,
            page_code,
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

        client = clients.get(client_code)

        if not client:

            print(
                f"Missing client: "
                f"{client_code}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # PAGE
        # -------------------------------------------------

        page = pages.get(
            (client_code, page_code)
        )

        if not page:

            print(
                f"Missing page: "
                f"{client_code} / {page_code}"
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
                f"{client_code} / "
                f"{page_code}"
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
                f"{client_code} / "
                f"{page_code}"
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
#client_code, page_code, htmlblob_en, htmlblob_fr, htmlblob_hi
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "03Dpagecontent.csv"

    # ── First pass: collect client_codes from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_codes = {
            (row.get("client_code") or "").strip().lower()
            for row in rows
            if (row.get("client_code") or "").strip()
        }


        page_codes = {
            (row.get("page_code") or "").strip().lower()
            for row in rows
            if (row.get("page_code") or "").strip()
        }

    # ── Fetch only required clients and pages ─────────────────────────

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    pages = {
        (p.client.client_code, p.page_code): p
        for p in Page.objects.filter(
            client__client_code__in=client_codes,
            page_code__in=page_codes,
        ).select_related("client")
    }



    # ── Second pass: load navs ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

    #    reader = csv.DictReader(f)

    for row in rows:

        client_code = row["client_code"]
        client = clients.get(client_code)
        if not client:
            print(f"Missing client: {client_code}")
            continue

        # ── page ───────────────────────────────────────

        page = None
        page_code = row.get("page_code")
        if page_code:
            page = pages.get((client_code, page_code))
            if not page:
                print(f"Missing page: {client_code} / {page_code}")
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
            f"PageContent: {client_code} / {page_code}"
        )

    print("Loaded PageContent")


def run():

    load_val01()

    print("Done")
"""