import csv
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Client,
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

LANGS = [lang[0] for lang in settings.LANGUAGES]

# taxonomy_slug,node_slug,type_slug,slug,
# name_en,name_hi,name_fr,name_ta,
# order,gpc_value_code,client_code

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "09nodeattributevalue.csv"

    # =========================================================
    # READ CSV
    # =========================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =========================================================
    # COLLECT IDS
    # =========================================================

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if clean(row.get("client_code"))
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

    type_slugs = {
        clean(row.get("type_slug"), lower=True)
        for row in rows
        if clean(row.get("type_slug"))
    }

    # =========================================================
    # PREFETCH CLIENTS
    # =========================================================

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # =========================================================
    # PREFETCH NODES
    # key = (client_code_or_none, taxonomy_slug, node_slug)
    # =========================================================

    nodes = {

        (
            n.client.client_code if n.client else None,
            n.taxonomy.slug,
            n.slug,
        ): n

        for n in (
            TaxonomyNode.objects
            .filter(
                slug__in=node_slugs,
                taxonomy__slug__in=taxonomy_slugs,
            )
            .select_related("client", "taxonomy")
        )
    }

    # =========================================================
    # PREFETCH ATTRIBUTE TYPES
    # key = (client_code_or_none, type_slug)
    # =========================================================

    attribute_types = {

        (
            at.client.client_code if at.client else None,
            at.slug,
        ): at

        for at in (
            AttributeType.objects
            .filter(slug__in=type_slugs)
            .select_related("client")
        )
    }

    # =========================================================
    # PREFETCH NODE ↔ TYPE LINKS
    # key = (node_id, attribute_type_id)
    # =========================================================

    node_attributes = {

        (na.node_id, na.attribute_type_id): na

        for na in TaxonomyNodeAttribute.objects.all()
    }

    # =========================================================
    # LOAD
    # =========================================================

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        # =====================================================
        # BASIC VALUES
        # =====================================================

        client_code = clean(
            row.get("client_code"),
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

        type_slug = clean(
            row.get("type_slug"),
            lower=True,
        )

        slug = clean(
            row.get("slug"),
            lower=True,
        )

        if (
            not taxonomy_slug
            or not node_slug
            or not type_slug
            or not slug
        ):

            print(
                "Skipping row with missing "
                "taxonomy_slug / node_slug / "
                "type_slug / slug"
            )

            skipped_count += 1
            continue

        # =====================================================
        # DUPLICATE CHECK
        # =====================================================

        key = (
            client_code,
            taxonomy_slug,
            node_slug,
            type_slug,
            slug,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # =====================================================
        # CLIENT
        # =====================================================

        client = (
            clients.get(client_code)
            if client_code else None
        )

        # =====================================================
        # NODE
        # =====================================================

        node = nodes.get(
            (client_code, taxonomy_slug, node_slug)
        )

        if not node:

            node = nodes.get(
                (None, taxonomy_slug, node_slug)
            )

        if not node:

            print(
                f"Missing node: "
                f"{client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{node_slug}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # ATTRIBUTE TYPE
        # =====================================================

        attribute_type = attribute_types.get(
            (client_code, type_slug)
        )

        # fallback to global attribute type

        if not attribute_type:

            attribute_type = attribute_types.get(
                (None, type_slug)
            )

        if not attribute_type:

            print(
                f"Missing attribute type: "
                f"{client_code or 'GLOBAL'} / "
                f"{type_slug}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # NODE ↔ TYPE LINK
        # =====================================================

        node_attribute = node_attributes.get(
            (node.id, attribute_type.id)
        )

        if not node_attribute:

            print(
                f"Missing node attribute link: "
                f"{taxonomy_slug} / {node_slug} / {type_slug}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # DEFAULTS
        # =====================================================

        value_defaults = {

            "gpc_code":
                clean(
                    row.get("gpc_value_code")
                ),
        }

        for lang in LANGS:

            value_defaults[f"name_{lang}"] = clean(
                row.get(f"name_{lang}")
            )

        link_defaults = {

            "order":
                to_int(
                    row.get("order")
                ) or 0,
        }

        # =====================================================
        # DRY RUN
        # =====================================================

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{type_slug} / "
                f"{slug}"
            )

            if verbose:
                print(value_defaults, link_defaults)

            continue

        # =====================================================
        # UPSERT
        # =====================================================

        attribute_value, created = (
            AttributeValue.objects
            .update_or_create(

                client=client,
                slug=slug,

                defaults=value_defaults,
            )
        )

        TaxonomyNodeAttributeValue.objects.update_or_create(
            node_attribute=node_attribute,
            attribute_value=attribute_value,
            defaults=link_defaults,
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"AttributeValue: "
                f"{client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{type_slug} / "
                f"{slug}"
            )

    # =========================================================
    # SUMMARY
    # =========================================================

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
python manage.py runscript load_09nodeattributevalue

Dry Run:
python manage.py runscript load_09nodeattributevalue --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_09nodeattributevalue --script-args dryrun verbose
"""

"""


import csv
from pathlib import Path

from mysite.models import (
    Client,
    Taxonomy,
    TaxonomyNode,
    NodeAttributeType,
    NodeAttributeValue,
)

# taxonomy_slug,node_slug,type_slug,slug,
# name_en,name_hi,name_fr,name_ta,
# order,gpc_value_code,client_code

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "09nodeattributevalue.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect required IDs/slugs ─────────────────────────

    client_codes = {
        (row.get("client_code") or "").strip().lower()
        for row in rows
        if (row.get("client_code") or "").strip()
    }

    taxonomy_slugs = {
        (row.get("taxonomy_slug") or "").strip().lower()
        for row in rows
        if (row.get("taxonomy_slug") or "").strip()
    }

    node_slugs = {
        (row.get("node_slug") or "").strip().lower()
        for row in rows
        if (row.get("node_slug") or "").strip()
    }

    type_slugs = {
        (row.get("type_slug") or "").strip().lower()
        for row in rows
        if (row.get("type_slug") or "").strip()
    }

    # ── Fetch clients ───────────────────────────────────────

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # ── Fetch attribute types ───────────────────────────────

    attribute_types = {

        (
            at.client.client_code if at.client else "",
            at.node.taxonomy.slug,
            at.node.slug,
            at.slug
        ): at

        for at in NodeAttributeType.objects.filter(
            slug__in=type_slugs,
            node__slug__in=node_slugs,
            node__taxonomy__slug__in=taxonomy_slugs,
        ).select_related(
            "client",
            "node",
            "node__taxonomy",
        )
    }

    # ── Load NodeAttributeValue ─────────────────────────────

    for row in rows:

        client_code = (
            row.get("client_code") or ""
        ).strip().lower()

        taxonomy_slug = (
            row.get("taxonomy_slug") or ""
        ).strip().lower()

        node_slug = (
            row.get("node_slug") or ""
        ).strip().lower()

        type_slug = (
            row.get("type_slug") or ""
        ).strip().lower()

        slug = (
            row.get("slug") or ""
        ).strip().lower()

        # ── Resolve client ────────────────────────────────

        client = (
            clients.get(client_code)
            if client_code else None
        )

        # ── Resolve attribute type ────────────────────────

        attribute_type = attribute_types.get(
            (
                client_code,
                taxonomy_slug,
                node_slug,
                type_slug,
            )
        )

        # fallback to global attribute type
        if not attribute_type:

            attribute_type = attribute_types.get(
                (
                    "",
                    taxonomy_slug,
                    node_slug,
                    type_slug,
                )
            )

        if not attribute_type:

            print(
                f"Missing attribute type: "
                f"{client_code or 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{node_slug} / "
                f"{type_slug}"
            )

            continue

        # ── Create / Update ───────────────────────────────

        obj, created = (
            NodeAttributeValue.objects.update_or_create(

                attribute_type=attribute_type,
                client=client,
                slug=slug,

                defaults={

                    "name_en":
                        row.get("name_en", ""),

                    "name_hi":
                        row.get("name_hi", ""),

                    "name_fr":
                        row.get("name_fr", ""),

                    "name_ta":
                        row.get("name_ta", ""),

                    "order":
                        int(row.get("order", 0)),

                    "gpc_value_code":
                        row.get("gpc_value_code", ""),
                }
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"NodeAttributeValue: "
            f"{client_code or 'GLOBAL'} / "
            f"{taxonomy_slug} / "
            f"{node_slug} / "
            f"{type_slug} / "
            f"{slug}"
        )

    print("Loaded NodeAttributeValue")


def run():

    load_val01()

    print("Done")
"""