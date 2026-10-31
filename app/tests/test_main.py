from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsroom.db import get_connection, init_db
from newsroom.main import app


@pytest.fixture()
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "newsroom.sqlite3"
    monkeypatch.setenv("NEWSROOM_DB", str(path))
    init_db(path)
    return path


@pytest.fixture()
def client(db_path: Path) -> TestClient:
    return TestClient(app)


def seed(db_path: Path, rows: list[tuple], run_finished_at: str | None = None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            for url, title, published_at, summary, description, tag in rows:
                conn.execute(
                    "INSERT INTO articles (url, title, source, published_at, summary, "
                    "description, tag) VALUES (?, ?, 'Example News', ?, ?, ?, ?)",
                    (url, title, published_at, summary, description, tag),
                )
            if run_finished_at:
                conn.execute(
                    "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, 'success')",
                    (run_finished_at, run_finished_at),
                )
    finally:
        conn.close()


def recent(minutes: int) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes)
    return dt.isoformat()


def test_homepage_empty_state(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "No Articles Available" in response.text


def test_homepage_shows_real_articles(client: TestClient, db_path: Path) -> None:
    seed(
        db_path,
        [
            ("https://a.example/1", "Headline One", "2026-10-30T10:00:00+00:00",
             "One-line summary.", None, "LLMs"),
            ("https://a.example/2", "Headline Two", "2026-10-30T09:00:00+00:00",
             None, "Original description text", None),
        ],
        run_finished_at=recent(5),
    )
    text = client.get("/").text
    assert "No Articles Available" not in text
    assert "Headline One" in text and "Headline Two" in text
    assert 'href="https://a.example/1"' in text
    assert "Example News" in text
    assert "2026-10-30 10:00 UTC" in text
    assert "One-line summary." in text
    assert "LLMs" in text
    assert "Summary pending" in text
    assert "Original description text" in text
    assert "Updated 5 minutes ago" in text


def test_homepage_orders_newest_first(client: TestClient, db_path: Path) -> None:
    seed(
        db_path,
        [
            ("https://a.example/old", "Older Story", "2026-10-01T00:00:00+00:00", "s", None, None),
            ("https://a.example/new", "Newer Story", "2026-10-30T00:00:00+00:00", "s", None, None),
        ],
    )
    text = client.get("/").text
    assert text.index("Newer Story") < text.index("Older Story")


def test_rss_feed_empty(client: TestClient) -> None:
    response = client.get("/rss.xml")
    assert response.status_code == 200
    assert "rss" in response.headers["content-type"]
    assert ET.fromstring(response.text).findall("./channel/item") == []


def test_rss_feed_contains_real_articles(client: TestClient, db_path: Path) -> None:
    seed(
        db_path,
        [
            ("https://a.example/1", "Tom & Jerry <News>", "2026-10-30T10:00:00+00:00",
             "Summary one", None, "LLMs"),
            ("https://a.example/2", "Pending Story", "2026-10-30T09:00:00+00:00", None, None, None),
        ],
        run_finished_at=recent(1),
    )
    response = client.get("/rss.xml")
    assert response.status_code == 200
    items = ET.fromstring(response.text).findall("./channel/item")
    assert len(items) == 2
    assert items[0].findtext("title") == "Tom & Jerry <News>"
    assert items[0].findtext("link") == "https://a.example/1"
    assert items[0].findtext("description") == "Summary one"
    assert items[0].findtext("pubDate") == "Fri, 30 Oct 2026 10:00:00 +0000"
    assert items[1].findtext("description") == "Summary pending"


def test_init_db_migrates_old_schema(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "old.sqlite3"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE articles (id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, "
        "title TEXT NOT NULL, source TEXT NOT NULL, published_at TEXT NOT NULL, "
        "summary TEXT, tag TEXT, created_at TEXT)"
    )
    old.commit()
    old.close()

    init_db(path)
    init_db(path)  # idempotent

    conn = get_connection(path)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(articles)")}
    conn.close()
    assert {"description", "summary_model"} <= columns


def test_rss_feed_links_browser_stylesheet(client: TestClient) -> None:
    feed = client.get("/rss.xml")
    assert '<?xml-stylesheet type="text/xsl" href="/rss.xsl"?>' in feed.text

    xsl = client.get("/rss.xsl")
    assert xsl.status_code == 200
    assert "xsl" in xsl.headers["content-type"]
    assert ET.fromstring(xsl.content).tag.endswith("stylesheet")
