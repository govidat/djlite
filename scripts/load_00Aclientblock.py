import csv
from pathlib import Path

from django.db import transaction

from mysite.models import (
    Client,
    ClientBlock,
)

from scripts.helpers import (
    clean,
    to_bool,
    to_datetime,
)


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


# id,from_date,to_date,remarks,is_active,created_at,client_code


# ═══════════════════════════════════════════════════════
# Load ClientBlock
# ═══════════════════════════════════════════════════════

def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = data_dir / "00Aclientblock.csv"

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        rows = list(csv.DictReader(f))

    # ── Collect client codes ─────────────────────────────

    client_codes = {
        clean(r.get("client_code"), lower=True)
        for r in rows
        if clean(r.get("client_code"))
    }

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    # ── Counters ─────────────────────────────────────────

    created_count = 0
    updated_count = 0
    skipped_count = 0

    # ── Load ─────────────────────────────────────────────

    for row in rows:

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        # ── resolve client (blank = all clients) ─────────

        client = None

        if client_code:

            client = clients.get(client_code)

            if not client:

                print(f"Missing client: {client_code}")
                skipped_count += 1
                continue

        from_date = to_datetime(row.get("from_date"))
        to_date = to_datetime(row.get("to_date"))

        if not from_date or not to_date:

            print("Skipping row with empty from_date/to_date")
            skipped_count += 1
            continue

        defaults = {
            "client": client,
            "from_date": from_date,
            "to_date": to_date,
            "remarks": clean(row.get("remarks")) or "",
            "is_active": to_bool(row.get("is_active"), default=True),
        }

        row_id = clean(row.get("id"))

        # ── DRY RUN ──────────────────────────────────────

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code or 'GLOBAL'} / "
                f"{from_date} -> {to_date}"
            )

            if verbose:
                print(defaults)

            continue

        # ── SAVE ─────────────────────────────────────────

        if row_id:

            obj, created = ClientBlock.objects.update_or_create(
                pk=int(row_id),
                defaults=defaults,
            )

        else:

            obj, created = ClientBlock.objects.update_or_create(
                client=client,
                from_date=from_date,
                to_date=to_date,
                defaults=defaults,
            )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"ClientBlock: {obj}"
            )

    # ── Summary ──────────────────────────────────────────

    print()

    print(
        f"{'Dry-Run Completed -> Rollback' if dry_run else 'Loading Completed'}"
    )

    print(
        f"(created={created_count}, "
        f"updated={updated_count}, "
        f"skipped={skipped_count})"
    )


# ═══════════════════════════════════════════════════════
# RUN
# ═══════════════════════════════════════════════════════

@transaction.atomic
def run(*args, data_dir=None):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
        data_dir=data_dir,
    )

    if DRY_RUN:

        print()
        print("DRY RUN COMPLETE → rollback")

        transaction.set_rollback(True)

    print("Done")


"""
Normal Run
----------
python manage.py runscript load_00aclientblock

Dry Run
--------
python manage.py runscript load_00aclientblock --script-args dryrun

Dry Run + Verbose
-----------------
python manage.py runscript load_00aclientblock --script-args dryrun verbose
"""
