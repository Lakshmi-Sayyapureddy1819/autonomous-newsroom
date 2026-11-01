from __future__ import annotations

import datetime
import sqlite3
from typing import Annotated, Generator

from fastapi import Depends, FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from newsroom.db import get_connection

# Initialize FastAPI app
SITE_NAME = "Autonomous Newsroom"
SITE_TAGLINE = "Your AI-powered news aggregator"

app = FastAPI()

# Mount static files
app.mount("/static", StaticFiles(directory="app/newsroom/static"), name="static")

# Configure Jinja2 templates
templates = Jinja2Templates(directory="app/newsroom/templates")
templates.globals["SITE_NAME"] = SITE_NAME
templates.globals["SITE_TAGLINE"] = SITE_TAGLINE

# Constants
DEFAULT_LIMIT = 20


# Database dependency
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
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


@app.get("/", response_class=HTMLResponse)
async def homepage(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
    try:
        articles = conn.execute(
            "SELECT title, url, summary, tag, published_at FROM articles "
            "WHERE summary IS NOT NULL AND trim(summary) != '' ORDER BY published_at DESC LIMIT ?",
            (DEFAULT_LIMIT,),
        ).fetchall()
        articles_hashable = tuple(tuple(item.items()) for item in articles)

        last_run_timestamp_row = conn.execute(
            """
            SELECT finished_at FROM runs
            WHERE status = 'success'
            ORDER BY finished_at DESC LIMIT 1
            """
        ).fetchone()
        last_updated_message = None
        if last_run_timestamp_row:
            last_updated_message = format_time_ago(last_run_timestamp_row["finished_at"])

        context_data = {
            "articles": articles_hashable,
            "last_updated_message": last_updated_message,
            "current_year": datetime.datetime.now().year,
        }
        return templates.TemplateResponse(
            request,
            "index.html",
            context_data,
        )
    finally:
        # Connection is now managed by FastAPI dependency, no need to close here
        pass


@app.get("/rss.xml", response_class=Response)
async def rss_feed(request: Request, conn: Annotated[sqlite3.Connection, Depends(get_db)]):
    try:
        articles = conn.execute(
            "SELECT title, url, summary, tag, published_at FROM articles "
            "WHERE summary IS NOT NULL AND trim(summary) != '' ORDER BY published_at DESC LIMIT ?",
            (DEFAULT_LIMIT,),
        ).fetchall()
        articles_hashable = tuple(tuple(item.items()) for item in articles)

        last_run_timestamp_row = conn.execute(
            """
            SELECT finished_at FROM runs
            WHERE status = 'success'
            ORDER BY finished_at DESC LIMIT 1
            """
        ).fetchone()
        last_build_date = None
        if last_run_timestamp_row:
            last_build_date = datetime.datetime.fromisoformat(
                last_run_timestamp_row["finished_at"]
            ).strftime("%a, %d %b %Y %H:%M:%S %z")

        # Basic RSS 2.0 structure
        # Need to implement proper templating for RSS
        base_url = str(request.base_url)
        context_data = {
            "articles": articles_hashable,
            "last_build_date": last_build_date,
            "base_url": base_url,
        }
        content = templates.TemplateResponse(
            request,
            "rss.xml",
            context_data,
        )
        return Response(content=content.body, media_type="application/rss+xml")
    finally:
        # Connection is now managed by FastAPI dependency, no need to close here
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
