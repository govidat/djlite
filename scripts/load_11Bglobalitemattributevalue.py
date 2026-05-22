import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    GlobalItem,
    NodeAttributeType,
    NodeAttributeValue,
    GlobalItemAttributeValue,
)

from scripts.helpers import (
    clean,
    to_decimal,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# global_item_id,taxonomy_slug,node_slug,
# attribute_slug,predefined_value_slug,
# value_text,value_number


def load_val01(dry_run=False, verbose=False):

    file_path = DATA_DIR / "11Bglobalitemattributevalue.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect keys ────────────────────────────────────────

    global_item_ids = {
        clean(row.get("global_item_id"), lower=True)
        for row in rows
        if clean(row.get("global_item_id"))
    }

    attribute_slugs = {
        clean(row.get("attribute_slug"), lower=True)
        for row in rows
        if clean(row.get("attribute_slug"))
    }

    predefined_slugs = {
        clean(row.get("predefined_value_slug"), lower=True)
        for row in rows
        if clean(row.get("predefined_value_slug"))
    }

    node_slugs = {
        clean(row.get("node_slug"), lower=True)
        for row in rows
        if clean(row.get("node_slug"))
    }

    taxonomy_slugs = {
        clean(row.get("taxonomy_slug"), lower=True)
        for row in rows
        if clean(row.get("taxonomy_slug"))
    }

    # ── Prefetch GlobalItems ────────────────────────────────

    global_items = {
        obj.global_item_id: obj
        for obj in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── Prefetch Attribute Types ────────────────────────────

    attribute_types = {
        (
            obj.node.taxonomy.slug,
            obj.node.slug,
            obj.slug,
        ): obj
        for obj in NodeAttributeType.objects.select_related(
            "node",
            "node__taxonomy",
        ).filter(
            slug__in=attribute_slugs,
            node__slug__in=node_slugs,
            node__taxonomy__slug__in=taxonomy_slugs,
        )
    }

    # ── Prefetch Predefined Values ──────────────────────────

    predefined_values = {
        (
            obj.attribute_type.node.taxonomy.slug,
            obj.attribute_type.node.slug,
            obj.attribute_type.slug,
            obj.slug,
        ): obj
        for obj in NodeAttributeValue.objects.select_related(
            "attribute_type",
            "attribute_type__node",
            "attribute_type__node__taxonomy",
        ).filter(
            slug__in=predefined_slugs
        )
    }

    # ── Stats ───────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load GlobalItemAttributeValue ───────────────────────

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

        attribute_slug = clean(
            row.get("attribute_slug"),
            lower=True,
        )

        predefined_value_slug = clean(
            row.get("predefined_value_slug"),
            lower=True,
        )

        # ── Validate required fields ─────────────────────

        if not global_item_id:

            print("Skipping row with empty global_item_id")
            skipped_count += 1
            continue

        if not attribute_slug:

            print(
                f"Skipping row with empty attribute_slug "
                f"[global_item={global_item_id}]"
            )
            skipped_count += 1
            continue

        # ── Duplicate detection ──────────────────────────

        key = (
            global_item_id,
            taxonomy_slug,
            node_slug,
            attribute_slug,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")
            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve GlobalItem ───────────────────────────

        global_item = global_items.get(global_item_id)

        if not global_item:

            print(
                f"Missing GlobalItem: {global_item_id}"
            )

            skipped_count += 1
            continue

        # ── Resolve AttributeType ────────────────────────

        attribute_type = attribute_types.get(
            (
                taxonomy_slug,
                node_slug,
                attribute_slug,
            )
        )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{attribute_slug}"
            )

            skipped_count += 1
            continue

        # ── Resolve predefined value ─────────────────────

        predefined_value = None

        if predefined_value_slug:

            predefined_value = predefined_values.get(
                (
                    taxonomy_slug,
                    node_slug,
                    attribute_slug,
                    predefined_value_slug,
                )
            )

            if not predefined_value:

                print(
                    f"Missing predefined value: "
                    f"{predefined_value_slug}"
                )

                skipped_count += 1
                continue

        # ── Defaults ─────────────────────────────────────

        defaults = {

            "predefined_value": predefined_value,

            "value_text": clean(
                row.get("value_text")
            ),

            "value_number": to_decimal(
                row.get("value_number")
            ),
        }

        # ── Dry Run ───────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{global_item_id} / "
                f"{attribute_slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ──────────────────────────────

        obj, created = (
            GlobalItemAttributeValue.objects.update_or_create(

                global_item=global_item,
                attribute_type=attribute_type,

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
                f"GlobalItemAttributeValue: "
                f"{global_item_id} / "
                f"{attribute_slug}"
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

    dry_run = "dryrun" in args
    verbose = "verbose" in args

    print(f"DRY_RUN = {dry_run}")
    print(f"VERBOSE = {verbose}")

    load_val01(
        dry_run=dry_run,
        verbose=verbose,
    )

    print("Done")


"""
Normal Run:
python manage.py runscript script_name

Dry Run + Verbose:
python manage.py runscript script_name --script-args dryrun verbose
"""

"""
import csv
from decimal import Decimal
from pathlib import Path

from mysite.models import (
    GlobalItem,
    NodeAttributeType,
    NodeAttributeValue,
    GlobalItemAttributeValue,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def to_decimal(value):

    value = (value or "").strip()

    if not value:
        return None

    try:
        return Decimal(value)
    except:
        return None


def load_val01():

    file_path = DATA_DIR / "11Bglobalitemattributevalue.csv"

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── collect keys ─────────────────────────────────────

    global_item_ids = {
        (r.get("global_item_id") or "").strip().lower()
        for r in rows
    }

    attribute_slugs = {
        (r.get("attribute_slug") or "").strip().lower()
        for r in rows
    }

    predefined_slugs = {
        (r.get("predefined_value_slug") or "").strip().lower()
        for r in rows
        if (r.get("predefined_value_slug") or "").strip()
    }

    # ── preload global items ─────────────────────────────

    global_items = {
        gi.global_item_id: gi
        for gi in GlobalItem.objects.filter(
            global_item_id__in=global_item_ids
        )
    }

    # ── preload attribute types ──────────────────────────

    attribute_types = {

        (
            at.node.taxonomy.slug,
            at.node.slug,
            at.slug
        ): at

        for at in NodeAttributeType.objects.select_related(
            "node",
            "node__taxonomy"
        ).filter(
            slug__in=attribute_slugs
        )
    }

    # ── preload predefined values ────────────────────────

    predefined_values = {

        (
            pv.attribute_type.node.taxonomy.slug,
            pv.attribute_type.node.slug,
            pv.attribute_type.slug,
            pv.slug
        ): pv

        for pv in NodeAttributeValue.objects.select_related(
            "attribute_type",
            "attribute_type__node",
            "attribute_type__node__taxonomy",
        ).filter(
            slug__in=predefined_slugs
        )
    }

    # ── load values ──────────────────────────────────────

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

        attribute_slug = (
            row.get("attribute_slug") or ""
        ).strip().lower()

        predefined_value_slug = (
            row.get("predefined_value_slug") or ""
        ).strip().lower()

        global_item = global_items.get(global_item_id)

        if not global_item:

            print(
                f"Missing GlobalItem: {global_item_id}"
            )
            continue

        attribute_type = attribute_types.get(
            (
                taxonomy_slug,
                node_slug,
                attribute_slug,
            )
        )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{attribute_slug}"
            )
            continue

        predefined_value = None

        if predefined_value_slug:

            predefined_value = predefined_values.get(
                (
                    taxonomy_slug,
                    node_slug,
                    attribute_slug,
                    predefined_value_slug,
                )
            )

            if not predefined_value:

                print(
                    f"Missing predefined value: "
                    f"{predefined_value_slug}"
                )
                continue

        obj, created = (
            GlobalItemAttributeValue.objects.update_or_create(

                global_item=global_item,
                attribute_type=attribute_type,

                defaults={

                    "predefined_value":
                        predefined_value,

                    "value_text":
                        row.get("value_text", ""),

                    "value_number":
                        to_decimal(
                            row.get("value_number")
                        ),
                }
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"GlobalItemAttributeValue: "
            f"{global_item_id} / "
            f"{attribute_slug}"
        )

    print("Loaded GlobalItemAttributeValue")


def run():

    load_val01()

    print("Done")
"""