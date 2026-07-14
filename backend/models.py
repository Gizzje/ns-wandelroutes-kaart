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


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)


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


def set_route_checked(user_id: int, route_id: str, checked: bool) -> None:
    with get_db() as conn:
        if checked:
            conn.execute(
                """INSERT INTO checked_routes (user_id, route_id, checked_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(user_id, route_id) DO UPDATE SET checked_at = excluded.checked_at""",
                (user_id, route_id, datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute(
                "DELETE FROM checked_routes WHERE user_id = ? AND route_id = ?",
                (user_id, route_id),
            )
