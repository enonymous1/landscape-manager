# Landscape Manager

A generalized web app for running a landscaping business — not tied to one
company. Manage clients and their properties, keep an editable service
catalog, schedule one-off and recurring jobs, and turn quotes into invoices.

This is a greenfield build from the `ss-sun-n-shade` idea. The original repo
was only a README and an Android `.gitignore` — no code — so nothing was
ported. This version pivots to the web, per the owner's direction.

## What it does

- **Dashboard** — today's jobs, jobs in the next 7 days, overdue jobs, and
  the total of unpaid invoices.
- **Clients and properties** — a client can have several properties; jobs,
  quotes, and invoices link to them.
- **Services** — editable catalog (mowing, mulching, trimming, and so on)
  with a default price and unit.
- **Jobs** — one-off, weekly, every-two-weeks, or monthly. Marking a
  recurring job done can schedule its next occurrence automatically
  (monthly dates clamp to month-end, so Jan 31 recurs to Feb 28).
- **Quotes and invoices** — line items from the catalog or custom lines,
  quantities, totals in integer cents. A quote converts to an invoice
  (due in 30 days) with its items copied over; invoices can be marked paid.
- **Settings** — change the business name shown in the header.

Deliberately out of v1: login/multi-user roles, online payments, and a
customer portal. Data is stored locally in SQLite.

## Run it

```bash
pip install -e .
landscape-manager --demo
# open http://127.0.0.1:5000
```

`--demo` seeds fictional demo data (fictional people, addresses, and
`@example.test` emails) only if the database is empty. Without it, you start
with an empty business and the default service catalog is empty — add
services from the Services page first.

Or run from source without installing:

```bash
pip install Flask
PYTHONPATH=src python -m landscape_manager --demo
```

The database file defaults to `landscape.db` in the working directory;
override with `--db path/to/file.db` or `LANDSCAPE_DB`.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest -q
```

## Project layout

- `src/landscape_manager/app.py` — Flask app factory and routes
- `src/landscape_manager/logic.py` — pure rules: money, totals, recurrence, overdue
- `src/landscape_manager/db.py` — SQLite schema
- `src/landscape_manager/demo.py` — fictional demo seed
- `src/landscape_manager/templates/` + `static/` — Jinja pages and CSS
- `tests/` — logic unit tests and route smoke tests
