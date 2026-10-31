"""Tests for the v1.4.0 staff-review fixes.

Each test pins a behaviour that used to be a crash or a silent
wrong answer, so a future refactor cannot reintroduce it quietly.
"""

import pytest

from landscape_manager.db import invoice_totals
from landscape_manager.freeze import freeze
from landscape_manager.logic import to_cents
from landscape_manager.validation import parse_quantity, validate_enum


def test_to_cents_rounds_half_up_not_truncates():
    # Old string-slicing code produced 4599 for "45.999".
    assert to_cents("45.999") == 4600
    assert to_cents("45.50") == 4550
    assert to_cents("$1,234.56") == 123456


def test_to_cents_rejects_malformed_input():
    with pytest.raises(ValueError):
        to_cents("abc")
    with pytest.raises(ValueError):
        to_cents("45.50.10")


def test_quantity_must_be_positive_and_finite():
    assert parse_quantity({"quantity": "1.5"}) == 1.5
    with pytest.raises(ValueError):
        parse_quantity({"quantity": "0"})
    with pytest.raises(ValueError):
        parse_quantity({"quantity": "-2"})
    with pytest.raises(ValueError):
        parse_quantity({"quantity": "banana"})


def test_enum_validation_rejects_crafted_status():
    assert validate_enum("done", ("scheduled", "done"), "status") == "done"
    with pytest.raises(ValueError):
        validate_enum("banana", ("scheduled", "done"), "status")


def test_bad_job_status_is_flashed_not_a_500(client):
    response = client.post("/jobs/1/status", data={"status": "banana"}, follow_redirects=True)
    assert response.status_code == 200
    assert b"Invalid status" in response.data


def test_bad_service_price_is_flashed_not_a_500(client):
    response = client.post(
        "/services", data={"name": "Bad Price", "price": "abc"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"not a valid price" in response.data


def test_unknown_route_renders_404_page(client):
    response = client.get("/clients/99999")
    # Detail routes still return their plain 404 for a missing record;
    # unknown routes go through the new handler.
    assert response.status_code == 404
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert b"Page not found" in response.data


def test_invoice_totals_uses_one_query_result(client, tmp_path):
    # invoice_totals is a pure DB helper: seed via the fixture app's DB
    # indirectly by checking the dashboard still totals correctly.
    response = client.get("/invoices")
    assert response.status_code == 200
    assert b"$85.00" in response.data
    # And the helper itself agrees with the document total.
    from landscape_manager.db import connect, init_db
    from landscape_manager.demo import seed_demo

    db_path = str(tmp_path / "totals.db")
    conn = connect(db_path)
    init_db(conn)
    seed_demo(conn)
    assert invoice_totals(conn)[1] == 8500
    conn.close()


def test_freeze_refuses_a_directory_containing_git(tmp_path):
    target = tmp_path / "repo"
    (target / ".git").mkdir(parents=True)
    (target / "keep.txt").write_text("keep me")
    with pytest.raises(ValueError):
        freeze(target)
    assert (target / "keep.txt").read_text() == "keep me"
