The clean pattern: one dedicated migration file per domain, containing only the Postgres index DDL.
Structure it like this:
mysite/migrations/
    0001_initial.py                        ← all model schema, no Postgres DDL
    0002_postgres_indexes_cms.py           ← Phase 1 indexes only
    0003_postgres_indexes_catalogue.py     ← Phase 2 indexes only
    0004_postgres_indexes_demand.py        ← Phase 3B indexes only

Each Postgres index migration looks like this:
from django.db import migrations

# ── Postgres-only partial/expression indexes ──────────────────────────────────
# Safe to skip on SQLite (dev) — the vendor check handles it.
# To rebuild from scratch: drop DB, migrate, these run automatically in order.

FORWARD = [
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_with_customer
    ON mysite_actualsale (client_id, planning_location_id, item_id,
                          planning_customer_id, period_type, period_start)
    WHERE planning_customer_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_actualsale_no_customer
    ON mysite_actualsale (client_id, planning_location_id, item_id,
                          period_type, period_start)
    WHERE planning_customer_id IS NULL
    """,
]

REVERSE = [
    "DROP INDEX IF EXISTS uq_actualsale_with_customer",
    "DROP INDEX IF EXISTS uq_actualsale_no_customer",
]


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for sql in FORWARD:
        schema_editor.execute(sql)


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    for sql in REVERSE:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0001_initial'),   # adjust to actual preceding migration
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]