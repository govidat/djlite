"""

3. Add to the indexing pattern kept in migration
# 1. Generate the migration normally
python manage.py makemigrations

# 2. Open the generated file and add the two functions
#    above the Migration class, then add RunPython at the
#    end of operations[]

# These functions live here — not imported from anywhere
def add_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    indexes = [
        # Item base table - REPLACE # in the beginning and # at the end of each line with ". So the line should read 3doubequote-Create - 3doublequote
        #""CREATE INDEX IF NOT EXISTS salesnode_path_idx ON  (path text_pattern_ops)#"",
    ]
    for sql in indexes:
        schema_editor.execute(sql)


def remove_postgres_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    drops = [
        'DROP INDEX IF EXISTS salesnode_path_idx',   

        # ... rest of drops
    ]
    for sql in drops:
        schema_editor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('mysite', '0001_initial'),
    ]

    operations = [
        # ... all auto-generated model operations first ...

        migrations.RunPython(
            add_postgres_indexes,      # ← runs on: python manage.py migrate (forward)
            remove_postgres_indexes,   # ← runs on: python manage.py migrate <app> <prev> (reverse)

        ),
    ]

# 3. Verify it runs cleanly
python manage.py migrate

# 4. Confirm on PostgreSQL (production)
#python manage.py dbshell
# slash d mysite_item   # should show the GIN index

5. Add the new sub model to signals.py, translation.py, admin
"""
"""
mysite/models/demand/forecast.py

Populated in Sprint 3B.1:
  ForecastVersion, ForecastLine, ForecastAggregate,
  ForecastOverride, OverrideSplitWeight, ForecastAccuracy
"""
# Models will be added in Sprint 3B.1.