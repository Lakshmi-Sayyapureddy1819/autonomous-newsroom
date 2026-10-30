"""Unit and integration tests for newsroom collector module."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from newsroom.collector import (
    DEFAULT_FEED_URL,
    collect,
    get_feed_url,
    normalize_iso_datetime,
    parse_entry,
)
from newsroom.db import get_connection, init_db

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(filename: str) -> bytes:
    return (FIXTURES_DIR / filename).read_bytes()


def test_get_feed_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSROOM_FEED_URL", raising=False)
    assert get_feed_url() == DEFAULT_FEED_URL


def test_get_feed_url_custom(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_url = "https://custom-news.example.com/rss"
    monkeypatch.setenv("NEWSROOM_FEED_URL", custom_url)
    assert get_feed_url() == custom_url


def test_parse_entry_valid() -> None:
    entry = {
        "title": "Title with &amp; entity",
        "link": "https://example.com/article-1",
        "source": {"title": "Daily AI News"},
        "published_parsed": (2026, 10, 30, 8, 30, 0, 4, 303, 0),
    }
    item = parse_entry(entry)
    assert item is not None
    assert item.title == "Title with & entity"
    assert item.url == "https://example.com/article-1"
    assert item.source == "Daily AI News"
    assert item.published_at.startswith("2026-10-30T08:30:00")


def test_parse_entry_invalid_link_or_title() -> None:
    # Missing title
    assert parse_entry({"link": "https://example.com/art1", "title": "   "}) is None
    # Missing link
    assert parse_entry({"link": "", "title": "Some Title"}) is None
    # Invalid URL scheme
    assert parse_entry({"link": "ftp://example.com/file", "title": "FTP Link"}) is None
    # Relative / malformed URL
    assert parse_entry({"link": "/relative/path", "title": "Relative Link"}) is None


def test_normalize_iso_datetime_fallback() -> None:
    # When no date info is present, falls back to a valid ISO UTC timestamp
    iso_str = normalize_iso_datetime({})
    assert "T" in iso_str


def test_collect_valid_feed_and_deduplication(tmp_path: Path) -> None:
    db_path = tmp_path / "test_collector.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    valid_xml = load_fixture("feed_valid.xml")

    # Mock httpx transport returning valid RSS XML
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=valid_xml, headers={"content-type": "application/xml"}
        )
    )
    client = httpx.Client(transport=transport)

    # First collection run
    res1 = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res1.status == "success"
    assert res1.fetched == 3
    assert res1.inserted == 3
    assert res1.error is None

    # Verify rows in articles table
    articles = conn.execute("SELECT * FROM articles ORDER BY id ASC").fetchall()
    assert len(articles) == 3
    assert articles[0]["title"] == "Breakthrough in Multi-Agent Autonomous Systems"
    assert articles[0]["url"] == "https://example.com/ai/multi-agent-breakthrough"
    assert articles[0]["source"] == "Tech News Daily"

    # Second collection run with identical fixture should insert 0 new rows (deduplication)
    res2 = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res2.status == "success"
    assert res2.fetched == 3
    assert res2.inserted == 0  # Deduplicated

    # Verify runs table records
    runs = conn.execute("SELECT * FROM runs ORDER BY id ASC").fetchall()
    assert len(runs) == 2
    assert runs[0]["status"] == "success"
    assert runs[0]["fetched"] == 3
    assert runs[0]["inserted"] == 3
    assert runs[1]["status"] == "success"
    assert runs[1]["fetched"] == 3
    assert runs[1]["inserted"] == 0

    conn.close()


def test_collect_partial_feed(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    partial_xml = load_fixture("feed_partial.xml")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=partial_xml)
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "partial"
    assert res.fetched == 4
    assert res.inserted == 2  # 2 of 4 entries were valid
    assert "feed entries were invalid or skipped" in (res.error or "")

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "partial"
    assert runs["fetched"] == 4
    assert runs["inserted"] == 2

    conn.close()


def test_collect_empty_feed(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    empty_xml = load_fixture("feed_empty.xml")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=empty_xml)
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "failed"
    assert res.fetched == 0
    assert res.inserted == 0
    assert "no entries" in (res.error or "").lower()

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"
    assert runs["error"] is not None

    conn.close()


def test_collect_malformed_feed(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    # Completely unparseable bytes
    bad_bytes = b"not xml at all"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=bad_bytes)
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "failed"
    assert res.fetched == 0
    assert res.inserted == 0
    assert res.error is not None

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"

    conn.close()


def test_collect_http_error(tmp_path: Path) -> None:
    db_path = tmp_path / "http_err.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    transport = httpx.MockTransport(
        lambda request: httpx.Response(500, content=b"Internal Server Error")
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "failed"
    assert res.fetched == 0
    assert res.inserted == 0
    assert "HTTP error" in (res.error or "")

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"
    assert runs["error"] is not None

    conn.close()


def test_collect_network_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "timeout.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    def raise_timeout(request):
        raise httpx.ConnectTimeout("Connection timed out", request=request)

    transport = httpx.MockTransport(raise_timeout)
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "failed"
    assert res.fetched == 0
    assert res.inserted == 0
    assert "timed out" in (res.error or "").lower()

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"

    conn.close()
