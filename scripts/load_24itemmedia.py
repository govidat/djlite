import csv
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.db import transaction

from mysite.models import (
    Item,
    ItemMedia,
)

from scripts.helpers import (
    clean,
    to_int,
    to_bool,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LANGS = [lang[0] for lang in settings.LANGUAGES]

# =========================================================
# Helpers
# =========================================================

def build_language_text(rows, lang):
    """
    Build structure:

    [
        {
            "title": "...",
            "children": [
                {
                    "subtitle": "...",
                    "content": [...]
                }
            ]
        }
    ]
    """

    sections = {}

    for row in rows:

        section_order = to_int(
            row.get("section_order"),
            default=0,
        )

        child_order = to_int(
            row.get("child_order"),
            default=0,
        )

        content_order = to_int(
            row.get("content_order"),
            default=0,
        )

        # -------------------------------------------------
        # Section
        # -------------------------------------------------

        if section_order not in sections:

            sections[section_order] = {
                "title": clean(
                    row.get(f"title_{lang}")
                ),
                "_children": {},
            }

        children = sections[section_order]["_children"]

        # -------------------------------------------------
        # Child
        # -------------------------------------------------

        if child_order not in children:

            children[child_order] = {
                "subtitle": clean(
                    row.get(f"subtitle_{lang}")
                ),
                "_content": {},
            }

        # -------------------------------------------------
        # Content
        # -------------------------------------------------

        content_val = clean(
            row.get(f"content_{lang}")
        )

        if content_val:

            children[child_order]["_content"][
                content_order
            ] = content_val

    # -----------------------------------------------------
    # Final structure
    # -----------------------------------------------------

    final_sections = []

    for section_order in sorted(sections.keys()):

        section = sections[section_order]

        final_children = []

        for child_order in sorted(
            section["_children"].keys()
        ):

            child = section["_children"][
                child_order
            ]

            content_lines = [

                child["_content"][k]

                for k in sorted(
                    child["_content"].keys()
                )
            ]

            final_children.append({
                "subtitle": child["subtitle"],
                "content": content_lines,
            })

        final_sections.append({
            "title": section["title"],
            "children": final_children,
        })

    return final_sections


# =========================================================
# Loader
# =========================================================

def load_val01(
    dry_run=False,
    verbose=False,
):

    main_file = (
        DATA_DIR /
        "24Aitemmediamain.csv"
    )

    text_file = (
        DATA_DIR /
        "24Bitemmediatext.csv"
    )

    # -----------------------------------------------------
    # Load CSVs
    # -----------------------------------------------------

    with open(
        main_file,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        main_rows = list(
            csv.DictReader(f)
        )

    with open(
        text_file,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        text_rows = list(
            csv.DictReader(f)
        )

    # -----------------------------------------------------
    # Fetch Items
    # -----------------------------------------------------

    client_ids = {

        clean(
            row.get("client_id"),
            lower=True,
        )

        for row in main_rows

        if row.get("client_id")
    }

    item_ids = {

        clean(
            row.get("item_id"),
            lower=True,
        )

        for row in main_rows

        if row.get("item_id")
    }

    items = {

        (
            item.client.client_id,
            item.item_id,
        ): item

        for item in Item.objects.filter(
            client__client_id__in=client_ids,
            item_id__in=item_ids,
        ).select_related("client")
    }

    # -----------------------------------------------------
    # Group text rows by text_key
    # -----------------------------------------------------

    text_rows_by_key = defaultdict(list)

    for row in text_rows:

        text_key = clean(
            row.get("text_key"),
            lower=True,
        )

        if text_key:

            text_rows_by_key[
                text_key
            ].append(row)

    # -----------------------------------------------------
    # Stats
    # -----------------------------------------------------

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    # -----------------------------------------------------
    # Process media rows
    # -----------------------------------------------------

    for row in main_rows:

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        item_id = clean(
            row.get("item_id"),
            lower=True,
        )

        media_type = clean(
            row.get("media_type"),
            lower=True,
        )

        order = to_int(
            row.get("order"),
            default=0,
        )

        # -------------------------------------------------
        # Validation
        # -------------------------------------------------

        if not client_id or not item_id:

            print(
                "Skipping row with empty "
                "client_id/item_id"
            )

            skipped_count += 1
            continue

        key = (
            client_id,
            item_id,
            media_type,
            order,
        )

        if key in seen:

            print(
                f"Duplicate CSV row: {key}"
            )

            skipped_count += 1
            continue

        seen.add(key)

        # -------------------------------------------------
        # Resolve Item
        # -------------------------------------------------

        item = items.get(
            (client_id, item_id)
        )

        if not item:

            print(
                f"Missing Item: "
                f"{client_id} / {item_id}"
            )

            skipped_count += 1
            continue

        # -------------------------------------------------
        # Build multilingual text content
        # -------------------------------------------------

        text_key = clean(
            row.get("text_key"),
            lower=True,
        )

        media_text_rows = (
            text_rows_by_key.get(
                text_key,
                [],
            )
        )

        text_content_by_lang = {}

        for lang in LANGS:

            text_content_by_lang[lang] = (
                build_language_text(
                    media_text_rows,
                    lang,
                )
            )

        # -------------------------------------------------
        # Defaults
        # -------------------------------------------------

        defaults = {

            "media_url": clean(
                row.get("media_url")
            ),

            "alt": clean(
                row.get("alt")
            ),

            "is_primary": to_bool(
                row.get("is_primary")
            ),
        }

        # -------------------------------------------------
        # Language JSON fields
        # -------------------------------------------------

        for lang in LANGS:

            defaults[
                f"text_content_{lang}"
            ] = text_content_by_lang[lang]

        # -------------------------------------------------
        # Base field fallback
        # -------------------------------------------------

        defaults["text_content"] = (
            text_content_by_lang.get(
                settings.LANGUAGE_CODE,
                text_content_by_lang.get(
                    "en",
                    [],
                )
            )
        )

        # -------------------------------------------------
        # Dry Run
        # -------------------------------------------------

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / "
                f"{item_id} / "
                f"{media_type} / "
                f"{order}"
            )

            if verbose:
                print(defaults)

            continue

        # -------------------------------------------------
        # Save
        # -------------------------------------------------

        obj, created = (
            ItemMedia.objects.update_or_create(

                item=item,
                media_type=media_type,
                order=order,

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
                f"ItemMedia: "
                f"{client_id} / "
                f"{item_id} / "
                f"{media_type} / "
                f"{order}"
            )

    # -----------------------------------------------------
    # Summary
    # -----------------------------------------------------

    print()

    if dry_run:

        print(
            "Dry-Run Completed -> Rollback"
        )

        transaction.set_rollback(True)

    else:

        print("Loading Completed")

        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )


# =========================================================
# Runner
# =========================================================

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
python manage.py runscript 24itemmedia

Dry Run + Verbose
-----------------
python manage.py runscript 24itemmedia --script-args dryrun verbose
"""
"""

import csv
from collections import defaultdict
from pathlib import Path

from django.conf import settings

from mysite.models import (
    Client,
    Item,
    ItemMedia,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

LANGS = [lang[0] for lang in settings.LANGUAGES]

# ─────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────

def clean(value):
    return (value or "").strip()


def clean_lower(value):
    return clean(value).lower()


def bool01(value):
    return clean(value) == "1"


def to_int(value, default=0):
    try:
        return int(clean(value) or default)
    except ValueError:
        return default

def build_language_text(rows, lang):
    

    # -------------------------------------------------------
    # Group by section_order
    # -------------------------------------------------------

    sections = {}

    for row in rows:

        section_order = to_int(row.get("section_order"))

        child_order = to_int(row.get("child_order"))

        content_order = to_int(row.get("content_order"))

        # ---------------------------------------------------
        # Create section
        # ---------------------------------------------------

        if section_order not in sections:

            sections[section_order] = {

                "title":
                    row.get(
                        f"title_{lang}",
                        ""
                    ).strip(),

                "_children": {}
            }

        children = sections[section_order]["_children"]

        # ---------------------------------------------------
        # Create child
        # ---------------------------------------------------

        if child_order not in children:

            children[child_order] = {

                "subtitle":
                    row.get(
                        f"subtitle_{lang}",
                        ""
                    ).strip(),

                "_content": {}
            }

        # ---------------------------------------------------
        # Add content line
        # ---------------------------------------------------

        content_val = (
            row.get(
                f"content_{lang}",
                ""
            ).strip()
        )

        if content_val:

            children[child_order]["_content"][
                content_order
            ] = content_val

    # -------------------------------------------------------
    # Convert to final structure
    # -------------------------------------------------------

    final_sections = []

    for section_order in sorted(sections.keys()):

        section = sections[section_order]

        final_children = []

        children = section["_children"]

        for child_order in sorted(children.keys()):

            child = children[child_order]

            content_lines = [

                child["_content"][k]

                for k in sorted(
                    child["_content"].keys()
                )
            ]

            final_children.append({

                "subtitle":
                    child["subtitle"],

                "content":
                    content_lines
            })

        final_sections.append({

            "title":
                section["title"],

            "children":
                final_children
        })

    return final_sections


def load_val01():

    main_file = (
        DATA_DIR /
        "24Aitemmediamain.csv"
    )

    text_file = (
        DATA_DIR /
        "24Bitemmediatext.csv"
    )

    # =======================================================
    # Load CSVs
    # =======================================================

    with open(
        main_file,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        main_rows = list(
            csv.DictReader(f)
        )

    with open(
        text_file,
        newline="",
        encoding="utf-8-sig"
    ) as f:

        text_rows = list(
            csv.DictReader(f)
        )

    # ── collect keys ─────────────────────────

    client_ids = {
        clean_lower(r.get("client_id"))
        for r in main_rows
    }

    item_ids = {
        clean_lower(r.get("item_id"))
        for r in main_rows
    }



    # =======================================================
    # Group text rows by text_key
    # =======================================================

    text_rows_by_key = defaultdict(list)

    for row in text_rows:

        text_key = (
            row.get("text_key", "")
            .strip()
            .lower()
        )

        if text_key:

            text_rows_by_key[
                text_key
            ].append(row)

    # ── preload items ────────────────────────

    items = {

        (
            i.client.client_id,
            i.item_id
        ): i

        for i in Item.objects.filter(

            client__client_id__in=client_ids,
            item_id__in=item_ids,

        ).select_related("client")
    }


    # =======================================================
    # Process media rows
    # =======================================================

    for row in main_rows:

        item_id = clean_lower(row.get("item_id"))


        media_type = clean_lower(row.get("media_type"))

        order = int(
            row.get("order", 0)
        )

        client_id = clean_lower(row.get("client_id"))


        item = items.get(
            (client_id, item_id)
        )
        if not item:

            print(
                f"Missing Item: "
                f"{item_id}"
            )

            continue

        # ---------------------------------------------------
        # Build multilingual text content
        # ---------------------------------------------------

        text_key = (
            row.get("text_key", "")
            .strip()
            .lower()
        )

        media_text_rows = (
            text_rows_by_key.get(
                text_key,
                []
            )
        )

        text_content_by_lang = {}

        for lang in LANGS:

            text_content_by_lang[lang] = (
                build_language_text(
                    media_text_rows,
                    lang
                )
            )

        # ---------------------------------------------------
        # Defaults
        # ---------------------------------------------------

        defaults = {

            "media_url":
                row.get(
                    "media_url",
                    ""
                ).strip(),

            "alt":
                row.get(
                    "alt",
                    ""
                ).strip(),

            "is_primary":
                row.get(
                    "is_primary",
                    "0"
                ) == "1",
        }

        # ---------------------------------------------------
        # modeltranslation JSON fields
        # ---------------------------------------------------

        for lang in LANGS:

            defaults[
                f"text_content_{lang}"
            ] = text_content_by_lang[lang]

        # ---------------------------------------------------
        # Base field
        # ---------------------------------------------------

        defaults["text_content"] = (
            text_content_by_lang.get(
                settings.LANGUAGE_CODE,
                text_content_by_lang.get(
                    "en",
                    []
                )
            )
        )

        # ---------------------------------------------------
        # Save
        # ---------------------------------------------------

        obj, created = (
            ItemMedia.objects.update_or_create(

                item=item,
                media_type=media_type,
                order=order,

                defaults=defaults
            )
        )

        print(

            f"{'Created' if created else 'Updated'} "

            f"ItemMedia: "

            f"{item_id} / "

            f"{media_type} / "

            f"{order}"
        )

    print("Loaded ItemMedia")


def run():

    load_val01()

    print("Done")
"""