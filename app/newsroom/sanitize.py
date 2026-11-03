"""Make error text safe to store in the runs table and show on the public /runs page."""

from __future__ import annotations

import os
import re
from typing import Optional

MAX_ERROR_LENGTH = 300
SECRET_ENV_VARS = ("NEWSROOM_LLM_API_KEY", "NEWSROOM_FALLBACK_API_KEY")
_TOKEN = re.compile(r"(ghp_|gho_|github_pat_|sk-|AIza)[A-Za-z0-9_\-]{8,}")
_BEARER = re.compile(r"(?i)\b(bearer|authorization:?)\s+[A-Za-z0-9._\-]{8,}")
_TAGS = re.compile(r"<[^>]+>")
_URL_SECRET = re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token)=)[^&\s\"']+")


def sanitize_error(text: Optional[str], limit: int = MAX_ERROR_LENGTH) -> Optional[str]:
    """Mask secrets, drop markup and newlines, and cap the length. None stays None."""
    if text is None:
        return None
    clean = str(text)
    for name in SECRET_ENV_VARS:  # mask the exact configured secrets, whatever their shape
        secret = os.environ.get(name, "").strip()
        if len(secret) >= 6:
            clean = clean.replace(secret, "[redacted]")
    clean = _URL_SECRET.sub(r"\1[redacted]", clean)
    clean = _BEARER.sub(r"\1 [redacted]", clean)
    clean = _TOKEN.sub("[redacted]", clean)
    clean = _TAGS.sub(" ", clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return clean
