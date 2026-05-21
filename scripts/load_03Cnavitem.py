import csv
from pathlib import Path

from mysite.models import Client, Page, NavItem
#id,location,nav_type,url,name,name_en,name_hi,name_fr,order,hidden,open_in_new_tab,client_id,page_id,svg_pre,svg_suf,name_ta,parent_name_en

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "03Cnavitem.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        
        rows = list(reader)   # if multiple passes are required, then this construct is required
        

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }

        #print(f"client_ids: {client_ids}")

        page_ids = {
            (row.get("page_id") or "").strip().lower()
            for row in rows
            if (row.get("page_id") or "").strip()
        }

        #print(f"page_ids: {page_ids}")

    # ── Fetch only required clients and pages ─────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    pages = {
        (p.client.client_id, p.page_id): p
        for p in Page.objects.filter(
            client__client_id__in=client_ids,
            page_id__in=page_ids,
        ).select_related("client")
    }

    parents = {
        (n.client.client_id, n.name_en): n
        for n in NavItem.objects.filter(
            client__client_id__in=client_ids
        ).select_related("client")
    }


    # ── Second pass: load navs ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

    #    reader = csv.DictReader(f)

    for row in rows:

        client_id = row["client_id"]
        client = clients.get(client_id)
        if not client:
            print(f"Missing client: {client_id}")
            continue

        # ── page ───────────────────────────────────────

        page = None
        page_id = row.get("page_id").strip().lower()
        if page_id:
            page = pages.get((client_id, page_id))
            if not page:
                print(f"Missing page: {client_id} / {page_id}")
                continue
        #print("LOOKUP:")
        #print((client_id, page_id))
        # ── parent ─────────────────────────────────────

        parent = None
        parent_name_en = row.get("parent_name_en").strip().lower()
        if parent_name_en:
            parent = parents.get((client_id, parent_name_en))
            if not parent:
                print(
                    f"Missing parent: "
                    f"{client_id} / {parent_name_en}"
                )
                continue

        obj, created = NavItem.objects.update_or_create(

            client=client,
            name_en=row.get("name_en", "").strip().lower(),

            defaults={

                "parent": parent,
                "page": page,

                "location": row.get("location", "header"),
                "nav_type": row.get("nav_type", "page"),
                "url": row.get("url", ""),

                "name_hi": row.get("name_hi", ""),
                "name_fr": row.get("name_fr", ""),
                "name_ta": row.get("name_ta", ""),

                "order": int(row.get("order", 0)),

                "hidden": row.get("hidden", "0") == "1",

                "open_in_new_tab": row.get("open_in_new_tab", "0") == "1",

                "svg_pre": row.get("svg_pre", ""),
                "svg_suf": row.get("svg_suf", ""),
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"Page: {client_id} / {obj.name_en}"
        )

    print("Loaded NavItem")


def run():

    load_val01()

    print("Done")