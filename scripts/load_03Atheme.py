import csv
from pathlib import Path

from mysite.models import Client, ThemePreset, Theme
#id,theme_id,order,hidden,overrides,is_default,client_id,themepreset_id,name,name_en,name_fr,name_hi,name_ta,ltext

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


 
def load_val01():

    file_path = DATA_DIR / "03Atheme.csv"

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

    # ── Second pass: load themes ─────────────────────────────

    themepresets = {
        c.themepreset_id: c
        for c in ThemePreset.objects.all()
    }    

    #with open(file_path, newline="", encoding="utf-8") as f:

        #reader = csv.DictReader(f)

    for row in rows:


        client_id = row["client_id"]
        client = clients.get(client_id)
        if not client:
            print(f"Missing client: {client_id}")
            continue

        themepreset_id = row["themepreset_id"]
        themepreset = themepresets.get(themepreset_id)
        if not themepreset:
            print(f"Missing themepreset: {themepreset_id}")
            continue

        obj, created = Theme.objects.update_or_create(

            client=client,
            theme_id=row["theme_id"],

            defaults={
                "hidden": row.get("hidden", "0") == "1",
                "order": row.get("order", 1),
                "overrides": row.get("overrides", {}),
                "is_default": row.get("is_default", "0") == "1", 
                "themepreset_id": themepresets[row["themepreset_id"]],
                "ltext": row.get("ltext", "test"),
                "name_en": row.get("name_en", ""),
                "name_hi": row.get("name_hi", ""),
                "name_fr": row.get("name_fr", "")                    
            }
        )

        print(
            f"{'Created' if created else 'Updated'} "
            f"Theme: {client_id} / {obj.theme_id}"
        )

    print("Loaded Theme")


def run():

    load_val01()

    print("Done")