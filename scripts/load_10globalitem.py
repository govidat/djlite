import csv
import json
from pathlib import Path

from django.contrib.auth import get_user_model

from mysite.models import GlobalItem
from django.conf import settings
import sys  # for DRY_RUN
from django.db import transaction # for DRY_RUN
from scripts.helpers import clean, to_int, to_bool, to_json, to_decimal


LANGS = [lang[0] for lang in settings.LANGUAGES]


# global_item_id,gtin,gpc_brick_code,domain,status,
# name_en,name_hi,name_fr,name_ta,
# description_en,description_hi,description_fr,description_ta,
# country_of_origin,image_url,image_alt,
# barcode,weight_g,length_mm,width_mm,height_mm,
# care_instructions_en,care_instructions_hi,
# care_instructions_fr,care_instructions_ta,
# attributes

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

User = get_user_model()


def load_val01(dry_run=False, verbose=False,):

    file_path = DATA_DIR / "10globalitem.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(file_path, newline="", encoding="utf-8-sig") as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Load GlobalItem ─────────────────────────────────────
    created_count = 0
    updated_count = 0
    skipped_count = 0
    seen = set()

    for row in rows:

        global_item_id = clean(row.get("global_item_id"),lower=True)

        if not global_item_id:

            print("Skipping row with empty global_item_id")
            skipped_count += 1            
            continue

        key = global_item_id
        if key in seen:
            print(
                f"Duplicate CSV row: {key}"
            )
            skipped_count += 1
            continue        
        seen.add(key)
        
        defaults = {

            "gtin": clean(row.get("gtin")),
            "gpc_brick_code": clean(row.get("gpc_brick_code")),
            "domain": clean(row.get("domain", "generic")),
            "status": clean(row.get("status", "draft")),
            # ── media / identity ───────────────

            "country_of_origin": clean(row.get("country_of_origin")),
            "image_url": clean(row.get("image_url")),
            "image_alt": clean(row.get("image_alt")),
            "barcode": clean(row.get("barcode")),

            # ── dimensions ─────────────────────

            "weight_g": to_int(row.get("weight_g")),
            "length_mm": to_int(row.get("length_mm")),
            "width_mm": to_int(row.get("width_mm")),
            "height_mm": to_int(row.get("height_mm")),
            # ── JSON attributes ────────────────
            "attributes": to_json(row.get("attributes")),
            
        }

        for lang in LANGS:

            defaults[f"name_{lang}"] = clean(row.get(f"name_{lang}"))
            defaults[f"description_{lang}"] = clean(row.get(f"description_{lang}"))
            defaults[f"care_instructions_{lang}"] = clean(row.get(f"care_instructions_{lang}"))

        if dry_run:

            print(
                
                f"[DRY RUN] "
                f"{global_item_id} "
            )

            if verbose:
                print(defaults)

        else:

            obj, created = (
                GlobalItem.objects.update_or_create(

                    global_item_id=global_item_id,
                    defaults=defaults
                )
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

            if verbose:
                print(
                    f"{'Created' if created else 'Updated'} "
                    f"GlobalItem: {global_item_id}"
                )                

    print()
    if dry_run:
        print(f"Dry-Run Completed -> Rollback")
        transaction.set_rollback(True)
        
    else: 
        print(f"Loading Completed")
        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )

        

@transaction.atomic
def run(*args):
    args = [a.lower() for a in args] # for DRY_RUN

    DRY_RUN = "dryrun" in args # for DRY_RUN
    VERBOSE = "verbose" in args # for DRY_RUN

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

        #if DRY_RUN:

    #    print("DRY RUN COMPLETE → rollback")
    #    raise Exception("Rollback requested")

    print("Done")

"""
Normal Run - python manage.py runscript ....
Dry Run + Verbose - python manage.py runscript ... --script-args dryrun verbose
"""