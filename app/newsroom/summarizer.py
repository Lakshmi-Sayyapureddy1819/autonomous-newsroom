"""LLM summarizer module with automated provider fallback for Autonomous Newsroom."""

from __future__ import annotations

import datetime
import json
import logging
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from typing import Optional

import httpx

from newsroom.db import get_connection

logger = logging.getLogger(__name__)

DEFAULT_PRIMARY_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_PRIMARY_MODEL = "openrouter/free"

DEFAULT_FALLBACK_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_FALLBACK_MODEL = "gemini-2.5-flash"

DEFAULT_LIMIT = 20

VALID_TAGS = {"LLMs", "Research", "Industry", "Policy", "Tools", "Other"}


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    model: str
    api_key: str

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())


@dataclass
class SummarizeResult:
    status: str  # 'success', 'partial', 'failed'
    fetched: int
    summarized: int
    error: Optional[str] = None


def get_primary_config() -> ProviderConfig:
    return ProviderConfig(
        name="primary",
        base_url=os.environ.get("NEWSROOM_LLM_BASE_URL", DEFAULT_PRIMARY_BASE_URL).rstrip("/"),
        model=os.environ.get("NEWSROOM_LLM_MODEL", DEFAULT_PRIMARY_MODEL),
        api_key=os.environ.get("NEWSROOM_LLM_API_KEY", "").strip(),
    )


def get_fallback_config() -> ProviderConfig:
    fallback_url = os.environ.get("NEWSROOM_FALLBACK_BASE_URL", DEFAULT_FALLBACK_BASE_URL)
    return ProviderConfig(
        name="fallback",
        base_url=fallback_url.rstrip("/"),
        model=os.environ.get("NEWSROOM_FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL),
        api_key=os.environ.get("NEWSROOM_FALLBACK_API_KEY", "").strip(),
    )


def get_limit() -> int:
    val = os.environ.get("NEWSROOM_SUMMARIZE_LIMIT", str(DEFAULT_LIMIT))
    try:
        return max(1, int(val))
    except ValueError:
        return DEFAULT_LIMIT


def parse_summary_response(content: str) -> tuple[str, str]:
    """Parse JSON or text completion into (summary, tag)."""
    clean = content.strip()
    # Remove markdown fences if present
    if clean.startswith("```"):
        lines = clean.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean = "\n".join(lines).strip()

    summary: Optional[str] = None
    tag: Optional[str] = None

    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            summary = data.get("summary")
            tag = data.get("tag")
    except Exception:
        # Fallback to regex extraction if JSON was wrapped in other text
        match = re.search(r"\{.*?\}", clean, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if isinstance(data, dict):
                    summary = data.get("summary")
                    tag = data.get("tag")
            except Exception:
                pass

    if not summary or not isinstance(summary, str):
        summary = clean.splitlines()[0] if clean else "Summary unavailable."

    # Normalize summary to single line and cap at 160 chars
    summary = " ".join(summary.split()).strip()
    if len(summary) > 160:
        summary = summary[:157].rstrip() + "..."

    # Normalize tag to fixed taxonomy
    if not tag or not isinstance(tag, str):
        tag = "Other"
    else:
        tag = tag.strip()
        if tag not in VALID_TAGS:
            tag = "Other"

    return summary, tag


def call_provider(
    provider: ProviderConfig,
    title: str,
    client: httpx.Client,
) -> tuple[str, str]:
    """Dispatch prompt to an OpenAI-compatible provider."""
    url = f"{provider.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }
    prompt = (
        f"You are a news editor. Provide a one-sentence summary (max 160 characters) "
        f"and exactly one tag from: [LLMs, Research, Industry, Policy, Tools, Other].\n"
        f"Article headline: {title}\n"
        f"Respond ONLY in valid JSON matching this exact structure: "
        f'{{"summary": "...", "tag": "..."}}'
    )
    payload = {
        "model": provider.model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    response = client.post(url, headers=headers, json=payload)
    if response.status_code in (402, 429):
        # Explicitly raise HTTPStatusError to trigger provider fallback
        response.raise_for_status()

    response.raise_for_status()
    res_data = response.json()
    choices = res_data.get("choices", [])
    if not choices:
        raise ValueError("Provider returned response with no choices")

    raw_message = choices[0].get("message", {}).get("content", "")
    return parse_summary_response(raw_message)


def summarize_article(
    title: str,
    primary: ProviderConfig,
    fallback: ProviderConfig,
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Attempt primary then fallback summarization.

    Returns: (summary, tag, model_used, error_msg)
    """
    close_client = False
    if client is None:
        client = httpx.Client(timeout=20.0)
        close_client = True

    try:
        # Check if primary is configured
        if primary.is_configured:
            try:
                summary, tag = call_provider(primary, title, client)
                return summary, tag, primary.model, None
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (402, 429):
                    logger.warning(
                        f"Primary provider returned HTTP {exc.response.status_code}. Falling back."
                    )
                    if fallback.is_configured:
                        try:
                            summary, tag = call_provider(fallback, title, client)
                            return summary, tag, fallback.model, None
                        except Exception as fb_exc:
                            return None, None, None, f"Fallback failed: {fb_exc}"
                    else:
                        return (
                            None,
                            None,
                            None,
                            f"Primary HTTP {exc.response.status_code} and fallback unconfigured",
                        )
                else:
                    return None, None, None, f"Primary HTTP error: {exc.response.status_code}"
            except Exception as exc:
                logger.warning(f"Primary error: {exc}. Attempting fallback.")
                if fallback.is_configured:
                    try:
                        summary, tag = call_provider(fallback, title, client)
                        return summary, tag, fallback.model, None
                    except Exception as fb_exc:
                        return None, None, None, f"Both providers failed: {fb_exc}"
                return None, None, None, f"Primary failed: {exc}"

        # If primary is not configured, try fallback directly
        elif fallback.is_configured:
            try:
                summary, tag = call_provider(fallback, title, client)
                return summary, tag, fallback.model, None
            except Exception as fb_exc:
                return None, None, None, f"Fallback failed: {fb_exc}"

        else:
            return None, None, None, "Neither provider configured with valid API credentials"
    finally:
        if close_client:
            client.close()


def record_run(
    conn: sqlite3.Connection,
    started_at: str,
    finished_at: str,
    status: str,
    fetched: int,
    summarized: int,
    error: Optional[str],
) -> int:
    """Record summarization execution in runs table."""
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO runs (started_at, finished_at, status, fetched, inserted, summarized, error)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            (started_at, finished_at, status, fetched, 0, summarized, error),
        )
        return cursor.lastrowid


def summarize(
    conn: Optional[sqlite3.Connection] = None,
    client: Optional[httpx.Client] = None,
    limit: Optional[int] = None,
) -> SummarizeResult:
    """Execute article summarization run."""
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True

    try:
        primary = get_primary_config()
        fallback = get_fallback_config()
        batch_limit = limit if limit is not None else get_limit()

        # Query unsummarized articles
        rows = conn.execute(
            """
            SELECT id, title FROM articles
            WHERE summary IS NULL OR trim(summary) = ''
            ORDER BY published_at DESC
            LIMIT ?;
            """,
            (batch_limit,),
        ).fetchall()

        fetched_count = len(rows)

        # Zero-candidate run is a normal success no-op
        if fetched_count == 0:
            finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            record_run(
                conn=conn,
                started_at=started_at,
                finished_at=finished_at,
                status="success",
                fetched=0,
                summarized=0,
                error=None,
            )
            return SummarizeResult(status="success", fetched=0, summarized=0, error=None)

        # Fatal configuration error if neither provider has credentials
        if not primary.is_configured and not fallback.is_configured:
            finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            cfg_err = "Configuration error: neither primary nor fallback provider has credentials"
            record_run(
                conn=conn,
                started_at=started_at,
                finished_at=finished_at,
                status="failed",
                fetched=fetched_count,
                summarized=0,
                error=cfg_err,
            )
            return SummarizeResult(
                status="failed", fetched=fetched_count, summarized=0, error=cfg_err
            )

        summarized_count = 0
        errors: list[str] = []

        for row in rows:
            article_id = row["id"]
            title = row["title"]

            summary, tag, model_used, err = summarize_article(
                title=title,
                primary=primary,
                fallback=fallback,
                client=client,
            )

            if summary is not None and tag is not None and model_used is not None:
                with conn:
                    conn.execute(
                        """
                        UPDATE articles
                        SET summary = ?, tag = ?, summary_model = ?
                        WHERE id = ?;
                        """,
                        (summary, tag, model_used, article_id),
                    )
                summarized_count += 1
            else:
                errors.append(f"Article #{article_id} failed: {err}")

        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if summarized_count == fetched_count:
            status = "success"
            final_error = None
        elif summarized_count > 0:
            status = "partial"
            final_error = f"{len(errors)} of {fetched_count} articles failed summarization"
        else:
            status = "partial"
            final_error = f"All {fetched_count} articles failed summarization"

        record_run(
            conn=conn,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            fetched=fetched_count,
            summarized=summarized_count,
            error=final_error,
        )

        return SummarizeResult(
            status=status,
            fetched=fetched_count,
            summarized=summarized_count,
            error=final_error,
        )

    except Exception as exc:
        logger.exception("Unexpected exception during summarization")
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        err_msg = f"Unexpected failure: {exc}"
        try:
            record_run(
                conn=conn,
                started_at=started_at,
                finished_at=finished_at,
                status="failed",
                fetched=0,
                summarized=0,
                error=err_msg,
            )
        except Exception:
            pass
        return SummarizeResult(status="failed", fetched=0, summarized=0, error=err_msg)

    finally:
        if close_conn:
            conn.close()


def main() -> None:
    """CLI entrypoint for summarizer."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    print("Starting newsroom summarizer run...")
    result = summarize()
    print(
        f"Summarizer completed with status='{result.status}': "
        f"fetched={result.fetched}, summarized={result.summarized}, error={result.error}"
    )
    if result.status == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
