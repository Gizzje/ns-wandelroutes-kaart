import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checked_routes (
    user_id INTEGER NOT NULL REFERENCES users(id),
    route_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, route_id)
);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Kleine, additieve schemawijzigingen die veilig zijn op een bestaande
    database (bestaande rijen blijven behouden; nieuwe kolom is NULL totdat
    hij expliciet gezet wordt)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(checked_routes)")}
    if "distance_km" not in columns:
        conn.execute("ALTER TABLE checked_routes ADD COLUMN distance_km REAL")


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def create_user(name: str, password_hash: str) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO users (name, password_hash, created_at) VALUES (?, ?, ?)",
            (name, password_hash, datetime.now(timezone.utc).isoformat()),
        )
        return cursor.lastrowid


def get_user_by_name(name: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()


def get_checked_route_ids(user_id: int) -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT route_id FROM checked_routes WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [row["route_id"] for row in rows]


def get_checked_routes_with_distance(user_id: int) -> dict[str, float | None]:
    """route_id -> zelf opgegeven gelopen afstand, of None als de gebruiker
    dat niet heeft aangegeven (dan valt achievements.py terug op de langste
    lengtevariant van de route)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT route_id, distance_km FROM checked_routes WHERE user_id = ?", (user_id,)
        ).fetchall()
        return {row["route_id"]: row["distance_km"] for row in rows}


def set_route_checked(user_id: int, route_id: str, checked: bool, distance_km: float | None = None) -> None:
    with get_db() as conn:
        if checked:
            conn.execute(
                """INSERT INTO checked_routes (user_id, route_id, checked_at, distance_km)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, route_id) DO UPDATE
                   SET checked_at = excluded.checked_at, distance_km = excluded.distance_km""",
                (user_id, route_id, datetime.now(timezone.utc).isoformat(), distance_km),
            )
        else:
            conn.execute(
                "DELETE FROM checked_routes WHERE user_id = ? AND route_id = ?",
                (user_id, route_id),
            )
