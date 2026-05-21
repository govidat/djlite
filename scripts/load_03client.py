import csv
from pathlib import Path

from mysite.models import Client

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "03client.csv"


    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            Client.objects.update_or_create(
                client_id=row["client_id"],
                
                defaults={
                    "language_list": row.get("language_list", []),
                    "theme_list": row.get("theme_list", []),
                    "name_en": row.get("name_en", ""),
                    "name_hi": row.get("name_hi", ""),
                    "name_fr": row.get("name_fr", ""),  
                    "nb_title_en": row.get("nb_title_en", ""),
                    "nb_title_hi": row.get("nb_title_hi", ""),
                    "nb_title_fr": row.get("nb_title_fr", ""), 
                    "nb_title_svg_pre": row.get("nb_title_svg_pre", ""),
                    "nb_title_svg_suf": row.get("nb_title_svg_suf", ""),
                    "default_language": row.get("default_language", "en")
                }
            )

    print("Loaded Client General")


def run():

    load_val01()

    print("Done")