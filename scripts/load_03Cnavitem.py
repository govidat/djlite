import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    Page,
    NavItem,
)

from scripts.helpers import (
    clean,
    to_bool,
    to_int,
)


LANGS = [lang[0] for lang in settings.LANGUAGES]


# id,location,nav_type,url,name,name_en,name_hi,name_fr,
# order,hidden,open_in_new_tab,client_id,page_id,
# svg_pre,svg_suf,name_ta,parent_name_en


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load NavItem
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "03Cnavitem.csv"

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

        if clean(r.get("client_id"))
    }

    page_ids = {

        clean(
            r.get("page_id"),
            lower=True,
        )

        for r in rows

        if clean(r.get("page_id"))
    }

    # ── Preload Clients ─────────────────────────────────

    clients = {

        c.client_id: c

        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Preload Pages ──────────────────────────────────

    pages = {

        (
            p.client.client_id,
            p.page_id,
        ): p

        for p in Page.objects.filter(
            client__client_id__in=client_ids,
            page_id__in=page_ids,
        ).select_related("client")
    }

    # ── Preload Existing Parents ───────────────────────

    parents = {

        (
            n.client.client_id,
            clean(n.name_en, lower=True),
        ): n

        for n in NavItem.objects.filter(
            client__client_id__in=client_ids
        ).select_related("client")
    }

    # ── Counters ────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load NavItems ───────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        name_en = clean(
            row.get("name_en"),
            lower=True,
        )

        # ── validation ────────────────────────────────

        if not client_id or not name_en:

            print(
                "Skipping row with empty "
                "client_id/name_en"
            )

            skipped_count += 1
            continue

        key = (
            client_id,
            name_en,
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

        # ── resolve page ──────────────────────────────

        page = None

        page_id = clean(
            row.get("page_id"),
            lower=True,
        )

        if page_id:

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

        # ── resolve parent ────────────────────────────

        parent = None

        parent_name_en = clean(
            row.get("parent_name_en"),
            lower=True,
        )

        if parent_name_en:

            parent = parents.get(
                (
                    client_id,
                    parent_name_en,
                )
            )

            if not parent:

                print(
                    f"Missing parent: "
                    f"{client_id} / "
                    f"{parent_name_en}"
                )

                skipped_count += 1
                continue

        # ── defaults ──────────────────────────────────

        defaults = {

            "parent":
                parent,

            "page":
                page,

            "location":
                clean(
                    row.get("location")
                ) or "header",

            "nav_type":
                clean(
                    row.get("nav_type")
                ) or "page",

            "url":
                clean(row.get("url")),

            "order":
                to_int(row.get("order")) or 0,

            "hidden":
                to_bool(row.get("hidden")),

            "open_in_new_tab":
                to_bool(
                    row.get("open_in_new_tab")
                ),

            "svg_pre":
                clean(row.get("svg_pre")),

            "svg_suf":
                clean(row.get("svg_suf")),
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
                f"{client_id} / {name_en}"
            )

            if verbose:
                print(defaults)

        # ── SAVE ──────────────────────────────────────

        else:

            obj, created = (
                NavItem.objects.update_or_create(

                    client=client,
                    name_en=name_en,

                    defaults=defaults,
                )
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            # ── update parents cache ────────────────

            parents[
                (
                    client_id,
                    name_en,
                )
            ] = obj

            if verbose:

                print(
                    f"{'Created' if created else 'Updated'} "
                    f"NavItem: "
                    f"{client_id} / {name_en}"
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
python manage.py runscript load_03cnavitem

Dry Run
--------
python manage.py runscript load_03cnavitem --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_03cnavitem --script-args dryrun verbose
"""