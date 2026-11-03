from __future__ import annotations

import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsroom.db import get_connection, init_db
from newsroom.main import SITE_NAME, SITE_TAGLINE, app, strip_source_suffix


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
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
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


def test_rss_feed_is_a_styled_page_for_browsers_and_xml_for_feed_readers(
    client: TestClient, db_path: Path
) -> None:
    seed(
        db_path,
        [
            (
                "https://a.example/1",
                "Feed Story",
                "2026-10-30T10:00:00+00:00",
                "A summary.",
                None,
                "Tools",
            )
        ],
        run_finished_at=recent(3),
    )
    browser = client.get("/rss.xml", headers={"accept": "text/html,application/xhtml+xml"})
    assert "text/html" in browser.headers["content-type"]
    assert 'class="masthead"' in browser.text  # same layout as every other page
    assert "Feed Story" in browser.text and "A summary." in browser.text
    assert "View the raw XML" in browser.text and "rss.xml?format=xml" in browser.text

    for accept in ("application/rss+xml, application/xml;q=0.9, */*;q=0.8", "*/*"):
        reader = client.get("/rss.xml", headers={"accept": accept})
        assert reader.headers["content-type"] == "application/xml; charset=utf-8"
        assert ET.fromstring(reader.text).findall("./channel/item")[0].findtext("title") == (
            "Feed Story"
        )

    forced = client.get("/rss.xml?format=xml", headers={"accept": "text/html"})
    assert forced.headers["content-type"].startswith("application/xml")
    assert "xml-stylesheet" not in forced.text  # no XSLT: browsers are removing support
    assert client.get("/rss.xsl").status_code == 404


def test_homepage_strips_source_suffix_and_shows_stats(client: TestClient, db_path: Path) -> None:
    seed(
        db_path,
        [("https://a.example/1", "Big News - Example News", "2026-10-30T10:00:00+00:00",
          "Short summary.", None, "Policy")],
    )
    text = client.get("/").text
    assert "<h2><a" in text and ">Big News</a>" in text
    assert "Big News - Example News" not in text
    assert "Stories collected" in text
    assert "AI summary" in text


def test_format_time_ago_singular_and_plural() -> None:
    from newsroom.main import format_time_ago

    def iso(**delta: int) -> str:
        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - datetime.timedelta(**delta)).isoformat()

    assert format_time_ago(iso(hours=1, minutes=1)) == "1 hour ago"
    assert format_time_ago(iso(hours=3, minutes=1)) == "3 hours ago"
    assert format_time_ago(iso(minutes=1, seconds=5)) == "1 minute ago"
    assert format_time_ago(iso(days=1, minutes=1)) == "1 day ago"


def test_homepage_does_not_expose_summarizer_model(client: TestClient, db_path: Path) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO articles (url, title, source, published_at, summary, summary_model) "
            "VALUES ('https://a.example/m', 'Model Story', 'Example News', "
            "'2026-10-30T10:00:00+00:00', 'A summary.', 'gemini-2.5-flash')"
        )
    conn.close()
    text = client.get("/").text
    assert "A summary." in text
    assert "gemini" not in text.lower()


def test_homepage_tag_filter_and_search_cover_all_articles(
    client: TestClient, db_path: Path
) -> None:
    rows = [
        (f"https://a.example/{i}", f"Story {i}", f"2026-10-{(i % 28) + 1:02d}T10:00:00+00:00",
         "summary", None, "Policy" if i % 2 else "Research")
        for i in range(60)
    ]
    rows.append(("https://a.example/rare", "Quantum widget breakthrough",
                 "2026-01-01T00:00:00+00:00", "old but findable", None, "Tools"))
    seed(db_path, rows)

    # An old story outside the newest 20 is still found by search and by tag.
    assert "Quantum widget breakthrough" in client.get("/?q=quantum").text
    assert "Quantum widget breakthrough" in client.get("/?tag=tools").text
    filtered = client.get("/?tag=Policy").text
    assert "Research</a>" in filtered  # chips list every tag
    assert "No stories match" not in filtered
    nothing = client.get("/?q=zzzznomatch").text
    assert "No stories match your filters" in nothing
    assert "No Articles Available" not in nothing
    # LIKE wildcards are matched literally, not as patterns.
    assert "No stories match your filters" in client.get("/?q=%25").text


def test_rss_feed_can_filter_by_tag(client: TestClient, db_path: Path) -> None:
    seed(db_path, [
        ("https://a.example/1", "Policy Story", "2026-10-30T10:00:00+00:00", "s", None, "Policy"),
        ("https://a.example/2", "Tools Story", "2026-10-30T09:00:00+00:00", "s", None, "Tools"),
    ])
    items = ET.fromstring(client.get("/rss.xml?tag=policy").text).findall("./channel/item")
    assert [i.findtext("title") for i in items] == ["Policy Story"]


def test_runs_page_lists_runs_and_handles_empty(client: TestClient, db_path: Path) -> None:
    assert "No runs yet" in client.get("/runs").text
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO runs (started_at, finished_at, status, fetched, inserted, summarized, "
            "error)"
            " VALUES (?, ?, 'partial', 20, 3, 0, 'feed warning')",
            (recent(10), recent(9)),
        )
    conn.close()
    response = client.get("/runs")
    assert response.status_code == 200
    assert "badge-partial" in response.text
    assert "feed warning" in response.text
    assert "10 minutes ago" in response.text


def test_homepage_paginates_through_all_stories(client: TestClient, db_path: Path) -> None:
    rows = [
        (f"https://a.example/{i}", f"Headline {i:02d}",
         f"2026-10-{(i // 24) + 1:02d}T{i % 24:02d}:00:00+00:00", "summary", None, "Policy")
        for i in range(45)
    ]
    seed(db_path, rows)

    first = client.get("/").text
    assert "Page 1 of 3" in first and "Older stories" in first
    assert "Headline 44" in first and "Headline 00" not in first

    last = client.get("/?page=3").text
    assert "Page 3 of 3" in last and "Older stories" not in last
    assert "Headline 00" in last and "Newer" in last
    assert "Top stories" not in last  # the top-stories layout only appears on page 1

    # Pagination keeps the active filters, and a huge/invalid page is harmless.
    assert "tag=Policy" in client.get("/?tag=Policy").text
    assert client.get("/?page=9999").status_code == 200


def test_homepage_topic_and_source_charts(client: TestClient, db_path: Path) -> None:
    seed(db_path, [
        ("https://a.example/1", "One", "2026-10-30T10:00:00+00:00", "s", None, "Policy"),
        ("https://a.example/2", "Two", "2026-10-30T09:00:00+00:00", "s", None, "Policy"),
        ("https://a.example/3", "Three", "2026-10-30T08:00:00+00:00", "s", None, "Tools"),
    ])
    text = client.get("/").text
    assert "Coverage by topic" in text and "Top sources" in text
    assert 'aria-label="Policy: 2 stories, 67 percent"' in text
    assert "View as table" in text
    # The charts only appear on the unfiltered first page.
    assert "Coverage by topic" not in client.get("/?tag=Policy").text


def test_unknown_page_shows_branded_404_for_browsers_and_json_for_apis(client: TestClient) -> None:
    html = client.get("/no-such-page", headers={"accept": "text/html,application/xhtml+xml"})
    assert html.status_code == 404
    assert "Page not found" in html.text
    assert "Back to the newsroom" in html.text
    assert 'id="theme-toggle"' in html.text  # same header/theme as the other pages

    api = client.get("/no-such-page", headers={"accept": "application/json"})
    assert api.status_code == 404
    assert api.json() == {"detail": "Not Found"}


def test_all_html_pages_share_the_same_layout(client: TestClient) -> None:
    for path in ("/", "/runs", "/no-such-page"):
        text = client.get(path, headers={"accept": "text/html"}).text
        assert 'class="masthead"' in text, path
        assert "Subscribe via RSS" in text, path  # footer link
        assert "data-theme" in text, path


def test_rss_feed_channel_link_uses_request_base_url(client: TestClient) -> None:
    response = client.get("/rss.xml")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    channel = ET.fromstring(response.text).find("channel")
    assert channel is not None
    assert channel.findtext("link") == "http://testserver/"


def test_brand_name_and_tagline_appear_everywhere(client: TestClient) -> None:
    for path in ("/", "/runs", "/no-such-page"):
        text = client.get(path, headers={"accept": "text/html"}).text
        assert "<title>" in text and SITE_NAME in text, path
        assert SITE_TAGLINE in text, path
        assert "Autonomous Newsroom" not in text, path


def test_rss_channel_uses_brand_name(client: TestClient) -> None:
    text = client.get("/rss.xml").text
    assert f"<title>{SITE_NAME}</title>" in text
    assert "Autonomous Newsroom" not in text


def test_synapse_logo_assets_are_served_and_linked(client: TestClient) -> None:
    page = client.get("/", headers={"accept": "text/html"}).text
    for name in (
        "synapse-logo.svg",
        "synapse-logo.png",
        "synapse-wordmark-light.svg",
        "synapse-wordmark-dark.svg",
    ):
        assert f"/static/brand/{name}" in page, name
        response = client.get(f"/static/brand/{name}")
        assert response.status_code == 200, name
        assert len(response.content) > 0, name

def test_strip_source_suffix_regression() -> None:
    # Test cases where the suffix should be stripped
    assert strip_source_suffix("Headline - Source", "Source") == "Headline"
    assert strip_source_suffix(
        "Another Headline - Another Source", "Another Source") == "Another Headline"
    assert strip_source_suffix(
        "Long Headline Text - My News Source", "My News Source") == "Long Headline Text"

    # Test cases where the suffix should NOT be stripped
    # (no suffix, different suffix, source not matching suffix)
    assert strip_source_suffix(
        "Headline with no suffix", "Source") == "Headline with no suffix"
    assert strip_source_suffix(
        "Headline - Other Source", "My Source") == "Headline - Other Source"
    assert strip_source_suffix("Headline - Source X", "Source Y") == "Headline - Source X"
    assert strip_source_suffix("Short - S", "S") == "Short"  # Very short title/source
    assert strip_source_suffix("Source", "Source") == "Source"  # Title is just source

    # Test with empty source
    assert strip_source_suffix("Headline - ", "") == "Headline - "
    assert strip_source_suffix("Headline", "") == "Headline"

    # Test with None source
    assert strip_source_suffix("Headline - Source", None) == "Headline - Source"
    assert strip_source_suffix("Headline", None) == "Headline"
