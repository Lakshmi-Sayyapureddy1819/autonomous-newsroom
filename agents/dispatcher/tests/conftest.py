"""Tests never really sleep (lag polling / gateway waits) and never touch a real Gateway."""

import time

import pytest


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
