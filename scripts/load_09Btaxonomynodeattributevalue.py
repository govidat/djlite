import csv
from pathlib import Path

from django.db import transaction

from mysite.models import (
    TaxonomyNode,
    AttributeType,
    AttributeValue,
    TaxonomyNodeAttribute,
    TaxonomyNodeAttributeValue,
)

from scripts.helpers import (
    clean,
    to_int,
)

# node_client_code,taxonomy_slug,node_slug,
# attribute_client_code,attribute_slug,
# value_client_code,value_slug,order

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


@transaction.atomic
def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "09Btaxonomynodeattributevalue.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect lookup keys ─────────────────────────────────

    taxonomy_slugs = {
        clean(row.get("taxonomy_slug"), lower=True)
        for row in rows
        if clean(row.get("taxonomy_slug"))
    }

    attribute_slugs = {
        clean(row.get("attribute_slug"), lower=True)
        for row in rows
        if clean(row.get("attribute_slug"))
    }

    value_slugs = {
        clean(row.get("value_slug"), lower=True)
        for row in rows
        if clean(row.get("value_slug"))
    }

    # ── Prefetch Nodes ──────────────────────────────────────
    # key = (client_code_or_None, taxonomy_slug, node_slug)

    nodes = {}

    for n in (
        TaxonomyNode.objects
        .filter(taxonomy__slug__in=taxonomy_slugs)
        .select_related("client", "taxonomy")
    ):

        key = (
            n.client.client_code if n.client else None,
            n.taxonomy.slug,
            n.slug,
        )

        nodes[key] = n

    # ── Prefetch Attribute Types ────────────────────────────
    # key = (client_code_or_None, attribute_slug)

    attribute_types = {}

    for at in (
        AttributeType.objects
        .filter(slug__in=attribute_slugs)
        .select_related("client")
    ):

        key = (
            at.client.client_code if at.client else None,
            at.slug,
        )

        attribute_types[key] = at

    # ── Prefetch Node Attributes ────────────────────────────
    # key = (node_id, attribute_type_id)

    node_attributes = {
        (na.node_id, na.attribute_type_id): na
        for na in TaxonomyNodeAttribute.objects.filter(
            node__taxonomy__slug__in=taxonomy_slugs,
        )
    }

    # ── Prefetch Attribute Values ───────────────────────────
    # key = (client_code_or_None, value_slug)

    attribute_values = {}

    for av in (
        AttributeValue.objects
        .filter(slug__in=value_slugs)
        .select_related("client")
    ):

        key = (
            av.client.client_code if av.client else None,
            av.slug,
        )

        attribute_values[key] = av

    # ── Counters ────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Process Rows ────────────────────────────────────────

    for row in rows:

        node_client_code = clean(
            row.get("node_client_code"),
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

        value_client_code = clean(
            row.get("value_client_code"),
            lower=True,
        )

        value_slug = clean(
            row.get("value_slug"),
            lower=True,
        )

        if (
            not taxonomy_slug
            or not node_slug
            or not attribute_slug
            or not value_slug
        ):

            print(
                "Skipping row with missing "
                "taxonomy_slug / node_slug / "
                "attribute_slug / value_slug"
            )

            skipped_count += 1
            continue

        # ── Resolve Node ───────────────────────────────────

        node = nodes.get(
            (
                node_client_code or None,
                taxonomy_slug,
                node_slug,
            )
        )

        if not node:

            print(
                f"Missing TaxonomyNode: "
                f"{node_client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / {node_slug}"
            )

            skipped_count += 1
            continue

        # ── Scope Enforcement ──────────────────────────────
        # global node  -> global types/values only
        # client node X -> global or X types/values only

        allowed = {None}

        if node.client:
            allowed.add(node.client.client_code)

        if (
            attribute_client_code
            and attribute_client_code not in allowed
        ):

            print(
                f"Scope violation: AttributeType "
                f"{attribute_client_code} / {attribute_slug} "
                f"not allowed on node "
                f"{node_client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / {node_slug}"
            )

            skipped_count += 1
            continue

        if (
            value_client_code
            and value_client_code not in allowed
        ):

            print(
                f"Scope violation: AttributeValue "
                f"{value_client_code} / {value_slug} "
                f"not allowed on node "
                f"{node_client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / {node_slug}"
            )

            skipped_count += 1
            continue

        # ── Resolve Attribute Type ─────────────────────────

        attribute_type = attribute_types.get(
            (
                attribute_client_code or None,
                attribute_slug,
            )
        )

        # fallback to GLOBAL attribute type

        if not attribute_type and attribute_client_code:

            attribute_type = attribute_types.get(
                (
                    None,
                    attribute_slug,
                )
            )

        if not attribute_type:

            print(
                f"Missing AttributeType: "
                f"{attribute_client_code or 'GLOBAL'} / "
                f"{attribute_slug}"
            )

            skipped_count += 1
            continue

        # ── Resolve Node Attribute ─────────────────────────

        node_attribute = node_attributes.get(
            (
                node.id,
                attribute_type.id,
            )
        )

        if not node_attribute:

            print(
                f"AttributeType not attached to node: "
                f"{node} / {attribute_slug}"
            )

            skipped_count += 1
            continue

        # ── Resolve Attribute Value ────────────────────────

        attribute_value = attribute_values.get(
            (
                value_client_code or None,
                value_slug,
            )
        )

        # fallback to GLOBAL attribute value

        if not attribute_value and value_client_code:

            attribute_value = attribute_values.get(
                (
                    None,
                    value_slug,
                )
            )

        if not attribute_value:

            print(
                f"Missing AttributeValue: "
                f"{value_client_code or 'GLOBAL'} / "
                f"{value_slug}"
            )

            skipped_count += 1
            continue

        # ── Duplicate Detection ────────────────────────────

        key = (
            node_attribute.id,
            attribute_value.id,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # ── Defaults ────────────────────────────────────────

        defaults = {
            "order": to_int(row.get("order")) or 0,
        }

        # ── Dry Run ─────────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{node} / {attribute_slug} -> {value_slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ─────────────────────────────────

        obj, created = (
            TaxonomyNodeAttributeValue.objects.update_or_create(

                node_attribute=node_attribute,
                attribute_value=attribute_value,

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
                f"TaxonomyNodeAttributeValue: "
                f"{node} / {attribute_slug} -> {value_slug}"
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
python manage.py runscript load_09Btaxonomynodeattributevalue

Dry Run:
python manage.py runscript load_09Btaxonomynodeattributevalue --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_09Btaxonomynodeattributevalue --script-args dryrun verbose
"""
