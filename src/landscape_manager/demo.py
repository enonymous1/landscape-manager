"""Fictional demo data. No real people, businesses, or addresses.

Seed only into an empty database (or with force=True for tests); it never
overwrites data a user has entered.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .logic import INVOICE_DUE_DAYS, to_cents

SERVICES = [
    ("Lawn Mowing", "Mow, trim edges, and blow off hard surfaces.", "45.00", "per visit"),
    ("Hedge Trimming", "Shape hedges and shrubs, haul clippings.", "65.00", "per visit"),
    ("Mulch Installation", "Spread hardwood mulch in beds.", "85.00", "per cubic yard"),
    ("Leaf Cleanup", "Rake, blow, and remove seasonal leaves.", "120.00", "per visit"),
    ("Fertilizer Application", "Seasonal lawn treatment.", "55.00", "per visit"),
    ("Garden Bed Weeding", "Weed beds and tidy borders.", "40.00", "per hour"),
]

CLIENTS = [
    ("Alex Rivera", "555-010-1001", "alex@example.test", "12 Oak Hollow Lane"),
    ("Jordan Patel", "555-010-1002", "jordan@example.test", "48 Maple Ridge Drive"),
    ("Sam Whitfield", "555-010-1003", "sam@example.test", "7 Willow Creek Court"),
]


def seed_demo(conn: sqlite3.Connection, force: bool = False) -> bool:
    """Insert demo data. Returns False if the DB already has clients."""
    existing = conn.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"]
    if existing and not force:
        return False
    service_ids = []
    for name, description, price, unit in SERVICES:
        cur = conn.execute(
            "INSERT INTO services (name, description, price_cents, unit) VALUES (?, ?, ?, ?)",
            (name, description, to_cents(price), unit),
        )
        service_ids.append(cur.lastrowid)
    today = date.today()
    for i, (name, phone, email, address) in enumerate(CLIENTS):
        client_id = conn.execute(
            "INSERT INTO clients (name, phone, email, address) VALUES (?, ?, ?, ?)",
            (name, phone, email, address),
        ).lastrowid
        prop_id = conn.execute(
            "INSERT INTO properties (client_id, label, address) VALUES (?, ?, ?)",
            (client_id, "Home", address),
        ).lastrowid
        conn.execute(
            "INSERT INTO jobs (property_id, service_id, scheduled_date, recurrence, status)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                prop_id,
                service_ids[i % len(service_ids)],
                (today + timedelta(days=i)).isoformat(),
                "weekly" if i == 0 else "none",
                "scheduled",
            ),
        )
        quote_id = conn.execute(
            "INSERT INTO quotes (client_id, property_id, status, created_date)"
            " VALUES (?, ?, 'sent', ?)",
            (client_id, prop_id, today.isoformat()),
        ).lastrowid
        conn.execute(
            "INSERT INTO quote_items (quote_id, service_id, description, quantity, unit_price_cents)"
            " VALUES (?, ?, ?, 1, ?)",
            (quote_id, service_ids[2], "Mulch Installation", to_cents("85.00")),
        )
        if i == 0:
            # One unpaid demo invoice, so the invoices pages and the
            # dashboard's unpaid total are not empty in the frozen demo.
            invoice_id = conn.execute(
                "INSERT INTO invoices (client_id, property_id, quote_id, status, due_date, created_date)"
                " VALUES (?, ?, ?, 'unpaid', ?, ?)",
                (
                    client_id,
                    prop_id,
                    quote_id,
                    (today + timedelta(days=INVOICE_DUE_DAYS)).isoformat(),
                    today.isoformat(),
                ),
            ).lastrowid
            conn.execute(
                "INSERT INTO invoice_items (invoice_id, service_id, description, quantity, unit_price_cents)"
                " VALUES (?, ?, ?, 1, ?)",
                (invoice_id, service_ids[2], "Mulch Installation", to_cents("85.00")),
            )
    conn.commit()
    return True
