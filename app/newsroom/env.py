"""Minimal .env loader (no third-party dependency)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# <repo>/app/newsroom/env.py -> <repo>
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Optional[Path | str] = None) -> Optional[Path]:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``.

    Looks in ``path`` if given, else in the current directory, then the project root.
    Variables already set in the environment win, and empty values are ignored.
    Returns the file that was loaded, or None if no file was found.
    """
    candidates = [Path(path)] if path else [Path.cwd() / ".env", PROJECT_ROOT / ".env"]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for raw in candidate.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key and value:
                os.environ.setdefault(key, value)
        return candidate
    return None
