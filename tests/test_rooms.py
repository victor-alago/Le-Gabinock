from datetime import date, timedelta

import main


# ---------- GET /salles ----------

def test_list_rooms(client, auth, future_day):
    r = client.get(f"/salles?jour={future_day}", headers=auth)
    assert r.status_code == 200
    rooms = r.json()
    assert len(rooms) == 6
    assert {"id", "nom", "capacite", "etage", "equipements", "heures_libres", "occupees"} <= rooms[0].keys()
    assert all(room["heures_libres"] == 9 for room in rooms)  # nothing booked yet


def test_booked_room_shows_as_occupied(client, auth, book, future_day):
    book(salle_id=1, debut=9, fin=11)
    rooms = {r["id"]: r for r in client.get(f"/salles?jour={future_day}", headers=auth).json()}
    assert rooms[1]["heures_libres"] == 7
    assert len(rooms[1]["occupees"]) == 1
    assert rooms[2]["heures_libres"] == 9


# ---------- GET /salles/{id} ----------

def test_room_detail(client, auth, future_day):
    r = client.get(f"/salles/1?jour={future_day}", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == 1
    assert (body["ouverture"], body["fermeture"], body["duree_min"]) == (9, 18, 2)
    assert body["occupees"] == []


