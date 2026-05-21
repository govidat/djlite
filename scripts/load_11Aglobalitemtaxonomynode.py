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