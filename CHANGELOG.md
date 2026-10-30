# Changelog

## 1.1.0 — 2026-10-30

- Default business name generalized from "Sun & Shade Landscaping" to
  "Landscaping" (change it in Settings; existing databases keep the name
  already stored in them).
- Site is theme-aware: Auto (default) follows the OS via
  `prefers-color-scheme`, with a header picker for Light / Dark saved per
  browser in `localStorage` (`landscape-theme`) and applied before first
  paint to avoid a flash. Native controls follow via `color-scheme`.

## 1.0.0 — 2026-10-30

Greenfield v1.0.0. Built from the `ss-sun-n-shade` concept (a landscaping
project-management idea whose original repo held no code) as a generalized
Flask web app.

- Clients, properties, editable service catalog
- Jobs with weekly/biweekly/monthly recurrence and complete-and-reschedule
- Quotes with line items, conversion to invoices, invoice paid tracking
- Dashboard with today/upcoming/overdue jobs and unpaid-invoice total
- Configurable business name, SQLite storage, fictional demo seed
- Tests: logic units + route smoke tests
