import hashlib
import hmac
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

BASE = Path(__file__).parent
DB = str(BASE / "salles.db")
OUVERTURE, FERMETURE, DUREE_MIN = 9, 18, 2
TOKEN_DAYS = 7
bearer = HTTPBearer(auto_error=False)


def db():
    conn = sqlite3.connect(DB, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, expected = stored.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 310_000).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS salles(
            id INTEGER PRIMARY KEY, nom TEXT, capacite INTEGER,
            etage INTEGER, equipements TEXT);
        CREATE TABLE IF NOT EXISTS reservations(
            id INTEGER PRIMARY KEY,
            salle_id INTEGER NOT NULL REFERENCES salles(id),
            user_id INTEGER NOT NULL REFERENCES users(id),
            date TEXT NOT NULL, debut INTEGER NOT NULL, fin INTEGER NOT NULL,
            cree_le TEXT NOT NULL,
            CHECK(debut < fin)
        );
        CREATE INDEX IF NOT EXISTS idx_resa_salle_date ON reservations(salle_id,date,debut,fin);
        CREATE INDEX IF NOT EXISTS idx_resa_user ON reservations(user_id,date,debut);
        """)
        # Comptes de démonstration demandés. Les mots de passe sont stockés hachés, jamais en clair.
        seed_users = [
            ("f.eric@legabinock.net", "ericfabre77"),
            ("r.rose@legabinock.net", "rosinerone6"),
        ]
        for email, password in seed_users:
            exists = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not exists:
                c.execute("INSERT INTO users(email,password_hash) VALUES(?,?)",
                          (email, hash_password(password)))
        if c.execute("SELECT COUNT(*) FROM salles").fetchone()[0] == 0:
            salles = [
                ("Salle C100", 16, 1, "Écran, visio"),
                ("Salle C102", 20, 1, "Écran, visio, Projecteur"),
                ("Salle C201", 10, 2, "Projecteur"),
                ("Salle C302", 14, 3, "Tableau blanc"),
                ("Salle C307", 40, 3, "Projecteur, visio, micro"),
                ("Salle C405", 20, 4, "Projecteur, visio, micro")
            ]
            c.executemany("INSERT INTO salles(nom,capacite,etage,equipements) VALUES(?,?,?,?)", salles)


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="MVP Réservation de salles", lifespan=lifespan)


@app.get("/")
def accueil():
    return FileResponse(BASE / "static" / "index.html")


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


def get_current_user(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if not credentials:
        raise HTTPException(401, "Veuillez vous connecter")
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    with db() as c:
        row = c.execute("""SELECT u.id,u.email,s.expires_at FROM sessions s
                           JOIN users u ON u.id=s.user_id WHERE s.token_hash=?""",
                        (token_hash,)).fetchone()
        if not row:
            raise HTTPException(401, "Session invalide. Reconnectez-vous.")
        if row["expires_at"] <= datetime.utcnow().isoformat():
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
            raise HTTPException(401, "Session expirée. Reconnectez-vous.")
        return {"id": row["id"], "email": row["email"]}


CurrentUser = Annotated[dict, Depends(get_current_user)]


@app.post("/login")
def login(b: LoginBody):
    email = str(b.email).strip().lower()
    with db() as c:
        user = c.execute("SELECT id,email,password_hash FROM users WHERE email=?", (email,)).fetchone()
        # Message générique pour ne pas révéler si un compte existe.
        if not user or not verify_password(b.password, user["password_hash"]):
            raise HTTPException(401, "Adresse e-mail ou mot de passe incorrect.")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires = (datetime.utcnow() + timedelta(days=TOKEN_DAYS)).isoformat()
        c.execute("INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                  (token_hash, user["id"], expires))
        return {"access_token": token, "token_type": "bearer",
                "user": {"id": user["id"], "email": user["email"]}}


@app.get("/me")
def me(user: CurrentUser):
    return user


@app.post("/logout", status_code=204)
def logout(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials:
        token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
        with db() as c:
            c.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    return None


def passe_avant(jour: str) -> int:
    try:
        d = date.fromisoformat(jour)
    except ValueError:
        raise HTTPException(422, "Date invalide")
    if d < date.today():
        return FERMETURE
    if d == date.today():
        return min(max(datetime.now().hour, OUVERTURE), FERMETURE)
    return OUVERTURE


def occupees(c, salle_id, jour):
    rows = c.execute("SELECT id,debut,fin FROM reservations WHERE salle_id=? AND date=? ORDER BY debut",
                     (salle_id, jour))
    return [dict(r) for r in rows]


def heures_libres(occ):
    prises = {h for r in occ for h in range(r["debut"], r["fin"])}
    return [h for h in range(OUVERTURE, FERMETURE) if h not in prises]


def a_plage_libre(libres):
    s = set(libres)
    return any(all(h + k in s for k in range(DUREE_MIN)) for h in libres)


@app.get("/salles")
def liste_salles(user: CurrentUser, jour: str | None = None, debut: int | None = None,
                 fin: int | None = None, disponible: bool = False):
    jour = jour or date.today().isoformat()
    pa, res = passe_avant(jour), []
    with db() as c:
        for s in c.execute("SELECT * FROM salles").fetchall():
            occ = occupees(c, s["id"], jour)
            libres = [h for h in heures_libres(occ) if h >= pa]
            if debut is not None and fin is not None:
                if any(r["debut"] < fin and r["fin"] > debut for r in occ):
                    continue
            if disponible and not a_plage_libre(libres):
                continue
            res.append({**dict(s), "heures_libres": len(libres), "occupees": occ, "passe_avant": pa})
    return res


@app.get("/salles/{salle_id}")
def detail_salle(salle_id: int, user: CurrentUser, jour: str | None = None):
    jour = jour or date.today().isoformat()
    with db() as c:
        s = c.execute("SELECT * FROM salles WHERE id=?", (salle_id,)).fetchone()
        if not s:
            raise HTTPException(404, "Salle introuvable")
        return {**dict(s), "jour": jour, "ouverture": OUVERTURE, "fermeture": FERMETURE,
                "duree_min": DUREE_MIN, "occupees": occupees(c, salle_id, jour),
                "passe_avant": passe_avant(jour)}


class Reservation(BaseModel):
    salle_id: int
    date: str
    debut: int
    fin: int


@app.post("/reservations", status_code=201)
def reserver(b: Reservation, user: CurrentUser):
    try:
        if date.fromisoformat(b.date) < date.today():
            raise HTTPException(422, "Date passée")
    except ValueError:
        raise HTTPException(422, "Date invalide")
    if b.debut < passe_avant(b.date):
        raise HTTPException(422, "Ces heures sont déjà passées")
    if b.debut < OUVERTURE or b.fin > FERMETURE or b.debut >= b.fin:
        raise HTTPException(422, f"Plage autorisée : {OUVERTURE}h–{FERMETURE}h")
    if b.fin - b.debut < DUREE_MIN:
        raise HTTPException(422, f"Durée minimale : {DUREE_MIN} h")
    with db() as c:
        if not c.execute("SELECT 1 FROM salles WHERE id=?", (b.salle_id,)).fetchone():
            raise HTTPException(404, "Salle introuvable")
        # SQLite verrouille les écritures ici : les demandes concurrentes sont sérialisées.
        c.execute("BEGIN IMMEDIATE")
        try:
            overlap = c.execute("""SELECT 1 FROM reservations
                WHERE salle_id=? AND date=? AND debut < ? AND fin > ? LIMIT 1""",
                (b.salle_id, b.date, b.fin, b.debut)).fetchone()
            if overlap:
                raise HTTPException(409, "Ce créneau vient d’être réservé. Choisissez une autre plage.")
            cur = c.execute("""INSERT INTO reservations(salle_id,user_id,date,debut,fin,cree_le)
                               VALUES(?,?,?,?,?,?)""",
                            (b.salle_id, user["id"], b.date, b.debut, b.fin, datetime.now().isoformat()))
            rid = cur.lastrowid
            c.execute("COMMIT")
            return {"id": rid}
        except Exception:
            c.execute("ROLLBACK")
            raise


@app.get("/reservations")
def mes_reservations(user: CurrentUser):
    with db() as c:
        rows = c.execute("""SELECT r.id,s.nom AS salle,r.date,r.debut,r.fin
                            FROM reservations r JOIN salles s ON s.id=r.salle_id
                            WHERE r.user_id=? ORDER BY r.date,r.debut""", (user["id"],))
        auj, h = date.today().isoformat(), datetime.now().hour
        return [{**dict(r), "passee": r["date"] < auj or (r["date"] == auj and r["fin"] <= h)}
                for r in rows]


@app.delete("/reservations/{reservation_id}", status_code=204)
def annuler(reservation_id: int, user: CurrentUser):
    with db() as c:
        n = c.execute("DELETE FROM reservations WHERE id=? AND user_id=?",
                      (reservation_id, user["id"])).rowcount
        if not n:
            raise HTTPException(404, "Réservation introuvable")
    return None
