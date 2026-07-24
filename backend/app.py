import os
import time
from collections import defaultdict, deque
from datetime import timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request, session, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import achievements
import models

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

DEBUG = os.environ.get("FLASK_DEBUG") == "1"

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-secret-key-alleen-voor-lokaal-testen"  # noqa: S105
    else:
        raise RuntimeError(
            "SECRET_KEY ontbreekt. Zet 'm in .env (zie .env.example) voordat je de "
            "server ergens anders dan lokaal (FLASK_DEBUG=1) draait -- zonder een "
            "echte, geheime sleutel kan een bezoeker sessies vervalsen en zich "
            "voordoen als een andere gebruiker."
        )

app = Flask(__name__, static_folder=None)
app.secret_key = SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=not DEBUG,
)
# Zonder dit verloopt de sessie zodra de browser dichtgaat (of soms al eerder
# op mobiel) -- met session.permanent = True bij het inloggen (zie login()
# en register()) blijft iemand nu een maand ingelogd.
app.permanent_session_lifetime = timedelta(days=30)

# Ga ervan uit dat de app achter één reverse proxy / tunnel draait (zoals
# beschreven in SETUP.md), zodat request.remote_addr het echte IP van de
# bezoeker is i.p.v. dat van de proxy -- nodig voor de rate limit hieronder.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# --- Simpele rate limit voor login/registratie --------------------------

RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_ATTEMPTS = 8
_attempts_by_key: dict[str, deque] = defaultdict(deque)


def rate_limited(bucket: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{bucket}:{request.remote_addr}"
            attempts = _attempts_by_key[key]
            now = time.monotonic()
            while attempts and attempts[0] < now - RATE_LIMIT_WINDOW_SECONDS:
                attempts.popleft()
            if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
                return jsonify({"error": "Te veel pogingen, probeer het over een minuut opnieuw."}), 429
            attempts.append(now)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


@app.before_request
def _ensure_db():
    models.init_db()


# --- Frontend ---------------------------------------------------------


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/static/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


# --- Data --------------------------------------------------------------


@app.get("/api/data/<name>")
def data_file(name):
    if name not in ("routes.geojson", "rail_network.geojson", "stations.geojson"):
        return jsonify({"error": "onbekend bestand"}), 404
    return send_from_directory(DATA_DIR, name)


# --- Auth ----------------------------------------------------------------


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return {"id": user_id, "name": session.get("user_name")}


@app.get("/api/me")
def me():
    user = _current_user()
    return jsonify({"user": user})


@app.post("/api/register")
@rate_limited("register")
def register():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""

    if not name or len(name) > 50:
        return jsonify({"error": "Vul een naam in (max 50 tekens)."}), 400
    if len(password) < 6:
        return jsonify({"error": "Wachtwoord moet minstens 6 tekens zijn."}), 400
    if models.get_user_by_name(name):
        return jsonify({"error": "Deze naam is al in gebruik."}), 409

    user_id = models.create_user(name, generate_password_hash(password))
    session.permanent = True
    session["user_id"] = user_id
    session["user_name"] = name
    return jsonify({"user": {"id": user_id, "name": name}})


@app.post("/api/login")
@rate_limited("login")
def login():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    password = body.get("password") or ""

    user = models.get_user_by_name(name)
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Naam of wachtwoord is onjuist."}), 401

    session.permanent = True
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return jsonify({"user": {"id": user["id"], "name": user["name"]}})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


# --- Afgevinkte routes -----------------------------------------------


@app.get("/api/checked")
def get_checked():
    user = _current_user()
    if not user:
        return jsonify({"error": "Niet ingelogd."}), 401
    return jsonify({"route_ids": models.get_checked_route_ids(user["id"])})


@app.post("/api/checked")
def post_checked():
    user = _current_user()
    if not user:
        return jsonify({"error": "Niet ingelogd."}), 401

    body = request.get_json(silent=True) or {}
    route_id = str(body.get("route_id") or "")
    checked = bool(body.get("checked"))
    if not route_id:
        return jsonify({"error": "route_id ontbreekt."}), 400

    before = achievements.compute_stats(models.get_checked_route_ids(user["id"]))
    unlocked_before = {a["id"] for a in before["achievements"] if a["unlocked"]}

    models.set_route_checked(user["id"], route_id, checked)

    after = achievements.compute_stats(models.get_checked_route_ids(user["id"]))
    newly_unlocked = [a for a in after["achievements"] if a["unlocked"] and a["id"] not in unlocked_before]

    return jsonify({"ok": True, "newly_unlocked": newly_unlocked})


# --- Statistieken & achievements --------------------------------------


@app.get("/api/stats")
def get_stats():
    user = _current_user()
    if not user:
        return jsonify({"error": "Niet ingelogd."}), 401
    checked_route_ids = models.get_checked_route_ids(user["id"])
    return jsonify(achievements.compute_stats(checked_route_ids))


if __name__ == "__main__":
    models.init_db()
    app.run(host="127.0.0.1", port=5000, debug=DEBUG)
