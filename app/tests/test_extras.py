from __future__ import annotations

import json
from pathlib import Path

import httpx

from newsroom.collector import ArticleItem, persist_articles, title_key
from newsroom.db import get_connection, init_db
from newsroom.hackernews import collect_hacker_news, parse_hits


def article(url: str, title: str, source: str = "Example") -> ArticleItem:
    return ArticleItem(
        url=url, title=title, source=source, published_at="2026-10-30T10:00:00+00:00"
    )


def test_title_key_ignores_source_suffix_and_punctuation() -> None:
    assert title_key("Big AI News! - Tom's Hardware", "Tom's Hardware") == title_key("big ai news")


def test_persist_skips_near_duplicate_titles(tmp_path: Path) -> None:
    db = tmp_path / "n.sqlite3"
    init_db(db)
    conn = get_connection(db)
    first = persist_articles(
        conn,
        [
            article("https://a.example/1", "Big AI News - Wire", "Wire"),
            article("https://b.example/2", "Big AI news", "Other"),  # same story, other URL
            article("https://c.example/3", "A different story"),
        ],
    )
    # Re-running with a new URL for an already-stored story inserts nothing.
    second = persist_articles(conn, [article("https://d.example/4", "BIG AI NEWS!")])
    rows = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    conn.close()
    assert (first, second, rows) == (2, 0, 2)


def test_parse_hits_skips_items_without_url_or_title() -> None:
    items = parse_hits(
        [
            {"title": "Show HN: tool", "url": "https://x.example/a", "created_at_i": 1761800000},
            {"title": "Ask HN: no url", "url": None, "created_at_i": 1761800000},
            {"title": "", "url": "https://x.example/b", "created_at_i": 1761800000},
        ]
    )
    assert len(items) == 1
    assert items[0].source == "Hacker News"
    assert items[0].published_at.startswith("2025-10-30")


def test_collect_hacker_news_records_run(tmp_path: Path) -> None:
    db = tmp_path / "n.sqlite3"
    init_db(db)
    payload = {
        "hits": [{"title": "HN story", "url": "https://x.example/a", "created_at_i": 1761800000}]
    }
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=json.dumps(payload)))
    )
    conn = get_connection(db)
    result = collect_hacker_news(conn=conn, client=client)
    run = conn.execute("SELECT status, fetched, inserted FROM runs").fetchone()
    conn.close()
    assert (result.status, result.fetched, result.inserted) == ("success", 1, 1)
    assert tuple(run) == ("success", 1, 1)


def test_collect_hacker_news_http_error_is_recorded_not_raised(tmp_path: Path) -> None:
    db = tmp_path / "n.sqlite3"
    init_db(db)
    client = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(500)))
    conn = get_connection(db)
    result = collect_hacker_news(conn=conn, client=client)
    status = conn.execute("SELECT status FROM runs").fetchone()[0]
    conn.close()
    assert result.status == "failed" and status == "failed"
