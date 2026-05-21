import csv
from pathlib import Path

from mysite.models import Client, Taxonomy
#slug,order,is_active,client_id,name_en,name_fr,name_hi,name_ta,description_en,description_fr,description_hi,description_ta,gpc_segment_code,taxonomy_type
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "06taxonomy.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }


    # ── Fetch only required clients  ─────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }



    # ── Second pass: load navs ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

    #    reader = csv.DictReader(f)

    for row in rows:
        client_id = (row.get("client_id") or "").strip().lower()
        client = clients.get(client_id) if client_id else None    # None is expected for Global Values
        
        slug= row.get("slug", "")

        obj, created = Taxonomy.objects.update_or_create(

            client=client,
            slug= slug,

            defaults={
                
                "is_active": row.get("is_active", "0") == "1",
                "order": int(row.get("order", 0)),                
                "name_en": row.get("name_en", ""),                
                "name_hi": row.get("name_hi", ""),
                "name_fr": row.get("name_fr", ""),
                "name_ta": row.get("name_ta", ""),

                "description_en": row.get("description_en", ""),                
                "description_hi": row.get("description_hi", ""),
                "description_fr": row.get("description_fr", ""),
                "description_ta": row.get("description_ta", ""),

                "gpc_segment_code": row.get("gpc_segment_code", ""),
                "taxonomy_type": row.get("taxonomy_type", ""),

            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"Taxonomy: {client_id if client_id else 'Global'} / {slug}"
        )

    print("Loaded Taxonomy")


def run():

    load_val01()

    print("Done")