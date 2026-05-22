import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
    GlobalItem,
    Item,
)

from scripts.helpers import (
    clean,
    to_bool,
    to_int,
    to_json,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

# client_id,item_id,global_item_id,
# inherit_global_media,
# gtin,gpc_brick_code,domain,status,
# order,
# name_en,name_hi,name_fr,name_ta,
# description_en,description_hi,description_fr,description_ta,
# country_of_origin,image_url,image_alt,
# barcode,weight_g,length_mm,width_mm,height_mm,
# care_instructions_en,care_instructions_hi,
# care_instructions_fr,care_instructions_ta,
# attributes

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_items(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "20item.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect IDs ─────────────────────────────────────────

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    global_item_ids = {
        clean(row.get("global_item_id"), lower=True)
        for row in rows
        if clean(row.get("global_item_id"))
    }

    # ── Prefetch Clients ────────────────────────────────────

    clients = {
        client.client_id: client
        for client in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Prefetch GlobalItems ────────────────────────────────

    global_items = {
        item.global_item_id: item
        for item in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── Counters ────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load Items ──────────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        item_id = clean(
            row.get("item_id"),
            lower=True,
        )

        if not client_id or not item_id:

            print(
                "Skipping row with empty "
                "client_id or item_id"
            )

            skipped_count += 1
            continue

        key = (client_id, item_id)

        if key in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve Client ────────────────────────────────

        client = clients.get(client_id)

        if not client:

            print(f"Missing client: {client_id}")

            skipped_count += 1
            continue

        # ── Resolve GlobalItem ────────────────────────────

        global_item = None

        global_item_id = clean(
            row.get("global_item_id"),
            lower=True,
        )

        if global_item_id:

            global_item = global_items.get(
                global_item_id
            )

            if not global_item:

                print(
                    f"Missing global item: "
                    f"{global_item_id}"
                )

                skipped_count += 1
                continue

        # ── Defaults ──────────────────────────────────────

        defaults = {

            "global_item": global_item,

            "inherit_global_media":
                to_bool(
                    row.get(
                        "inherit_global_media",
                        "1"
                    )
                ),

            "gtin":
                clean(row.get("gtin")),

            "gpc_brick_code":
                clean(row.get("gpc_brick_code")),

            "domain":
                clean(
                    row.get("domain"),
                    default="generic",
                ),

            "status":
                clean(
                    row.get("status"),
                    default="draft",
                ),

            "order":
                to_int(row.get("order")),

            # ── media / identity ─────────────

            "country_of_origin":
                clean(row.get("country_of_origin")),

            "image_url":
                clean(row.get("image_url")),

            "image_alt":
                clean(row.get("image_alt")),

            "barcode":
                clean(row.get("barcode")),

            # ── dimensions ───────────────────

            "weight_g":
                to_int(row.get("weight_g")),

            "length_mm":
                to_int(row.get("length_mm")),

            "width_mm":
                to_int(row.get("width_mm")),

            "height_mm":
                to_int(row.get("height_mm")),

            # ── JSON attributes ──────────────

            "attributes":
                to_json(row.get("attributes")),
        }

        # ── Language fields ───────────────────────────────

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

            defaults[f"description_{lang}"] = clean(
                row.get(f"description_{lang}")
            )

            defaults[
                f"care_instructions_{lang}"
            ] = clean(
                row.get(
                    f"care_instructions_{lang}"
                )
            )

        # ── Dry Run ───────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / {item_id}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ───────────────────────────────

        obj, created = (
            Item.objects.update_or_create(

                client=client,
                item_id=item_id,

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
                f"Item: "
                f"{client_id} / {item_id}"
            )

    # ── Summary ─────────────────────────────────────────────

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

    args = [arg.lower() for arg in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_items(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

    print("Done")


"""
Normal Run
----------
python manage.py runscript ...

Dry Run + Verbose
-----------------
python manage.py runscript ... --script-args dryrun verbose
"""
"""


import csv
import json
from pathlib import Path

from mysite.models import (
    Client,
    GlobalItem,
    Item,
)

from django.conf import settings

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_items():

    file_path = DATA_DIR / "20item.csv"

    with open(file_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    client_ids = {
        (r.get("client_id") or "").strip().lower()
        for r in rows
        if (r.get("client_id") or "").strip()
    }

    global_item_ids = {
        (r.get("global_item_id") or "").strip().lower()
        for r in rows
        if (r.get("global_item_id") or "").strip()
    }

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    global_items = {
        g.global_item_id: g
        for g in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    for row in rows:

        client_id = (row.get("client_id") or "").strip().lower()
        client = clients.get(client_id)

        if not client:
            print(f"Missing client: {client_id}")
            continue

        global_item = None

        global_item_id = (
            row.get("global_item_id") or ""
        ).strip().lower()

        if global_item_id:
            global_item = global_items.get(global_item_id)

            if not global_item:
                print(
                    f"Missing global item: "
                    f"{global_item_id}"
                )
                continue

        item_id = (
            row.get("item_id") or ""
        ).strip().lower()

        defaults = {

            "global_item": global_item,

            "inherit_global_media":
                row.get(
                    "inherit_global_media",
                    "1"
                ) == "1",

            "gtin":
                row.get("gtin", ""),

            "gpc_brick_code":
                row.get("gpc_brick_code", ""),

            "domain":
                row.get("domain", "generic"),

            "status":
                row.get("status", "draft"),

            "order":
                int(row.get("order", 0)),

            "country_of_origin":
                row.get("country_of_origin", ""),

            "image_url":
                row.get("image_url", ""),

            "image_alt":
                row.get("image_alt", ""),

            "barcode":
                row.get("barcode", ""),

            "weight_g":
                int(row["weight_g"])
                if row.get("weight_g")
                else None,

            "length_mm":
                int(row["length_mm"])
                if row.get("length_mm")
                else None,

            "width_mm":
                int(row["width_mm"])
                if row.get("width_mm")
                else None,

            "height_mm":
                int(row["height_mm"])
                if row.get("height_mm")
                else None,

            "attributes":
                json.loads(
                    row.get("attributes", "{}")
                ),
        }

        for lang in LANGS:

            defaults[f"name_{lang}"] = \
                row.get(f"name_{lang}", "")

            defaults[f"description_{lang}"] = \
                row.get(f"description_{lang}", "")

            defaults[
                f"care_instructions_{lang}"
            ] = row.get(
                f"care_instructions_{lang}",
                ""
            )

        obj, created = Item.objects.update_or_create(

            client=client,
            item_id=item_id,

            defaults=defaults
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"Item: {client_id} / {item_id}"
        )

    print("Loaded Items")


def run():

    load_items()

    print("Done")
"""