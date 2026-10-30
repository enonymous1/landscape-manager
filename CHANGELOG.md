# Changelog

## 1.3.0 — 2026-10-30

- GitHub Pages is now CI-generated, replacing the manually committed
  `docs/` output (supersedes v1.2.0's Pages instructions). New
  `.github/workflows/pages.yml` runs on push to `main` and on manual
  dispatch: install, ruff, pytest, freeze to `frozen-demo/`, then
  `configure-pages` / `upload-pages-artifact` / `deploy-pages` with
  `contents: read`, `pages: write`, `id-token: write`. `docs/` and
  `frozen-demo/` are now gitignored, so generated output is never
  committed. After push, set Pages source to **GitHub Actions** in repo
  Settings (not `main` / `docs`).

## 1.2.0 — 2026-10-30

- Frozen static demo for GitHub Pages: `landscape-manager freeze` (or
  `landscape-manager-freeze`) boots a temporary database, seeds only the
  fictional demo data, and writes a read-only site to `docs/` — 28 pages
  plus `static/style.css` and `.nojekyll`. Internal links are rewritten to
  relative paths so it works from a project Pages subpath, every page
  carries a "Static demo" banner, and all form controls are disabled
  (the theme picker, which is outside any form, still works). The freezer
  takes no database argument, so real data cannot be frozen by mistake.
  Re-run it before pushing after any app change, then enable Pages from
  `main` / `docs` in the repo settings.

## 1.1.1 — 2026-10-30

- Removed the hardcoded Flask `SECRET_KEY`. It now comes from
  `LANDSCAPE_SECRET_KEY` when set, otherwise a random key is generated per
  process start (sessions do not survive a restart without the env var).
  Set the env var for any deployment where sessions should persist.

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
