import csv
from pathlib import Path

from django.db import transaction
from django.conf import settings

from mysite.models import (
    Client,
    PlanningCustomer,
    SalesNode,
    CustomerSalesAssignment,
)

from scripts.helpers import (
    clean,
    to_date,
)

# =========================================================
# CSV FORMAT
# =========================================================
#
# valid_from,valid_to,planning_customer_code,sales_node_code,client_id
# 2026-05-24,2027-05-31,tvsmountroad,rmchennai,bahushira
# 2027-06-01,,tvsmountroad,rmcoimbatore,bahushira
#
# valid_to can be blank for active assignment
#

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def load_val01(
    dry_run=False,
    verbose=False,
):

    file_path = DATA_DIR / "33customersalesassignment.csv"

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

    client_ids = {
        clean(row.get("client_id"), lower=True)
        for row in rows
        if clean(row.get("client_id"))
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

    # =========================================================
    # PREFETCH CLIENTS
    # =========================================================

    clients = {
        c.client_id: c
        for c in Client.objects.filter(
            client_id__in=client_ids
        )
    }

    # =========================================================
    # PREFETCH PLANNING CUSTOMERS
    # key = (client_id, code)
    # =========================================================

    planning_customers = {}

    for obj in (
        PlanningCustomer.objects
        .filter(
            code__in=planning_customer_codes,
            client__client_id__in=client_ids,
        )
        .select_related("client")
    ):

        key = (
            obj.client.client_id,
            clean(obj.code, lower=True),
        )

        planning_customers[key] = obj

    # =========================================================
    # PREFETCH SALES NODES
    # key = (client_id, code)
    # =========================================================

    sales_nodes = {}

    for obj in (
        SalesNode.objects
        .filter(
            code__in=sales_node_codes,
            client__client_id__in=client_ids,
        )
        .select_related("client")
    ):

        key = (
            obj.client.client_id,
            clean(obj.code, lower=True),
        )

        sales_nodes[key] = obj

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

        client_id = clean(
            row.get("client_id"),
            lower=True,
        )

        planning_customer_code = clean(
            row.get("planning_customer_code"),
            lower=True,
        )

        sales_node_code = clean(
            row.get("sales_node_code"),
            lower=True,
        )

        valid_from = to_date(
            row.get("valid_from")
        )

        valid_to = to_date(
            row.get("valid_to")
        )

        # =====================================================
        # VALIDATIONS
        # =====================================================

        if (
            not client_id or
            not planning_customer_code or
            not sales_node_code or
            not valid_from
        ):

            print(
                "Skipping row with missing required fields"
            )

            skipped_count += 1
            continue

        # prevent duplicate rows inside CSV

        row_key = (
            client_id,
            planning_customer_code,
            sales_node_code,
            str(valid_from),
        )

        if row_key in seen:

            print(
                f"Duplicate CSV row: {row_key}"
            )

            skipped_count += 1
            continue

        seen.add(row_key)

        # =====================================================
        # CLIENT
        # =====================================================

        client = clients.get(client_id)

        if not client:

            print(
                f"Missing client: {client_id}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # PLANNING CUSTOMER
        # =====================================================

        planning_customer = planning_customers.get(
            (
                client_id,
                planning_customer_code,
            )
        )

        if not planning_customer:

            print(
                f"Missing PlanningCustomer: "
                f"{client_id} / {planning_customer_code}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # SALES NODE
        # =====================================================

        sales_node = sales_nodes.get(
            (
                client_id,
                sales_node_code,
            )
        )

        if not sales_node:

            print(
                f"Missing SalesNode: "
                f"{client_id} / {sales_node_code}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # DATE VALIDATION
        # =====================================================

        if valid_to and valid_to < valid_from:

            print(
                f"Invalid date range: "
                f"{planning_customer_code} -> "
                f"{sales_node_code}"
            )

            skipped_count += 1
            continue

        # =====================================================
        # DEFAULTS
        # =====================================================

        defaults = {

            "valid_to": valid_to,
        }

        # =====================================================
        # DRY RUN
        # =====================================================

        if dry_run:

            print(
                f"[DRY RUN] "
                f"{client_id} / "
                f"{planning_customer_code} -> "
                f"{sales_node_code} "
                f"({valid_from} - {valid_to or 'present'})"
            )

            if verbose:
                print(defaults)

            continue

        # =====================================================
        # UPSERT
        # =====================================================

        obj, created = (
            CustomerSalesAssignment.objects
            .update_or_create(

                client=client,
                planning_customer=planning_customer,
                sales_node=sales_node,
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
                f"{'Created' if created else 'Updated'} "
                f"CustomerSalesAssignment: "
                f"{planning_customer_code} -> "
                f"{sales_node_code}"
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

        print(
            f"(created={created_count}, "
            f"updated={updated_count}, "
            f"skipped={skipped_count})"
        )


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
python manage.py runscript load_33customersalesassignment

Dry Run:
python manage.py runscript load_33customersalesassignment --script-args dryrun

Dry Run + Verbose:
python manage.py runscript load_33customersalesassignment --script-args dryrun verbose
"""