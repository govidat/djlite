import csv
from pathlib import Path

from mysite.models import (
    Client,
    Taxonomy,
    TaxonomyNode,
    NodeAttributeType,
)

# taxonomy_slug,node_slug,slug,name_en,name_hi,name_fr,name_ta,
# field_type,is_required,is_filterable,order,
# gpc_attribute_code,client_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "08nodeattributetype.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect required IDs/slugs ─────────────────────────

    client_ids = {
        (row.get("client_id") or "").strip().lower()
        for row in rows
        if (row.get("client_id") or "").strip()
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

    # ── Fetch clients ───────────────────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Fetch taxonomies ────────────────────────────────────

    taxonomies = {
        (
            t.client.client_id if t.client else "",
            t.slug
        ): t

        for t in Taxonomy.objects.filter(
            slug__in=taxonomy_slugs
        ).select_related("client")
    }

    # ── Fetch nodes ─────────────────────────────────────────

    nodes = {
        (
            n.client.client_id if n.client else "",
            n.taxonomy.slug,
            n.slug
        ): n

        for n in TaxonomyNode.objects.filter(
            slug__in=node_slugs,
            taxonomy__slug__in=taxonomy_slugs,
        ).select_related(
            "client",
            "taxonomy",
        )
    }

    # ── Load NodeAttributeType ──────────────────────────────

    for row in rows:

        client_id = (
            row.get("client_id") or ""
        ).strip().lower()

        taxonomy_slug = (
            row.get("taxonomy_slug") or ""
        ).strip().lower()

        node_slug = (
            row.get("node_slug") or ""
        ).strip().lower()

        slug = (
            row.get("slug") or ""
        ).strip().lower()

        # ── Resolve client ────────────────────────────────

        client = (
            clients.get(client_id)
            if client_id else None
        )

        # ── Resolve taxonomy ──────────────────────────────

        taxonomy = taxonomies.get(
            (client_id, taxonomy_slug)
        )

        # fallback to global taxonomy
        if not taxonomy:
            taxonomy = taxonomies.get(
                ("", taxonomy_slug)
            )

        if not taxonomy:
            print(
                f"Missing taxonomy: "
                f"{client_id or 'GLOBAL'} / "
                f"{taxonomy_slug}"
            )
            continue

        # ── Resolve node ──────────────────────────────────

        node = nodes.get(
            (client_id, taxonomy_slug, node_slug)
        )

        # fallback to global node
        if not node:
            node = nodes.get(
                ("", taxonomy_slug, node_slug)
            )

        if not node:
            print(
                f"Missing node: "
                f"{client_id or 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{node_slug}"
            )
            continue

        # ── Create / Update ───────────────────────────────

        obj, created = (
            NodeAttributeType.objects.update_or_create(

                node=node,
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

                    "field_type":
                        row.get("field_type", "text"),

                    "is_required":
                        row.get("is_required", "0") == "1",

                    "is_filterable":
                        row.get("is_filterable", "1") == "1",

                    "order":
                        int(row.get("order", 0)),

                    "gpc_attribute_code":
                        row.get("gpc_attribute_code", ""),
                }
            )
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"NodeAttributeType: "
            f"{client_id or 'GLOBAL'} / "
            f"{taxonomy_slug} / "
            f"{node_slug} / "
            f"{slug}"
        )

    print("Loaded NodeAttributeType")


def run():

    load_val01()

    print("Done")