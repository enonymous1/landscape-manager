import pytest

from landscape_manager import create_app
from landscape_manager.db import connect, init_db
from landscape_manager.demo import seed_demo


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    app = create_app({"DATABASE": db_path, "TESTING": True})
    conn = connect(db_path)
    init_db(conn)
    seed_demo(conn)
    conn.close()
    with app.test_client() as test_client:
        yield test_client


def test_dashboard_shows_generic_business_name(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Landscaping" in response.data
    assert b"Sun" not in response.data


def test_secret_key_comes_from_env_or_is_random(monkeypatch):
    monkeypatch.setenv("LANDSCAPE_SECRET_KEY", "test-only-key-123")
    app = create_app({"DATABASE": ":memory:"})
    assert app.config["SECRET_KEY"] == "test-only-key-123"
    monkeypatch.delenv("LANDSCAPE_SECRET_KEY")
    app2 = create_app({"DATABASE": ":memory:"})
    assert app2.config["SECRET_KEY"] != "dev-only-change-me"
    assert len(app2.config["SECRET_KEY"]) >= 32


def test_theme_picker_and_dark_css_present(client):
    page = client.get("/")
    assert b'id="theme-picker"' in page.data
    assert b"landscape-theme" in page.data
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert b"prefers-color-scheme: dark" in css.data
    assert b'[data-theme="dark"]' in css.data


def test_create_client_and_property_flow(client):
    response = client.post(
        "/clients/new",
        data={"name": "Test Client", "phone": "555-010-9999", "email": "", "address": "1 Test Way"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Test Client" in response.data


def test_quote_total_and_convert_to_invoice(client):
    # Demo quote 1 has one $85.00 mulch item.
    response = client.get("/quotes/1")
    assert response.status_code == 200
    assert b"$85.00" in response.data
    response = client.post("/quotes/1/convert", follow_redirects=True)
    assert response.status_code == 200
    assert b"Invoice" in response.data
    assert b"$85.00" in response.data


def test_recurring_job_completion_schedules_next(client):
    # Demo job 1 is weekly, scheduled in the demo seed.
    response = client.post(
        "/jobs/1/status", data={"status": "done", "reschedule": "1"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Next occurrence scheduled" in response.data
    jobs_page = client.get("/jobs?status=scheduled")
    assert jobs_page.status_code == 200


def test_settings_update(client):
    response = client.post(
        "/settings", data={"business_name": "Green Acres Co."}, follow_redirects=True
    )
    assert response.status_code == 200
    assert b"Green Acres Co." in response.data
