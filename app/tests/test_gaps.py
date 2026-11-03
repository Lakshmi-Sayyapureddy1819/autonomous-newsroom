"""Multiple RSS feeds and sanitized run errors (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from newsroom import collector
from newsroom.collector import DEFAULT_FEED_URL, get_feed_urls
from newsroom.db import get_connection, init_db
from newsroom.sanitize import MAX_ERROR_LENGTH, SECRET_ENV_VARS, sanitize_error

FIXTURES = Path(__file__).parent / "fixtures"


def test_feed_urls_default_and_single(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSROOM_FEED_URLS", raising=False)
    monkeypatch.delenv("NEWSROOM_FEED_URL", raising=False)
    assert get_feed_urls() == [DEFAULT_FEED_URL]
    monkeypatch.setenv("NEWSROOM_FEED_URL", "https://one.example/rss")
    assert get_feed_urls() == ["https://one.example/rss"]


def test_feed_urls_list_dedups_and_ignores_junk(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEWSROOM_FEED_URLS",
        "https://a.example/rss, https://b.example/rss\nhttps://a.example/rss  not-a-url,",
    )
    assert get_feed_urls() == ["https://a.example/rss", "https://b.example/rss"]


def test_main_collects_every_feed_and_survives_one_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "multi.sqlite3"
    init_db(db)
    monkeypatch.setenv("NEWSROOM_DB", str(db))
    monkeypatch.setenv("NEWSROOM_HN_ENABLED", "0")
    monkeypatch.setenv("NEWSROOM_FEED_URLS", "https://bad.example/rss,https://good.example/rss")
    good = (FIXTURES / "feed_valid.xml").read_bytes()

    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "bad.example":
            return httpx.Response(500)
        return httpx.Response(200, content=good)

    real_client = httpx.Client
    monkeypatch.setattr(
        collector.httpx, "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(collector, "load_env", lambda *a, **k: None)
    collector.main()  # must not exit: one feed succeeded

    conn = get_connection(db)
    statuses = sorted(r["status"] for r in conn.execute("SELECT status FROM runs"))
    conn.close()
    assert statuses == ["failed", "success"]


def test_sanitize_masks_tokens_bearer_and_url_keys() -> None:
    # All fake values are assembled at runtime so no credential-shaped literal is committed.
    bearer, vendor_key = "abcd" + "efgh12345678", "sk" + "-" + "proj-AbCdEf123456"
    url_secret, gh_token = "SECRET" + "VALUE", "gh" + "p_" + "abcdefgh12345"
    text = (
        f"401 Bearer {bearer} key {vendor_key} "
        f"https://x.example/v1?{'api' + '_key'}={url_secret}&x=1 {gh_token}"
    )
    out = sanitize_error(text) or ""
    for leaked in (bearer, vendor_key, url_secret, gh_token):
        assert leaked not in out
    assert "[redacted]" in out


def test_sanitize_masks_configured_secret_and_strips_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = "-".join(["odd", "shape", "9"])  # built at runtime: not a real credential
    monkeypatch.setenv(SECRET_ENV_VARS[0], fake)
    out = sanitize_error(f"bad {fake}\n<html><b>boom</b></html>\n\ttrace") or ""
    assert fake not in out
    assert "<" not in out and "\n" not in out
    assert out == "bad [redacted] boom trace"


def test_sanitize_truncates_and_keeps_none() -> None:
    assert sanitize_error(None) is None
    out = sanitize_error("x" * 5000) or ""
    assert len(out) <= MAX_ERROR_LENGTH


def test_run_error_is_sanitized_when_recorded(tmp_path: Path) -> None:
    db = tmp_path / "s.sqlite3"
    init_db(db)
    conn = get_connection(db)
    token = "abcd" + "efgh12345678"
    collector.record_run(conn, "t0", "t1", "failed", 0, 0, f"denied Bearer {token}")
    row = conn.execute("SELECT error FROM runs").fetchone()
    conn.close()
    assert token not in row["error"]
