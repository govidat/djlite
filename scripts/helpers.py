import json
from decimal import Decimal

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