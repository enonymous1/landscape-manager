"""Pure, testable business logic for landscape-manager.

Nothing in this module touches Flask, the database, or the filesystem,
so every rule here is covered by plain unit tests.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def to_cents(amount: str | float) -> int:
    """Convert a dollar amount (``"45.50"``, ``45.5``, ``45``) to integer cents.

    Money is stored as integer cents, never as a float: binary floats
    cannot represent most decimal prices exactly (``0.1 + 0.2 != 0.3``),
    so float totals drift by cents over many line items. Parsing goes
    through ``Decimal`` and rounds half-up to the nearest cent, so
    ``"45.999"`` becomes 4600, not 4599 as the old string-slicing code
    produced. Malformed input raises ``ValueError`` (callers turn it
    into a flashed form error) instead of crashing with a raw
    ``int()`` error. An empty string is 0, preserving the old
    "blank price" behaviour of the service/item forms.
    """
    if isinstance(amount, bool):
        raise TypeError("Amount must be a number, not a boolean.")
    if isinstance(amount, int):
        return amount * 100
    text = str(amount).strip().replace("$", "").replace(",", "").strip()
    if not text:
        return 0
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError(f"Not a valid dollar amount: {amount!r}.") from None
    if not value.is_finite():
        raise ValueError(f"Not a valid dollar amount: {amount!r}.")
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_money(cents: int) -> str:
    """Format integer cents as ``$1,234.56`` (``-$12.00`` for negatives)."""
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}${value // 100:,}.{value % 100:02d}"


def line_total(quantity: float, unit_price_cents: int) -> int:
    """One line-item total, rounded to the nearest cent."""
    return round(quantity * unit_price_cents)


def document_total(items) -> int:
    """Sum of line totals for items with ``quantity`` and ``unit_price_cents``."""
    return sum(line_total(item["quantity"], item["unit_price_cents"]) for item in items)


def next_recurrence(scheduled: date, recurrence: str) -> date | None:
    """Next occurrence for a recurrence rule, or None for one-off jobs.

    Monthly recurrence clamps to the last day of the next month, so
    January 31 recurs to February 28 (or 29 in a leap year).
    """
    if recurrence == "weekly":
        return scheduled + timedelta(days=7)
    if recurrence == "biweekly":
        return scheduled + timedelta(days=14)
    if recurrence == "monthly":
        year = scheduled.year + (1 if scheduled.month == 12 else 0)
        month = 1 if scheduled.month == 12 else scheduled.month + 1
        day = min(scheduled.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    return None


def is_overdue_job(scheduled: date | None, status: str, today: date) -> bool:
    """A job is overdue when its date has passed and it is not done/cancelled."""
    return scheduled is not None and scheduled < today and status in ("scheduled", "in_progress")


def is_overdue_invoice(due: date | None, status: str, today: date) -> bool:
    """An unpaid invoice is overdue when its due date has passed."""
    return due is not None and due < today and status == "unpaid"


JOB_STATUSES = ("scheduled", "in_progress", "done", "cancelled")
QUOTE_STATUSES = ("draft", "sent", "accepted", "declined")
INVOICE_STATUSES = ("unpaid", "paid", "overdue")
RECURRENCES = ("none", "weekly", "biweekly", "monthly")

#: Business rules that used to be literals buried in routes and the demo
#: seed. They live here, with the other pure rules, so a change is one
#: edit and every caller (app, demo seed, tests) agrees.
#: An invoice created from a quote is due this many days after creation.
INVOICE_DUE_DAYS = 30
#: The dashboard's "upcoming" window, in days.
UPCOMING_DAYS = 7
