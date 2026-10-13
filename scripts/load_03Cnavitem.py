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
# order,hidden,open_in_new_tab,client_code,page_code,
# svg_pre,svg_suf,name_ta,parent_name_en


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ═══════════════════════════════════════════════════════
# Load NavItem
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = data_dir / "03Cnavitem.csv"

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

        if clean(r.get("client_code"))
    }

    page_codes = {

        clean(
            r.get("page_code"),
            lower=True,
        )

        for r in rows

        if clean(r.get("page_code"))
    }

    # ── Preload Clients ─────────────────────────────────

    clients = {

        c.client_code: c

        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # ── Preload Pages ──────────────────────────────────

    pages = {

        (
            p.client.client_code,
            p.page_code,
        ): p

        for p in Page.objects.filter(
            client__client_code__in=client_codes,
            page_code__in=page_codes,
        ).select_related("client")
    }

    # ── Preload Existing Parents ───────────────────────

    parents = {

        (
            n.client.client_code,
            clean(n.name_en, lower=True),
        ): n

        for n in NavItem.objects.filter(
            client__client_code__in=client_codes
        ).select_related("client")
    }

    # ── Counters ────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load NavItems ───────────────────────────────────

    for row in rows:

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        name_en = clean(
            row.get("name_en"),
            lower=True,
        )

        # ── validation ────────────────────────────────

        if not client_code or not name_en:

            print(
                "Skipping row with empty "
                "client_code/name_en"
            )

            skipped_count += 1
            continue

        key = (
            client_code,
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

        client = clients.get(client_code)

        if not client:

            print(
                f"Missing client: "
                f"{client_code}"
            )

            skipped_count += 1
            continue

        # ── resolve page ──────────────────────────────

        page = None

        page_code = clean(
            row.get("page_code"),
            lower=True,
        )

        if page_code:

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

        # ── resolve parent ────────────────────────────

        parent = None

        parent_name_en = clean(
            row.get("parent_name_en"),
            lower=True,
        )

        if parent_name_en:

            parent = parents.get(
                (
                    client_code,
                    parent_name_en,
                )
            )

            if not parent:

                print(
                    f"Missing parent: "
                    f"{client_code} / "
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
                f"{client_code} / {name_en}"
            )

            if verbose:
                print(defaults)

        # ── SAVE ──────────────────────────────────────

        else:

            obj = (
                NavItem.objects
                .filter(client=client, name_en__iexact=name_en)
                .order_by("id").first()
            )

            if obj is None:

                obj = NavItem(client=client, **defaults)
                obj.save()

                created_count += 1

            else:

                for field, value in defaults.items():
                    setattr(obj, field, value)

                obj.save()
                updated_count += 1

            # ── update parents cache ────────────────

            parents[
                (
                    client_code,
                    name_en,
                )
            ] = obj

            if verbose:

                print(
                    f"{'Created' if created else 'Updated'} "
                    f"NavItem: "
                    f"{client_code} / {name_en}"
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