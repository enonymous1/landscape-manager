"""Shared test fixtures.

The app fixture lives here, not in a single test module, so every
test file gets the same seeded demo database instead of each module
re-defining (and drifting) its own copy.
"""

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
