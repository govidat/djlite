import csv
from pathlib import Path

from mysite.models import Client, Page
#id,page_id,ltext,hidden,client_id

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "03Bpage.csv"

    # ── First pass: collect client_ids from CSV ─────────────

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)
        rows = list(reader)   # if multiple passes are required, then this construct is required

        client_ids = {
            row["client_id"]
            for row in rows
            if row.get("client_id")
        }

    # ── Fetch only required clients ─────────────────────────

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # ── Second pass: load pages ─────────────────────────────

    #with open(file_path, newline="", encoding="utf-8") as f:

        #reader = csv.DictReader(f)

    for row in rows:

        client_id = row["client_id"]
        client = clients.get(client_id)

        if not client:
            print(f"Missing client: {client_id}")
            continue

        obj, created = Page.objects.update_or_create(

            client=client,
            page_id=row["page_id"],

            defaults={
                "hidden": row.get("hidden", "0") == "1",
                "ltext": row.get("ltext", ""),
            }
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"Page: {client_id} / {obj.page_id}"
        )

    print("Loaded Page")


def run():

    load_val01()

    print("Done")

