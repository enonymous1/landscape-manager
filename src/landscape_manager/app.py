"""Flask app factory for landscape-manager.

Architecture note: this module is deliberately the thinnest layer that
can hold routes — pure rules live in :mod:`logic`, storage in :mod:`db`,
and form validation in :mod:`validation`. It is still one 500+ line
file, which is the largest remaining structural smell (see the review
notes): the next refactor, when routes grow again, is to split it into
blueprints (clients, jobs, documents, settings) behind a service layer,
not to add more routes here. Nothing in this file should compute money
or dates directly when ``logic`` already does.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import date, timedelta

from flask import Flask, flash, g, redirect, render_template, request, url_for

from .db import DEFAULT_BUSINESS_NAME, connect, get_setting, init_db, invoice_totals
from .demo import seed_demo
from .logic import (
    INVOICE_DUE_DAYS,
    JOB_STATUSES,
    QUOTE_STATUSES,
    RECURRENCES,
    UPCOMING_DAYS,
    document_total,
    format_money,
    is_overdue_invoice,
    is_overdue_job,
    line_total,
    next_recurrence,
)
from .validation import (
    optional_text,
    parse_money_cents,
    parse_quantity,
    require_int,
    require_text,
    validate_enum,
)

#: Business-rule constants live in ``logic`` (see there) and are imported
#: above, so routes, the demo seed, and tests cannot drift apart.


def create_app(test_config: dict | None = None) -> Flask:
    """Build the Flask app.

    ``test_config`` overrides (e.g. ``DATABASE``) are for tests only;
    production configuration comes from the environment (see
    ``LANDSCAPE_SECRET_KEY`` below and ``LANDSCAPE_DB`` in ``__main__``).
    """
    app = Flask(__name__)
    # No hardcoded secret: use LANDSCAPE_SECRET_KEY when set (stable across
    # restarts, required for any real deployment), otherwise generate a random
    # key per process start. Sessions therefore do not survive a restart
    # without the env var, which is the safe default for a demo app.
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("LANDSCAPE_SECRET_KEY") or secrets.token_hex(32),
        DATABASE="landscape.db",
    )
    if test_config:
        app.config.update(test_config)

    def get_db() -> sqlite3.Connection:
        if "db" not in g:
            g.db = connect(app.config["DATABASE"])
            init_db(g.db)
        return g.db

    @app.teardown_appcontext
    def close_db(_exc=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(404)
    def not_found(_error):
        # Detail routes previously returned plain text ("Client not found")
        # while list pages rendered full templates — inconsistent, and a
        # dead end for the user. All unknown routes now get this page.
        return render_template("404.html"), 404

    @app.context_processor
    def inject_globals():
        try:
            business = get_setting(get_db(), "business_name", DEFAULT_BUSINESS_NAME)
        except sqlite3.Error:
            # The database may not exist yet on the very first request;
            # fall back to the default rather than failing the page.
            business = DEFAULT_BUSINESS_NAME
        return {"business_name": business, "format_money": format_money}

    def parse_date(text: str) -> date | None:
        """Parse an ISO ``YYYY-MM-DD`` date, or ``None`` if malformed.

        Returns ``None`` instead of raising so stored dates that are
        blank (e.g. an invoice with no due date) and bad form input
        both flow through the ``is_overdue_*`` helpers, which treat
        ``None`` as "not overdue".
        """
        try:
            y, m, d = (int(p) for p in text.split("-"))
            return date(y, m, d)
        except (ValueError, AttributeError, TypeError):
            return None

    def items_for(table: str, doc_id: int):
        """Line items for a quote or invoice, each with its line total.

        ``table`` is an internal constant only, never user input — it is
        whitelisted here so this function can never become an SQL
        injection vector if a future caller passes it something else.
        The template previously recomputed each line total with
        ``(quantity * price)|int``, which *truncates* (499.5 -> 499)
        while ``logic.line_total`` *rounds* (499.5 -> 500). Computing
        the total once, here, makes the row and the document total agree.
        """
        if table not in ("quote_items", "invoice_items"):
            raise ValueError(f"Unknown item table: {table!r}.")
        prefix = "quote" if table == "quote_items" else "invoice"
        rows = (
            get_db()
            .execute(f"SELECT * FROM {table} WHERE {prefix}_id = ? ORDER BY id", (doc_id,))
            .fetchall()
        )
        items = [dict(r) for r in rows]
        for item in items:
            item["line_total"] = line_total(item["quantity"], item["unit_price_cents"])
        return items

    def add_item(table: str, doc_id: int) -> bool:
        """Add one line item from the detail-page form. Returns False (after
        flashing the error) instead of crashing on bad input."""
        db = get_db()
        try:
            service_id = request.form.get("service_id") or None
            if service_id is not None:
                # Reject a non-numeric service id early; the lookup below
                # would otherwise silently treat it as "no service".
                service_id = str(require_int(request.form, "service_id"))
            description = optional_text(request.form, "description")
            price = optional_text(request.form, "unit_price")
            if service_id and not description:
                row = db.execute("SELECT name FROM services WHERE id = ?", (service_id,)).fetchone()
                description = row["name"] if row else ""
            if service_id and not price:
                row = db.execute(
                    "SELECT price_cents FROM services WHERE id = ?", (service_id,)
                ).fetchone()
                price_cents = row["price_cents"] if row else 0
            else:
                price_cents = parse_money_cents(request.form, "unit_price")
            quantity = parse_quantity(request.form)
        except ValueError as exc:
            flash(str(exc))
            return False
        prefix = "quote" if table == "quote_items" else "invoice"
        db.execute(
            f"INSERT INTO {table} ({prefix}_id, service_id, description, quantity, unit_price_cents)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_id, service_id, description, quantity, price_cents),
        )
        db.commit()
        return True

    @app.route("/")
    def dashboard():
        db = get_db()
        today = date.today()
        rows = db.execute(
            "SELECT j.*, p.label AS property_label, c.name AS client_name, s.name AS service_name"
            " FROM jobs j JOIN properties p ON p.id = j.property_id"
            " JOIN clients c ON c.id = p.client_id JOIN services s ON s.id = j.service_id"
            " ORDER BY j.scheduled_date"
        ).fetchall()
        jobs = []
        for row in rows:
            item = dict(row)
            item["overdue"] = is_overdue_job(
                parse_date(item["scheduled_date"]), item["status"], today
            )
            jobs.append(item)
        todays = [j for j in jobs if j["scheduled_date"] == today.isoformat()]
        upcoming = [
            j
            for j in jobs
            if j["status"] == "scheduled"
            and today.isoformat()
            < j["scheduled_date"]
            <= (today + timedelta(days=UPCOMING_DAYS)).isoformat()
        ]
        overdue = [j for j in jobs if j["overdue"]]
        # One batched totals query, not one per invoice (see db.invoice_totals).
        totals = invoice_totals(db)
        unpaid_total = sum(
            totals.get(inv["id"], 0)
            for inv in db.execute("SELECT id FROM invoices WHERE status = 'unpaid'").fetchall()
        )
        counts = {
            "clients": db.execute("SELECT COUNT(*) AS n FROM clients").fetchone()["n"],
            "jobs": len(jobs),
            "quotes": db.execute("SELECT COUNT(*) AS n FROM quotes").fetchone()["n"],
            "invoices": db.execute("SELECT COUNT(*) AS n FROM invoices").fetchone()["n"],
        }
        return render_template(
            "dashboard.html",
            todays=todays,
            upcoming=upcoming,
            overdue=overdue,
            unpaid_total=unpaid_total,
            counts=counts,
        )

    @app.route("/clients")
    def clients():
        return render_template(
            "clients.html",
            clients=get_db().execute("SELECT * FROM clients ORDER BY name").fetchall(),
        )

    @app.route("/clients/new", methods=["GET", "POST"])
    def client_new():
        if request.method == "POST":
            db = get_db()
            cur = db.execute(
                "INSERT INTO clients (name, phone, email, address, notes) VALUES (?, ?, ?, ?, ?)",
                (
                    request.form["name"],
                    request.form.get("phone", ""),
                    request.form.get("email", ""),
                    request.form.get("address", ""),
                    request.form.get("notes", ""),
                ),
            )
            db.commit()
            return redirect(url_for("client_detail", client_id=cur.lastrowid))
        return render_template("client_form.html", client=None)

    @app.route("/clients/<int:client_id>")
    def client_detail(client_id):
        db = get_db()
        client = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if client is None:
            return "Client not found", 404
        props = db.execute(
            "SELECT * FROM properties WHERE client_id = ? ORDER BY label", (client_id,)
        ).fetchall()
        quotes = db.execute(
            "SELECT * FROM quotes WHERE client_id = ? ORDER BY id DESC", (client_id,)
        ).fetchall()
        invoices = db.execute(
            "SELECT * FROM invoices WHERE client_id = ? ORDER BY id DESC", (client_id,)
        ).fetchall()
        return render_template(
            "client_detail.html", client=client, properties=props, quotes=quotes, invoices=invoices
        )

    @app.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
    def client_edit(client_id):
        db = get_db()
        client = db.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if client is None:
            return "Client not found", 404
        if request.method == "POST":
            db.execute(
                "UPDATE clients SET name=?, phone=?, email=?, address=?, notes=? WHERE id=?",
                (
                    request.form["name"],
                    request.form.get("phone", ""),
                    request.form.get("email", ""),
                    request.form.get("address", ""),
                    request.form.get("notes", ""),
                    client_id,
                ),
            )
            db.commit()
            return redirect(url_for("client_detail", client_id=client_id))
        return render_template("client_form.html", client=client)

    @app.route("/clients/<int:client_id>/delete", methods=["POST"])
    def client_delete(client_id):
        db = get_db()
        try:
            db.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            db.commit()
        except sqlite3.IntegrityError:
            flash("Delete the client's properties first — they are still linked.")
            return redirect(url_for("client_detail", client_id=client_id))
        return redirect(url_for("clients"))

    @app.route("/properties/new", methods=["GET", "POST"])
    def property_new():
        db = get_db()
        clients = db.execute("SELECT * FROM clients ORDER BY name").fetchall()
        if request.method == "POST":
            db.execute(
                "INSERT INTO properties (client_id, label, address, notes) VALUES (?, ?, ?, ?)",
                (
                    request.form["client_id"],
                    request.form["label"],
                    request.form.get("address", ""),
                    request.form.get("notes", ""),
                ),
            )
            db.commit()
            return redirect(url_for("client_detail", client_id=request.form["client_id"]))
        return render_template(
            "property_form.html",
            property=None,
            clients=clients,
            selected=request.args.get("client_id", ""),
        )

    @app.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
    def property_edit(property_id):
        db = get_db()
        prop = db.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()
        if prop is None:
            return "Property not found", 404
        if request.method == "POST":
            db.execute(
                "UPDATE properties SET label=?, address=?, notes=? WHERE id=?",
                (
                    request.form["label"],
                    request.form.get("address", ""),
                    request.form.get("notes", ""),
                    property_id,
                ),
            )
            db.commit()
            return redirect(url_for("client_detail", client_id=prop["client_id"]))
        clients = db.execute("SELECT * FROM clients ORDER BY name").fetchall()
        return render_template(
            "property_form.html", property=prop, clients=clients, selected=str(prop["client_id"])
        )

    @app.route("/properties/<int:property_id>/delete", methods=["POST"])
    def property_delete(property_id):
        db = get_db()
        prop = db.execute("SELECT * FROM properties WHERE id = ?", (property_id,)).fetchone()
        if prop is None:
            return "Property not found", 404
        try:
            db.execute("DELETE FROM properties WHERE id = ?", (property_id,))
            db.commit()
        except sqlite3.IntegrityError:
            flash("That property still has jobs linked to it.")
            return redirect(url_for("client_detail", client_id=prop["client_id"]))
        return redirect(url_for("client_detail", client_id=prop["client_id"]))

    @app.route("/services", methods=["GET", "POST"])
    def services():
        db = get_db()
        if request.method == "POST":
            try:
                name = require_text(request.form, "name")
                price_cents = parse_money_cents(request.form, "price")
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for("services"))
            db.execute(
                "INSERT INTO services (name, description, price_cents, unit) VALUES (?, ?, ?, ?)",
                (
                    name,
                    optional_text(request.form, "description"),
                    price_cents,
                    optional_text(request.form, "unit", "per visit"),
                ),
            )
            db.commit()
            return redirect(url_for("services"))
        return render_template(
            "services.html", services=db.execute("SELECT * FROM services ORDER BY name").fetchall()
        )

    @app.route("/jobs")
    def jobs():
        status = request.args.get("status", "")
        query = (
            "SELECT j.*, p.label AS property_label, c.name AS client_name, s.name AS service_name"
            " FROM jobs j JOIN properties p ON p.id = j.property_id JOIN clients c ON c.id = p.client_id"
            " JOIN services s ON s.id = j.service_id"
        )
        args: list = []
        if status:
            query += " WHERE j.status = ?"
            args.append(status)
        query += " ORDER BY j.scheduled_date"
        return render_template(
            "jobs.html", jobs=get_db().execute(query, args).fetchall(), status=status
        )

    @app.route("/jobs/new", methods=["GET", "POST"])
    def job_new():
        db = get_db()
        props = db.execute(
            "SELECT p.*, c.name AS client_name FROM properties p JOIN clients c ON c.id = p.client_id ORDER BY c.name, p.label"
        ).fetchall()
        services = db.execute("SELECT * FROM services ORDER BY name").fetchall()
        if request.method == "POST":
            try:
                property_id = require_int(request.form, "property_id")
                service_id = require_int(request.form, "service_id")
                scheduled = require_text(request.form, "scheduled_date")
                if parse_date(scheduled) is None:
                    raise ValueError("Scheduled date must be a valid date.")
                recurrence = validate_enum(
                    request.form.get("recurrence", "none"), RECURRENCES, "recurrence"
                )
                status = validate_enum(
                    request.form.get("status", "scheduled"), JOB_STATUSES, "status"
                )
            except ValueError as exc:
                flash(str(exc))
                return redirect(url_for("job_new"))
            try:
                cur = db.execute(
                    "INSERT INTO jobs (property_id, service_id, scheduled_date, recurrence, status, notes) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        property_id,
                        service_id,
                        scheduled,
                        recurrence,
                        status,
                        optional_text(request.form, "notes"),
                    ),
                )
            except sqlite3.IntegrityError:
                # A property/service id that does not exist: previously
                # a bare 500 from SQLite. Flash and re-show the form.
                flash("That property or service does not exist.")
                return redirect(url_for("job_new"))
            db.commit()
            return redirect(url_for("job_detail", job_id=cur.lastrowid))
        return render_template("job_form.html", job=None, properties=props, services=services)

    @app.route("/jobs/<int:job_id>")
    def job_detail(job_id):
        job = (
            get_db()
            .execute(
                "SELECT j.*, p.label AS property_label, p.address AS property_address, c.name AS client_name, s.name AS service_name, s.price_cents AS service_price"
                " FROM jobs j JOIN properties p ON p.id = j.property_id JOIN clients c ON c.id = p.client_id JOIN services s ON s.id = j.service_id WHERE j.id = ?",
                (job_id,),
            )
            .fetchone()
        )
        if job is None:
            return "Job not found", 404
        return render_template("job_detail.html", job=job)

    @app.route("/jobs/<int:job_id>/status", methods=["POST"])
    def job_status(job_id):
        db = get_db()
        job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            return "Job not found", 404
        try:
            # Previously any string was stored as a status, including
            # typos and crafted values no other page understands.
            new_status = validate_enum(request.form.get("status", ""), JOB_STATUSES, "status")
        except ValueError as exc:
            flash(str(exc))
            return redirect(url_for("job_detail", job_id=job_id))
        db.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
        if new_status == "done" and request.form.get("reschedule") == "1":
            # Rescheduling is deliberately opt-in (the checkbox), not
            # automatic: completing a job should not silently create
            # work the business did not ask for. next_recurrence returns
            # None for one-off jobs, so this branch is a no-op for them.
            nxt = next_recurrence(parse_date(job["scheduled_date"]), job["recurrence"])
            if nxt is not None:
                db.execute(
                    "INSERT INTO jobs (property_id, service_id, scheduled_date, recurrence, status, notes) VALUES (?, ?, ?, ?, 'scheduled', ?)",
                    (
                        job["property_id"],
                        job["service_id"],
                        nxt.isoformat(),
                        job["recurrence"],
                        job["notes"],
                    ),
                )
                flash(f"Next occurrence scheduled for {nxt.isoformat()}.")
        db.commit()
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/quotes")
    def quotes():
        rows = (
            get_db()
            .execute(
                "SELECT q.*, c.name AS client_name FROM quotes q JOIN clients c ON c.id = q.client_id ORDER BY q.id DESC"
            )
            .fetchall()
        )
        return render_template("quotes.html", quotes=rows)

    @app.route("/quotes/new", methods=["GET", "POST"])
    def quote_new():
        db = get_db()
        clients = db.execute("SELECT * FROM clients ORDER BY name").fetchall()
        props = db.execute(
            "SELECT p.*, c.name AS client_name FROM properties p JOIN clients c ON c.id = p.client_id ORDER BY c.name"
        ).fetchall()
        if request.method == "POST":
            cur = db.execute(
                "INSERT INTO quotes (client_id, property_id, status, notes, created_date) VALUES (?, ?, 'draft', ?, ?)",
                (
                    request.form["client_id"],
                    request.form.get("property_id") or None,
                    request.form.get("notes", ""),
                    date.today().isoformat(),
                ),
            )
            db.commit()
            return redirect(url_for("quote_detail", quote_id=cur.lastrowid))
        return render_template("quote_form.html", clients=clients, properties=props)

    @app.route("/quotes/<int:quote_id>", methods=["GET", "POST"])
    def quote_detail(quote_id):
        db = get_db()
        quote = db.execute(
            "SELECT q.*, c.name AS client_name FROM quotes q JOIN clients c ON c.id = q.client_id WHERE q.id = ?",
            (quote_id,),
        ).fetchone()
        if quote is None:
            return "Quote not found", 404
        if request.method == "POST":
            if "add_item" in request.form:
                add_item("quote_items", quote_id)
            elif "status" in request.form:
                try:
                    status = validate_enum(request.form["status"], QUOTE_STATUSES, "status")
                except ValueError as exc:
                    flash(str(exc))
                    return redirect(url_for("quote_detail", quote_id=quote_id))
                db.execute("UPDATE quotes SET status = ? WHERE id = ?", (status, quote_id))
                db.commit()
            return redirect(url_for("quote_detail", quote_id=quote_id))
        items = items_for("quote_items", quote_id)
        services = db.execute("SELECT * FROM services ORDER BY name").fetchall()
        return render_template(
            "quote_detail.html",
            quote=quote,
            items=items,
            total=document_total(items),
            services=services,
        )

    @app.route("/quotes/<int:quote_id>/convert", methods=["POST"])
    def quote_convert(quote_id):
        db = get_db()
        quote = db.execute("SELECT * FROM quotes WHERE id = ?", (quote_id,)).fetchone()
        if quote is None:
            return "Quote not found", 404
        cur = db.execute(
            "INSERT INTO invoices (client_id, property_id, quote_id, status, due_date, created_date) VALUES (?, ?, ?, 'unpaid', ?, ?)",
            (
                quote["client_id"],
                quote["property_id"],
                quote_id,
                (date.today() + timedelta(days=INVOICE_DUE_DAYS)).isoformat(),
                date.today().isoformat(),
            ),
        )
        invoice_id = cur.lastrowid
        for item in items_for("quote_items", quote_id):
            db.execute(
                "INSERT INTO invoice_items (invoice_id, service_id, description, quantity, unit_price_cents) VALUES (?, ?, ?, ?, ?)",
                (
                    invoice_id,
                    item["service_id"],
                    item["description"],
                    item["quantity"],
                    item["unit_price_cents"],
                ),
            )
        db.commit()
        return redirect(url_for("invoice_detail", invoice_id=invoice_id))

    @app.route("/invoices")
    def invoices():
        today = date.today()
        db = get_db()
        totals = invoice_totals(db)
        enriched = []
        for row in db.execute(
            "SELECT i.*, c.name AS client_name FROM invoices i JOIN clients c ON c.id = i.client_id ORDER BY i.id DESC"
        ).fetchall():
            item = dict(row)
            item["overdue"] = is_overdue_invoice(
                parse_date(item["due_date"]), item["status"], today
            )
            item["total"] = totals.get(item["id"], 0)
            enriched.append(item)
        return render_template("invoices.html", invoices=enriched)

    @app.route("/invoices/new", methods=["GET", "POST"])
    def invoice_new():
        db = get_db()
        clients = db.execute("SELECT * FROM clients ORDER BY name").fetchall()
        props = db.execute(
            "SELECT p.*, c.name AS client_name FROM properties p JOIN clients c ON c.id = p.client_id ORDER BY c.name"
        ).fetchall()
        if request.method == "POST":
            cur = db.execute(
                "INSERT INTO invoices (client_id, property_id, status, due_date, created_date) VALUES (?, ?, 'unpaid', ?, ?)",
                (
                    request.form["client_id"],
                    request.form.get("property_id") or None,
                    request.form.get("due_date", ""),
                    date.today().isoformat(),
                ),
            )
            db.commit()
            return redirect(url_for("invoice_detail", invoice_id=cur.lastrowid))
        return render_template("invoice_form.html", clients=clients, properties=props)

    @app.route("/invoices/<int:invoice_id>", methods=["GET", "POST"])
    def invoice_detail(invoice_id):
        db = get_db()
        invoice = db.execute(
            "SELECT i.*, c.name AS client_name FROM invoices i JOIN clients c ON c.id = i.client_id WHERE i.id = ?",
            (invoice_id,),
        ).fetchone()
        if invoice is None:
            return "Invoice not found", 404
        if request.method == "POST":
            if "add_item" in request.form:
                add_item("invoice_items", invoice_id)
            elif "mark_paid" in request.form:
                db.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
                db.commit()
            return redirect(url_for("invoice_detail", invoice_id=invoice_id))
        items = items_for("invoice_items", invoice_id)
        services = db.execute("SELECT * FROM services ORDER BY name").fetchall()
        return render_template(
            "invoice_detail.html",
            invoice=invoice,
            items=items,
            total=document_total(items),
            services=services,
        )

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        db = get_db()
        if request.method == "POST":
            db.execute(
                "INSERT INTO settings (key, value) VALUES ('business_name', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (request.form.get("business_name", ""),),
            )
            db.commit()
            flash("Business name saved.")
            return redirect(url_for("settings"))
        return render_template("settings.html", business_name=get_setting(db, "business_name", ""))

    @app.cli.command("seed-demo")
    def seed_demo_command():
        db = get_db()
        print(
            "Seeded demo data."
            if seed_demo(db)
            else "Database already has clients; nothing seeded."
        )

    return app
