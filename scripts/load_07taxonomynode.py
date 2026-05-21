import csv
import json
from pathlib import Path

from mysite.models import (
    Client,
    Taxonomy,
    TaxonomyNode,
)

# slug,order,is_active,metadata,taxonomy_slug,
# name_en,name_fr,name_hi,name_ta,client_id,gpc_code,
# parent_slug,global_node_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "07taxonomynode.csv"

    # =========================================================
    # FIRST PASS — READ CSV
    # =========================================================

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)

        rows = list(reader)

    # =========================================================
    # COLLECT REQUIRED IDS
    # =========================================================

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

    # =========================================================
    # PREFETCH CLIENTS
    # =========================================================

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # =========================================================
    # PREFETCH TAXONOMIES
    # key = (client_id_or_none, taxonomy_slug)
    # =========================================================

    taxonomies = {}

    for t in Taxonomy.objects.filter(
        slug__in=taxonomy_slugs
    ).select_related("client"):

        key = (
            t.client.client_id if t.client else None,
            t.slug,
        )

        taxonomies[key] = t

    # =========================================================
    # NODE CACHE
    # =========================================================
    # key = (client_id_or_none, taxonomy_slug, slug)

    node_cache = {}

    existing_nodes = TaxonomyNode.objects.filter(
        taxonomy__slug__in=taxonomy_slugs
    ).select_related(
        "client",
        "taxonomy",
    )

    for n in existing_nodes:

        key = (
            n.client.client_id if n.client else None,
            n.taxonomy.slug,
            n.slug,
        )

        node_cache[key] = n

    # =========================================================
    # ITERATIVE LOADING
    # =========================================================

    pending_rows = rows.copy()

    loaded_count = 0
    pass_num = 1

    while pending_rows:

        print(f"\n--- PASS {pass_num} ---")

        next_pending = []

        progress_made = False

        for row in pending_rows:

            # -------------------------------------------------
            # BASIC VALUES
            # -------------------------------------------------

            client_id = (
                row.get("client_id") or ""
            ).strip().lower()

            client = (
                clients.get(client_id)
                if client_id else None
            )

            taxonomy_slug = (
                row.get("taxonomy_slug") or ""
            ).strip().lower()

            slug = (
                row.get("slug") or ""
            ).strip().lower()

            parent_slug = (
                row.get("parent_slug") or ""
            ).strip().lower()

            # -------------------------------------------------
            # TAXONOMY RESOLUTION
            # -------------------------------------------------

            taxonomy = taxonomies.get(
                (client_id if client_id else None,
                 taxonomy_slug)
            )

            # fallback to GLOBAL taxonomy
            if not taxonomy:
                taxonomy = taxonomies.get(
                    (None, taxonomy_slug)
                )

            if not taxonomy:

                print(
                    f"SKIPPED: taxonomy not found "
                    f"[client={client_id or 'GLOBAL'} "
                    f"taxonomy={taxonomy_slug} "
                    f"slug={slug}]"
                )

                continue

            # -------------------------------------------------
            # PARENT RESOLUTION
            # -------------------------------------------------

            parent = None

            if parent_slug:

                parent = node_cache.get(
                    (
                        client_id if client_id else None,
                        taxonomy_slug,
                        parent_slug,
                    )
                )

                # fallback to global parent
                if not parent:
                    parent = node_cache.get(
                        (
                            None,
                            taxonomy_slug,
                            parent_slug,
                        )
                    )

                # parent not yet loaded
                if not parent:

                    next_pending.append(row)

                    continue

            # -------------------------------------------------
            # GLOBAL NODE
            # -------------------------------------------------

            global_node = None

            global_node_id = (
                row.get("global_node_id") or ""
            ).strip()

            if global_node_id:

                global_node = TaxonomyNode.objects.filter(
                    id=global_node_id
                ).first()

            # -------------------------------------------------
            # CREATE / UPDATE
            # -------------------------------------------------

            metadata_raw = row.get("metadata") or "{}"

            try:
                metadata = json.loads(metadata_raw)
            except Exception:
                metadata = {}

            obj, created = TaxonomyNode.objects.update_or_create(

                taxonomy=taxonomy,
                client=client,
                slug=slug,

                defaults={

                    "parent": parent,

                    "order":
                        int(row.get("order") or 0),

                    "is_active":
                        (row.get("is_active") or "0") == "1",

                    "metadata": metadata,

                    "name_en":
                        row.get("name_en", ""),

                    "name_hi":
                        row.get("name_hi", ""),

                    "name_fr":
                        row.get("name_fr", ""),

                    "name_ta":
                        row.get("name_ta", ""),

                    "gpc_code":
                        row.get("gpc_code", ""),

                    "global_node":
                        global_node,
                }
            )

            # -------------------------------------------------
            # UPDATE CACHE
            # -------------------------------------------------

            cache_key = (
                client_id if client_id else None,
                taxonomy_slug,
                slug,
            )

            node_cache[cache_key] = obj

            loaded_count += 1
            progress_made = True

            print(
                f"{'Created' if created else 'Updated'} "
                f"Node: "
                f"{client_id if client_id else 'GLOBAL'} / "
                f"{taxonomy_slug} / "
                f"{slug}"
            )

        # -----------------------------------------------------
        # STOP IF NO PROGRESS
        # -----------------------------------------------------

        if not progress_made:

            print("\nUNRESOLVED ROWS:")

            for row in next_pending:

                print(
                    f"Could not resolve parent "
                    f"[taxonomy={row.get('taxonomy_slug')} "
                    f"slug={row.get('slug')} "
                    f"parent={row.get('parent_slug')}]"
                )

            break

        pending_rows = next_pending

        pass_num += 1

    print(f"\nLoaded {loaded_count} taxonomy nodes")


def run():

    load_val01()

    print("Done")