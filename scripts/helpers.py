import json
from decimal import Decimal
from datetime import datetime, date

def clean(value, lower=False):
    value = (value or "").strip()
    return value.lower() if lower else value

def to_int(value):

    value = (value or "").strip()

    if not value:
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def to_bool(value):
    # usage "is_active": to_bool(row.get("is_active")),
    return str(value).strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )

def to_json(value):

    value = (value or "").strip()

    if not value:
        return {}

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {value}")
        return {}

def to_decimal(value):

    value = clean(value)

    if value == "":
        return None

    return Decimal(value)

def to_date(value, fmt="%Y-%m-%d"):
    """
    Convert CSV/string value to Python date object.

    Examples:
        "2026-04-01" -> date(2026, 4, 1)
        ""           -> None
        None         -> None

    Usage:
        period_start = to_date(row.get("period_start"))
    """

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        return datetime.strptime(value, fmt).date()

    except (ValueError, TypeError):
        return None