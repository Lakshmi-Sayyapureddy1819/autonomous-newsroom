from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.env import load_env


def test_load_env_sets_values_and_respects_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "NR_TEST_A=plain\n"
        'NR_TEST_B="quoted value"\n'
        "export NR_TEST_C = spaced\n"
        "NR_TEST_EMPTY=\n"
        "NR_TEST_KEEP=from-file\n"
    )
    for name in ("NR_TEST_A", "NR_TEST_B", "NR_TEST_C", "NR_TEST_EMPTY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NR_TEST_KEEP", "from-shell")

    assert load_env(env_file) == env_file

    import os

    assert os.environ["NR_TEST_A"] == "plain"
    assert os.environ["NR_TEST_B"] == "quoted value"
    assert os.environ["NR_TEST_C"] == "spaced"
    assert "NR_TEST_EMPTY" not in os.environ
    assert os.environ["NR_TEST_KEEP"] == "from-shell"
    for name in ("NR_TEST_A", "NR_TEST_B", "NR_TEST_C"):
        monkeypatch.delenv(name)


def test_load_env_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_env(tmp_path / "nope.env") is None
