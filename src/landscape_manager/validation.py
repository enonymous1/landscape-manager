"""Input validation for form data.

Why this module exists, instead of parsing inline in each route: the
previous code called ``request.form[...]`` and ``to_cents(...)`` directly,
so a missing field, a bad status, or a price like ``"abc"`` raised
``KeyError``/``ValueError`` and Flask returned a bare 500. Every helper
here raises ``ValueError`` with a user-facing message instead, and routes
catch it, flash the message, and redirect back to the form. Valid input
takes exactly the same path as before; only bad input changes, from a
crash to a message.
"""

from __future__ import annotations

import math

from .logic import to_cents


def require_text(form, field: str) -> str:
    """Return a stripped, non-empty form value, or raise ``ValueError``."""
    value = (form.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is required.")
    return value


def optional_text(form, field: str, default: str = "") -> str:
    """Return a form value, or ``default`` when it is absent or blank."""
    return (form.get(field) or "").strip() or default


def require_int(form, field: str) -> int:
    """Return a form value parsed as an integer, or raise ``ValueError``."""
    try:
        return int((form.get(field) or "").strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"{field.replace('_', ' ').capitalize()} must be a whole number."
        ) from None


def parse_money_cents(form, field: str, default: str = "0") -> int:
    """Return a form price as integer cents, or raise ``ValueError``.

    Delegates to :func:`landscape_manager.logic.to_cents`, which uses
    ``Decimal`` so ``"45.999"`` rounds to 4600 cents instead of being
    truncated to 4599 by the old string-slicing implementation.
    """
    raw = form.get(field)
    if raw is None or str(raw).strip() == "":
        raw = default
    try:
        return to_cents(raw)
    except (ValueError, ArithmeticError):
        raise ValueError(f"{field.replace('_', ' ').capitalize()} is not a valid price.") from None


def parse_quantity(form, field: str = "quantity", default: float = 1) -> float:
    """Return a quantity that is finite and greater than zero."""
    raw = form.get(field)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number.") from None
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Quantity must be greater than zero.")
    return value


def validate_enum(value: str, allowed: tuple[str, ...], field: str) -> str:
    """Return ``value`` if it is in ``allowed``, else raise ``ValueError``.

    This is why the status/recurrence constants in ``logic.py`` exist:
    previously they were defined but never checked, so a crafted POST
    could store an arbitrary status (e.g. ``"banana"``) that no list page
    filters for and no overdue rule understands.
    """
    if value not in allowed:
        raise ValueError(f"Invalid {field}: {value!r}.")
    return value
