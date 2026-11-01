import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch


def test_gh_timeout_becomes_runtime_error(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=120)

    monkeypatch.setattr(dispatch.subprocess, "run", boom)
    with pytest.raises(RuntimeError, match="timed out"):
        dispatch.GitHub("o/r")._gh("issue", "comment")
