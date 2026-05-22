import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    GlobalItem,
    TaxonomyNode,
    GlobalItemTaxonomyNode,
)

from scripts.helpers import clean, to_bool


LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# global_item_id,taxonomy_slug,node_slug,is_primary


def load_val01(dry_run=False, verbose=False):

    file_path = DATA_DIR / "11Aglobalitemtaxonomynode.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect lookup keys ─────────────────────────────────

    global_item_ids = {
        clean(row.get("global_item_id"), lower=True)
        for row in rows
        if clean(row.get("global_item_id"))
    }

    taxonomy_slugs = {
        clean(row.get("taxonomy_slug"), lower=True)
        for row in rows
        if clean(row.get("taxonomy_slug"))
    }

    node_slugs = {
        clean(row.get("node_slug"), lower=True)
        for row in rows
        if clean(row.get("node_slug"))
    }

    # ── Prefetch GlobalItems ────────────────────────────────

    global_items = {
        gi.global_item_id: gi
        for gi in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── Prefetch TaxonomyNodes ──────────────────────────────

    nodes = {
        (
            n.taxonomy.slug,
            n.slug,
        ): n

        for n in TaxonomyNode.objects.filter(
            taxonomy__slug__in=taxonomy_slugs,
            slug__in=node_slugs,
        ).select_related("taxonomy")
    }

    # ── Load mappings ───────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        global_item_id = clean(
            row.get("global_item_id"),
            lower=True,
        )

        taxonomy_slug = clean(
            row.get("taxonomy_slug"),
            lower=True,
        )

        node_slug = clean(
            row.get("node_slug"),
            lower=True,
        )

        # ── Validation ────────────────────────────────────

        if not global_item_id:
            print("Skipping row with empty global_item_id")
            skipped_count += 1
            continue

        if not taxonomy_slug or not node_slug:
            print(
                f"Skipping row with missing taxonomy/node: "
                f"{global_item_id}"
            )
            skipped_count += 1
            continue

        key = (
            global_item_id,
            taxonomy_slug,
            node_slug,
        )

        if key in seen:
            print(f"Duplicate CSV row: {key}")
            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve GlobalItem ────────────────────────────

        global_item = global_items.get(global_item_id)

        if not global_item:

            print(
                f"Missing GlobalItem: "
                f"{global_item_id}"
            )

            skipped_count += 1
            continue

        # ── Resolve TaxonomyNode ──────────────────────────

        node = nodes.get(
            (taxonomy_slug, node_slug)
        )

        if not node:

            print(
                f"Missing TaxonomyNode: "
                f"{taxonomy_slug} / {node_slug}"
            )

            skipped_count += 1
            continue

        defaults = {
            "is_primary": to_bool(
                row.get("is_primary")
            ),
        }

        # ── Dry Run ───────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{global_item_id} -> "
                f"{taxonomy_slug}/{node_slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ──────────────────────────────

        obj, created = (
            GlobalItemTaxonomyNode.objects.update_or_create(

                global_item=global_item,
                node=node,

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
                f"GlobalItemTaxonomyNode: "
                f"{global_item_id} -> "
                f"{taxonomy_slug}/{node_slug}"
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
python manage.py runscript ... 

Dry Run + Verbose:
python manage.py runscript ... --script-args dryrun verbose
"""
"""

import csv
from pathlib import Path

from mysite.models import (
    GlobalItem,
    TaxonomyNode,
    GlobalItemTaxonomyNode,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "11Aglobalitemtaxonomynode.csv"

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── collect keys ─────────────────────────────────────

    global_item_ids = {
        (r.get("global_item_id") or "").strip().lower()
        for r in rows
    }

    taxonomy_slugs = {
        (r.get("taxonomy_slug") or "").strip().lower()
        for r in rows
    }

    node_slugs = {
        (r.get("node_slug") or "").strip().lower()
        for r in rows
    }

    # ── preload global items ─────────────────────────────

    global_items = {
        gi.global_item_id: gi
        for gi in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── preload nodes ────────────────────────────────────

    nodes = {

        (n.taxonomy.slug, n.slug): n

        for n in TaxonomyNode.objects.filter(
            taxonomy__slug__in=taxonomy_slugs,
            slug__in=node_slugs,
        ).select_related("taxonomy")
    }

    # ── load mappings ────────────────────────────────────

    for row in rows:

        global_item_id = (
            row.get("global_item_id") or ""
        ).strip().lower()

        taxonomy_slug = (
            row.get("taxonomy_slug") or ""
        ).strip().lower()

        node_slug = (
            row.get("node_slug") or ""
        ).strip().lower()

        global_item = global_items.get(global_item_id)

        if not global_item:

            print(
                f"Missing GlobalItem: {global_item_id}"
            )
            continue

        node = nodes.get(
            (taxonomy_slug, node_slug)
        )

        if not node:

            print(
                f"Missing TaxonomyNode: "
                f"{taxonomy_slug} / {node_slug}"
            )
            continue

        obj, created = (
            GlobalItemTaxonomyNode.objects.update_or_create(

                global_item=global_item,
                node=node,

                defaults={
                    "is_primary":
                        row.get("is_primary", "0") == "1"
                }
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"GlobalItemTaxonomyNode: "
            f"{global_item_id} -> "
            f"{taxonomy_slug}/{node_slug}"
        )

    print("Loaded GlobalItemTaxonomyNode")


def run():

    load_val01()

    print("Done")
"""