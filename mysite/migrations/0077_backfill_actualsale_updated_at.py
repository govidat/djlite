# Backfill ActualSale.updated_at for rows imported before the column existed.
# Use the import batch's upload time when known; otherwise fall back to now.
from django.db import migrations


def backfill_actualsale_updated_at(apps, schema_editor):
    from django.utils import timezone
    ActualSale = apps.get_model('mysite', 'ActualSale')

    now = timezone.now()

    # 1. Rows tied to an import batch → stamp with the batch upload time.
    batch_rows = list(
        ActualSale.objects
        .filter(updated_at__isnull=True, import_batch__isnull=False)
        .select_related('import_batch')
        .only('pk', 'import_batch')
    )
    for chunk_start in range(0, len(batch_rows), 500):
        chunk = batch_rows[chunk_start:chunk_start + 500]
        for row in chunk:
            row.updated_at = row.import_batch.uploaded_at or now
        ActualSale.objects.bulk_update(chunk, ['updated_at'], batch_size=500)

    # 2. Any remaining nulls (no batch) → stamp with now.
    ActualSale.objects.filter(updated_at__isnull=True).update(updated_at=now)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0076_actualsale_updated_at_forecastaccuracy_actual_value_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_actualsale_updated_at, noop),
    ]
