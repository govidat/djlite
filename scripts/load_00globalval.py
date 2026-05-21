import csv
from pathlib import Path

from mysite.models import GlobalValCat, GlobalVal


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_globalvalcats():

    file_path = DATA_DIR / "00globalvalcat.csv"

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            GlobalValCat.objects.update_or_create(
                globalvalcat_id=row["globalvalcat_id"]
            )

    print("Loaded GlobalValCat")


def load_globalvals():

    file_path = DATA_DIR / "01globalval.csv"

    globalvalcats = {
        c.globalvalcat_id: c
        for c in GlobalValCat.objects.all()
    }

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            GlobalVal.objects.update_or_create(
                globalvalcat=globalvalcats[row["globalvalcat_id"]],
                key=row["key"],

                defaults={
                    "keyval_en": row.get("keyval_en", ""),
                    "keyval_hi": row.get("keyval_hi", ""),
                    "keyval_fr": row.get("keyval_fr", ""),
                }
            )

    print("Loaded GlobalVal")


def run():

    load_globalvalcats()
    load_globalvals()

    print("Done")