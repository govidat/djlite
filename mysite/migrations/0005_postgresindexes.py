from django.db import migrations

INDEXES = [
    # mysite_item
    "CREATE INDEX IF NOT EXISTS item_attributes_gin_idx ON mysite_item USING GIN (attributes jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS item_client_domain_status_idx ON mysite_item (client_id, domain, status)",
    'CREATE INDEX IF NOT EXISTS item_client_status_order_idx ON mysite_item (client_id, status, "order")',
    "CREATE INDEX IF NOT EXISTS item_global_item_idx ON mysite_item (global_item_id, client_id)",
    "CREATE INDEX IF NOT EXISTS item_gtin_idx ON mysite_item (gtin) WHERE gtin != ''",
    # mysite_globalitem
    "CREATE INDEX IF NOT EXISTS globalitem_gtin_idx ON mysite_globalitem (gtin) WHERE gtin != ''",
    "CREATE INDEX IF NOT EXISTS globalitem_gpc_idx ON mysite_globalitem (gpc_brick_code) WHERE gpc_brick_code != ''",
    "CREATE INDEX IF NOT EXISTS globalitem_attributes_gin_idx ON mysite_globalitem USING GIN (attributes jsonb_path_ops)",
    # taxonomy
    "CREATE INDEX IF NOT EXISTS taxonomy_node_path_idx ON mysite_taxonomynode USING BTREE (taxonomy_id, path text_pattern_ops)",
    "CREATE INDEX IF NOT EXISTS taxonomynode_gpc_idx ON mysite_taxonomynode (gpc_code) WHERE gpc_code != ''",
    # product / song / document / service items
    "CREATE INDEX IF NOT EXISTS productitem_attributes_gin_idx ON mysite_productitem USING GIN (attributes jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS productitem_sku_idx ON mysite_productitem (sku) WHERE sku != ''",
    "CREATE INDEX IF NOT EXISTS productitem_price_idx ON mysite_productitem (price) WHERE price IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS songitem_attributes_gin_idx ON mysite_songitem USING GIN (attributes jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS songitem_artist_idx ON mysite_songitem (artist) WHERE artist != ''",
    "CREATE INDEX IF NOT EXISTS songitem_album_idx ON mysite_songitem (album) WHERE album != ''",
    "CREATE INDEX IF NOT EXISTS documentitem_attributes_gin_idx ON mysite_documentitem USING GIN (attributes jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS documentitem_format_idx ON mysite_documentitem (format) WHERE format != ''",
    "CREATE INDEX IF NOT EXISTS serviceitem_attributes_gin_idx ON mysite_serviceitem USING GIN (attributes jsonb_path_ops)",
    "CREATE INDEX IF NOT EXISTS serviceitem_fulfillment_type_idx ON mysite_serviceitem (fulfillment_type) WHERE fulfillment_type != ''",
    # attribute values
    "CREATE INDEX IF NOT EXISTS itemattributevalue_lookup_idx ON mysite_itemattributevalue (attribute_type_id, predefined_value_id)",
    "CREATE INDEX IF NOT EXISTS globalitemattributevalue_lookup_idx ON mysite_globalitemattributevalue (attribute_type_id, predefined_value_id)",
    # hierarchies (text_pattern_ops for LIKE 'prefix%')
    "CREATE INDEX IF NOT EXISTS clientlocation_path_idx ON mysite_clientlocation (path text_pattern_ops)",
    "CREATE INDEX IF NOT EXISTS planloc_path_tpo_idx ON mysite_planninglocation (path text_pattern_ops)",
    "CREATE INDEX IF NOT EXISTS plancust_path_tpo_idx ON mysite_planningcustomer (path text_pattern_ops)",
    "CREATE INDEX IF NOT EXISTS salesnode_path_tpo_idx ON mysite_salesnode (path text_pattern_ops)",
    # forecast
    "CREATE INDEX IF NOT EXISTS ix_fcstline_ver ON mysite_forecastline (version_id, period_start)",
    "CREATE INDEX IF NOT EXISTS ix_fcstline_item_period ON mysite_forecastline (version_id, item_id, period_start)",
    "CREATE INDEX IF NOT EXISTS ix_fcstline_loc_period ON mysite_forecastline (version_id, planning_location_id, period_start)",
    "CREATE INDEX IF NOT EXISTS ix_fcstagg_ver_level ON mysite_forecastaggregate (version_id, agg_level, period_start)",
    "CREATE INDEX IF NOT EXISTS ix_fcstacc_ver_period ON mysite_forecastaccuracy (version_id, period_start)",
    # actual sales partial unique indexes: include ONLY if step 1 shows 0063 did not replace them
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_with_customer ON mysite_actualsale (client_id, planning_location_id, item_id, planning_customer_id, period_type, period_start) WHERE planning_customer_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_no_customer ON mysite_actualsale (client_id, planning_location_id, item_id, period_type, period_start) WHERE planning_customer_id IS NULL",
]


def names(sqls):
    out = []
    for s in sqls:
        out.append(s.split(" EXISTS ")[1].split(" ON ")[0].strip())
    return out


class Migration(migrations.Migration):
    dependencies = [("mysite", "0004_seed_countries")]  # or your last seed migration

    operations = [
        migrations.RunSQL(sql=INDEXES, reverse_sql=[f"DROP INDEX IF EXISTS {n}" for n in names(INDEXES)]),
    ]