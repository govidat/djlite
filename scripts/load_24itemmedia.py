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

    value = clean(value)

    if value == "":
        return default

    return int(value)

def build_language_text(rows, lang):
    """
    Build structure like:

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

    # -------------------------------------------------------
    # Group by section_order
    # -------------------------------------------------------

    sections = {}

    for row in rows:

        section_order = int(
            row.get("section_order", 0)
        )

        child_order = int(
            row.get("child_order", 0)
        )

        content_order = int(
            row.get("content_order", 0)
        )

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

        item = items.get(item_id)

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