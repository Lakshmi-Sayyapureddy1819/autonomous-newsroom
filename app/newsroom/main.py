from __future__ import annotations

import datetime
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Generator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

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

# Constants
DEFAULT_LIMIT = 20


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

    seconds = int(diff.total_seconds())
    if seconds < 60:
        return f"{seconds} seconds ago"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hours ago"
    days = hours // 24
    return f"{days} days ago"


def fetch_articles(conn: sqlite3.Connection) -> list[dict]:
    """Return the most recent articles as dicts with a parsed ``published_at`` datetime."""
    rows = conn.execute(
        "SELECT title, url, source, summary, description, tag, published_at FROM articles "
        "ORDER BY published_at DESC LIMIT ?",
        (DEFAULT_LIMIT,),
    ).fetchall()
    articles = []
    for row in rows:
        article = dict(row)
        article["published_at"] = datetime.datetime.fromisoformat(article["published_at"])
        articles.append(article)
    return articles


def last_successful_run(conn: sqlite3.Connection) -> str | None:
    """Return the ``finished_at`` timestamp of the latest successful run, if any."""
    row = conn.execute(
        "SELECT finished_at FROM runs WHERE status = 'success' AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    return row["finished_at"] if row else None


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
    finished_at = last_successful_run(conn)
    context_data = {
        "articles": fetch_articles(conn),
        "last_updated_message": format_time_ago(finished_at) if finished_at else None,
        "current_year": datetime.datetime.now().year,
    }
    return templates.TemplateResponse(request, "index.html", context_data)


@app.get("/rss.xml", response_class=Response)
def rss_feed(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
    finished_at = last_successful_run(conn)
    last_build_date = None
    if finished_at:
        last_build_date = datetime.datetime.fromisoformat(finished_at).strftime(
            "%a, %d %b %Y %H:%M:%S %z"
        )
    content = templates.TemplateResponse(
        request,
        "rss.xml",
        {"articles": fetch_articles(conn), "last_build_date": last_build_date},
    )
    return Response(content=content.body, media_type="application/rss+xml")


@app.get("/rss.xsl", response_class=Response)
def rss_stylesheet():
    """XSLT that makes /rss.xml readable in a browser; feed readers ignore it."""
    xsl = (TEMPLATES_DIR / "rss.xsl").read_bytes()
    return Response(content=xsl, media_type="text/xsl")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
