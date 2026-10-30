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
    assert (
        parse_entry(
            {
                "link": "https://example.com/art1",
                "title": "   ",
                "published_parsed": (2026, 10, 30, 8, 30, 0, 4, 303, 0),
            }
        )
        is None
    )
    # Missing link
    assert (
        parse_entry(
            {
                "link": "",
                "title": "Some Title",
                "published_parsed": (2026, 10, 30, 8, 30, 0, 4, 303, 0),
            }
        )
        is None
    )
    # Invalid URL scheme
    assert (
        parse_entry(
            {
                "link": "ftp://example.com/file",
                "title": "FTP Link",
                "published_parsed": (2026, 10, 30, 8, 30, 0, 4, 303, 0),
            }
        )
        is None
    )
    # Relative / malformed URL
    assert (
        parse_entry(
            {
                "link": "/relative/path",
                "title": "Relative Link",
                "published_parsed": (2026, 10, 30, 8, 30, 0, 4, 303, 0),
            }
        )
        is None
    )
    # Missing or invalid publication date (must reject, no fallback to datetime.now())
    assert (
        parse_entry(
            {
                "link": "https://example.com/valid-url",
                "title": "Valid Title",
                "published": "not a valid date",
            }
        )
        is None
    )
    assert (
        parse_entry(
            {
                "link": "https://example.com/valid-url",
                "title": "Valid Title",
            }
        )
        is None
    )


def test_normalize_iso_datetime_strict() -> None:
    # Valid parsed time returns ISO UTC
    valid_parsed = (2026, 10, 30, 10, 0, 0, 4, 303, 0)
    assert normalize_iso_datetime({"published_parsed": valid_parsed}) == "2026-10-30T10:00:00+00:00"

    # Missing or unparseable date returns None (no synthetic current time)
    assert normalize_iso_datetime({}) is None
    assert normalize_iso_datetime({"published": "unparseable string"}) is None


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
    assert res.fetched == 5
    assert res.inserted == 2  # 2 of 5 entries were valid
    assert "feed entries were invalid or skipped" in (res.error or "")

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "partial"
    assert runs["fetched"] == 5
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


def test_collect_malformed_feed_unrecoverable(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    # Load unrecoverable malformed XML fixture
    malformed_xml = load_fixture("feed_malformed.xml")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=malformed_xml)
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    assert res.status == "failed"
    assert res.inserted == 0
    assert res.error is not None
    assert "parser" in res.error.lower() or "malformed" in res.error.lower()

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"
    assert runs["inserted"] == 0
    assert runs["error"] is not None

    conn.close()


def test_collect_malformed_feed_recoverable_entries(tmp_path: Path) -> None:
    db_path = tmp_path / "malformed_recoverable.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    # Load fixture with recoverable valid entry but malformed XML
    recoverable_xml = load_fixture("feed_malformed_recoverable.xml")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=recoverable_xml)
    )
    client = httpx.Client(transport=transport)

    res = collect(feed_url="https://mock.feed/rss", conn=conn, client=client)
    # Must be 'partial', never 'success', because bozo parser error is flagged
    assert res.status == "partial"
    assert res.fetched >= 1
    assert res.inserted == 1
    assert res.error is not None
    assert "parser" in res.error.lower() or "xml" in res.error.lower()

    # Verify article was persisted
    articles = conn.execute("SELECT * FROM articles WHERE url LIKE '%recoverable%'").fetchall()
    assert len(articles) == 1
    assert articles[0]["title"] == "Recoverable Valid Article"

    # Verify runs table status
    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "partial"
    assert runs["inserted"] == 1
    assert runs["error"] is not None

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
