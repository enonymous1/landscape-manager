from datetime import date

from landscape_manager.logic import (
    document_total,
    format_money,
    is_overdue_job,
    next_recurrence,
    to_cents,
)


def test_to_cents_and_format():
    assert to_cents("45.50") == 4550
    assert to_cents("45") == 4500
    assert to_cents("$1,234.56") == 123456
    assert format_money(4550) == "$45.50"
    assert format_money(123456) == "$1,234.56"


def test_document_total_uses_quantity():
    items = [
        {"quantity": 2, "unit_price_cents": 4500},
        {"quantity": 1.5, "unit_price_cents": 8500},
    ]
    assert document_total(items) == 9000 + 12750


def test_recurrence_weekly_biweekly_none():
    day = date(2026, 10, 30)
    assert next_recurrence(day, "weekly") == date(2026, 11, 6)
    assert next_recurrence(day, "biweekly") == date(2026, 11, 13)
    assert next_recurrence(day, "none") is None


def test_recurrence_monthly_clamps_to_month_end():
    assert next_recurrence(date(2025, 1, 31), "monthly") == date(2025, 2, 28)
    assert next_recurrence(date(2024, 1, 31), "monthly") == date(2024, 2, 29)
    assert next_recurrence(date(2026, 12, 15), "monthly") == date(2027, 1, 15)


def test_overdue_job_only_when_open_and_past():
    today = date(2026, 10, 30)
    assert is_overdue_job(date(2026, 10, 29), "scheduled", today)
    assert not is_overdue_job(date(2026, 10, 29), "done", today)
    assert not is_overdue_job(date(2026, 10, 30), "scheduled", today)
    assert not is_overdue_job(None, "scheduled", today)
