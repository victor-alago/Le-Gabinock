import main
from conftest import SEED_EMAIL, SEED_PASSWORD


# ---------- password hashing ----------

def test_hash_and_verify_password():
    stored = main.hash_password("secret123")
    assert "secret123" not in stored
    assert main.verify_password("secret123", stored)
    assert not main.verify_password("wrong-pass", stored)


# ---------- login / logout / session ----------

def test_login_success(client):
    r = client.post("/login", json={"email": SEED_EMAIL, "password": SEED_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == SEED_EMAIL


def test_login_wrong_password(client):
    r = client.post("/login", json={"email": SEED_EMAIL, "password": "badpassword"})
    assert r.status_code == 401


def test_me_returns_current_user(client, auth):
    r = client.get("/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["email"] == SEED_EMAIL


def test_protected_routes_require_login(client):
    for method, url in [("get", "/me"), ("get", "/salles"), ("get", "/salles/1"),
                        ("get", "/reservations"), ("delete", "/reservations/1")]:
        assert getattr(client, method)(url).status_code == 401, url
    assert client.post("/reservations", json={"salle_id": 1, "date": "2030-01-01",
                                              "debut": 9, "fin": 11}).status_code == 401



def test_expired_session_rejected_and_removed(client, auth):
    with main.db() as c:
        c.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00'")
    assert client.get("/me", headers=auth).status_code == 401
    with main.db() as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_logout_invalidates_token(client, auth):
    assert client.post("/logout", headers=auth).status_code == 204
    assert client.get("/me", headers=auth).status_code == 401

