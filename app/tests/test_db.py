"""Unit tests for newsroom database module."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.db import DEFAULT_DB_PATH, get_connection, get_db_path, init_db


def test_get_db_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSROOM_DB", raising=False)
    assert get_db_path() == Path(DEFAULT_DB_PATH)


def test_get_db_path_custom(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom_path = tmp_path / "custom.db"
    monkeypatch.setenv("NEWSROOM_DB", str(custom_path))
    assert get_db_path() == custom_path


def test_init_db_idempotence(tmp_path: Path) -> None:
    db_file = tmp_path / "test_newsroom.db"

    # Run initialization twice to verify idempotency
    init_db(db_file)
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ).fetchall()
        table_names = [row["name"] for row in tables]
        assert "articles" in table_names
        assert "runs" in table_names

        # Verify WAL mode
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"
    finally:
        conn.close()


def test_articles_crud_and_constraints(tmp_path: Path) -> None:
    db_file = tmp_path / "articles.db"
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        # Insert article
        conn.execute(
            """
            INSERT INTO articles (url, title, source, published_at, summary, tag, summary_model)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "https://example.com/ai-update",
                "New AI Breakthrough",
                "TechNews",
                "2026-10-30T10:00:00Z",
                "A breakthrough in autonomous agents.",
                "LLMs",
                "gemini-3.7-flash",
            ),
        )
        conn.commit()

        # Query article
        row = conn.execute("SELECT * FROM articles WHERE url = ?", ("https://example.com/ai-update",)).fetchone()
        assert row is not None
        assert row["title"] == "New AI Breakthrough"
        assert row["source"] == "TechNews"
        assert row["summary"] == "A breakthrough in autonomous agents."
        assert row["tag"] == "LLMs"
        assert row["summary_model"] == "gemini-3.7-flash"
        assert row["created_at"] is not None

        # Verify url uniqueness constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO articles (url, title, source, published_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "https://example.com/ai-update",
                    "Duplicate URL Story",
                    "OtherSource",
                    "2026-10-30T10:05:00Z",
                ),
            )
            conn.commit()
    finally:
        conn.close()


def test_runs_crud(tmp_path: Path) -> None:
    db_file = tmp_path / "runs.db"
    init_db(db_file)

    conn = get_connection(db_file)
    try:
        # Insert run
        cursor = conn.execute(
            """
            INSERT INTO runs (started_at, status, fetched, inserted, summarized, error)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("2026-10-30T10:00:00Z", "in-progress", 10, 8, 5, None),
        )
        conn.commit()
        run_id = cursor.lastrowid

        # Update run completion
        conn.execute(
            """
            UPDATE runs
            SET finished_at = ?, status = ?
            WHERE id = ?
            """,
            ("2026-10-30T10:02:00Z", "success", run_id),
        )
        conn.commit()

        # Query run
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert row is not None
        assert row["status"] == "success"
        assert row["fetched"] == 10
        assert row["inserted"] == 8
        assert row["summarized"] == 5
        assert row["error"] is None
        assert row["finished_at"] == "2026-10-30T10:02:00Z"
    finally:
        conn.close()
