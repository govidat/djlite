import sys

from django.db import transaction
from django.db.models import Count, Min
from django.db.models.functions import Lower

from mysite.models import NavItem


def run(client_code=None, dry_run=False):
    qs = NavItem.objects.all()
    if client_code:
        qs = qs.filter(client__client_code=client_code)

    groups = (
        qs.annotate(nk=Lower("name_en"))
        .values("client_id", "nk")
        .annotate(c=Count("id"), first_id=Min("id"))
        .filter(c__gt=1)
    )

    total_kept = 0
    total_deleted = 0

    for group in groups:
        client_id = group["client_id"]
        name = group["nk"]
        keep_id = group["first_id"]

        dupes = list(
            NavItem.objects.filter(
                client_id=client_id,
                name_en__iexact=name,
            )
            .exclude(pk=keep_id)
            .order_by("pk")
        )

        children = NavItem.objects.filter(parent_id__in=[d.pk for d in dupes])
        children.update(parent_id=keep_id)

        for dup in dupes:
            label = (
                f"{dup.client.client_code} / {dup.name_en} "
                f"(pk={dup.pk}, kept pk={keep_id})"
            )

            if dry_run:
                print(f"[dry-run] would delete NavItem: {label}")
            else:
                dup.delete()
                print(f"deleted NavItem: {label}")

            total_deleted += 1

        total_kept += 1

    print(
        f"done: {total_kept} row(s) kept, "
        f"{total_deleted} duplicate row(s) deleted"
    )


@transaction.atomic
def main(*args):
    args = [a.lower() for a in args]

    if "dryrun" in args:
        args.remove("dryrun")
        dry_run = True
    else:
        dry_run = False

    client_code = args[0] if args else None

    run(client_code=client_code, dry_run=dry_run)

    if dry_run:
        print("dry-run complete -> rollback")
        transaction.set_rollback(True)


if __name__ == "__main__":
    main(*sys.argv[1:])