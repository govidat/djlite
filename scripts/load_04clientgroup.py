import csv
from pathlib import Path

from mysite.models import Client, ClientGroup
#group_id,name,role,description,is_active,client_id
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"



def load_val01():

    file_path = DATA_DIR / "04clientgroup.csv"

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

        client_id = row["client_id"]
        client = clients.get(client_id)
        if not client:
            print(f"Missing client: {client_id}")
            continue
        
        group_id= row.get("group_id", "")

        obj, created = ClientGroup.objects.update_or_create(

            client=client,
            group_id= group_id,

            defaults={
                
                "is_active": row.get("is_active", "0") == "1",

                "name": row.get("name", ""),
                "role": row.get("role", ""),
                "description": row.get("description", ""),                    
            }
        )


        print(
            f"{'Created' if created else 'Updated'} "
            f"ClientGroup: {client_id} / {group_id}"
        )

    print("Loaded ClientGroup")


def run():

    load_val01()

    print("Done")