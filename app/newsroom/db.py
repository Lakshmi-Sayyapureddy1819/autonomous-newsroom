"""SQLite database configuration, schema definition, and initialization for Autonomous Newsroom."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = "newsroom.sqlite3"

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    published_at TEXT NOT NULL,
    summary TEXT,
    tag TEXT,
    summary_model TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    fetched INTEGER DEFAULT 0,
    inserted INTEGER DEFAULT 0,
    summarized INTEGER DEFAULT 0,
    error TEXT
);
"""


def get_db_path() -> Path:
    """Return database file path from NEWSROOM_DB or default."""
    path_str = os.environ.get("NEWSROOM_DB", DEFAULT_DB_PATH)
    return Path(path_str)


def get_connection(db_path: Optional[Path | str] = None) -> sqlite3.Connection:
    """Get a SQLite database connection with row factory and WAL mode enabled."""
    target_path = Path(db_path) if db_path is not None else get_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db(db_path: Optional[Path | str] = None) -> None:
    """Idempotently initialize database schema."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.executescript(SCHEMA_SQL)
    finally:
        conn.close()


def main() -> None:
    """CLI entrypoint for database management (e.g. python -m newsroom.db init)."""
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        path = get_db_path()
        init_db(path)
        print(f"Initialized database at {path.resolve()}")
    else:
        print("Usage: python -m newsroom.db init")
        sys.exit(1)


if __name__ == "__main__":
    main()
