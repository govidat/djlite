import csv
from pathlib import Path

from mysite.models import ThemePreset


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01():

    file_path = DATA_DIR / "02themepreset.csv"

    with open(file_path, newline="", encoding="utf-8") as f:

        reader = csv.DictReader(f)

        for row in reader:

            ThemePreset.objects.update_or_create(
                themepreset_id=row["themepreset_id"],
                defaults={
                    "ltext": row.get("ltext", ""),
                    "primary": row.get("primary", ""),
                    "primary_content": row.get("primary_content", ""),
                    "secondary": row.get("secondary", ""),
                    "secondary_content": row.get("secondary_content", ""),
                    "accent": row.get("accent", ""),
                    "accent_content": row.get("accent_content", ""),
                    "neutral": row.get("neutral", ""),
                    "neutral_content": row.get("neutral_content", ""),
                    "base_100": row.get("base_100", ""),
                    "base_200": row.get("base_200", ""),
                    "base_300": row.get("base_300", ""),
                    "base_content": row.get("base_content", ""),
                    "success": row.get("success", ""),
                    "success_content": row.get("success_content", ""),
                    "warning": row.get("warning", ""),
                    "warning_content": row.get("warning_content", ""),
                    "error": row.get("error", ""),
                    "error_content": row.get("error_content", ""),
                    "info": row.get("info", ""),
                    "info_content": row.get("info_content", "")
                }
            )                     

    print("Loaded ThemePresets")


def run():

    load_val01()

    print("Done")