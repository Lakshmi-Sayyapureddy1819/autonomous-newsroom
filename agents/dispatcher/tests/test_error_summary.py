import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dispatch import error_summary


def test_picks_the_rate_limit_line_not_the_tail():
    out = (
        "Query: do the thing\n"
        "Attempt 3/3 failed: HTTP 429: Rate limit exceeded: free-models-per-day\n"
        "Resume this session with:\n  hermes --resume abc\nSession: abc\nDuration: 58s\n"
    )
    assert "429" in error_summary(out)


def test_redacts_secrets_and_falls_back_to_tail():
    assert "ghp_" not in error_summary("boom ghp_abcdefghijkl1234 error")
    assert error_summary("a\nb\nc\nd") == "b\nc\nd"
