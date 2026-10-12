import csv
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from mysite.models import (
    Client,
    Item,
    PlanningLocation,
    PlanningCustomer,
    ActualSale,
    ActualSaleImport,
    DistributionChannel
)

from scripts.helpers import (
    clean,
    to_decimal,
    to_date
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

User = get_user_model()


# ============================================================================
# CSV
# ============================================================================

# id,period_type,period_start,qty,revenue,
# client_code,planning_customer_code,
# planning_location_code,item_code


def load_val01(
    dry_run=False,
    verbose=False,
    data_dir=None,
):
    data_dir = Path(data_dir) if data_dir else DATA_DIR

    file_path = data_dir / "34actualsale.csv"

    # =========================================================================
    # READ CSV
    # =========================================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =========================================================================
    # COLLECT IDS
    # =========================================================================

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if row.get("client_code")
    }

    location_codes = {
        clean(row.get("planning_location_code"), lower=True)
        for row in rows
        if row.get("planning_location_code")
    }

    customer_codes = {
        clean(row.get("planning_customer_code"), lower=True)
        for row in rows
        if row.get("planning_customer_code")
    }

    item_codes = {
        clean(row.get("item_code"), lower=True)
        for row in rows
        if row.get("item_code")
    }

    distribution_channel_codes = {
        clean(row.get("distribution_channel_code"), lower=True)
        for row in rows
        if row.get("distribution_channel_code")
    }

    # =========================================================================
    # PREFETCH
    # =========================================================================

    clients = {
        c.client_code: c
        for c in Client.objects.filter(
            client_code__in=client_codes
        )
    }

    planning_locations = {}

    for obj in (
        PlanningLocation.objects
        .filter(code__in=location_codes)
        .select_related("client")
    ):

        key = (
            obj.client.client_code,
            obj.code,
        )

        planning_locations[key] = obj

    planning_customers = {}

    for obj in (
        PlanningCustomer.objects
        .filter(code__in=customer_codes)
        .select_related("client")
    ):

        key = (
            obj.client.client_code,
            obj.code,
        )

        planning_customers[key] = obj

    items = {}

    for obj in (
        Item.objects
        .filter(item_code__in=item_codes)
        .select_related("client")
    ):

        key = (
            obj.client.client_code,
            obj.item_code,
        )

        items[key] = obj

    distribution_channels = {
        c.code: c
        for c in DistributionChannel.objects.filter(
            code__in=distribution_channel_codes
        )
    }

    # =========================================================================
    # CREATE IMPORT BATCH
    # =========================================================================

    first_client_code = clean(
        rows[0].get("client_code"),
        lower=True,
    )

    batch_client = clients.get(first_client_code)

    import_batch = None

    if not dry_run and batch_client:

        import_batch = ActualSaleImport.objects.create(

            client=batch_client,

            uploaded_by=None,

            file_name=file_path.name,

            period_type=clean(
                rows[0].get("period_type")
            ),

            status="processing",
        )

    # =========================================================================
    # PROCESS
    # =========================================================================

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    error_logs = []

    for row in rows:

        # =====================================================================
        # BASIC VALUES
        # =====================================================================

        client_code = clean(
            row.get("client_code"),
            lower=True,
        )

        planning_location_code = clean(
            row.get("planning_location_code"),
            lower=True,
        )

        planning_customer_code = clean(
            row.get("planning_customer_code"),
            lower=True,
        )

        item_code = clean(
            row.get("item_code"),
            lower=True,
        )

        distribution_channel_code = clean(
            row.get("distribution_channel_code"),
            lower=True,
        )        

        period_type = clean(
            row.get("period_type"),
            lower=True,
        )
        period_start = to_date(
            row.get("period_start")
        )
        if not period_start:

            msg = (
                f"Invalid period_start: "
                f"{row.get('period_start')}"
            )

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue        

        # =====================================================================
        # REQUIRED
        # =====================================================================

        if not all([
            client_code,
            planning_location_code,
            item_code,
            period_type,
            period_start,
        ]):

            msg = (
                "Skipping row with missing required fields"
            )

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue

        # =====================================================================
        # DUPLICATE CSV CHECK
        # =====================================================================

        unique_key = (
            client_code,
            planning_location_code,
            planning_customer_code,
            item_code,
            distribution_channel_code,
            period_type,
            period_start,
        )

        if unique_key in seen:

            msg = f"Duplicate CSV row: {unique_key}"

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue

        seen.add(unique_key)

        # =====================================================================
        # CLIENT
        # =====================================================================

        client = clients.get(client_code)

        if not client:

            msg = f"Missing client: {client_code}"

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue

        # =====================================================================
        # LOCATION
        # =====================================================================

        planning_location = planning_locations.get(
            (
                client_code,
                planning_location_code,
            )
        )

        if not planning_location:

            msg = (
                f"Missing planning location: "
                f"{client_code} / "
                f"{planning_location_code}"
            )

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue

        # =====================================================================
        # CUSTOMER
        # =====================================================================

        planning_customer = None

        if planning_customer_code:

            planning_customer = planning_customers.get(
                (
                    client_code,
                    planning_customer_code,
                )
            )

            if not planning_customer:

                msg = (
                    f"Missing planning customer: "
                    f"{client_code} / "
                    f"{planning_customer_code}"
                )

                print(msg)

                error_logs.append(msg)

                skipped_count += 1
                continue

        # =====================================================================
        # DISTRIBUTION_CHANNEL
        # =====================================================================

        distribution_channel = None
        if distribution_channel_code:

            distribution_channel = distribution_channels.get(
                (
                    distribution_channel_code
                )
            )

            if not distribution_channel:

                msg = (
                    f"Missing distribution_channel: "
                    f"{client_code} / "
                    f"{distribution_channel_code}"
                )

                print(msg)

                error_logs.append(msg)

                skipped_count += 1
                continue

        # =====================================================================
        # ITEM
        # =====================================================================

        item = items.get(
            (
                client_code,
                item_code,
            )
        )

        if not item:

            msg = (
                f"Missing item: "
                f"{client_code} / "
                f"{item_code}"
            )

            print(msg)

            error_logs.append(msg)

            skipped_count += 1
            continue

        # =====================================================================
        # DEFAULTS
        # =====================================================================

        defaults = {

            "qty":
                to_decimal(row.get("qty")),

            "revenue":
                to_decimal(row.get("revenue")),

            "import_batch":
                import_batch,
            
        }

        # =====================================================================
        # DRY RUN
        # =====================================================================

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_code} / "
                f"{planning_location_code} / "
                f"{planning_customer_code} / "
                f"{distribution_channel_code} / "
                f"{item_code} / "
                f"{period_type} / "
                f"{period_start}"
            )

            if verbose:
                print(defaults)

            continue

        # =====================================================================
        # UPSERT
        # =====================================================================

        obj, created = (
            ActualSale.objects.update_or_create(

                client=client,

                planning_location=planning_location,

                planning_customer=planning_customer,

                distribution_channel=distribution_channel,

                item=item,

                period_type=period_type,

                period_start=period_start,

                defaults=defaults,
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:

            print(
                f"{'Created' if created else 'Updated'} "
                f"ActualSale: "
                f"{client_code} / "
                f"{planning_location_code} / "
                f"{item_code}"
            )

    # =========================================================================
    # UPDATE IMPORT BATCH
    # =========================================================================

    if not dry_run and import_batch:

        import_batch.row_count = (
            created_count + updated_count
        )

        if error_logs:

            import_batch.status = "failed"

            import_batch.error_log = "\n".join(error_logs)

        else:

            import_batch.status = "done"

        import_batch.save()

    # =========================================================================
    # SUMMARY
    # =========================================================================

    print()

    if dry_run:

        print("Dry-Run Completed -> Rollback")

        transaction.set_rollback(True)

    else:

        print("Loading Completed")

        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )


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

    print("Done")


"""
Normal Run:
python manage.py runscript load_34actualsale

Dry Run:
python manage.py runscript load_34actualsale --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_34actualsale --script-args dryrun verbose
"""