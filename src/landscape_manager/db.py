"""SQLite storage for landscape-manager (stdlib only, no ORM).

Schema note, and the reason this module has no migrations yet: the schema
is applied with ``CREATE TABLE IF NOT EXISTS``, so it only helps a fresh
database. Adding a column or index later does *not* change an existing
``landscape.db``. That is acceptable for a local-first v1, but it is the
first thing to fix before any schema change ships (see the review notes
in the README's architecture section): introduce a ``PRAGMA user_version``
migration step, or existing users will silently run the old schema.
"""

from __future__ import annotations

import sqlite3

from .logic import line_total

#: Default shown in the header until Settings changes it. Defined here so
#: the app factory and the schema seed cannot drift apart.
DEFAULT_BUSINESS_NAME = "Landscaping"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    label TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT 'per visit'
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL REFERENCES properties(id),
    service_id INTEGER NOT NULL REFERENCES services(id),
    scheduled_date TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'scheduled',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    property_id INTEGER REFERENCES properties(id),
    status TEXT NOT NULL DEFAULT 'draft',
    notes TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quote_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL REFERENCES quotes(id),
    service_id INTEGER REFERENCES services(id),
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price_cents INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id),
    property_id INTEGER REFERENCES properties(id),
    quote_id INTEGER REFERENCES quotes(id),
    status TEXT NOT NULL DEFAULT 'unpaid',
    due_date TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id),
    service_id INTEGER REFERENCES services(id),
    description TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 1,
    unit_price_cents INTEGER NOT NULL DEFAULT 0
);
-- Indexes for the queries the app actually runs: list pages order/filter
-- by these columns, and the dashboard joins on them. Without them every
-- list page is a full table scan; with a few hundred jobs that is fine,
-- with a few thousand it is not. New databases only (see module docstring).
CREATE INDEX IF NOT EXISTS idx_properties_client ON properties(client_id);
CREATE INDEX IF NOT EXISTS idx_jobs_property ON jobs(property_id);
CREATE INDEX IF NOT EXISTS idx_jobs_scheduled ON jobs(scheduled_date);
CREATE INDEX IF NOT EXISTS idx_quotes_client ON quotes(client_id);
CREATE INDEX IF NOT EXISTS idx_quote_items_quote ON quote_items(quote_id);
CREATE INDEX IF NOT EXISTS idx_invoices_client ON invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value) VALUES ('business_name', ?)",
        (DEFAULT_BUSINESS_NAME,),
    )
    conn.commit()


def invoice_totals(conn: sqlite3.Connection) -> dict[int, int]:
    """Total (integer cents) per invoice, computed with a single query.

    The old dashboard and invoice-list code called ``items_for`` once per
    invoice — the classic N+1 query pattern: one query for the invoices,
    then one more per invoice to total its items. This fetches all items
    in one query and totals them in Python, so per-line rounding matches
    :func:`landscape_manager.logic.line_total` exactly (a SQL
    ``SUM(quantity * unit_price_cents)`` would round only the grand
    total, and could differ by a cent on fractional quantities).
    Returns ``{invoice_id: total_cents}``; invoices with no items are
    absent, so callers should use ``.get(invoice_id, 0)``.
    """
    totals: dict[int, int] = {}
    for row in conn.execute("SELECT invoice_id, quantity, unit_price_cents FROM invoice_items"):
        totals[row["invoice_id"]] = totals.get(row["invoice_id"], 0) + line_total(
            row["quantity"], row["unit_price_cents"]
        )
    return totals


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default
