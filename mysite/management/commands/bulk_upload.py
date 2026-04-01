# mysite/management/commands/bulk_upload.py

import json
from django.core.management.base import BaseCommand
from mysite.scripts.bulk_upload import bulk_upload


class Command(BaseCommand):
    help = "Bulk upload client page/layout/component data from JSON file"

    def add_arguments(self, parser):
        parser.add_argument(
            "json_file",
            type=str,
            help="Path to JSON file"
        )

    def handle(self, *args, **options):
        json_file = options["json_file"]
        try:
            with open(json_file, "r") as f:
                json_data = json.load(f)
            bulk_upload(json_data)
            self.stdout.write(
                self.style.SUCCESS(f"Bulk upload successful from {json_file}")
            )
        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(f"File not found: {json_file}")
            )
            raise
        except json.JSONDecodeError as e:
            self.stdout.write(
                self.style.ERROR(f"Invalid JSON: {e}")
            )
            raise
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Bulk upload failed: {e}")
            )
            raise