from __future__ import annotations

import datetime
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Generator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from newsroom.db import get_connection
from newsroom.env import load_env


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load .env at server startup (not at import, so tests are unaffected).
    load_env()
    yield


# Initialize FastAPI app
app = FastAPI(lifespan=lifespan)

# Configure Jinja2 templates
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

ERROR_COPY = {
    404: ("Page not found", "We couldn't find that page. It may have moved, or the link is wrong."),
    405: ("Method not allowed", "That page doesn't support this kind of request."),
}


@app.exception_handler(StarletteHTTPException)
async def http_error_page(request: Request, exc: StarletteHTTPException):
    """Branded HTML error page for browsers; plain JSON for API-style clients."""
    if "text/html" not in request.headers.get("accept", ""):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    title, message = ERROR_COPY.get(
        exc.status_code, ("Something went wrong", "An unexpected error occurred. Please try again.")
    )
    context = {
        "code": exc.status_code,
        "title": title,
        "message": message,
        "current_year": datetime.datetime.now().year,
    }
    return templates.TemplateResponse(request, "errors.html", context, status_code=exc.status_code)


# Constants
DEFAULT_LIMIT = 20

# Emoji and hue (0-360) used to generate cover art and colors for each topic tag.
TAG_META = {
    "llms": ("🧠", 262),
    "research": ("🔬", 160),
    "industry": ("🏭", 220),
    "policy": ("⚖️", 32),
    "tools": ("🛠️", 320),
    "other": ("📰", 205),
}
DEFAULT_TAG_META = ("📰", 205)


# Database dependency
def get_db() -> Generator[sqlite3.Connection, None, None]:
    # FastAPI runs this dependency and the endpoint in different worker threads.
    conn = get_connection(check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


# Helper function to format "Updated X ago"
def format_time_ago(dt: str) -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    article_dt = datetime.datetime.fromisoformat(dt)
    diff = now - article_dt

    def ago(count: int, unit: str) -> str:
        return f"{count} {unit}{'' if count == 1 else 's'} ago"

    seconds = max(0, int(diff.total_seconds()))
    if seconds < 60:
        return ago(seconds, "second")
    minutes = seconds // 60
    if minutes < 60:
        return ago(minutes, "minute")
    hours = minutes // 60
    if hours < 24:
        return ago(hours, "hour")
    return ago(hours // 24, "day")


LIKE_ESCAPE = chr(92)  # backslash


def _like(term: str) -> str:
    """Build a LIKE pattern that matches ``term`` literally anywhere in a column."""
    for ch in (LIKE_ESCAPE, "%", "_"):
        term = term.replace(ch, LIKE_ESCAPE + ch)
    return f"%{term}%"


def _filter_clause(tag: str | None, q: str | None) -> tuple[str, list]:
    """SQL WHERE clause (and params) for the topic-tag filter and the search term."""
    where, params = [], []
    if tag:
        where.append("tag = ? COLLATE NOCASE")
        params.append(tag)
    if q:
        like = f"LIKE ? ESCAPE '{LIKE_ESCAPE}'"
        where.append(f"(title {like} OR summary {like} OR source {like})")
        params.extend([_like(q)] * 3)
    return (f"WHERE {' AND '.join(where)} " if where else ""), params


def count_articles(conn: sqlite3.Connection, tag: str | None = None, q: str | None = None) -> int:
    clause, params = _filter_clause(tag, q)
    return conn.execute(f"SELECT COUNT(*) FROM articles {clause}", params).fetchone()[0]


def fetch_articles(
    conn: sqlite3.Connection,
    tag: str | None = None,
    q: str | None = None,
    page: int = 1,
) -> list[dict]:
    """Return one page of articles as dicts with a parsed ``published_at`` datetime.

    ``tag`` filters by topic tag (case-insensitive); ``q`` searches titles, summaries and
    sources across all stored articles; ``page`` is 1-based (DEFAULT_LIMIT per page).
    """
    clause, params = _filter_clause(tag, q)
    rows = conn.execute(
        "SELECT title, url, source, summary, summary_model, description, tag, published_at "
        f"FROM articles {clause}ORDER BY published_at DESC LIMIT ? OFFSET ?",
        (*params, DEFAULT_LIMIT, (max(page, 1) - 1) * DEFAULT_LIMIT),
    ).fetchall()
    articles = []
    for row in rows:
        article = dict(row)
        article["published_at"] = datetime.datetime.fromisoformat(article["published_at"])
        article["display_title"] = strip_source_suffix(article["title"], article["source"])
        article["ago"] = format_time_ago(article["published_at"].isoformat())
        article["hue"] = sum(ord(ch) for ch in article["source"]) * 37 % 360
        article["initial"] = article["source"][:1].upper() or "?"
        emoji, tag_hue = TAG_META.get((article["tag"] or "").lower(), DEFAULT_TAG_META)
        article["emoji"], article["tag_hue"] = emoji, tag_hue
        articles.append(article)
    return articles


def strip_source_suffix(title: str, source: str) -> str:
    """Google News appends ' - Source' to headlines; drop it when it repeats the source."""
    suffix = f" - {source}"
    if source and title.endswith(suffix) and len(title) > len(suffix):
        return title[: -len(suffix)]
    return title


def fetch_stats(conn: sqlite3.Connection) -> dict:
    """Totals shown in the page header."""
    row = conn.execute(
        "SELECT COUNT(*) AS total, COUNT(DISTINCT source) AS sources, "
        "SUM(summary IS NOT NULL AND trim(summary) != '') AS summarized FROM articles"
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "sources": row["sources"] or 0,
        "summarized": row["summarized"] or 0,
    }


def fetch_tags(conn: sqlite3.Connection) -> list[str]:
    """Distinct topic tags currently in use, alphabetical."""
    rows = conn.execute(
        "SELECT DISTINCT tag FROM articles WHERE tag IS NOT NULL AND trim(tag) != '' "
        "ORDER BY tag COLLATE NOCASE"
    ).fetchall()
    return [row["tag"] for row in rows]


def fetch_tag_counts(conn: sqlite3.Connection) -> list[dict]:
    """Topic tags with story counts (most common first), for the topic tiles."""
    rows = conn.execute(
        "SELECT tag, COUNT(*) AS n FROM articles WHERE tag IS NOT NULL AND trim(tag) != '' "
        "GROUP BY tag COLLATE NOCASE ORDER BY n DESC, tag COLLATE NOCASE"
    ).fetchall()
    result = []
    for row in rows:
        emoji, hue = TAG_META.get(row["tag"].lower(), DEFAULT_TAG_META)
        result.append({"tag": row["tag"], "count": row["n"], "emoji": emoji, "hue": hue})
    return result


def fetch_source_counts(conn: sqlite3.Connection, limit: int = 6) -> list[dict]:
    """Sources with the most stories, for the 'top sources' chart."""
    rows = conn.execute(
        "SELECT source, COUNT(*) AS n FROM articles GROUP BY source "
        "ORDER BY n DESC, source COLLATE NOCASE LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"name": row["source"], "count": row["n"]} for row in rows]


def last_successful_run(conn: sqlite3.Connection) -> str | None:
    """Return the ``finished_at`` timestamp of the latest successful run, if any."""
    row = conn.execute(
        "SELECT finished_at FROM runs WHERE status = 'success' AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return row["finished_at"] if row else None


@app.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    tag: str | None = None,
    q: str | None = None,
    page: int = 1,
):
    page = max(1, min(page, 500))
    tag = (tag or "").strip() or None
    q = (q or "").strip()[:100] or None
    finished_at = last_successful_run(conn)
    context_data = {
        "active": "home",
        "tags": fetch_tags(conn),
        "tag_counts": fetch_tag_counts(conn),
        "selected_tag": tag,
        "q": q,
        "articles": fetch_articles(conn, tag, q, page),
        "total": (total := count_articles(conn, tag, q)),
        "page": page,
        "pages": max(1, -(-total // DEFAULT_LIMIT)),
        "source_counts": fetch_source_counts(conn),
        "stats": fetch_stats(conn),
        "last_updated_message": format_time_ago(finished_at) if finished_at else None,
        "current_year": datetime.datetime.now().year,
    }
    return templates.TemplateResponse(request, "index.html", context_data)


@app.get("/rss.xml", response_class=Response)
def rss_feed(
    request: Request,
    conn: Annotated[sqlite3.Connection, Depends(get_db)],
    tag: str | None = None,
    format: str | None = None,
):
    """The RSS feed. Feed readers get XML; people opening it in a browser get a styled page.

    The page is chosen by content negotiation (browsers ask for text/html); ``?format=xml``
    always returns the raw XML.
    """
    tag = (tag or "").strip() or None
    finished_at = last_successful_run(conn)
    articles = fetch_articles(conn, tag)

    if "text/html" in request.headers.get("accept", "") and format != "xml":
        context = {
            "active": "rss",
            "articles": articles,
            "tag": tag,
            "feed_url": str(request.url.replace(query="", fragment="")),
            "last_updated_message": format_time_ago(finished_at) if finished_at else None,
            "current_year": datetime.datetime.now().year,
        }
        return templates.TemplateResponse(request, "feed.html", context)

    last_build_date = None
    if finished_at:
        last_build_date = datetime.datetime.fromisoformat(finished_at).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
    content = templates.TemplateResponse(
        request,
        "rss.xml",
        {
            "articles": articles,
            "last_build_date": last_build_date,
            "base_url": str(request.base_url),
        },
    )
    return Response(content=content.body, media_type="application/xml; charset=utf-8")


def format_duration(started_at: str, finished_at: str | None) -> str:
    if not finished_at:
        return "-"
    seconds = (
        datetime.datetime.fromisoformat(finished_at) - datetime.datetime.fromisoformat(started_at)
    ).total_seconds()
    return f"{seconds:.1f}s" if seconds < 60 else f"{int(seconds // 60)}m {int(seconds % 60)}s"


@app.get("/runs", response_class=HTMLResponse)
def runs_page(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
    """Run log: recent collector and summarizer runs."""
    rows = conn.execute(
        "SELECT started_at, finished_at, status, fetched, inserted, summarized, error "
        "FROM runs ORDER BY id DESC LIMIT 50"
    ).fetchall()
    runs = []
    for row in rows:
        run = dict(row)
        run["ago"] = format_time_ago(run["started_at"])
        run["duration"] = format_duration(run["started_at"], run["finished_at"])
        runs.append(run)
    finished_at = last_successful_run(conn)
    context_data = {
        "active": "runs",
        "runs": runs,
        "totals": {
            "runs": len(runs),
            "success": sum(r["status"] == "success" for r in runs),
            "inserted": sum(r["inserted"] or 0 for r in runs),
            "summarized": sum(r["summarized"] or 0 for r in runs),
        },
        "last_updated_message": format_time_ago(finished_at) if finished_at else None,
        "current_year": datetime.datetime.now().year,
    }
    return templates.TemplateResponse(request, "runs.html", context_data)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
