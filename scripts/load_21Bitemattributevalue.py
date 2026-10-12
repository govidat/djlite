import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from scripts.helpers import (
    clean,
    to_decimal,
)

from mysite.models import (
    Item,
    AttributeType,
    AttributeValue,
    TaxonomyNodeAttribute,
    TaxonomyNodeAttributeValue,
    ItemAttributeValue,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# taxonomy_slug,node_slug,
# attribute_client_code,attribute_slug,
# predefined_client_code,predefined_value_slug,
# item_code,client_code,
# value_text,value_number


@transaction.atomic
def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "21Bitemattributevalue.csv"

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

    item_ids = {
        clean(row.get("item_code"), lower=True)
        for row in rows
        if clean(row.get("item_code"))
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

    # ── Prefetch Items ──────────────────────────────────────

    items = {
        (
            item.client.client_code,
            item.item_code,
        ): item

        for item in Item.objects.filter(
            client__client_code__in=client_codes,
            item_code__in=item_ids,
        ).select_related("client")
    }

    # ── Prefetch Attribute Types ────────────────────────────

    attribute_types = {

        (
            na.node.taxonomy.slug,
            na.node.slug,
            na.attribute_type.client.client_code
            if na.attribute_type.client else "",
            na.attribute_type.slug,
        ): na.attribute_type

        for na in TaxonomyNodeAttribute.objects.filter(
            attribute_type__slug__in=attribute_slugs,
        ).select_related(
            "attribute_type",
            "attribute_type__client",
            "node",
            "node__taxonomy",
        )
    }

    # ── Prefetch Predefined Values ──────────────────────────

    predefined_values = {

        (
            nav.node_attribute.node.taxonomy.slug,
            nav.node_attribute.node.slug,

            nav.node_attribute.attribute_type.client.client_code
            if nav.node_attribute.attribute_type.client else "",

            nav.node_attribute.attribute_type.slug,

            nav.attribute_value.client.client_code
            if nav.attribute_value.client else "",

            nav.attribute_value.slug,
        ): nav.attribute_value

        for nav in TaxonomyNodeAttributeValue.objects.filter(
            attribute_value__slug__in=predefined_slugs,
        ).select_related(
            "attribute_value",
            "attribute_value__client",
            "node_attribute",
            "node_attribute__attribute_type",
            "node_attribute__attribute_type__client",
            "node_attribute__node",
            "node_attribute__node__taxonomy",
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

        item_code = clean(
            row.get("item_code"),
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

        attribute_client_code = clean(
            row.get("attribute_client_code"),
            lower=True,
        )

        attribute_slug = clean(
            row.get("attribute_slug"),
            lower=True,
        )

        predefined_client_code = clean(
            row.get("predefined_client_code"),
            lower=True,
        )

        predefined_value_slug = clean(
            row.get("predefined_value_slug"),
            lower=True,
        )

        # ── Duplicate Detection ────────────────────────────

        key = (
            client_code,
            item_code,
            taxonomy_slug,
            node_slug,
            attribute_client_code,
            attribute_slug,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve Item ───────────────────────────────────

        item = items.get(
            (
                client_code,
                item_code,
            )
        )

        if not item:

            print(
                f"Missing Item: "
                f"{client_code} / {item_code}"
            )

            skipped_count += 1
            continue

        # ── Resolve Attribute Type ────────────────────────

        attribute_type = attribute_types.get(
            (
                taxonomy_slug,
                node_slug,
                attribute_client_code,
                attribute_slug,
            )
        )

        # fallback to GLOBAL attribute type

        if not attribute_type:

            attribute_type = attribute_types.get(
                (
                    taxonomy_slug,
                    node_slug,
                    "",
                    attribute_slug,
                )
            )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{attribute_client_code or 'GLOBAL'} / "
                f"{attribute_slug}"
            )

            skipped_count += 1
            continue

        # ── Resolve Predefined Value ──────────────────────

        predefined_value = None

        if predefined_value_slug:

            predefined_value = predefined_values.get(
                (
                    taxonomy_slug,
                    node_slug,
                    attribute_client_code,
                    attribute_slug,
                    predefined_client_code,
                    predefined_value_slug,
                )
            )

            # fallback to GLOBAL predefined value

            if not predefined_value:

                predefined_value = predefined_values.get(
                    (
                        taxonomy_slug,
                        node_slug,
                        attribute_client_code,
                        attribute_slug,
                        "",
                        predefined_value_slug,
                    )
                )

            if not predefined_value:

                print(
                    f"Missing PredefinedValue: "
                    f"{predefined_value_slug}"
                )

                skipped_count += 1
                continue

        # ── Values ─────────────────────────────────────────

        value_text = clean(
            row.get("value_text")
        )

        value_number = to_decimal(
            row.get("value_number")
        )

        # ── Validation ─────────────────────────────────────

        if (
            predefined_value
            and (
                value_text
                or value_number is not None
            )
        ):

            print(
                f"Conflicting values: "
                f"{item_code} / {attribute_slug}"
            )

            skipped_count += 1
            continue

        defaults = {

            "predefined_value": predefined_value,

            "value_text": value_text,

            "value_number": value_number,
        }

        # ── Dry Run ────────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{item_code} / {attribute_slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ───────────────────────────────

        obj, created = (
            ItemAttributeValue.objects.update_or_create(

                item=item,
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
                f"ItemAttributeValue: "
                f"{item_code} / "
                f"{attribute_slug}"
            )

    # ── Summary ────────────────────────────────────────────

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
Normal Run
python manage.py runscript ...

Dry Run + Verbose
python manage.py runscript ... --script-args dryrun verbose
"""
"""


import csv

from decimal import (
    Decimal,
    InvalidOperation,
)

from pathlib import Path

from django.db import transaction

from mysite.models import (
    Item,
    NodeAttributeType,
    NodeAttributeValue,
    ItemAttributeValue,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def clean(value):
    return (value or "").strip()


def clean_lower(value):
    return clean(value).lower()


def to_decimal(value):

    value = clean(value)

    if value == "":
        return None

    try:
        return Decimal(value)

    except InvalidOperation:
        return None


# ─────────────────────────────────────────────
# loader
# ─────────────────────────────────────────────

@transaction.atomic
def load_val01():

    file_path = DATA_DIR / "21Bitemattributevalue.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── collect keys ─────────────────────────

    client_codes = {
        clean_lower(r.get("client_code"))
        for r in rows
    }

    item_ids = {
        clean_lower(r.get("item_code"))
        for r in rows
    }

    attribute_slugs = {
        clean_lower(r.get("attribute_slug"))
        for r in rows
    }

    predefined_slugs = {

        clean_lower(r.get("predefined_value_slug"))

        for r in rows

        if clean(r.get("predefined_value_slug"))
    }

    # ── preload items ────────────────────────

    items = {

        (
            i.client.client_code,
            i.item_code
        ): i

        for i in Item.objects.filter(

            client__client_code__in=client_codes,
            item_code__in=item_ids,

        ).select_related("client")
    }

    # ── preload attribute types ──────────────

    attribute_types = {

        (
            at.node.taxonomy.slug,
            at.node.slug,
            at.client.client_code if at.client else "",
            at.slug
        ): at

        for at in NodeAttributeType.objects.select_related(
            "node",
            "node__taxonomy",
            "client",
        ).filter(
            slug__in=attribute_slugs
        )
    }

    # ── preload predefined values ────────────

    predefined_values = {

        (
            pv.attribute_type.node.taxonomy.slug,
            pv.attribute_type.node.slug,

            pv.attribute_type.client.client_code
            if pv.attribute_type.client else "",

            pv.attribute_type.slug,

            pv.client.client_code
            if pv.client else "",

            pv.slug
        ): pv

        for pv in NodeAttributeValue.objects.select_related(
            "attribute_type",
            "attribute_type__node",
            "attribute_type__node__taxonomy",
            "attribute_type__client",
            "client",
        ).filter(
            slug__in=predefined_slugs
        )
    }

    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ── load rows ────────────────────────────

    for row in rows:

        client_code = clean_lower(
            row.get("client_code")
        )

        item_code = clean_lower(
            row.get("item_code")
        )

        taxonomy_slug = clean_lower(
            row.get("taxonomy_slug")
        )

        node_slug = clean_lower(
            row.get("node_slug")
        )

        attribute_client_code = clean_lower(
            row.get("attribute_client_code")
        )

        attribute_slug = clean_lower(
            row.get("attribute_slug")
        )

        predefined_client_code = clean_lower(
            row.get("predefined_client_code")
        )

        predefined_value_slug = clean_lower(
            row.get("predefined_value_slug")
        )

        item = items.get(
            (client_code, item_code)
        )

        if not item:

            print(
                f"Missing item: "
                f"{client_code} / {item_code}"
            )

            skipped_count += 1
            continue

        attribute_type = attribute_types.get(

            (
                taxonomy_slug,
                node_slug,
                attribute_client_code,
                attribute_slug,
            )
        )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{attribute_client_code or 'GLOBAL'} / "
                f"{attribute_slug}"
            )

            skipped_count += 1
            continue

        predefined_value = None

        if predefined_value_slug:

            predefined_value = predefined_values.get(

                (
                    taxonomy_slug,
                    node_slug,
                    attribute_client_code,
                    attribute_slug,
                    predefined_client_code,
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

        value_text = clean(
            row.get("value_text")
        )

        value_number = to_decimal(
            row.get("value_number")
        )

        # ── optional validation ──────────────

        if (
            predefined_value
            and (
                value_text
                or value_number is not None
            )
        ):

            print(
                f"Conflicting values for "
                f"{item_code} / {attribute_slug}"
            )

            skipped_count += 1
            continue

        obj, created = \
            ItemAttributeValue.objects.update_or_create(

                item=item,
                attribute_type=attribute_type,

                defaults={

                    "predefined_value":
                        predefined_value,

                    "value_text":
                        value_text,

                    "value_number":
                        value_number,
                }
            )

        if created:
            created_count += 1
        else:
            updated_count += 1

        print(
            f"{'Created' if created else 'Updated'} "
            f"ItemAttributeValue: "
            f"{item_code} / "
            f"{attribute_slug}"
        )

    print()

    print(
        f"Loaded ItemAttributeValue "
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )


def run():

    load_val01()

    print("Done")

"""