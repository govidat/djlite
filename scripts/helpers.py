import json
from decimal import Decimal, InvalidOperation
from datetime import datetime, date

def clean(value, lower=False, default=None):

    value = (value or "").strip()

    if not value:
        return default

    if lower:
        value = value.lower()

    return value
"""
def clean(value, lower=False):
    value = (value or "").strip()
    return value.lower() if lower else value
"""
def to_int(value, default=None):

    value = (value or "").strip()

    if not value:
        return default

    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def to_bool(value, default=None):

    value = (value or "").strip().lower()

    if not value:
        return default

    if value in ("1", "true", "yes", "y"):
        return True

    if value in ("0", "false", "no", "n"):
        return False

    return default
"""
def to_bool(value):
    # usage "is_active": to_bool(row.get("is_active")),
    return str(value).strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
    )
"""
def to_json(value, default=None):

    if default is None:
        default = {}

    value = (value or "").strip()

    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default
"""
def to_json(value):

    value = (value or "").strip()

    if not value:
        return {}

    try:
        return json.loads(value)
    except json.JSONDecodeError:
        print(f"Invalid JSON: {value}")
        return {}
"""
def to_decimal(value, default=None):

    value = clean(value)

    if not value:
        return default

    try:
        return Decimal(value)

    except (InvalidOperation, ValueError, TypeError):
        return default
"""    
def to_decimal(value):

    value = clean(value)

    if value == "":
        return None

    return Decimal(value)
"""
def to_date(
    value,
    fmt="%Y-%m-%d",
    default=None,
):
    """
    Convert string to date.

    Examples:
        to_date("2026-04-01")
        to_date("", default=date.today())
    """

    if value is None:
        return default

    value = str(value).strip()

    if not value:
        return default

    try:
        return datetime.strptime(
            value,
            fmt,
        ).date()

    except (ValueError, TypeError):
        return default
"""
def to_date(value, fmt="%Y-%m-%d"):


    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        return datetime.strptime(value, fmt).date()

    except (ValueError, TypeError):
        return None
"""