"""Repair legacy QuestionPracticeRecord tables whose migration was already marked applied.

Older project bundles created this table with selected_answer/elapsed_ms/submitted_at.
The current model uses submitted_answer/first_correct_at/updated_at. This migration
renames compatible columns and adds the missing nullable timestamp without dropping data.
"""
from django.db import migrations


def repair_legacy_table(apps, schema_editor):
    connection = schema_editor.connection
    table = 'core_questionpracticerecord'
    with connection.cursor() as cursor:
        tables = connection.introspection.table_names(cursor)
        if table not in tables:
            # A fresh install creates the correct table in migration 0005.
            return
        columns = {col.name for col in connection.introspection.get_table_description(cursor, table)}
    quote = schema_editor.quote_name
    # The included legacy SQLite DB had migration 0005 recorded, but an older table.
    # ALTER TABLE RENAME COLUMN preserves existing rows and their foreign keys.
    for old, new in [('selected_answer', 'submitted_answer'), ('submitted_at', 'updated_at')]:
        if old in columns and new not in columns:
            schema_editor.execute(f'ALTER TABLE {quote(table)} RENAME COLUMN {quote(old)} TO {quote(new)}')
            columns.remove(old)
            columns.add(new)
    if 'first_correct_at' not in columns:
        schema_editor.execute(f'ALTER TABLE {quote(table)} ADD COLUMN {quote("first_correct_at")} datetime NULL')
    # The legacy elapsed_ms column was NOT NULL and has no model default. Leaving it
    # behind would make new ORM inserts fail, so remove it after preserving all modeled
    # values. SQLite >= 3.35 supports DROP COLUMN (the project's Python 3.11 bundle does).
    if 'elapsed_ms' in columns:
        schema_editor.execute(f'ALTER TABLE {quote(table)} DROP COLUMN {quote("elapsed_ms")}')


class Migration(migrations.Migration):
    dependencies = [('core', '0005_questionpracticerecord')]
    operations = [migrations.RunPython(repair_legacy_table, migrations.RunPython.noop)]
