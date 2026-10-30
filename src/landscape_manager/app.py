"""Flask app factory for landscape-manager."""

from __future__ import annotations

import os
import secrets
import sqlite3
from datetime import date, timedelta

from flask import Flask, flash, g, redirect, render_template, request, url_for

from .db import connect, get_setting, init_db
from .demo import seed_demo
from .logic import (
    document_total,
    format_money,
    is_overdue_invoice,
    is_overdue_job,
    next_recurrence,
    to_cents,
)


def create_app(test_config: dict | None = None) -> Flask:
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

    @app.context_processor
    def inject_globals():
        try:
            business = get_setting(get_db(), "business_name", "Landscaping")
        except sqlite3.Error:
            business = "Landscaping"
        return {"business_name": business, "format_money": format_money}

    def parse_date(text: str) -> date | None:
        try:
            y, m, d = (int(p) for p in text.split("-"))
            return date(y, m, d)
        except (ValueError, AttributeError, TypeError):
            return None

    def items_for(table: str, doc_id: int):
        prefix = "quote" if table == "quote_items" else "invoice"
        rows = (
            get_db()
            .execute(f"SELECT * FROM {table} WHERE {prefix}_id = ? ORDER BY id", (doc_id,))
            .fetchall()
        )
        return [dict(r) for r in rows]

    def add_item(table: str, doc_id: int):
        db = get_db()
        service_id = request.form.get("service_id") or None
        description = request.form.get("description", "")
        price = request.form.get("unit_price", "")
        if service_id and not description:
            row = db.execute("SELECT name FROM services WHERE id = ?", (service_id,)).fetchone()
            description = row["name"] if row else ""
        if service_id and not price:
            row = db.execute(
                "SELECT price_cents FROM services WHERE id = ?", (service_id,)
            ).fetchone()
            price_cents = row["price_cents"] if row else 0
        else:
            price_cents = to_cents(price or "0")
        try:
            quantity = float(request.form.get("quantity", "1"))
        except ValueError:
            quantity = 1
        prefix = "quote" if table == "quote_items" else "invoice"
        db.execute(
            f"INSERT INTO {table} ({prefix}_id, service_id, description, quantity, unit_price_cents)"
            " VALUES (?, ?, ?, ?, ?)",
            (doc_id, service_id, description, quantity, price_cents),
        )
        db.commit()

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
            and today.isoformat() < j["scheduled_date"] <= (today + timedelta(days=7)).isoformat()
        ]
        overdue = [j for j in jobs if j["overdue"]]
        unpaid_total = sum(
            document_total(items_for("invoice_items", inv["id"]))
            for inv in db.execute("SELECT * FROM invoices WHERE status = 'unpaid'").fetchall()
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
            db.execute(
                "INSERT INTO services (name, description, price_cents, unit) VALUES (?, ?, ?, ?)",
                (
                    request.form["name"],
                    request.form.get("description", ""),
                    to_cents(request.form.get("price", "0")),
                    request.form.get("unit", "per visit"),
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
            cur = db.execute(
                "INSERT INTO jobs (property_id, service_id, scheduled_date, recurrence, status, notes) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    request.form["property_id"],
                    request.form["service_id"],
                    request.form["scheduled_date"],
                    request.form.get("recurrence", "none"),
                    request.form.get("status", "scheduled"),
                    request.form.get("notes", ""),
                ),
            )
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
        new_status = request.form["status"]
        db.execute("UPDATE jobs SET status = ? WHERE id = ?", (new_status, job_id))
        if new_status == "done" and request.form.get("reschedule") == "1":
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
                db.execute(
                    "UPDATE quotes SET status = ? WHERE id = ?", (request.form["status"], quote_id)
                )
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
                (date.today() + timedelta(days=30)).isoformat(),
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
        enriched = []
        for row in (
            get_db()
            .execute(
                "SELECT i.*, c.name AS client_name FROM invoices i JOIN clients c ON c.id = i.client_id ORDER BY i.id DESC"
            )
            .fetchall()
        ):
            item = dict(row)
            item["overdue"] = is_overdue_invoice(
                parse_date(item["due_date"]), item["status"], today
            )
            item["total"] = document_total(items_for("invoice_items", item["id"]))
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
