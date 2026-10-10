"""
Generic import engine for master data CSV uploads.

Reads CSV files, validates columns, resolves FKs, and upserts rows
using update_or_create() — matching the existing load script pattern.
"""
import csv
import io
import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models, transaction
from django.utils import timezone

from mysite.models import Client, Country, TaxonomyNode
from upload_masters.registry import get_registry_entry

logger = logging.getLogger(__name__)

LANGS = [lang[0] for lang in settings.LANGUAGES]


def _clean(value, lower=False):
    if value is None:
        return ""
    v = str(value).strip()
    if lower:
        v = v.lower()
    return v


def _coerce_default(model_class, field_name, value):
    """
    Coerce a raw CSV string to the target model field's Python type,
    matching the load scripts (scripts/helpers.py to_int/to_bool etc.).
    """
    if not value:
        return value
    try:
        field = model_class._meta.get_field(field_name)
    except Exception:
        return value
    if isinstance(field, (models.IntegerField,)):
        return int(value)
    if isinstance(field, models.DecimalField):
        from decimal import Decimal
        return Decimal(value)
    if isinstance(field, models.FloatField):
        return float(value)
    if isinstance(field, models.BooleanField):
        return value.lower() in ("1", "true", "yes", "on", "y", "t")
    if isinstance(field, models.JSONField):
        import json
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value


def _resolve_fk(model_label, lookup_field, lookup_value, lookup_cache):
    """
    Resolve a FK using the pre-built lookup cache.
    Returns the FK value (PK or object) or None if not found.
    """
    cache_key = (model_label, lookup_field)
    cache = lookup_cache.get(cache_key, {})
    return cache.get(lookup_value)


def _build_fk_caches(client, entry, csv_rows, lookup_fields_map):
    """
    Pre-fetch all FK objects referenced in the CSV into a dict cache.
    lookup_fields_map: {field_name: (model_class, lookup_attr, cache_key_prefix)}
    """
    cache = {}

    for field_name, (model_class, lookup_attr, cache_prefix) in lookup_fields_map.items():
        # Collect all unique values for this FK from CSV rows
        values = set()
        for row in csv_rows:
            val = _clean(row.get(field_name))
            if val:
                values.add(val)

        if not values:
            continue

        # Build queryset filter
        if lookup_attr == "client_code":
            # Client is looked up by client_code string
            qs = model_class.objects.filter(client_code__in=values)
        elif lookup_attr == "code" and hasattr(model_class, "client_id"):
            # Client-scoped models: filter by client + code
            qs = model_class.objects.filter(
                client=client, code__in=values
            )
        else:
            qs = model_class.objects.filter(**{f"{lookup_attr}__in": values})

        # Build cache dict
        cache_dict = {}
        for obj in qs:
            if lookup_attr == "client_code":
                cache_dict[str(getattr(obj, "client_code", ""))] = obj
            elif hasattr(obj, "code"):
                cache_dict[str(obj.code)] = obj
            else:
                cache_dict[str(getattr(obj, lookup_attr, ""))] = obj

        cache[(model_label, field_name)] = cache_dict

    return cache


def _build_translated_defaults(row, translated_fields, prefix=""):
    """Build a dict of translated field values from CSV columns."""
    defaults = {}
    for field in translated_fields:
        for lang in LANGS:
            col = f"{field}_{lang}"
            value = _clean(row.get(col))
            if value:
                defaults[f"{prefix}{field}_{lang}"] = value
    return defaults


def _build_country_cache(rows):
    """Pre-fetch Country objects for all country_code values in CSV rows."""
    codes = set()
    for row in rows:
        code = _clean(row.get("country_code"))
        if code:
            codes.add(code.upper())
    if not codes:
        return {}
    countries = Country.objects.filter(code__in=codes)
    return {c.code: c for c in countries}


def _resolve_country_from_row(row, country_obj, country_cache, country_scoped):
    """
    Resolve the Country FK for a row using the CSV's country_code column.

    Cross-check logic:
      - CSV has country_code + form has selection → must match, else error
      - CSV has country_code + no form selection  → use CSV value
      - CSV blank + form has selection             → use form value
      - CSV blank + no form selection              → None (global seed data)

    Returns (country_object_or_None, error_string_or_None).
    """
    if not country_scoped:
        return None, None

    csv_code = _clean(row.get("country_code")).upper()

    if csv_code and country_obj:
        # Both CSV and form have a country — cross-check
        if csv_code != country_obj.code:
            return None, (
                f"country_code='{csv_code}' does not match "
                f"selected country '{country_obj.code}'"
            )
        return country_obj, None

    if csv_code and not country_obj:
        # CSV has country_code but no form selection — use CSV's value
        csv_country = country_cache.get(csv_code)
        if csv_country:
            return csv_country, None
        return None, f"country_code='{csv_code}' is not a valid country"

    if not csv_code and country_obj:
        # CSV blank but form has selection — use form's country
        return country_obj, None

    # Neither — global seed data
    return None, None


def _resolve_taxonomy(client, country_obj, tax_slug):
    """
    Resolve a Taxonomy by slug, mirroring scripts/load_07taxonomynode.py:
     1. client-scoped taxonomy (exact country match, then country-less)
     2. global taxonomy     (exact country match, then country-less)
    Returns the Taxonomy object or None.
    """
    if not tax_slug:
        return None
    from mysite.models import Taxonomy
    qs = Taxonomy.objects.filter(slug=tax_slug)
    candidates = []
    if country_obj:
        candidates.append(qs.filter(client=client, country=country_obj))
        candidates.append(qs.filter(client__isnull=True, country=country_obj))
    candidates.append(qs.filter(client=client, country__isnull=True))
    candidates.append(qs.filter(client__isnull=True, country__isnull=True))
    for c in candidates:
        taxonomy = c.first()
        if taxonomy:
            return taxonomy
    return qs.first()


def _process_rows(rows, entry, client, country_obj, fk_cache, job):
    """
    Process CSV rows and return (created, updated, skipped, errors).
    Uses update_or_create() for idempotent upserts.
    """
    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []
    seen = set()

    # Dynamic model import
    from django.apps import apps
    model_label = entry["model_label"]
    # Registry stores dotted module paths like "mysite.models.TaxonomyNode"
    # or "mysite.models.demand.hierarchy.PlanningLocation"; the model name is
    # always the last segment and all master-data models live in the 'mysite'
    # app, so resolve against that app label rather than the module.
    parts = model_label.split(".")
    model_class = apps.get_model("mysite", parts[-1])

    valid_field_names = {f.name for f in model_class._meta.get_fields()}

    unique_fields = entry["unique_fields"]
    hierarchical = entry.get("hierarchical", False)
    parent_field = entry.get("parent_field")
    country_scoped = entry.get("country_scoped", False)

    # Blank client_code in the CSV means "global" (client=None) — but only for
    # models whose client FK is nullable (e.g. TaxonomyNode). Demand-hierarchy
    # models require a client, so their rows keep the upload-job client.
    client_is_nullable = (
        "client" in unique_fields
        and model_class._meta.get_field("client").null
    )

    # Pre-fetch Country objects for all country_code values in the CSV
    country_cache = _build_country_cache(rows) if country_scoped else {}

    # For hierarchical data: multi-pass processing
    pending_rows = list(rows)
    pass_num = 1
    max_passes = 50  # safety limit

    # Build cache for hierarchical lookups (parent field).
    # Keys mirror the load scripts: taxonomy → (client_or_none, taxonomy_slug, slug)
    # demand     → (client_code, code)
    obj_cache = {}

    def _job_client(row):
        """Client a row is stored under: the upload-job client by default, or
        None (global) when the CSV client_code is blank and the model allows it."""
        if not _clean(row.get("client_code")) and client_is_nullable:
            return None
        return client

    def _cache_key(row, code_value):
        # Use the same per-row client that the row is stored under so parent
        # lookups match what was upserted.
        jc = _job_client(row)
        cid = jc.client_code if jc else None
        tax_slug = _clean(row.get("taxonomy_slug"), lower=True)
        if tax_slug:
            return (cid, tax_slug, _clean(code_value, lower=True))
        return (cid, _clean(code_value, lower=True))

    def _obj_cache_key(obj):
        cid = obj.client.client_code if obj.client else None
        if hasattr(obj, "taxonomy") and obj.taxonomy_id is not None:
            return (cid, obj.taxonomy.slug, obj.slug)
        if hasattr(obj, "code"):
            return (cid, obj.code)
        return (cid, obj.slug)

    if hierarchical and parent_field:
        code_field = "slug" if "slug" in rows[0] else "code"
        # Seed the cache with existing DB rows so re-uploads (and parents that
        # already exist) resolve without an error, mirroring the load scripts'
        # node_cache prefetch.
        codes = {
            _clean(r.get(code_field), lower=True)
            for r in rows if r.get(code_field)
        }
        if codes:
            seed_qs = model_class.objects.all()
            if hasattr(model_class, "client_id"):
                seed_qs = seed_qs.filter(
                    models.Q(client=client) | models.Q(client__isnull=True)
                )
            seed_qs = seed_qs.filter(**{f"{code_field}__in": codes}).select_related("client", "taxonomy")
            for obj in seed_qs:
                obj_cache[_obj_cache_key(obj)] = obj

    while pending_rows and pass_num <= max_passes:
        next_pending = []
        progress_made = False

        for row_num_offset, row in enumerate(pending_rows):
            row_num = row_num_offset + 1  # approximate row number

            try:
                # Build the lookup kwargs for update_or_create
                lookup_kwargs = {}
                defaults = {}

                for field in unique_fields:
                    if field == "client":
                        lookup_kwargs["client"] = _job_client(row)
                    elif field == "country":
                        # Handled below in the country_scoped block
                        pass
                    elif field == "taxonomy":
                        # Resolve by slug with client/global fallback (load script behaviour)
                        tax_slug = _clean(row.get("taxonomy_slug"))
                        taxonomy = _resolve_taxonomy(_job_client(row), country_obj, tax_slug)
                        if taxonomy:
                            lookup_kwargs["taxonomy"] = taxonomy
                        elif tax_slug:
                            errors.append(f"Row ~{row_num}: taxonomy '{tax_slug}' not found")
                            skipped_count += 1
                            continue
                        else:
                            errors.append(f"Row ~{row_num}: missing taxonomy_slug")
                            skipped_count += 1
                            continue
                    elif field in ("planning_location", "distribution_channel",
                                   "planning_customer", "sales_node", "item",
                                   "scheme", "version", "global_item"):
                        # FK fields — resolve from cache
                        csv_col = f"{field}_code" if field != "item" else "item_code"
                        if field == "item":
                            csv_col = "item_code"
                        elif field == "scheme":
                            continue  # schemes are not resolved from CSV
                        elif field == "version":
                            continue  # versions are not resolved from CSV
                        elif field == "global_item":
                            csv_col = "global_item_code"
                        else:
                            csv_col = f"{field}_code"

                        val = _clean(row.get(csv_col))
                        if not val and field in ("planning_customer", "distribution_channel",
                                                   "sales_node", "planning_location"):
                            # These can be nullable
                            continue
                        # Use FK cache
                        cached = _resolve_fk(model_label, field, val, fk_cache)
                        if cached:
                            lookup_kwargs[field] = cached
                        elif val:
                            errors.append(f"Row ~{row_num}: FK {field}='{val}' not found")
                            skipped_count += 1
                            continue
                    elif field == "old_item":
                        val = _clean(row.get("old_item_id"))
                        cached = _resolve_fk(model_label, "old_item", val, fk_cache)
                        if cached:
                            lookup_kwargs["old_item"] = cached
                        else:
                            errors.append(f"Row ~{row_num}: old_item '{val}' not found")
                            skipped_count += 1
                            continue
                    elif field == "new_item":
                        val = _clean(row.get("new_item_id"))
                        cached = _resolve_fk(model_label, "new_item", val, fk_cache)
                        if cached:
                            lookup_kwargs["new_item"] = cached
                        else:
                            errors.append(f"Row ~{row_num}: new_item '{val}' not found")
                            skipped_count += 1
                            continue
                    elif field == "reference_item":
                        val = _clean(row.get("reference_item_id"))
                        cached = _resolve_fk(model_label, "reference_item", val, fk_cache)
                        if cached:
                            lookup_kwargs["reference_item"] = cached
                        else:
                            errors.append(f"Row ~{row_num}: reference_item '{val}' not found")
                            skipped_count += 1
                            continue
                    elif field == "node":
                        # TaxonomyNode FK: resolve via (taxonomy_slug, node_slug)
                        tax_slug = _clean(row.get("taxonomy_slug"))
                        node_slug = _clean(row.get("node_slug"))
                        node_client_code = _clean(row.get("node_client_code"))
                        if tax_slug and node_slug:
                            from mysite.models import TaxonomyNode
                            node_qs = TaxonomyNode.objects.filter(
                                taxonomy__slug=tax_slug, slug=node_slug
                            )
                            if node_client_code:
                                node_qs = node_qs.filter(client__client_code=node_client_code)
                            node_obj = node_qs.first()
                            if node_obj:
                                lookup_kwargs["node"] = node_obj
                            else:
                                errors.append(f"Row ~{row_num}: node '{tax_slug}/{node_slug}' not found")
                                skipped_count += 1
                                continue
                        else:
                            errors.append(f"Row ~{row_num}: missing taxonomy_slug or node_slug")
                            skipped_count += 1
                            continue
                    elif field == "attribute_type":
                        # AttributeType is a STANDALONE master: it has no node.
                        # Resolve by slug, preferring an explicit
                        # attribute_client_code, else the row's own client,
                        # else global-or-that-client.
                        from mysite.models import AttributeType
                        type_slug = _clean(row.get("attribute_slug")) or _clean(row.get("type_slug"))
                        attr_client_code = _clean(row.get("attribute_client_code"))
                        row_client_code = _clean(row.get("client_code"))
                        if type_slug:
                            attr_qs = AttributeType.objects.filter(slug=type_slug)
                            if attr_client_code:
                                attr_qs = attr_qs.filter(client__client_code=attr_client_code)
                            elif row_client_code:
                                attr_qs = attr_qs.filter(
                                    models.Q(client__isnull=True)
                                    | models.Q(client__client_code=row_client_code)
                                )
                            attr_obj = attr_qs.first()
                            if attr_obj:
                                lookup_kwargs["attribute_type"] = attr_obj
                            else:
                                errors.append(f"Row ~{row_num}: attribute_type '{type_slug}' not found")
                                skipped_count += 1
                                continue
                        else:
                            errors.append(f"Row ~{row_num}: missing attribute_slug")
                            skipped_count += 1
                            continue
                    elif field == "node_attribute_type":
                        # NodeAttributeType is the (node, type, client) join row.
                        # Resolved for 08C availability rows.
                        tax_slug = _clean(row.get("taxonomy_slug"))
                        node_slug = _clean(row.get("node_slug"))
                        type_slug = _clean(row.get("attribute_slug"))
                        if tax_slug and node_slug and type_slug:
                            from mysite.models import NodeAttributeType
                            nat_qs = NodeAttributeType.objects.filter(
                                node__taxonomy__slug=tax_slug,
                                node__slug=node_slug,
                                attribute_type__slug=type_slug,
                            )
                            row_client_code = _clean(row.get("client_code"))
                            if row_client_code:
                                nat_qs = nat_qs.filter(
                                    models.Q(client__isnull=True)
                                    | models.Q(client__client_code=row_client_code)
                                )
                            nat_obj = nat_qs.first()
                            if nat_obj:
                                lookup_kwargs["node_attribute_type"] = nat_obj
                            else:
                                errors.append(
                                    f"Row ~{row_num}: node_attribute_type "
                                    f"'{tax_slug}/{node_slug}/{type_slug}' not found"
                                )
                                skipped_count += 1
                                continue
                        else:
                            errors.append(
                                f"Row ~{row_num}: missing taxonomy_slug, node_slug, "
                                f"or attribute_slug for node_attribute_type"
                            )
                            skipped_count += 1
                            continue
                    elif field == "value":
                        # AttributeValue pool lookup, same scope rules as above.
                        from mysite.models import AttributeValue
                        value_slug = _clean(row.get("value_slug")) or _clean(row.get("predefined_value_slug"))
                        val_client_code = _clean(row.get("value_client_code"))
                        row_client_code = _clean(row.get("client_code"))
                        if value_slug:
                            val_qs = AttributeValue.objects.filter(slug=value_slug)
                            if val_client_code:
                                val_qs = val_qs.filter(client__client_code=val_client_code)
                            elif row_client_code:
                                val_qs = val_qs.filter(
                                    models.Q(client__isnull=True)
                                    | models.Q(client__client_code=row_client_code)
                                )
                            val_obj = val_qs.first()
                            if val_obj:
                                lookup_kwargs["value"] = val_obj
                            else:
                                errors.append(f"Row ~{row_num}: value '{value_slug}' not found")
                                skipped_count += 1
                                continue
                        else:
                            errors.append(f"Row ~{row_num}: missing value_slug")
                            skipped_count += 1
                            continue
                    elif field == "item":
                        val = _clean(row.get("item_code"))
                        cached = _resolve_fk(model_label, "item", val, fk_cache)
                        if cached:
                            lookup_kwargs["item"] = cached
                        else:
                            errors.append(f"Row ~{row_num}: item '{val}' not found")
                            skipped_count += 1
                            continue
                    elif field == "global_item":
                        val = _clean(row.get("global_item_code"))
                        cached = _resolve_fk(model_label, "global_item", val, fk_cache)
                        if cached:
                            lookup_kwargs["global_item"] = cached
                        else:
                            errors.append(f"Row ~{row_num}: global_item '{val}' not found")
                            skipped_count += 1
                            continue
                    else:
                        # Simple field (code, slug, etc.)
                        val = _clean(row.get(field))
                        if val:
                            lookup_kwargs[field] = val

                # Resolve country for country-scoped models (cross-check CSV vs form)
                if country_scoped:
                    resolved_country, country_err = _resolve_country_from_row(
                        row, country_obj, country_cache, country_scoped,
                    )
                    if country_err:
                        errors.append(f"Row ~{row_num}: {country_err}")
                        skipped_count += 1
                        continue
                    lookup_kwargs["country"] = resolved_country

                # Build defaults for non-unique fields
                for col, val in row.items():
                    col_clean = _clean(col).lower()
                    if col_clean and col_clean not in unique_fields and col_clean not in ("parent_slug", "parent_code"):
                        # Skip translated fields (handled separately)
                        if any(col_clean.startswith(f"{tf}_") for tf in entry.get("translated_fields", [])):
                            continue
                        # Skip FK code fields (already resolved)
                        if col_clean.endswith("_code") and col_clean[:-5] in unique_fields:
                            continue
                        if col_clean.endswith("_id") and col_clean[:-3] in unique_fields:
                            continue
                        # Skip parent fields for hierarchical data
                        if col_clean == parent_field:
                            continue
                        # Skip country_code (handled above)
                        if col_clean == "country_code":
                            continue
                        # Skip columns that aren't real model fields (e.g. taxonomy_slug)
                        if col_clean not in valid_field_names:
                            continue

                        # Resolve global_node_id → global_node FK (as load script does)
                        if col_clean == "global_node_id":
                            gn_id = _clean(val)
                            if gn_id:
                                gn_obj = (
                                    TaxonomyNode.objects
                                    .filter(id=gn_id)
                                    .first()
                                )
                                if gn_obj:
                                    defaults["global_node"] = gn_obj
                            continue

                        # Add to defaults
                        val_clean = _clean(val)
                        if val_clean:
                            defaults[col_clean] = _coerce_default(
                                model_class, col_clean, val_clean
                            )

                # Add translated fields
                translated_defaults = _build_translated_defaults(
                    row, entry.get("translated_fields", [])
                )
                defaults.update(translated_defaults)

                # Resolve hierarchical parent from the node cache (multi-pass);
                # if the parent is not in the file yet, defer this row to the
                # next pass instead of erroring out.
                if hierarchical and parent_field:
                    parent_ref = _clean(row.get(parent_field))
                    if parent_ref:
                        parent_obj = obj_cache.get(_cache_key(row, parent_ref))
                        if not parent_obj:
                            next_pending.append(row)
                            continue
                        defaults["parent"] = parent_obj

                if not lookup_kwargs:
                    errors.append(f"Row ~{row_num}: no valid lookup fields found")
                    skipped_count += 1
                    continue

                # Upsert
                obj, created = model_class.objects.update_or_create(
                    **lookup_kwargs,
                    defaults=defaults,
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

                # Update hierarchical cache
                if hierarchical and parent_field:
                    obj_cache[_obj_cache_key(obj)] = obj

                progress_made = True

            except Exception as e:
                errors.append(f"Row ~{row_num}: {str(e)}")
                skipped_count += 1
                continue

        # TaxonomyNode: resolve parents that were deferred while their parent
        # hadn't been upserted yet. Repeat until nothing new resolves.
        if hierarchical and parent_field and next_pending:
            if progress_made:
                progress_made = False
                pending_rows = next_pending
                pass_num += 1
                continue
            # No progress: parents for these rows genuinely can't be resolved
            for row in next_pending:
                parent_ref = _clean(row.get(parent_field))
                slug = row.get("slug") or row.get("code") or ""
                errors.append(
                    f"Row: parent '{parent_ref}' not found for '{slug}'"
                )
                skipped_count += 1
            break
        break

    return created_count, updated_count, skipped_count, errors


@transaction.atomic
def run_import(job_id):
    """
    Main entry point: reads the uploaded CSV and processes it.
    Called by the Celery task.
    """
    from upload_masters.models import MasterUploadJob

    job = MasterUploadJob.objects.get(pk=job_id)
    job.status = "processing"
    job.save(update_fields=["status"])

    try:
        entry = get_registry_entry(job.csv_key)
        if not entry:
            raise ValueError(f"Unknown CSV key: {job.csv_key}")

        client = job.client

        # Resolve country if provided
        country_obj = None
        if job.country_code and client and client.is_country_enabled():
            try:
                country_obj = Country.objects.get(code=job.country_code)
            except Country.DoesNotExist:
                pass

        # Read file — route by extension
        from django.core.files.storage import default_storage
        with default_storage.open(job.file_path, "rb") as f:
            content = f.read()

        file_path_lower = job.file_path.lower()
        if file_path_lower.endswith((".xlsx", ".xls")):
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            headers = [str(c.value or "").strip() for c in next(ws.iter_rows(max_row=1))]
            rows = [
                dict(zip(headers, [str(c.value or "") for c in row]))
                for row in ws.iter_rows(min_row=2)
            ]
            wb.close()
        elif file_path_lower.endswith(".ods"):
            import pandas as pd
            df = pd.read_excel(io.BytesIO(content), engine="odf")
            df = df.fillna("")
            rows = [{k: str(v) for k, v in rec.items()} for rec in df.to_dict("records")]
        else:
            # CSV (default)
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            rows = list(reader)

        if not rows:
            job.status = "done"
            job.error_log = {"message": "CSV file is empty"}
            job.save(update_fields=["status", "error_log"])
            return

        # Build FK caches
        fk_cache = _build_fk_caches(client, entry, rows, {})

        # Process rows
        created, updated, skipped, errors = _process_rows(
            rows, entry, client, country_obj, fk_cache, job
        )

        # Update job
        job.row_count = len(rows)
        job.created_count = created
        job.updated_count = updated
        job.skipped_count = skipped
        job.error_log = {"errors": errors[:100]}  # limit to first 100 errors
        job.status = "done" if not errors else "done"  # partial success is still done
        job.save(update_fields=[
            "row_count", "created_count", "updated_count",
            "skipped_count", "error_log", "status",
        ])

    except Exception as e:
        logger.exception("Import failed for job %s", job_id)
        job.status = "failed"
        job.error_log = {"error": str(e)}
        job.save(update_fields=["status", "error_log"])
