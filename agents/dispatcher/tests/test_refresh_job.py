"""Offline tests for the dispatcher-managed refresh job (fake runner, fake GitHub)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch
import refresh_job


class FakeGH:
    def __init__(self):
        self.created = []

    def create_issue(self, title, body, labels):
        self.created.append((title, body, labels))


def make(tmp_path, runner):
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_REPO_DIR": str(tmp_path)})
    gh = FakeGH()
    return refresh_job.RefreshJob(cfg, gh, runner=runner, log=lambda m: None), gh


def test_success_runs_collector_then_summarizer(tmp_path):
    calls = []
    job, gh = make(tmp_path, lambda argv, cwd, t: calls.append((argv[-1], cwd.name)) or (0, "ok"))
    assert job.run() == 0
    assert calls == [("newsroom.collector", "app"), ("newsroom.summarizer", "app")]
    assert job.state.load("refresh")["failures"] == 0 and not gh.created


def test_failed_collection_skips_summarizer_and_counts(tmp_path):
    calls = []

    def runner(argv, cwd, t):
        calls.append(argv[-1])
        return 1, "boom sk-abcdefghij12345"

    job, _ = make(tmp_path, runner)
    assert job.run() == 1
    assert calls == ["newsroom.collector"]
    st = job.state.load("refresh")
    assert st["failures"] == 1 and "sk-abcdefghij" not in st["last_error"]


def test_escalates_once_after_three_failures_and_resets_on_success(tmp_path):
    results = iter([(1, "x")] * 5 + [(0, "ok"), (0, "ok")])
    job, gh = make(tmp_path, lambda argv, cwd, t: next(results))
    for _ in range(5):
        job.run()
    assert len(gh.created) == 1
    assert gh.created[0][2] == ["status:blocked", "agent:editor"]
    assert job.run() == 0
    assert job.state.load("refresh") == {"failures": 0, "last_ok": job.state.load("refresh")["last_ok"]}


def test_second_refresh_is_not_started_while_one_runs(tmp_path):
    job, _ = make(tmp_path, lambda *a: (0, "ok"))
    lock = dispatch.AgentLock(job.state.dir, "refresh", 600)
    assert lock.acquire()
    assert job.run() == 2
    lock.release()
    assert job.run() == 0


def test_dispatch_cli_refresh_flag_uses_refresh_job(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWSROOM_DISPATCH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("NEWSROOM_REPO_DIR", str(tmp_path))
    seen = []
    monkeypatch.setattr(refresh_job.RefreshJob, "run", lambda self: seen.append("run") or 0)
    assert dispatch.main(["--refresh"]) == 0 and seen == ["run"]
