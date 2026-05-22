import csv
from pathlib import Path

from django.db import transaction

from mysite.models import (
    Item,
    TaxonomyNode,
    ItemTaxonomyNode,
)

from scripts.helpers import (
    clean,
    to_int,
    to_bool,
)

# item_id,client_id,taxonomy_slug,node_slug,
# node_client_id,is_primary,order

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "21Aitemtaxonomynode.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect keys ────────────────────────────────────────

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
    }

    item_ids = {
        clean(row.get("item_id"), lower=True)
        for row in rows
        if clean(row.get("item_id"))
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

    # ── Preload nodes ───────────────────────────────────────

    nodes = {
        (
            n.taxonomy.slug,
            n.client.client_id if n.client else "",
            n.slug,
        ): n

        for n in TaxonomyNode.objects.filter(
            taxonomy__slug__in=taxonomy_slugs,
            slug__in=node_slugs,
        ).select_related(
            "taxonomy",
            "client",
        )
    }

    # ── Preload items ───────────────────────────────────────

    items = {
        (
            i.client.client_id,
            i.item_id,
        ): i

        for i in Item.objects.filter(
            client__client_id__in=client_ids,
            item_id__in=item_ids,
        ).select_related("client")
    }

    # ── Stats ───────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load rows ───────────────────────────────────────────

    for row in rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        item_id = clean(
            row.get("item_id"),
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

        node_client_id = clean(
            row.get("node_client_id"),
            lower=True,
        )

        # ── Duplicate check ────────────────────────────────

        key = (
            client_id,
            item_id,
            taxonomy_slug,
            node_client_id,
            node_slug,
        )

        if key in seen:

            print(f"Duplicate CSV row: {key}")

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve item ───────────────────────────────────

        item = items.get(
            (
                client_id,
                item_id,
            )
        )

        if not item:

            print(
                f"Missing item: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        # ── Resolve node ───────────────────────────────────

        node = nodes.get(
            (
                taxonomy_slug,
                node_client_id,
                node_slug,
            )
        )

        # fallback to GLOBAL node
        if not node:

            node = nodes.get(
                (
                    taxonomy_slug,
                    "",
                    node_slug,
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

        # ── Defaults ───────────────────────────────────────

        defaults = {

            "is_primary":
                to_bool(row.get("is_primary")),

            "order":
                to_int(row.get("order")),
        }

        # ── Dry Run ─────────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{item_id} → {node_slug}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ────────────────────────────────

        obj, created = (
            ItemTaxonomyNode.objects.update_or_create(

                item=item,
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
                f"ItemTaxonomyNode: "
                f"{item_id} → {node_slug}"
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
Normal Run
python manage.py runscript 21Aitemtaxonomynode

Dry Run + Verbose
python manage.py runscript 21Aitemtaxonomynode --script-args dryrun verbose
"""

"""


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

"""