import csv
import json

from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Item,
    SongItem,
)

from scripts.helpers import (
    clean,
    to_int,
    to_json,
)

LANGS = [lang[0] for lang in settings.LANGUAGES]

# client_code,item_code,
# artist,album,duration_s,bpm,
# musical_key,genre,audio_url,preview_url,
# isrc,attributes,
# artist_en,artist_hi,artist_fr,artist_ta,
# album_en,album_hi,album_fr,album_ta

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


@transaction.atomic
def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "23songitem.csv"

    # ── Read CSV once ───────────────────────────────────────

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # ── Collect required IDs ────────────────────────────────

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if clean(row.get("client_code"))
    }

    item_ids = {
        clean(row.get("item_code"), lower=True)
        for row in rows
        if clean(row.get("item_code"))
    }

    # ── Prefetch items ──────────────────────────────────────

    items = {
        (
            item.client.client_code,
            item.item_code,
        ): item

        for item in Item.objects.filter(
            client__client_code__in=client_codes,
            item_code__in=item_ids,
        ).select_related("client")
    }

    # ── Counters ────────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # ── Load SongItem ───────────────────────────────────────

    for row in rows:

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        item_code = clean(
            row.get("item_code"),
            lower=True,
        )

        if not client_code or not item_code:

            print(
                "Skipping row with empty "
                "client_code/item_code"
            )

            skipped_count += 1
            continue

        key = (client_code, item_code)

        if key in seen:

            print(
                f"Duplicate CSV row: "
                f"{client_code} / {item_code}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # ── Resolve item ───────────────────────────────────

        item = items.get(key)

        if not item:

            print(
                f"Missing item: "
                f"{client_code} / {item_code}"
            )

            skipped_count += 1
            continue

        # ── Defaults ───────────────────────────────────────

        defaults = {

            "artist":
                clean(row.get("artist")),

            "album":
                clean(row.get("album")),

            "duration_s":
                to_int(row.get("duration_s")),

            "bpm":
                to_int(row.get("bpm")),

            "musical_key":
                clean(row.get("musical_key")),

            "genre":
                clean(row.get("genre")),

            "audio_url":
                clean(row.get("audio_url")),

            "preview_url":
                clean(row.get("preview_url")),

            "isrc":
                clean(row.get("isrc")),

            "attributes":
                to_json(row.get("attributes")),
        }

        # ── Multilingual fields ────────────────────────────

        for lang in LANGS:

            defaults[f"artist_{lang}"] = clean(
                row.get(f"artist_{lang}")
            )

            defaults[f"album_{lang}"] = clean(
                row.get(f"album_{lang}")
            )

        # ── Dry Run ────────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code} / {item_code}"
            )

            if verbose:
                print(defaults)

            continue

        # ── Create / Update ────────────────────────────────

        obj, created = (
            SongItem.objects.update_or_create(

                item=item,

                defaults=defaults,
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"SongItem: "
                f"{client_code} / {item_code}"
            )

    # ── Summary ─────────────────────────────────────────────

    print()

    if dry_run:

        print("Dry-Run Completed -> Rollback")

        transaction.set_rollback(True)

    else:

        print("Loading Completed")

        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )


@transaction.atomic
def run(*args):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

    print("Done")


"""
Normal Run
----------
python manage.py runscript 23songitem

Dry Run + Verbose
-----------------
python manage.py runscript 23songitem --script-args dryrun verbose
"""

"""

import csv
import json

from decimal import Decimal
from pathlib import Path

from django.db import transaction
from django.conf import settings

LANGS = [lang[0] for lang in settings.LANGUAGES]

from mysite.models import (
    Item,
    SongItem,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def clean(value):
    return (value or "").strip()


def clean_lower(value):
    return clean(value).lower()


def bool01(value):
    return clean(value) == "1"


def to_decimal(value):

    value = clean(value)

    if value == "":
        return None

    return Decimal(value)


def to_int(value):

    value = clean(value)

    if value == "":
        return 0

    return int(value)


# ─────────────────────────────────────────────
# loader
# ─────────────────────────────────────────────

@transaction.atomic
def load_val01():

    file_path = DATA_DIR / "23songitem.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        rows = list(csv.DictReader(f))

    # ── collect keys ─────────────────────────

    client_codes = {
        clean_lower(r.get("client_code"))
        for r in rows
    }

    item_ids = {
        clean_lower(r.get("item_code"))
        for r in rows
    }

    # ── preload items ───────────────────────

    items = {

        (
            i.client.client_code,
            i.item_code
        ): i

        for i in Item.objects.filter(

            client__client_code__in=client_codes,
            item_code__in=item_ids,

        ).select_related("client")
    }

    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ── load rows ───────────────────────────

    for row in rows:

        client_code = clean_lower(
            row.get("client_code")
        )

        item_code = clean_lower(
            row.get("item_code")
        )

        item = items.get(
            (client_code, item_code)
        )

        if not item:

            print(
                f"Missing item: "
                f"{client_code} / {item_code}"
            )

            skipped_count += 1
            continue

        defaults = {

            "artist": clean(row.get("artist")),
            "album": clean(row.get("album")),

            "duration_s": to_int(row.get("duration_s")),       
            "bpm": to_int(row.get("bpm")),  

            "musical_key": clean(row.get("musical_key")),
            "genre": clean(row.get("genre")),

            "audio_url": clean(row.get("audio_url")),
            "preview_url": clean(row.get("preview_url")),

            "isrc": clean(row.get("isrc")),


            "attributes":
                json.loads(
                    row.get("attributes", "{}")
                ),
        }
        for lang in LANGS:

            defaults[f"artist_{lang}"] = row.get(f"artist_{lang}", "")

            defaults[f"album_{lang}"] = row.get(f"album_{lang}", "")


        obj, created = \
            SongItem.objects.update_or_create(

                item=item,

                defaults=defaults
            )

        if created:
            created_count += 1
        else:
            updated_count += 1

        print(
            f"{'Created' if created else 'Updated'} "
            f"{client_code} → {item_code}"
        )

    print()

    print(
        f"Loaded SongItem "
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )


def run():

    load_val01()

    print("Done")

"""