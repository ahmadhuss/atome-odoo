"""Input validation. Mirrors the zod-style behaviour of the Atome API: every problem is collected and
returned together as ``{"field.path": ["message", ...]}`` inside an HTTP 422 response."""

import math
import re
from decimal import Decimal, InvalidOperation

from .envelope import ValidationFailed

REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,59}$")
DOOR_CATEGORIES = ("FIRE_RATED", "SMOKE_RATED", "STANDARD", "OTHER")
MAX_LINES = 200
MAX_QTY = 10_000
MAX_PRICE = Decimal("10000000")
MAX_ID = 2**31 - 1


class Errors(dict):
    """{field path: [messages]}"""

    def add(self, path, message):
        self.setdefault(path, []).append(message)


def parse_string(value, path, errors, *, required=False, max_len=None, pattern=None, pattern_message=None):
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            errors.add(path, "Required")
        return None
    if not isinstance(value, str):
        errors.add(path, "Must be text")
        return None
    value = value.strip()
    if max_len and len(value) > max_len:
        errors.add(path, f"Must be at most {max_len} characters")
        return None
    if pattern and not pattern.match(value):
        errors.add(path, pattern_message or "Invalid format")
        return None
    return value


def parse_int(value, path, errors, *, minimum, maximum, required=True):
    if value is None or value == "":
        if required:
            errors.add(path, "Required")
        return None
    if isinstance(value, bool):
        errors.add(path, "Must be a whole number")
        return None
    number = None
    if isinstance(value, int):
        number = value
    elif isinstance(value, float) and value.is_integer():
        number = int(value)
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        number = int(value.strip())
    if number is None:
        errors.add(path, "Must be a whole number")
        return None
    if number < minimum:
        errors.add(path, f"Must be at least {minimum}")
        return None
    if number > maximum:
        errors.add(path, f"Must be at most {maximum}")
        return None
    return number


def parse_money(value, path, errors, *, required=True):
    """Accepts a number or numeric string; at most 2 decimals; 0 <= value <= MAX_PRICE."""
    if value is None or value == "":
        if required:
            errors.add(path, "Required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        errors.add(path, "Must be an amount, e.g. 125.50")
        return None
    try:
        amount = Decimal(str(value).strip())
    except InvalidOperation:
        errors.add(path, "Must be an amount, e.g. 125.50")
        return None
    if not amount.is_finite() or (isinstance(value, float) and not math.isfinite(value)):
        errors.add(path, "Must be an amount, e.g. 125.50")
        return None
    if amount < 0:
        errors.add(path, "Must not be negative")
        return None
    if amount > MAX_PRICE:
        errors.add(path, "Amount is too large")
        return None
    if amount != amount.quantize(Decimal("0.01")):
        errors.add(path, "Use at most 2 decimal places")
        return None
    return amount


def parse_quotation_payload(body):
    """Validates the body of ``POST /quotations``. Raises ValidationFailed listing every problem."""
    errors = Errors()

    reference = parse_string(
        body.get("atome_reference"),
        "atome_reference",
        errors,
        required=True,
        pattern=REFERENCE_RE,
        pattern_message="Use 3-60 letters, numbers, '.', '_' or '-' (start with a letter or number)",
    )

    customer_raw = body.get("customer")
    customer_name = None
    customer_partner_id = None
    if not isinstance(customer_raw, dict):
        errors.add("customer", "Required: an object with a name")
    else:
        customer_name = parse_string(customer_raw.get("name"), "customer.name", errors, required=True, max_len=120)
        customer_partner_id = parse_int(
            customer_raw.get("partner_id"), "customer.partner_id", errors, minimum=1, maximum=MAX_ID, required=False
        )

    create_customer = body.get("create_customer_if_missing", False)
    if not isinstance(create_customer, bool):
        errors.add("create_customer_if_missing", "Must be true or false")
        create_customer = False

    lines = []
    lines_raw = body.get("lines")
    if not isinstance(lines_raw, list) or not lines_raw:
        errors.add("lines", "Required: at least one line")
    elif len(lines_raw) > MAX_LINES:
        errors.add("lines", f"Must have at most {MAX_LINES} lines")
    else:
        for i, line in enumerate(lines_raw):
            prefix = f"lines.{i}"
            if not isinstance(line, dict):
                errors.add(prefix, "Must be an object")
                continue
            category = line.get("door_category")
            if category is not None and category not in DOOR_CATEGORIES:
                errors.add(f"{prefix}.door_category", f"Must be one of {', '.join(DOOR_CATEGORIES)}")
                category = None
            product_id = parse_int(line.get("product_id"), f"{prefix}.product_id", errors, minimum=1, maximum=MAX_ID, required=False)
            if line.get("door_category") is None and product_id is None and f"{prefix}.product_id" not in errors:
                errors.add(f"{prefix}.door_category", "Provide door_category or product_id")
            lines.append(
                {
                    "index": i,
                    "door_category": category,
                    "product_id": product_id,
                    "description": parse_string(line.get("description"), f"{prefix}.description", errors, max_len=500),
                    "qty": parse_int(line.get("qty"), f"{prefix}.qty", errors, minimum=1, maximum=MAX_QTY),
                    "unit_price": parse_money(line.get("unit_price"), f"{prefix}.unit_price", errors),
                }
            )

    if errors:
        raise ValidationFailed(dict(errors))

    return {
        "reference": reference,
        "customer_name": customer_name,
        "customer_partner_id": customer_partner_id,
        "create_customer": create_customer,
        "lines": lines,
    }


def parse_page_params(args):
    """``limit`` (1-100, default 20) and ``cursor`` (an id) for cursor pagination."""
    errors = Errors()
    limit = parse_int(args.get("limit"), "limit", errors, minimum=1, maximum=100, required=False) or 20
    cursor = parse_int(args.get("cursor"), "cursor", errors, minimum=1, maximum=MAX_ID, required=False)
    if errors:
        raise ValidationFailed(dict(errors))
    return limit, cursor
