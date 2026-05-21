import csv
from pathlib import Path

from mysite.models import Client, ClientTemplate
#client_id, page_id, htmlblob_en, htmlblob_fr, htmlblob_hi
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "03Eclienttemplate.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            (row.get("client_id") or "").strip().lower()
            for row in rows
            if (row.get("client_id") or "").strip()
        }


    # ── Fetch only required clients and pages ─────────────────────────

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

        client_id = row["client_id"]
        client = clients.get(client_id)
        if not client:
            print(f"Missing client: {client_id}")
            continue
        
        template_key= row.get("template_key", "")

        obj, created = ClientTemplate.objects.update_or_create(

            client=client,
            template_key= template_key,

            defaults={
                "is_active": row.get("is_active", "0") == "1",

                "htmlblob_en": row.get("htmlblob_en", ""),
                "htmlblob_hi": row.get("htmlblob_hi", ""),
                "htmlblob_fr": row.get("htmlblob_fr", ""),                    
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"ClientTemplate: {client_id} / {template_key}"
        )

    print("Loaded ClientTemplate")


def run():

    load_val01()

    print("Done")