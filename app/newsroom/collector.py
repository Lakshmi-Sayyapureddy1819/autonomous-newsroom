"""RSS feed collector for Autonomous Newsroom."""

from __future__ import annotations

import datetime
import html
import logging
import os
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import feedparser
import httpx

from newsroom.db import get_connection

DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search?q=artificial+intelligence&hl=en-US&gl=US&ceid=US:en"
)

logger = logging.getLogger(__name__)


@dataclass
class ArticleItem:
    url: str
    title: str
    source: str
    published_at: str


@dataclass
class CollectionResult:
    status: str  # 'success', 'partial', 'failed'
    fetched: int
    inserted: int
    error: Optional[str] = None


def get_feed_url() -> str:
    """Return the RSS feed URL configured in environment or default."""
    return os.environ.get("NEWSROOM_FEED_URL", DEFAULT_FEED_URL)


def normalize_iso_datetime(entry: dict) -> Optional[str]:
    """Extract and normalize published datetime to ISO 8601 UTC string.

    Returns None if no valid date can be parsed (does not synthesize current time).
    """
    parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time:
        try:
            dt = datetime.datetime(*parsed_time[:6], tzinfo=datetime.timezone.utc)
            return dt.isoformat()
        except Exception:
            pass

    for date_key in ("published", "updated", "pubDate"):
        raw_val = entry.get(date_key)
        if raw_val and isinstance(raw_val, str):
            try:
                dt = datetime.datetime.fromisoformat(raw_val)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=datetime.timezone.utc)
                else:
                    dt = dt.astimezone(datetime.timezone.utc)
                return dt.isoformat()
            except Exception:
                pass

    return None


def extract_source(entry: dict) -> str:
    """Extract source or publisher name from entry."""
    source_obj = entry.get("source")
    if isinstance(source_obj, dict) and source_obj.get("title"):
        return html.unescape(str(source_obj["title"]).strip())
    if hasattr(source_obj, "title") and getattr(source_obj, "title"):
        return html.unescape(str(getattr(source_obj, "title")).strip())

    author = entry.get("author")
    if author and isinstance(author, str) and author.strip():
        return html.unescape(author.strip())

    publisher = entry.get("publisher")
    if publisher and isinstance(publisher, str) and publisher.strip():
        return html.unescape(publisher.strip())

    return "Unknown"


def parse_entry(entry: dict) -> Optional[ArticleItem]:
    """Validate and parse a single feed entry into an ArticleItem."""
    url = (entry.get("link") or "").strip()
    if not url:
        return None

    parsed_url = urlparse(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return None

    title = (entry.get("title") or "").strip()
    if not title:
        return None
    clean_title = html.unescape(title)

    source = extract_source(entry)
    published_at = normalize_iso_datetime(entry)
    if not published_at:
        return None

    return ArticleItem(
        url=url,
        title=clean_title,
        source=source,
        published_at=published_at,
    )


def fetch_and_parse_feed(
    feed_url: str,
    client: Optional[httpx.Client] = None,
    timeout: float = 15.0,
) -> tuple[list[ArticleItem], int, Optional[str]]:
    """Fetch feed content via httpx and parse entries with feedparser."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=True)
        close_client = True

    try:
        response = client.get(feed_url)
        response.raise_for_status()
        content = response.content
    except Exception as exc:
        logger.error(f"Failed to fetch feed from {feed_url}: {exc}")
        return [], 0, f"HTTP error fetching feed: {exc}"
    finally:
        if close_client:
            client.close()

    parsed = feedparser.parse(content)

    if parsed.bozo and not parsed.entries:
        err_msg = f"Malformed feed XML: {parsed.bozo_exception}"
        logger.error(err_msg)
        return [], 0, err_msg

    raw_count = len(parsed.entries)
    if raw_count == 0:
        return [], 0, "Feed contains no entries"

    articles: list[ArticleItem] = []
    invalid_count = 0

    for entry in parsed.entries:
        item = parse_entry(entry)
        if item is not None:
            articles.append(item)
        else:
            invalid_count += 1

    error_parts: list[str] = []
    if parsed.bozo:
        bozo_msg = f"XML parser warning/error: {parsed.bozo_exception}"
        logger.warning(bozo_msg)
        error_parts.append(bozo_msg)

    if invalid_count > 0:
        error_parts.append(f"{invalid_count} of {raw_count} feed entries were invalid or skipped")

    error_msg = "; ".join(error_parts) if error_parts else None

    return articles, raw_count, error_msg


def persist_articles(conn: sqlite3.Connection, articles: list[ArticleItem]) -> int:
    """Insert articles into database with URL deduplication, returning count inserted."""
    inserted = 0
    with conn:
        for article in articles:
            cursor = conn.execute(
                """
                INSERT INTO articles (url, title, source, published_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url) DO NOTHING;
                """,
                (article.url, article.title, article.source, article.published_at),
            )
            inserted += cursor.rowcount
    return inserted


def record_run(
    conn: sqlite3.Connection,
    started_at: str,
    finished_at: str,
    status: str,
    fetched: int,
    inserted: int,
    error: Optional[str],
) -> int:
    """Record collection run execution metadata in the runs table."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (started_at, finished_at, status, fetched, inserted, summarized, error)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (started_at, finished_at, status, fetched, inserted, 0, error),
        )
        return cursor.lastrowid


def collect(
    feed_url: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    client: Optional[httpx.Client] = None,
) -> CollectionResult:
    """Execute a single collection run."""
    target_url = feed_url or get_feed_url()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        articles, fetched_count, parse_error = fetch_and_parse_feed(target_url, client=client)

        if fetched_count == 0:
            status = "failed"
            inserted_count = 0
            final_error = parse_error or "Feed contains no entries"
        elif len(articles) == 0:
            status = "failed"
            inserted_count = 0
            final_error = parse_error or "No valid article entries found in feed"
        elif parse_error is not None:
            status = "partial"
            inserted_count = persist_articles(conn, articles)
            final_error = parse_error
        else:
            status = "success"
            inserted_count = persist_articles(conn, articles)
            final_error = None

        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record_run(
            conn=conn,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            fetched=fetched_count,
            inserted=inserted_count,
            error=final_error,
        )

        return CollectionResult(
            status=status,
            fetched=fetched_count,
            inserted=inserted_count,
            error=final_error,
        )
    except Exception as exc:
        logger.exception("Unexpected exception during collection")
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        err_msg = f"Unexpected failure: {exc}"
        try:
            record_run(
                conn=conn,
                started_at=started_at,
                finished_at=finished_at,
                status="failed",
                fetched=0,
                inserted=0,
                error=err_msg,
            )
        except Exception:
            pass
        return CollectionResult(
            status="failed",
            fetched=0,
            inserted=0,
            error=err_msg,
        )
    finally:
        if close_conn:
            conn.close()


def main() -> None:
    """CLI entrypoint for collector."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    feed_url = get_feed_url()
    print(f"Starting collector run for: {feed_url}")
    result = collect(feed_url)
    print(
        f"Collector completed with status='{result.status}': "
        f"fetched={result.fetched}, inserted={result.inserted}, error={result.error}"
    )
    if result.status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
