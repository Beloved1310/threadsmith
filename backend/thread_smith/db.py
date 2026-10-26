"""Durable record of threads sent to Buffer (or dry-run), for the history panel.

SQLite at <threadsmith>/threadsmith.db, stdlib only. Session state holds the
thread being worked on; this holds the ones that went out.
"""

import datetime
import json
import pathlib
import sqlite3
from typing import Optional

DB_PATH = pathlib.Path(__file__).resolve().parents[2] / "threadsmith.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                posts TEXT NOT NULL,
                status TEXT NOT NULL,
                due_at TEXT,
                buffer_post_id TEXT,
                created_at TEXT NOT NULL
            )
            """
        )


def save_thread(
    posts: list[str], status: str, due_at: Optional[str], buffer_post_id: Optional[str]
) -> dict:
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO threads (posts, status, due_at, buffer_post_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (json.dumps(posts), status, due_at, buffer_post_id, created_at),
        )
    return {
        "id": cursor.lastrowid,
        "posts": posts,
        "status": status,
        "due_at": due_at,
        "buffer_post_id": buffer_post_id,
        "created_at": created_at,
    }


def list_threads(limit: int = 20) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM threads ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [{**dict(r), "posts": json.loads(r["posts"])} for r in rows]


init_db()
