"""Second news source: the public Hacker News search API (no API key required)."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Optional

import httpx

from newsroom.collector import ArticleItem, CollectionResult, persist_articles, record_run
from newsroom.db import get_connection

logger = logging.getLogger(__name__)

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HN_SOURCE_NAME = "Hacker News"
DEFAULT_HN_QUERY = "artificial intelligence"
MIN_POINTS = 5
MAX_HITS = 30


def hn_enabled() -> bool:
    return os.environ.get("NEWSROOM_HN_ENABLED", "1").strip().lower() not in {"0", "false", "no"}


def get_hn_query() -> str:
    return os.environ.get("NEWSROOM_HN_QUERY", DEFAULT_HN_QUERY)


def parse_hits(hits: list[dict]) -> list[ArticleItem]:
    """Convert Algolia hits to articles. Skips items without a title or external URL."""
    items: list[ArticleItem] = []
    for hit in hits:
        title = (hit.get("title") or "").strip()
        url = (hit.get("url") or "").strip()
        created = hit.get("created_at_i")
        if not title or not url.startswith(("http://", "https://")) or not created:
            continue
        published = datetime.datetime.fromtimestamp(int(created), tz=datetime.timezone.utc)
        items.append(
            ArticleItem(
                url=url,
                title=title,
                source=HN_SOURCE_NAME,
                published_at=published.isoformat(),
                description=None,
            )
        )
    return items


def fetch_hits(
    query: str, client: Optional[httpx.Client] = None
) -> tuple[list[ArticleItem], int, Optional[str]]:
    close_client = client is None
    client = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        response = client.get(
            HN_SEARCH_URL,
            params={
                "query": query,
                "tags": "story",
                "numericFilters": f"points>{MIN_POINTS}",
                "hitsPerPage": MAX_HITS,
            },
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])
    except Exception as exc:
        logger.error(f"Failed to fetch Hacker News stories: {exc}")
        return [], 0, f"Hacker News fetch error: {exc}"
    finally:
        if close_client:
            client.close()
    return parse_hits(hits), len(hits), None


def collect_hacker_news(
    conn=None, client: Optional[httpx.Client] = None, query: Optional[str] = None
) -> CollectionResult:
    """Run one Hacker News collection and record it in the runs table."""
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_conn = conn is None
    conn = conn or get_connection()
    try:
        articles, fetched, error = fetch_hits(query or get_hn_query(), client)
        if error is not None or not articles:
            status, inserted = "failed", 0
            error = error or "Hacker News returned no usable stories"
        else:
            status, inserted = "success", persist_articles(conn, articles)
        record_run(
            conn,
            started_at,
            datetime.datetime.now(datetime.timezone.utc).isoformat(),
            status,
            fetched,
            inserted,
            error,
        )
        return CollectionResult(status=status, fetched=fetched, inserted=inserted, error=error)
    finally:
        if close_conn:
            conn.close()
