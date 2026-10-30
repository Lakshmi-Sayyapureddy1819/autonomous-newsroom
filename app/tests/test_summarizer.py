"""Unit and integration tests for newsroom summarizer module."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from newsroom.db import get_connection, init_db
from newsroom.summarizer import (
    DEFAULT_FALLBACK_BASE_URL,
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_LIMIT,
    DEFAULT_PRIMARY_BASE_URL,
    DEFAULT_PRIMARY_MODEL,
    get_fallback_config,
    get_limit,
    get_primary_config,
    parse_summary_response,
    summarize,
)


def seed_article(conn, url: str, title: str, summary: str | None = None) -> int:
    with conn:
        cur = conn.execute(
            """
            INSERT INTO articles (url, title, source, published_at, summary)
            VALUES (?, ?, 'TestSource', '2026-10-30T10:00:00+00:00', ?)
            """,
            (url, title, summary),
        )
        return cur.lastrowid


def make_chat_response(content: str) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1793290000,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def test_config_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEWSROOM_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("NEWSROOM_LLM_MODEL", raising=False)
    monkeypatch.delenv("NEWSROOM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NEWSROOM_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("NEWSROOM_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("NEWSROOM_FALLBACK_API_KEY", raising=False)
    monkeypatch.delenv("NEWSROOM_SUMMARIZE_LIMIT", raising=False)

    p = get_primary_config()
    assert p.base_url == DEFAULT_PRIMARY_BASE_URL.rstrip("/")
    assert p.model == DEFAULT_PRIMARY_MODEL
    assert not p.is_configured

    f = get_fallback_config()
    assert f.base_url == DEFAULT_FALLBACK_BASE_URL.rstrip("/")
    assert f.model == DEFAULT_FALLBACK_MODEL
    assert not f.is_configured

    assert get_limit() == DEFAULT_LIMIT


def test_parse_summary_response() -> None:
    # Valid JSON with known tag
    valid_json = '{"summary": "A breakthrough in AI chips.", "tag": "Hardware"}'
    s, t = parse_summary_response(valid_json)
    assert s == "A breakthrough in AI chips."
    assert t == "Other"  # Hardware not in VALID_TAGS, normalized to Other

    # Valid JSON with known tag
    valid_json2 = '{"summary": "New LLM reasoning model released.", "tag": "LLMs"}'
    s2, t2 = parse_summary_response(valid_json2)
    assert s2 == "New LLM reasoning model released."
    assert t2 == "LLMs"

    # Markdown fence wrapped JSON
    fenced = '```json\n{"summary": "Fenced summary test.", "tag": "Research"}\n```'
    s3, t3 = parse_summary_response(fenced)
    assert s3 == "Fenced summary test."
    assert t3 == "Research"

    # Plain text / malformed JSON
    plain = "This is a plain text summary that is not JSON."
    s4, t4 = parse_summary_response(plain)
    assert s4 == "This is a plain text summary that is not JSON."
    assert t4 == "Other"

    # Long summary truncated to 160 chars
    long_text = "A" * 200
    s5, _ = parse_summary_response(json.dumps({"summary": long_text, "tag": "Tools"}))
    assert len(s5) <= 160
    assert s5.endswith("...")


def test_summarize_zero_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "zero.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")

    res = summarize(conn=conn)
    assert res.status == "success"
    assert res.fetched == 0
    assert res.summarized == 0
    assert res.error is None

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "success"
    assert runs["fetched"] == 0
    assert runs["summarized"] == 0
    assert runs["error"] is None

    conn.close()


def test_summarize_neither_provider_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "no_keys.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "Article One")

    monkeypatch.delenv("NEWSROOM_LLM_API_KEY", raising=False)
    monkeypatch.delenv("NEWSROOM_FALLBACK_API_KEY", raising=False)

    res = summarize(conn=conn)
    assert res.status == "failed"
    assert res.fetched == 1
    assert res.summarized == 0
    assert "Configuration error" in (res.error or "")

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "failed"
    assert "Configuration error" in runs["error"]

    conn.close()


def test_summarize_primary_missing_fallback_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "fb_direct.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "Article One")

    monkeypatch.delenv("NEWSROOM_LLM_API_KEY", raising=False)
    monkeypatch.setenv("NEWSROOM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("NEWSROOM_FALLBACK_MODEL", "fallback-model-v1")

    payload = make_chat_response('{"summary": "Fallback direct summary", "tag": "Industry"}')
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 1
    assert res.summarized == 1

    art = conn.execute("SELECT * FROM articles WHERE id = 1").fetchone()
    assert art["summary"] == "Fallback direct summary"
    assert art["tag"] == "Industry"
    assert art["summary_model"] == "fallback-model-v1"

    conn.close()


def test_summarize_primary_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "pri_success.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "AI News 1")
    seed_article(conn, "https://example.com/art2", "AI News 2")

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")
    monkeypatch.setenv("NEWSROOM_LLM_MODEL", "primary-model-v1")

    payload = make_chat_response('{"summary": "Primary summary", "tag": "Policy"}')
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 2
    assert res.summarized == 2

    articles = conn.execute("SELECT * FROM articles ORDER BY id ASC").fetchall()
    for art in articles:
        assert art["summary"] == "Primary summary"
        assert art["tag"] == "Policy"
        assert art["summary_model"] == "primary-model-v1"

    conn.close()


def test_summarize_primary_429_fallback_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "pri_429.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "AI Rate Limit Test")

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")
    monkeypatch.setenv("NEWSROOM_LLM_MODEL", "primary-model")
    monkeypatch.setenv("NEWSROOM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("NEWSROOM_FALLBACK_MODEL", "fallback-model")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if "primary-key" in auth:
            return httpx.Response(429, json={"error": "Rate limit exceeded"})
        if "fallback-key" in auth:
            return httpx.Response(
                200, json=make_chat_response('{"summary": "Fallback after 429", "tag": "Tools"}')
            )
        return httpx.Response(400)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 1
    assert res.summarized == 1

    art = conn.execute("SELECT * FROM articles WHERE id = 1").fetchone()
    assert art["summary"] == "Fallback after 429"
    assert art["tag"] == "Tools"
    assert art["summary_model"] == "fallback-model"

    conn.close()


def test_summarize_primary_402_fallback_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "pri_402.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "AI Payment Required Test")

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")
    monkeypatch.setenv("NEWSROOM_LLM_MODEL", "primary-model")
    monkeypatch.setenv("NEWSROOM_FALLBACK_API_KEY", "fallback-key")
    monkeypatch.setenv("NEWSROOM_FALLBACK_MODEL", "fallback-model")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization", "")
        if "primary-key" in auth:
            return httpx.Response(402, json={"error": "Insufficient credits"})
        if "fallback-key" in auth:
            return httpx.Response(
                200, json=make_chat_response('{"summary": "Fallback after 402", "tag": "Research"}')
            )
        return httpx.Response(400)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 1
    assert res.summarized == 1

    art = conn.execute("SELECT * FROM articles WHERE id = 1").fetchone()
    assert art["summary"] == "Fallback after 402"
    assert art["tag"] == "Research"
    assert art["summary_model"] == "fallback-model"

    conn.close()


def test_summarize_both_fail_partial_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "both_fail.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "Both Providers Fail")

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")
    monkeypatch.setenv("NEWSROOM_FALLBACK_API_KEY", "fallback-key")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Rate limited everywhere"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "partial"
    assert res.fetched == 1
    assert res.summarized == 0

    art = conn.execute("SELECT * FROM articles WHERE id = 1").fetchone()
    assert art["summary"] is None
    assert art["tag"] is None
    assert art["summary_model"] is None

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    assert runs["status"] == "partial"
    assert runs["summarized"] == 0

    conn.close()


def test_summarize_skips_already_summarized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "skip.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    # 1 already summarized, 1 unsummarized
    seed_article(conn, "https://example.com/art1", "Old Article", summary="Already done")
    seed_article(conn, "https://example.com/art2", "New Article", summary=None)

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")

    payload = make_chat_response('{"summary": "Newly summarized", "tag": "LLMs"}')
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 1
    assert res.summarized == 1

    art1 = conn.execute("SELECT * FROM articles WHERE id = 1").fetchone()
    assert art1["summary"] == "Already done"

    art2 = conn.execute("SELECT * FROM articles WHERE id = 2").fetchone()
    assert art2["summary"] == "Newly summarized"

    conn.close()


def test_summarize_respects_batch_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "limit.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    for i in range(5):
        seed_article(conn, f"https://example.com/art{i}", f"Article {i}")

    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", "primary-key")
    monkeypatch.setenv("NEWSROOM_SUMMARIZE_LIMIT", "2")

    payload = make_chat_response('{"summary": "Batch test summary", "tag": "Other"}')
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)

    res = summarize(conn=conn, client=client)
    assert res.status == "success"
    assert res.fetched == 2
    assert res.summarized == 2

    summarized_count = conn.execute(
        "SELECT count(*) as c FROM articles WHERE summary IS NOT NULL"
    ).fetchone()["c"]
    assert summarized_count == 2

    conn.close()


def test_summarize_scrubs_secrets_from_error_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "scrub.sqlite3"
    init_db(db_path)
    conn = get_connection(db_path)

    seed_article(conn, "https://example.com/art1", "Secret Leak Test")

    secret_key = "super-secret-agent-key-12345"
    monkeypatch.setenv("NEWSROOM_LLM_API_KEY", secret_key)
    monkeypatch.delenv("NEWSROOM_FALLBACK_API_KEY", raising=False)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"Server crashed with internal error")

    transport = httpx.MockTransport(mock_handler)
    client = httpx.Client(transport=transport)

    summarize(conn=conn, client=client)

    runs = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    error_text = runs["error"] or ""
    assert secret_key not in error_text

    conn.close()
