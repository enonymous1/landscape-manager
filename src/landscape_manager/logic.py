"""Pure, testable business logic for landscape-manager.

Nothing in this module touches Flask, the database, or the filesystem,
so every rule here is covered by plain unit tests.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta


def to_cents(amount: str | float) -> int:
    """Convert a dollar amount (``"45.50"``, ``45.5``, ``45``) to integer cents."""
    if isinstance(amount, int):
        return amount * 100
    text = str(amount).strip().replace("$", "").replace(",", "")
    if not text:
        return 0
    negative = text.startswith("-")
    text = text.lstrip("-")
    if "." in text:
        dollars, cents = text.split(".", 1)
        cents = (cents + "00")[:2]
    else:
        dollars, cents = text, "00"
    total = int(dollars or 0) * 100 + int(cents or 0)
    return -total if negative else total


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
