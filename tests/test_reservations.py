from datetime import date, datetime, timedelta

import pytest

import main


# ---------- creating reservations ----------

def test_create_reservation(client, auth, book):
    r = book(salle_id=1, debut=9, fin=11)
    assert r.status_code == 201
    assert "id" in r.json()


def test_created_reservation_appears_in_my_reservations(client, auth, book, future_day):
    book(salle_id=3, debut=14, fin=17)
    r = client.get("/reservations", headers=auth)
    assert r.status_code == 200
    [resa] = r.json()
    assert resa["salle"] == "Salle C201"
    assert (resa["date"], resa["debut"], resa["fin"]) == (future_day, 14, 17)
    assert resa["passee"] is False


def test_overlapping_reservation_is_rejected(client, book):
    assert book(debut=10, fin=13).status_code == 201
    for debut, fin in [(10, 13), (9, 11), (12, 14), (11, 13), (9, 15)]:
        assert book(debut=debut, fin=fin).status_code == 409, (debut, fin)


@pytest.mark.parametrize("debut,fin,why", [
    (8, 10, "opens at 9"),
    (16, 19, "closes at 18"),
    (9, 10, "minimum duration is 2h"),
    (12, 12, "empty range"),
    (14, 11, "end before start"),
])
def test_invalid_hours_are_rejected(client, book, debut, fin, why):
    assert book(debut=debut, fin=fin).status_code == 422, why


def test_past_date_is_rejected(client, book):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert book(jour=yesterday).status_code == 422


def test_booking_the_full_day_is_allowed(client, book):
    assert book(debut=9, fin=18).status_code == 201


# ---------- listing ----------

def test_reservations_are_private_per_user(client, auth, auth_other, book):
    book(debut=9, fin=11)
    assert len(client.get("/reservations", headers=auth).json()) == 1
    assert client.get("/reservations", headers=auth_other).json() == []


# ---------- cancelling ----------

def test_cancel_reservation_frees_the_slot(client, auth, book):
    rid = book(debut=9, fin=11).json()["id"]
    assert client.delete(f"/reservations/{rid}", headers=auth).status_code == 204
    assert client.get("/reservations", headers=auth).json() == []
    assert book(debut=9, fin=11).status_code == 201  # slot is bookable again


def test_cannot_cancel_someone_elses_reservation(client, auth, auth_other, book):
    rid = book(debut=9, fin=11).json()["id"]
    assert client.delete(f"/reservations/{rid}", headers=auth_other).status_code == 404
    assert len(client.get("/reservations", headers=auth).json()) == 1  # still there


# ---------- misc ----------

def test_homepage_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
