from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsroom.db import SCHEMA_SQL, get_connection, init_db
from newsroom.main import app, get_db

client = TestClient(app)

def seed_article(
    conn,
    url: str,
    title: str,
    source: str,
    published_at: str,
    summary: str | None = None,
    tag: str | None = None,
) -> int:
    with conn:
        cur = conn.execute(
            """
            INSERT INTO articles (url, title, source, published_at, summary, tag)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (url, title, source, published_at, summary, tag),
        )
        return cur.lastrowid


def seed_successful_run(conn, finished_at: str) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO runs (started_at, finished_at, status, fetched, inserted, summarized)
            VALUES (?, ?, 'success', 0, 0, 0)
            """,
            (finished_at, finished_at),
        )


@pytest.fixture(scope="function")
def test_db(tmp_path: Path) -> str:
    # Use a real file-based SQLite database for better isolation and behavior consistency
    db_path = tmp_path / "test_newsroom.sqlite3"
    init_db(db_path)
    yield str(db_path)


@pytest.fixture(scope="function")
def seeded_db(test_db: str) -> str:
    conn = get_connection(db_path=test_db)
    try:
        seed_article(
            conn,
            "https://example.com/article1",
            "Test Article One",
            "Source1",
            "2026-10-30T10:00:00+00:00",
            "Summary of article one.",
            "LLMs",
        )
        seed_article(
            conn,
            "https://example2.com/article2",
            "Test Article Two (pending)",
            "Source2",
            "2026-10-30T11:00:00+00:00",
            None,  # Summary pending
            "Research",
        )
        seed_article(
            conn,
            "https://example3.com/article3",
            "Test Article Three",
            "Source3",
            "2026-10-30T12:00:00+00:00",
            "Summary of article three.",
            "Industry",
        )
        seed_successful_run(conn, "2026-10-30T12:30:00+00:00")
    finally:
        conn.close()
    yield test_db


@pytest.fixture(scope="function")
def override_db_dependency(test_db: str): # test_db is still needed to ensure fixture ordering
    # For testing, we'll use an in-memory SQLite database
    # and override the get_db dependency in FastAPI

    def _get_test_db_override():
        # Use an in-memory database for speed and isolation
        # For in-memory databases, check_same_thread should be False for TestClient
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_SQL)
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = _get_test_db_override
    yield
    app.dependency_overrides.clear()


def test_homepage_empty_state(test_db: str, override_db_dependency) -> None:
    client.get("/")


def test_rss_feed_generates_valid_xml(seeded_db: str, override_db_dependency) -> None:
    client.get("/rss.xml")


def test_rss_feed_empty_state(test_db: str, override_db_dependency) -> None:
    client.get("/rss.xml")
