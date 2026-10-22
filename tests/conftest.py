import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402

SEED_EMAIL = "f.eric@legabinock.net"
SEED_PASSWORD = "ericfabre77"
OTHER_EMAIL = "r.rose@legabinock.net"
OTHER_PASSWORD = "rosinerone6"


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    """Build a seeded database once (password hashing is slow), then copy it per test."""
    path = tmp_path_factory.mktemp("tpl") / "template.db"
    original = main.DB
    main.DB = str(path)
    try:
        main.init_db()
    finally:
        main.DB = original
    return path


@pytest.fixture
def client(template_db, tmp_path, monkeypatch):
    """TestClient on a fresh, isolated copy of the seeded DB. The real salles.db is never touched."""
    test_db = tmp_path / "test.db"
    shutil.copy(template_db, test_db)
    monkeypatch.setattr(main, "DB", str(test_db))
    with TestClient(main.app) as c:
        yield c


def _login(client, email, password):
    r = client.post("/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth(client):
    """Auth headers for the first seeded user."""
    return _login(client, SEED_EMAIL, SEED_PASSWORD)


@pytest.fixture
def auth_other(client):
    """Auth headers for the second seeded user."""
    return _login(client, OTHER_EMAIL, OTHER_PASSWORD)


@pytest.fixture
def future_day():
    """A date safely in the future, so tests don't depend on the current time of day."""
    return (date.today() + timedelta(days=3)).isoformat()


@pytest.fixture
def book(client, auth, future_day):
    """Helper: book a room. Returns the response."""
    def _book(salle_id=1, debut=9, fin=11, jour=None, headers=None):
        return client.post(
            "/reservations",
            json={"salle_id": salle_id, "date": jour or future_day, "debut": debut, "fin": fin},
            headers=headers or auth,
        )
    return _book
