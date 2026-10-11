import csv
from pathlib import Path

from django.db import transaction
from django.conf import settings

from mysite.models import Client, DistributionChannel
from mysite.models.demand.hierarchy import PlanningLocation, PlanningCustomer, SalesNode, SalesForecastLink

from scripts.helpers import (
    clean,
    to_date,
)

# =========================================================
# CSV FORMAT
# =========================================================
#
# client_code,planning_location_code,distribution_channel_code,planning_customer_code,sales_node_code,valid_from,valid_to
# autocomp,del-01,,,rm-ntn,2024-01-01,                                    <- shape c, open
# autocomp,del-01,00,,rm-ntn,2024-01-01,                                  <- shape b, open
# autocomp,del-01,00,cust-chn-001,rm-ntn,2024-01-01,2024-12-31            <- shape a, closed (historical)
# autocomp,del-01,00,cust-chn-001,rm-north-2,2025-01-01,                  <- shape a, open (successor row)
#
# distribution_channel_code and planning_customer_code may be blank.
# valid_to may be blank (open/current link).
# valid_from is required.
#

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

import datetime as _dt
_MAX_DATE = _dt.date(9999, 12, 31)   # sentinel for "no valid_to" in overlap comparisons


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "33asalesforecastlink.csv"

    # =========================================================
    # READ CSV
    # =========================================================

    with open(
        file_path,
        newline="",
        encoding="utf-8-sig",
    ) as f:

        reader = csv.DictReader(f)
        rows = list(reader)

    # =========================================================
    # COLLECT IDS
    # =========================================================

    client_codes = {
        clean(row.get("client_code"), lower=True)
        for row in rows
        if clean(row.get("client_code"))
    }

    planning_location_codes = {
        clean(row.get("planning_location_code"), lower=True)
        for row in rows
        if clean(row.get("planning_location_code"))
    }

    planning_customer_codes = {
        clean(row.get("planning_customer_code"), lower=True)
        for row in rows
        if clean(row.get("planning_customer_code"))
    }

    sales_node_codes = {
        clean(row.get("sales_node_code"), lower=True)
        for row in rows
        if clean(row.get("sales_node_code"))
    }

    distribution_channel_codes = {
        clean(row.get("distribution_channel_code"), lower=False)
        for row in rows
        if clean(row.get("distribution_channel_code"))
    }

    # =========================================================
    # PREFETCH
    # =========================================================

    clients = {
        c.client_code: c
        for c in Client.objects.filter(client_code__in=client_codes)
    }

    planning_locations = {}
    for obj in (
        PlanningLocation.objects
        .filter(code__in=planning_location_codes, client__client_code__in=client_codes)
        .select_related("client")
    ):
        key = (obj.client.client_code, clean(obj.code, lower=True))
        planning_locations[key] = obj

    planning_customers = {}
    for obj in (
        PlanningCustomer.objects
        .filter(code__in=planning_customer_codes, client__client_code__in=client_codes)
        .select_related("client")
    ):
        key = (obj.client.client_code, clean(obj.code, lower=True))
        planning_customers[key] = obj

    sales_nodes = {}
    for obj in (
        SalesNode.objects
        .filter(code__in=sales_node_codes, client__client_code__in=client_codes)
        .select_related("client")
    ):
        key = (obj.client.client_code, clean(obj.code, lower=True))
        sales_nodes[key] = obj

    distribution_channels = {
        dc.code: dc
        for dc in DistributionChannel.objects.filter(code__in=distribution_channel_codes)
    }

    # =========================================================
    # PROCESS
    # =========================================================

    created_count = 0
    updated_count = 0
    skipped_count = 0

    seen = set()

    for row in rows:

        # =====================================================
        # BASIC VALUES
        # =====================================================

        client_code = clean(row.get("client_code"), lower=True)
        planning_location_code = clean(row.get("planning_location_code"), lower=True)
        distribution_channel_code = clean(row.get("distribution_channel_code"), lower=False) or None
        planning_customer_code = clean(row.get("planning_customer_code"), lower=True) or None
        sales_node_code = clean(row.get("sales_node_code"), lower=True)
        valid_from = to_date(row.get("valid_from"))
        valid_to = to_date(row.get("valid_to"))

        # =====================================================
        # VALIDATIONS
        # =====================================================

        if not client_code or not planning_location_code or not sales_node_code or not valid_from:
            print("Skipping row with missing required fields (valid_from is mandatory)")
            skipped_count += 1
            continue

        if valid_to and valid_to < valid_from:
            print(
                f"Invalid date range: {planning_location_code} -> {sales_node_code} "
                f"({valid_from} - {valid_to})"
            )
            skipped_count += 1
            continue

        if planning_customer_code and not distribution_channel_code:
            print(
                f"Invalid shape (customer without channel): "
                f"{planning_location_code} / {planning_customer_code}"
            )
            skipped_count += 1
            continue

        # prevent duplicate rows inside CSV — identity now includes valid_from,
        # since the same key can legitimately recur across time as a new row.
        row_key = (
            client_code, planning_location_code, distribution_channel_code,
            planning_customer_code, str(valid_from),
        )
        if row_key in seen:
            print(f"Duplicate CSV row: {row_key}")
            skipped_count += 1
            continue
        seen.add(row_key)

        # =====================================================
        # LOOKUPS
        # =====================================================

        client = clients.get(client_code)
        if not client:
            print(f"Missing client: {client_code}")
            skipped_count += 1
            continue

        planning_location = planning_locations.get((client_code, planning_location_code))
        if not planning_location:
            print(f"Missing PlanningLocation: {client_code} / {planning_location_code}")
            skipped_count += 1
            continue

        if not planning_location.is_leaf:
            print(f"PlanningLocation is not a leaf: {client_code} / {planning_location_code}")
            skipped_count += 1
            continue

        sales_node = sales_nodes.get((client_code, sales_node_code))
        if not sales_node:
            print(f"Missing SalesNode: {client_code} / {sales_node_code}")
            skipped_count += 1
            continue

        if sales_node.children.exists():
            print(f"SalesNode is not a leaf: {client_code} / {sales_node_code}")
            skipped_count += 1
            continue

        distribution_channel = None
        if distribution_channel_code:
            distribution_channel = distribution_channels.get(distribution_channel_code)
            if not distribution_channel:
                print(f"Missing DistributionChannel: {distribution_channel_code}")
                skipped_count += 1
                continue

        planning_customer = None
        if planning_customer_code:
            planning_customer = planning_customers.get((client_code, planning_customer_code))
            if not planning_customer:
                print(f"Missing PlanningCustomer: {client_code} / {planning_customer_code}")
                skipped_count += 1
                continue

        # =====================================================
        # OVERLAP CHECK (in-memory, against already-committed rows;
        # matches the permissive "warn and skip" style used elsewhere in
        # this loader rather than raising — bulk loads trust the source
        # data but flag anything that looks wrong for manual review)
        # =====================================================

        existing_open = SalesForecastLink.objects.filter(
            client=client, planning_location=planning_location,
            distribution_channel=distribution_channel, planning_customer=planning_customer,
        ).exclude(valid_from=valid_from)

        self_to = valid_to or _MAX_DATE
        conflict = False
        for other in existing_open:
            other_to = other.valid_to or _MAX_DATE
            if valid_from <= other_to and other.valid_from <= self_to:
                conflict = True
                break
        if conflict:
            print(
                f"Overlapping date range, skipping: {client_code} / {planning_location_code} "
                f"/ dc={distribution_channel_code or '-'} / cust={planning_customer_code or '-'} "
                f"({valid_from} - {valid_to or 'present'})"
            )
            skipped_count += 1
            continue

        # =====================================================
        # DEFAULTS
        # =====================================================

        defaults = {
            "sales_node": sales_node,
            "valid_to": valid_to,
        }

        # =====================================================
        # DRY RUN
        # =====================================================

        if dry_run:
            shape = 'a' if planning_customer else ('b' if distribution_channel else 'c')
            print(
                f"[DRY RUN] shape={shape} "
                f"{client_code} / {planning_location_code} "
                f"/ dc={distribution_channel_code or '-'} "
                f"/ cust={planning_customer_code or '-'} -> {sales_node_code} "
                f"({valid_from} - {valid_to or 'present'})"
            )
            if verbose:
                print(defaults)
            continue

        # =====================================================
        # UPSERT — key now includes valid_from, since the same
        # location/channel/customer combo can recur across time as
        # distinct historical rows (territory reassignment).
        # =====================================================

        obj, created = (
            SalesForecastLink.objects
            .update_or_create(
                client=client,
                planning_location=planning_location,
                distribution_channel=distribution_channel,
                planning_customer=planning_customer,
                valid_from=valid_from,
                defaults=defaults,
            )
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

        if verbose:
            print(
                f"{'Created' if created else 'Updated'} SalesForecastLink: "
                f"{planning_location_code} -> {sales_node_code}"
            )

    # =========================================================
    # SUMMARY
    # =========================================================

    print()

    if dry_run:
        print("Dry-Run Completed -> Rollback")
        transaction.set_rollback(True)
    else:
        print("Loading Completed")
        print(f"(created={created_count}, updated={updated_count}, skipped={skipped_count})")


@transaction.atomic
def run(*args):

    args = [a.lower() for a in args]

    DRY_RUN = "dryrun" in args
    VERBOSE = "verbose" in args

    print(f"DRY_RUN = {DRY_RUN}")
    print(f"VERBOSE = {VERBOSE}")

    load_val01(
        dry_run=DRY_RUN,
        verbose=VERBOSE,
    )

    print("Done")


"""
Normal Run:
python manage.py runscript load_34salesforecastlink

Dry Run:
python manage.py runscript load_34salesforecastlink --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_34salesforecastlink --script-args dryrun verbose
"""