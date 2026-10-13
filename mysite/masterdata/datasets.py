# mysite/masterdata/datasets.py
#
# Single source of truth for the Master Data upload UI.
#
# Each Dataset ties together:
#   * the loader script that ingests the file (now accepting a data_dir path
#     argument — see scripts/load_*.py)
#   * the expected CSV/XLSX file name(s) and columns
#   * whether the data is client-scoped or global
#   * the Django model + natural key used for overlap detection / deletion
#
# The dataset registry is intentionally import-light: models are referenced
# lazily by label string so this module can be imported before apps are ready.

from dataclasses import dataclass, field

from scripts.helpers import clean, to_int, to_datetime


# ── Natural key part ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NK:
    """One part of a dataset's natural key.

    csv     column name in the uploaded file
    lookup  ORM lookup path relative to the target model
    kind    coercion: 'client' | 'lower' | 'str' | 'int' | 'datetime'
    """
    csv: str
    lookup: str
    kind: str = "lower"


# ── Dataset ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Dataset:
    key: str
    title: str
    script: str                 # importable module name under scripts/
    scope: str                  # 'client' | 'global'
    files: tuple                # expected file name(s), in order
    columns: tuple              # tuple of tuples, aligned with `files`
    group: str
    order: int
    model_label: str = ""       # 'mysite.ModelName'
    natural_key: tuple = field(default_factory=tuple)
    client_columns: tuple = ("client_code",)
    multi_file: bool = False
    description: str = ""

    @property
    def is_global(self) -> bool:
        return self.scope == "global"

    @property
    def primary_file(self) -> str:
        return self.files[0]

    @property
    def primary_columns(self) -> tuple:
        return self.columns[0]


# ── Coercion ──────────────────────────────────────────────────────────────────

def coerce(kind: str, raw):
    """Coerce a raw CSV value for use in an ORM filter."""
    if kind == "client":
        value = clean(raw, lower=True)
        return value or None
    if kind == "lower":
        return clean(raw, lower=True) or None
    if kind == "str":
        return clean(raw)
    if kind == "int":
        return to_int(raw)
    if kind == "datetime":
        return to_datetime(raw)
    return clean(raw)


# ── Common natural-key fragments ──────────────────────────────────────────────

CLIENT = NK("client_code", "client__client_code", "client")


def item_nk():
    return (
        NK("client_code", "item__client__client_code", "client"),
        NK("item_code", "item__item_code", "lower"),
    )


# ── Datasets ──────────────────────────────────────────────────────────────────

_GROUP_GLOBAL_CONFIG = "Global Configuration"
_GROUP_GLOBAL_ITEMS = "Global Items"
_GROUP_CLIENT_SETUP = "Client Setup"
_GROUP_TAXONOMY = "Taxonomy & Attributes"
_GROUP_ITEMS = "Items"


DATASETS = [
    # ── Global configuration ──────────────────────────────────────────────
    Dataset(
        key="00Aclientblock",
        title="Client Blocks",
        script="load_00Aclientblock",
        scope="global",
        files=("00Aclientblock.csv",),
        columns=(("from_date", "to_date", "remarks", "is_active", "client_code"),),
        group=_GROUP_GLOBAL_CONFIG,
        order=10,
        model_label="mysite.ClientBlock",
        natural_key=(
            NK("client_code", "client__client_code", "client"),
            NK("from_date", "from_date", "datetime"),
            NK("to_date", "to_date", "datetime"),
        ),
        description="Time-bounded blocks (client-specific or global).",
    ),
    Dataset(
        key="00Bclientfeaturecontrol",
        title="Client Feature Controls",
        script="load_00Bclientfeaturecontrol",
        scope="global",
        files=("00Bclientfeaturecontrol.csv",),
        columns=((
            "feature", "is_disabled", "from_date", "to_date",
            "message", "remarks", "client_code",
        ),),
        group=_GROUP_GLOBAL_CONFIG,
        order=20,
        model_label="mysite.ClientFeatureControl",
        natural_key=(
            NK("client_code", "client__client_code", "client"),
            NK("feature", "feature", "lower"),
            NK("from_date", "from_date", "datetime"),
            NK("to_date", "to_date", "datetime"),
        ),
        description="Feature disable windows (client-specific or global).",
    ),
    Dataset(
        key="00globalvalcat",
        title="Global Value Categories",
        script="load_00Aglobalvalcat",
        scope="global",
        files=("00globalvalcat.csv",),
        columns=(("globalvalcat_code",),),
        group=_GROUP_GLOBAL_CONFIG,
        order=30,
        model_label="mysite.GlobalValCat",
        natural_key=(NK("globalvalcat_code", "globalvalcat_code", "lower"),),
    ),
    Dataset(
        key="01globalval",
        title="Global Values",
        script="load_00Bglobalval",
        scope="global",
        files=("01globalval.csv",),
        columns=(("globalvalcat_code", "key", "keyval_en", "keyval_hi", "keyval_fr"),),
        group=_GROUP_GLOBAL_CONFIG,
        order=40,
        model_label="mysite.GlobalVal",
        natural_key=(
            NK("globalvalcat_code", "globalvalcat__globalvalcat_code", "lower"),
            NK("key", "key", "lower"),
        ),
    ),
    Dataset(
        key="02themepreset",
        title="Theme Presets",
        script="load_01themepreset",
        scope="global",
        files=("02themepreset.csv",),
        columns=((
            "themepreset_code", "primary", "secondary", "accent", "neutral",
            "primary_content", "secondary_content", "accent_content",
            "neutral_content", "base_100", "base_200", "base_300",
            "base_content", "success", "warning", "error", "info",
            "success_content", "warning_content", "error_content",
            "info_content", "font_body", "font_heading", "base_font_size",
            "scale_ratio", "section_gap", "container_padding", "radius_btn",
            "radius_card", "radius_input", "shadow_sm", "shadow_md",
            "shadow_lg", "is_system", "ltext",
        ),),
        group=_GROUP_GLOBAL_CONFIG,
        order=50,
        model_label="mysite.ThemePreset",
        natural_key=(NK("themepreset_code", "themepreset_code", "lower"),),
    ),

    # ── Global items ──────────────────────────────────────────────────────
    Dataset(
        key="10globalitem",
        title="Global Items",
        script="load_10globalitem",
        scope="global",
        files=("10globalitem.csv",),
        columns=((
            "global_item_code", "gtin", "gpc_brick_code", "domain", "status",
            "name_en", "name_hi", "name_fr", "name_ta",
            "description_en", "description_hi", "description_fr", "description_ta",
            "country_of_origin", "image_url", "image_alt", "barcode",
            "weight_g", "length_mm", "width_mm", "height_mm",
            "care_instructions_en", "care_instructions_hi",
            "care_instructions_fr", "care_instructions_ta", "attributes",
        ),),
        group=_GROUP_GLOBAL_ITEMS,
        order=10,
        model_label="mysite.GlobalItem",
        natural_key=(NK("global_item_code", "global_item_code", "lower"),),
    ),
    Dataset(
        key="11Aglobalitemtaxonomynode",
        title="Global Item Taxonomy Nodes",
        script="load_11Aglobalitemtaxonomynode",
        scope="global",
        files=("11Aglobalitemtaxonomynode.csv",),
        columns=(("global_item_code", "taxonomy_slug", "node_slug", "is_primary"),),
        group=_GROUP_GLOBAL_ITEMS,
        order=20,
        model_label="mysite.GlobalItemTaxonomyNode",
        natural_key=(
            NK("global_item_code", "global_item__global_item_code", "lower"),
            NK("taxonomy_slug", "node__taxonomy__slug", "lower"),
            NK("node_slug", "node__slug", "lower"),
        ),
    ),
    Dataset(
        key="11Bglobalitemattributevalue",
        title="Global Item Attribute Values",
        script="load_11Bglobalitemattributevalue",
        scope="global",
        files=("11Bglobalitemattributevalue.csv",),
        columns=((
            "global_item_code", "taxonomy_slug", "node_slug",
            "attribute_slug", "predefined_value_slug", "value_text", "value_number",
        ),),
        group=_GROUP_GLOBAL_ITEMS,
        order=30,
        model_label="mysite.GlobalItemAttributeValue",
        natural_key=(
            NK("global_item_code", "global_item__global_item_code", "lower"),
            NK("attribute_slug", "attribute_type__slug", "lower"),
        ),
    ),
    Dataset(
        key="12globalitemmedia",
        title="Global Item Media",
        script="load_12globalitemmedia",
        scope="global",
        files=("12Aglobalitemmediamain.csv", "12Bglobalitemmediatext.csv"),
        columns=(
            ("global_item_code", "media_type", "media_url", "alt", "order",
             "is_primary", "text_key"),
            ("text_key", "section_order", "child_order", "content_order",
             "title_en", "title_hi", "title_fr", "title_ta",
             "subtitle_en", "subtitle_hi", "subtitle_fr", "subtitle_ta",
             "content_en", "content_hi", "content_fr", "content_ta"),
        ),
        group=_GROUP_GLOBAL_ITEMS,
        order=40,
        model_label="mysite.GlobalItemMedia",
        multi_file=True,
        natural_key=(
            NK("global_item_code", "global_item__global_item_code", "lower"),
            NK("media_type", "media_type", "lower"),
            NK("order", "order", "int"),
        ),
        description="Two files: media entries (A) + multilingual text (B).",
    ),

    # ── Client setup ──────────────────────────────────────────────────────
    Dataset(
        key="03client",
        title="Client",
        script="load_03client",
        scope="client",
        files=("03client.csv",),
        columns=((
            "client_code", "language_list", "theme_list",
            "nb_title_svg_pre", "nb_title_svg_suf",
            "name_en", "name_fr", "name_hi", "name_ta",
            "nb_title_en", "nb_title_fr", "nb_title_hi", "nb_title_ta",
            "default_language", "parent_id",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=5,
        model_label="mysite.Client",
        natural_key=(NK("client_code", "client_code", "lower"),),
        description="Acting client's own row, or any client when uploaded by the "
                    "bahushira operator (type the new client's code as the target "
                    "to provision it).",
    ),
    Dataset(
        key="03Atheme",
        title="Themes",
        script="load_03Atheme",
        scope="client",
        files=("03Atheme.csv",),
        columns=((
            "theme_code", "order", "hidden", "overrides", "is_default",
            "client_code", "themepreset_code",
            "name_en", "name_fr", "name_hi", "name_ta", "ltext",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=10,
        model_label="mysite.Theme",
        natural_key=(
            CLIENT,
            NK("theme_code", "theme_code", "lower"),
        ),
    ),
    Dataset(
        key="03Bpage",
        title="Pages",
        script="load_03Bpage",
        scope="client",
        files=("03Bpage.csv",),
        columns=(("page_code", "ltext", "hidden", "client_code"),),
        group=_GROUP_CLIENT_SETUP,
        order=20,
        model_label="mysite.Page",
        natural_key=(CLIENT, NK("page_code", "page_code", "lower")),
    ),
    Dataset(
        key="03Cnavitem",
        title="Nav Items",
        script="load_03Cnavitem",
        scope="client",
        files=("03Cnavitem.csv",),
        columns=((
            "location", "nav_type", "url", "name_en", "name_hi", "name_fr",
            "order", "hidden", "open_in_new_tab", "client_code", "page_code",
            "svg_pre", "svg_suf", "name_ta", "parent_name_en",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=30,
        model_label="mysite.NavItem",
        natural_key=(CLIENT, NK("name_en", "name_en__iexact", "lower")),
    ),
    Dataset(
        key="03Dpagecontent",
        title="Page Content",
        script="load_03Dpagecontent",
        scope="client",
        files=("03Dpagecontent.csv",),
        columns=((
            "client_code", "page_code",
            "htmlblob_en", "htmlblob_fr", "htmlblob_hi", "htmlblob_ta",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=40,
        model_label="mysite.PageContent",
        natural_key=(
            NK("client_code", "page__client__client_code", "client"),
            NK("page_code", "page__page_code", "lower"),
        ),
    ),
    Dataset(
        key="03Eclienttemplate",
        title="Client Templates",
        script="load_03Eclienttemplate",
        scope="client",
        files=("03Eclienttemplate.csv",),
        columns=((
            "template_key", "is_active", "client_code",
            "htmlblob_en", "htmlblob_fr", "htmlblob_hi", "htmlblob_ta",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=50,
        model_label="mysite.ClientTemplate",
        natural_key=(CLIENT, NK("template_key", "template_key", "lower")),
    ),
    Dataset(
        key="04clientgroup",
        title="Client Groups",
        script="load_04clientgroup",
        scope="client",
        files=("04clientgroup.csv",),
        columns=((
            "clientgroup_code", "name", "role", "description",
            "is_active", "client_code",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=60,
        model_label="mysite.ClientGroup",
        natural_key=(CLIENT, NK("clientgroup_code", "clientgroup_code", "lower")),
    ),
    Dataset(
        key="05clientlocation",
        title="Client Locations",
        script="load_05clientlocation",
        scope="client",
        files=("05clientlocation.csv",),
        columns=((
            "location_code", "name", "location_type", "is_active",
            "client_code", "parent_location_code",
        ),),
        group=_GROUP_CLIENT_SETUP,
        order=70,
        model_label="mysite.ClientLocation",
        natural_key=(CLIENT, NK("location_code", "location_code", "lower")),
    ),

    # ── Taxonomy & attributes ─────────────────────────────────────────────
    Dataset(
        key="06taxonomy",
        title="Taxonomies",
        script="load_06taxonomy",
        scope="client",
        files=("06taxonomy.csv",),
        columns=((
            "slug", "order", "is_active", "client_code",
            "name_en", "name_fr", "name_hi", "name_ta",
            "description_en", "description_fr", "description_hi", "description_ta",
            "gpc_segment_code", "taxonomy_type",
        ),),
        group=_GROUP_TAXONOMY,
        order=10,
        model_label="mysite.Taxonomy",
        natural_key=(CLIENT, NK("slug", "slug", "lower")),
    ),
    Dataset(
        key="07taxonomynode",
        title="Taxonomy Nodes",
        script="load_07taxonomynode",
        scope="client",
        files=("07taxonomynode.csv",),
        columns=((
            "slug", "order", "is_active", "metadata", "taxonomy_slug",
            "name_en", "name_fr", "name_hi", "name_ta", "client_code",
            "gpc_code", "parent_slug", "global_node_id",
        ),),
        group=_GROUP_TAXONOMY,
        order=20,
        model_label="mysite.TaxonomyNode",
        natural_key=(
            NK("taxonomy_slug", "taxonomy__slug", "lower"),
            CLIENT,
            NK("slug", "slug", "lower"),
        ),
    ),
    Dataset(
        key="08Aattributetype",
        title="Attribute Types",
        script="load_08Aattributetype",
        scope="client",
        files=("08Aattributetype.csv",),
        columns=((
            "client_code", "slug", "name_en", "name_hi", "name_fr",
            "name_ta", "field_type", "gpc_code",
        ),),
        group=_GROUP_TAXONOMY,
        order=30,
        model_label="mysite.AttributeType",
        natural_key=(CLIENT, NK("slug", "slug", "lower")),
    ),
    Dataset(
        key="08Btaxonomynodeattribute",
        title="Taxonomy Node Attributes",
        script="load_08Btaxonomynodeattribute",
        scope="client",
        files=("08Btaxonomynodeattribute.csv",),
        columns=((
            "node_client_code", "taxonomy_slug", "node_slug",
            "attribute_client_code", "attribute_slug",
            "is_required", "is_filterable", "order",
        ),),
        group=_GROUP_TAXONOMY,
        order=40,
        model_label="mysite.TaxonomyNodeAttribute",
        client_columns=("node_client_code", "attribute_client_code"),
        natural_key=(
            NK("node_client_code", "node__client__client_code", "client"),
            NK("taxonomy_slug", "node__taxonomy__slug", "lower"),
            NK("node_slug", "node__slug", "lower"),
            NK("attribute_client_code", "attribute_type__client__client_code", "client"),
            NK("attribute_slug", "attribute_type__slug", "lower"),
        ),
    ),
    Dataset(
        key="09Aattributevalue",
        title="Attribute Values",
        script="load_09Aattributevalue",
        scope="client",
        files=("09Aattributevalue.csv",),
        columns=((
            "client_code", "slug", "name_en", "name_hi", "name_fr",
            "name_ta", "gpc_code",
        ),),
        group=_GROUP_TAXONOMY,
        order=50,
        model_label="mysite.AttributeValue",
        natural_key=(CLIENT, NK("slug", "slug", "lower")),
    ),
    Dataset(
        key="09Btaxonomynodeattributevalue",
        title="Node Attribute Values",
        script="load_09Btaxonomynodeattributevalue",
        scope="client",
        files=("09Btaxonomynodeattributevalue.csv",),
        columns=((
            "node_client_code", "taxonomy_slug", "node_slug",
            "attribute_client_code", "attribute_slug",
            "value_client_code", "value_slug", "order",
        ),),
        group=_GROUP_TAXONOMY,
        order=60,
        model_label="mysite.TaxonomyNodeAttributeValue",
        client_columns=("node_client_code", "attribute_client_code", "value_client_code"),
        natural_key=(
            NK("node_client_code",
               "node_attribute__node__client__client_code", "client"),
            NK("taxonomy_slug",
               "node_attribute__node__taxonomy__slug", "lower"),
            NK("node_slug", "node_attribute__node__slug", "lower"),
            NK("attribute_client_code",
               "node_attribute__attribute_type__client__client_code", "client"),
            NK("attribute_slug",
               "node_attribute__attribute_type__slug", "lower"),
            NK("value_client_code",
               "attribute_value__client__client_code", "client"),
            NK("value_slug", "attribute_value__slug", "lower"),
        ),
    ),

    # ── Items ─────────────────────────────────────────────────────────────
    Dataset(
        key="20item",
        title="Items",
        script="load_20item",
        scope="client",
        files=("20item.csv",),
        columns=((
            "client_code", "item_code", "global_item_code", "inherit_global_media",
            "gtin", "gpc_brick_code", "domain", "status", "order",
            "name_en", "name_hi", "name_fr", "name_ta",
            "description_en", "description_hi", "description_fr", "description_ta",
            "country_of_origin", "image_url", "image_alt", "barcode",
            "weight_g", "length_mm", "width_mm", "height_mm",
            "care_instructions_en", "care_instructions_hi",
            "care_instructions_fr", "care_instructions_ta", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=10,
        model_label="mysite.Item",
        natural_key=(CLIENT, NK("item_code", "item_code", "lower")),
    ),
    Dataset(
        key="21Aitemtaxonomynode",
        title="Item Taxonomy Nodes",
        script="load_21Aitemtaxonomynode",
        scope="client",
        files=("21Aitemtaxonomynode.csv",),
        columns=((
            "client_code", "item_code", "taxonomy_slug",
            "node_client_code", "node_slug", "is_primary", "order",
        ),),
        group=_GROUP_ITEMS,
        order=20,
        model_label="mysite.ItemTaxonomyNode",
        natural_key=(
            *item_nk(),
            NK("taxonomy_slug", "node__taxonomy__slug", "lower"),
            NK("node_slug", "node__slug", "lower"),
        ),
    ),
    Dataset(
        key="21Bitemattributevalue",
        title="Item Attribute Values",
        script="load_21Bitemattributevalue",
        scope="client",
        files=("21Bitemattributevalue.csv",),
        columns=((
            "client_code", "item_code", "taxonomy_slug", "node_slug",
            "attribute_client_code", "attribute_slug",
            "predefined_client_code", "predefined_value_slug",
            "value_text", "value_number",
        ),),
        group=_GROUP_ITEMS,
        order=30,
        model_label="mysite.ItemAttributeValue",
        natural_key=(
            *item_nk(),
            NK("attribute_client_code",
               "attribute_type__client__client_code", "client"),
            NK("attribute_slug", "attribute_type__slug", "lower"),
        ),
    ),
    Dataset(
        key="22productitem",
        title="Product Items",
        script="load_22productitem",
        scope="client",
        files=("22productitem.csv",),
        columns=((
            "client_code", "item_code", "price", "compare_price", "currency",
            "sku", "barcode", "track_inventory", "stock_quantity", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=40,
        model_label="mysite.ProductItem",
        natural_key=item_nk(),
    ),
    Dataset(
        key="23songitem",
        title="Song Items",
        script="load_23songitem",
        scope="client",
        files=("23songitem.csv",),
        columns=((
            "client_code", "item_code",
            "artist_en", "artist_hi", "artist_fr", "artist_ta",
            "album_en", "album_hi", "album_fr", "album_ta",
            "duration_s", "bpm", "musical_key", "genre",
            "audio_url", "preview_url", "isrc", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=50,
        model_label="mysite.SongItem",
        natural_key=item_nk(),
    ),
    Dataset(
        key="24itemmedia",
        title="Item Media",
        script="load_24itemmedia",
        scope="client",
        files=("24Aitemmediamain.csv", "24Bitemmediatext.csv"),
        columns=(
            ("client_code", "item_code", "media_type", "media_url", "alt",
             "order", "is_primary", "text_key"),
            ("client_code", "text_key", "section_order", "child_order",
             "content_order", "title_en", "title_hi", "title_fr", "title_ta",
             "subtitle_en", "subtitle_hi", "subtitle_fr", "subtitle_ta",
             "content_en", "content_hi", "content_fr", "content_ta"),
        ),
        group=_GROUP_ITEMS,
        order=60,
        model_label="mysite.ItemMedia",
        multi_file=True,
        natural_key=(
            *item_nk(),
            NK("media_type", "media_type", "lower"),
            NK("order", "order", "int"),
        ),
        description="Two files: media entries (A) + multilingual text (B).",
    ),
    Dataset(
        key="25itemvariant",
        title="Item Variants",
        script="load_25itemvariant",
        scope="client",
        files=("25itemvariant.csv",),
        columns=((
            "client_code", "item_code", "variant_code",
            "name_en", "name_hi", "name_fr", "name_ta",
            "sku", "gtin", "price", "stock", "is_active", "order",
            "image_url", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=70,
        model_label="mysite.ItemVariant",
        natural_key=(
            *item_nk(),
            NK("variant_code", "variant_code", "lower"),
        ),
    ),
    Dataset(
        key="26documentitem",
        title="Document Items",
        script="load_26documentitem",
        scope="client",
        files=("26documentitem.csv",),
        columns=((
            "client_code", "item_code", "file_url", "format", "page_count",
            "file_size_kb", "version", "language", "is_free", "price",
            "currency", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=80,
        model_label="mysite.DocumentItem",
        natural_key=item_nk(),
    ),
    Dataset(
        key="26serviceitem",
        title="Service Items",
        script="load_26serviceitem",
        scope="client",
        files=("26serviceitem.csv",),
        columns=((
            "client_code", "item_code", "price", "currency",
            "duration_minutes", "is_location_based", "service_area",
            "fulfillment_type", "attributes",
        ),),
        group=_GROUP_ITEMS,
        order=90,
        model_label="mysite.ServiceItem",
        natural_key=item_nk(),
    ),
]


# ── Lookup helpers ────────────────────────────────────────────────────────────

_BY_KEY = {d.key: d for d in DATASETS}


def get_dataset(key: str) -> Dataset:
    return _BY_KEY[key]


def all_datasets() -> list:
    return list(DATASETS)


def datasets_for_scope(scope: str) -> list:
    return [d for d in DATASETS if d.scope == scope]


def grouped_for_scope(scope: str) -> list:
    """Return [(group, [datasets...]), ...] preserving registry order."""
    groups = {}
    for d in sorted(datasets_for_scope(scope), key=lambda x: x.order):
        groups.setdefault(d.group, []).append(d)
    return list(groups.items())


def dependent_datasets(dataset: Dataset) -> list:
    """Datasets whose model is referenced by `dataset`'s model via a natural key.

    Used to warn + require a second confirmation when a delete would cascade
    into other master data (e.g. deleting Items also removes their media,
    attribute values, variants, …).
    """
    from django.apps import apps

    if not dataset.model_label:
        return []
    model = apps.get_model(dataset.model_label)

    dependents = []
    for other in DATASETS:
        if other is dataset or not other.model_label:
            continue
        other_model = apps.get_model(other.model_label)
        for nk in other.natural_key:
            rel = nk.lookup.split("__", 1)[0]
            try:
                field = other_model._meta.get_field(rel)
            except Exception:
                continue
            if getattr(field, "remote_field", None) and field.remote_field.model is model:
                dependents.append(other)
                break
    return dependents
