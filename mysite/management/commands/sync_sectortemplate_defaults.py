"""
Sync global-default SectorTemplate rows from their filesystem sources.

The catalogue chrome defaults are DB-owned (migration 0083), but the
catalogue_* blobs are copies of files under templates/catalogue/. This
command refreshes the NULL-sector (global default) rows so file edits
reach the rendered pages without hand-pasting HTML in admin.

  python manage.py sync_sectortemplate_defaults            # only diffs
  python manage.py sync_sectortemplate_defaults --dry-run  # show what would change

Rows with a sector_node or ClientTemplate overrides are NEVER touched —
those are intentional customisations.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from mysite.models.client import SectorTemplate

BASE = Path(settings.BASE_DIR) / 'templates' / 'catalogue'

# template_key → filesystem source of the seeded default
SOURCES = {
    'catalogue_filter_sidebar': BASE / 'partials' / 'filter_sidebar.html',
    'catalogue_item_card':      BASE / 'partials' / 'item_card.html',
    'catalogue_item_detail':    BASE / 'partials' / 'item_detail.html',
    'catalogue_items_list':     BASE / 'partials' / 'items_list.html',
    'catalogue_pagination':     BASE / 'partials' / 'pagination.html',
}


def _html_field_names(model):
    names = []
    for f in model._meta.get_fields():
        if hasattr(f, 'column') and (
            f.name == 'htmlblob' or f.name.startswith('htmlblob_')
        ):
            names.append(f.name)
    return names


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report differences without writing',
        )

    def handle(self, *args, **options):
        fields = _html_field_names(SectorTemplate)
        updated, skipped, missing = [], [], []

        for key, src in SOURCES.items():
            if not src.exists():
                missing.append(f'{key} (source file gone: {src})')
                continue
            html = src.read_text(encoding='utf-8')

            row = SectorTemplate.objects.filter(
                sector_node__isnull=True, template_key=key,
            ).first()
            if row is None:
                missing.append(f'{key} (no global default row — run migration 0083)')
                continue

            current = getattr(row, fields[0], '')
            if (current or '') == html:
                skipped.append(key)
                continue

            if not options['dry_run']:
                for name in fields:
                    setattr(row, name, html)
                row.save(update_fields=fields)
            updated.append(key)

        if updated:
            self.stdout.write(f'updated: {", ".join(updated)}')
        if skipped:
            self.stdout.write(f'unchanged: {", ".join(skipped)}')
        for m in missing:
            self.stdout.write(self.style.WARNING(f'missing: {m}'))
        if options['dry_run'] and updated:
            self.stdout.write(self.style.NOTICE('(dry run — nothing written)'))
