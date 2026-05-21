import csv

from pathlib import Path

from django.db import transaction

from mysite.models import (
    Item,
    TaxonomyNode,
    ItemTaxonomyNode,
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


def bool01(value):
    return clean(value) == "1"


def to_int(value, default=0):

    value = clean(value)

    if value == "":
        return default

    return int(value)


# ─────────────────────────────────────────────
# loader
# ─────────────────────────────────────────────

@transaction.atomic
def load_item_taxonomy_nodes():

    file_path = DATA_DIR / "21Aitemtaxonomynode.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── collect keys ─────────────────────────

    client_ids = {
        clean_lower(r.get("client_id"))
        for r in rows
    }

    item_ids = {
        clean_lower(r.get("item_id"))
        for r in rows
    }

    taxonomy_slugs = {
        clean_lower(r.get("taxonomy_slug"))
        for r in rows
    }

    node_slugs = {
        clean_lower(r.get("node_slug"))
        for r in rows
    }

    node_client_ids = {
        clean_lower(r.get("node_client_id"))
        for r in rows
    }

    # ── preload nodes ────────────────────────

    nodes = {

        (
            n.taxonomy.slug,
            n.client.client_id if n.client else "",
            n.slug
        ): n

        for n in TaxonomyNode.objects.filter(

            taxonomy__slug__in=taxonomy_slugs,
            slug__in=node_slugs,

        ).select_related(
            "taxonomy",
            "client"
        )
    }

    # ── preload items ────────────────────────

    items = {

        (
            i.client.client_id,
            i.item_id
        ): i

        for i in Item.objects.filter(

            client__client_id__in=client_ids,
            item_id__in=item_ids,

        ).select_related("client")
    }

    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ── load rows ────────────────────────────

    for row in rows:

        client_id = clean_lower(
            row.get("client_id")
        )

        item_id = clean_lower(
            row.get("item_id")
        )

        taxonomy_slug = clean_lower(
            row.get("taxonomy_slug")
        )

        node_slug = clean_lower(
            row.get("node_slug")
        )

        node_client_id = clean_lower(
            row.get("node_client_id")
        )

        item = items.get(
            (client_id, item_id)
        )

        if not item:

            print(
                f"Missing item: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        node = nodes.get(
            (
                taxonomy_slug,
                node_client_id,
                node_slug
            )
        )

        if not node:

            print(
                f"Missing node: "
                f"{taxonomy_slug} / "
                f"{node_client_id or 'GLOBAL'} / "
                f"{node_slug}"
            )

            skipped_count += 1
            continue

        obj, created = \
            ItemTaxonomyNode.objects.update_or_create(

                item=item,
                node=node,

                defaults={

                    "is_primary":
                        bool01(
                            row.get("is_primary")
                        ),

                    "order":
                        to_int(
                            row.get("order")
                        ),
                }
            )

        if created:
            created_count += 1
        else:
            updated_count += 1

        print(
            f"{'Created' if created else 'Updated'} "
            f"{item_id} → {node_slug}"
        )

    print()

    print(
        f"Loaded ItemTaxonomyNode "
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )


def run():

    load_item_taxonomy_nodes()

    print("Done")

