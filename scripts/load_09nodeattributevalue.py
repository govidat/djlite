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
# order,gpc_value_code,client_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "09nodeattributevalue.csv"

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

    type_slugs = {
        (row.get("type_slug") or "").strip().lower()
        for row in rows
        if (row.get("type_slug") or "").strip()
    }

    # ── Fetch clients ───────────────────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Fetch attribute types ───────────────────────────────

    attribute_types = {

        (
            at.client.client_id if at.client else "",
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

        client_id = (
            row.get("client_id") or ""
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
            clients.get(client_id)
            if client_id else None
        )

        # ── Resolve attribute type ────────────────────────

        attribute_type = attribute_types.get(
            (
                client_id,
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
                f"{client_id or 'GLOBAL'} / "
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
            f"{client_id or 'GLOBAL'} / "
            f"{taxonomy_slug} / "
            f"{node_slug} / "
            f"{type_slug} / "
            f"{slug}"
        )

    print("Loaded NodeAttributeValue")


def run():

    load_val01()

    print("Done")