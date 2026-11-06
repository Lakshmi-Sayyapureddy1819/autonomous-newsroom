"""Gateway loss, long runs, timeouts, PR races, backoff, recovery and the full pipeline
(all mocked: no real GitHub issues, no real Gateway)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch  # noqa: E402
from test_dispatcher import FakeGH, issue, labels_of  # noqa: E402

READY = ["status:ready", "agent:reporter", "attempt:1"]
GATEWAY_LOST = ("Gateway agent call connection closed; the Gateway may still be running this "
                "turn.\nCouldn't connect to OpenClaw.\n")


class FakeGateway:
    def __init__(self, up_after=0, stays_up=True):
        self.polls, self.up_after, self.stays_up, self.started = 0, up_after, stays_up, 0

    def up(self):
        self.polls += 1
        return self.polls > self.up_after and (self.stays_up or self.polls <= self.up_after + 1)

    def ensure(self, log=print):
        if self.up():
            return True
        self.started += 1
        self.polls = self.up_after + 1
        return True


def pr(n, closes, labels=(), head="a" * 40):
    return {"number": n, "labels": [{"name": x} for x in labels], "headRefOid": head,
            "closingIssuesReferences": [{"number": c} for c in closes]}


def make(tmp_path, gh, runner=None, gateway=None, sleeps=None, **env):
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "0",
                           "NEWSROOM_GATEWAY_WAIT": "20", **env})
    return dispatch.Dispatcher(cfg, gh, runner=runner, gateway=gateway,
                               sleep=(sleeps.append if sleeps is not None else (lambda s: None)))


def reporter_handoff(gh, n=1, pr_no=10):
    """What a finished Reporter leaves on GitHub."""
    if not gh.prs:
        gh.prs.append(pr(pr_no, [n]))
    gh.edit_labels("issue", n, ["status:in-review", "agent:copydesk"],
                   ["status:ready", "agent:reporter"])
    gh.comment("issue", n, "handoff")


# ---- Gateway ---------------------------------------------------------------------------
def test_gateway_class_starts_only_when_down_and_waits_for_cold_start(tmp_path):
    cfg = dispatch.Config({"NEWSROOM_GATEWAY_WAIT": "60"})
    state = {"polls": 0, "starts": 0}

    def connect():
        state["polls"] += 1
        if state["polls"] < 6:
            raise ConnectionRefusedError

    gw = dispatch.Gateway(cfg, sleep=lambda s: None, connect=connect,
                          starter=lambda: state.__setitem__("starts", state["starts"] + 1))
    assert gw.ensure(lambda m: None) is True
    assert state["starts"] == 1  # started once, then waited
    state["polls"] = 100
    assert gw.ensure(lambda m: None) is True
    assert state["starts"] == 1  # healthy Gateway is never restarted


def test_gateway_never_up_gives_up_after_the_configured_wait():
    cfg = dispatch.Config({"NEWSROOM_GATEWAY_WAIT": "15"})
    slept = []

    def refuse():
        raise ConnectionRefusedError

    gw = dispatch.Gateway(cfg, sleep=slept.append, connect=refuse, starter=lambda: None)
    assert gw.ensure(lambda m: None) is False
    assert sum(slept) == 15


def test_gateway_down_means_agent_not_woken_and_no_failure_counted(tmp_path):
    gh = FakeGH([issue(1, READY)])
    calls = []

    class Dead(FakeGateway):
        def ensure(self, log=print):
            return False

    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (0, ""), Dead())
    d.cfg.env = {}  # runner injected, but force the OpenClaw path
    d.tick()
    assert calls == []
    assert d.state.load("issue-1").get("failures", 0) == 0
    assert d.state.load("issue-1-wakes") == {}


def test_gateway_lost_during_run_is_reported_as_invocation_failure_not_missing_pr(tmp_path):
    gh = FakeGH([issue(1, READY)])
    gw = FakeGateway(stays_up=True)
    gw.up = lambda: False  # the Gateway is gone after the call
    d = make(tmp_path, gh, lambda *a, **k: (1, GATEWAY_LOST), gw)
    d.tick()
    err = d.state.load("issue-1")["last_error"]
    assert err.startswith("Gateway lost (exit 1)")
    assert "expected exactly one open PR closing #1, found 0" in err  # kept, but second
    assert "uncertain" not in d.state.load("issue-1")


def test_disconnect_with_live_gateway_never_reruns_and_settles_from_github(tmp_path):
    gh = FakeGH([issue(1, READY)])
    calls = []
    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (1, GATEWAY_LOST),
             FakeGateway(), NEWSROOM_SETTLE_SECONDS="600")
    d.tick()
    assert len(calls) == 1 and "uncertain" in d.state.load("issue-1")
    d.tick()
    d.tick()
    assert len(calls) == 1  # the turn may still be running: not woken again
    # The turn finishes on the Gateway's side and leaves a valid hand-off.
    reporter_handoff(gh)
    d2 = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (0, ""), FakeGateway())  # restart
    d2.tick()
    assert len(calls) == 1
    assert d2.state.load("issue-1")["failures"] == 0
    assert "last_ok" in d2.state.load("issue-1")


def test_uncertain_outcome_that_never_appears_counts_one_failure_after_the_wait(tmp_path):
    gh = FakeGH([issue(1, READY)])
    t = [1000.0]
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "s"),
                          "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "0",
                          "NEWSROOM_SETTLE_SECONDS": "100"})
    d = dispatch.Dispatcher(cfg, gh, runner=lambda *a, **k: (1, GATEWAY_LOST),
                            clock=lambda: t[0], gateway=FakeGateway())
    d.tick()
    t[0] += 101
    d.tick()
    assert d.state.load("issue-1")["failures"] == 1
    assert "never appeared" in d.state.load("issue-1")["last_error"]


# ---- long-running agent / real subprocess handling -------------------------------------
def run_real(tmp_path, script, timeout="30"):
    gh = FakeGH([issue(1, READY)])
    py = sys.executable.replace("\\", "/")
    d = make(tmp_path, gh, None, None, NEWSROOM_AGENT_TIMEOUT=timeout,
             NEWSROOM_CMD_REPORTER=f'"{py}" -c "{script}"')
    code, out = d._run_subprocess("reporter", "1", "prompt")
    return d, code, out


def test_long_output_and_exit_code_are_preserved_and_log_is_complete(tmp_path):
    d, code, out = run_real(
        tmp_path, "import sys; print('x'*50000); print('ERR-TAIL', file=sys.stderr); sys.exit(7)")
    assert code == 7 and "ERR-TAIL" in out and len(out) > 50000
    log = next((d.state.dir / "logs").glob("reporter-1-*.log")).read_text(encoding="utf-8")
    assert len(log) > 50000 and "exit=7" in log and "ERR-TAIL" in log


def test_secrets_are_redacted_in_the_stored_log(tmp_path):
    d, _, _ = run_real(tmp_path, "print('token ghp_abcdefghijklmnop1234')")
    log = next((d.state.dir / "logs").glob("reporter-1-*.log")).read_text(encoding="utf-8")
    assert "ghp_" not in log and "[redacted]" in log


def test_reporter_timeout_keeps_partial_output_and_is_uncertain(tmp_path, monkeypatch):
    gh = FakeGH([issue(1, READY)])
    py = sys.executable.replace("\\", "/")
    script = "import time; print('started', flush=True); time.sleep(60)"
    d = make(tmp_path, gh, None, None, NEWSROOM_AGENT_TIMEOUT="1",
             NEWSROOM_CMD_REPORTER=f'"{py}" -c "{script}"')
    monkeypatch.setattr(dispatch.subprocess.Popen, "communicate", _fast_timeout(
        dispatch.subprocess.Popen.communicate), raising=True)
    code, out = d._run_subprocess("reporter", "1", "p")
    assert code == 124 and "outcome uncertain" in out


def _fast_timeout(orig):
    calls = {"n": 0}

    def wrapper(self, input=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:  # first call is the real wait: shrink 31s -> 2s
            return orig(self, input, 2)
        return orig(self, input, timeout)
    return wrapper


def test_per_agent_timeout_is_configurable_and_passed_to_openclaw(tmp_path):
    cfg = dispatch.Config({"NEWSROOM_AGENT_TIMEOUT": "900",
                           "NEWSROOM_AGENT_TIMEOUT_REPORTER": "2400"})
    argv = cfg.command("reporter", "1", "msg")
    assert argv[argv.index("--timeout") + 1] == "2400"
    assert cfg.command("factcheck", "1", "msg")[-1] == "900"
    assert cfg.timeout_for("copydesk") == 900


def test_timed_out_agent_is_not_rewoken_while_its_lock_is_kept(tmp_path):
    gh = FakeGH([issue(1, READY)])
    calls = []
    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (124, "timed out"),
             NEWSROOM_SETTLE_SECONDS="600")
    for _ in range(4):
        d.tick()
    assert len(calls) == 1


# ---- PR creation, duplicates, GitHub lag -----------------------------------------------
def test_failed_pr_creation_is_a_failed_attempt_with_a_clear_reason(tmp_path):
    gh = FakeGH([issue(1, READY)])
    d = make(tmp_path, gh, lambda *a, **k: (0, "I pushed a branch"))
    d.tick()
    st = d.state.load("issue-1")
    assert st["failures"] == 1 and "found 0" in st["last_error"]
    assert labels_of(gh, 1) == set(READY)  # nothing fabricated


def test_github_lag_polls_instead_of_failing_or_rerunning(tmp_path):
    gh = FakeGH([issue(1, READY)])
    calls, sleeps = [], []

    class LaggyGH(FakeGH):
        hidden = 0  # reads (after the agent finished) during which GitHub shows no PR yet

        def open_prs(self):
            if self.hidden > 0:
                self.hidden -= 1
                return []
            return self.prs

    gh = LaggyGH([issue(1, READY)])

    def runner(agent, n, prompt, pr=""):
        calls.append(agent)
        gh.prs.append(globals()["pr"](10, [1]))
        gh.hidden = 3
        gh.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                       ["status:ready", "agent:reporter"])
        gh.comment("issue", 1, "handoff")
        return 0, "done"

    d = make(tmp_path, gh, runner, sleeps=sleeps, NEWSROOM_GITHUB_LAG_WAIT="30")
    d.tick()
    assert calls == ["reporter"]  # exactly one run
    assert sleeps and d.state.load("issue-1")["failures"] == 0


def test_two_open_prs_for_one_issue_block_the_reporter(tmp_path):
    gh = FakeGH([issue(1, READY)], prs=[pr(10, [1]), pr(11, [1])])
    calls = []
    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (0, ""))
    d.tick()
    assert calls == []
    assert "ambiguous" in d.state.load("issue-1")["last_error"]


def test_unrelated_pr_is_never_accepted(tmp_path):
    gh = FakeGH([issue(1, READY)], prs=[pr(10, [99])])
    d = make(tmp_path, gh, lambda *a, **k: (reporter_handoff_unrelated(gh), "ok")[1:] and (0, "ok"))
    d.tick()
    assert d.state.load("issue-1")["failures"] == 1
    assert "found 0" in d.state.load("issue-1")["last_error"]


def reporter_handoff_unrelated(gh):
    gh.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                   ["status:ready", "agent:reporter"])
    gh.comment("issue", 1, "handoff")


# ---- retry / backoff / recovery --------------------------------------------------------
def test_backoff_is_exponential_and_not_woken_during_the_window(tmp_path):
    gh = FakeGH([issue(1, READY)])
    t, calls = [1000.0], []
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "s"),
                          "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "60"})
    d = dispatch.Dispatcher(cfg, gh, runner=lambda *a, **k: calls.append(1) or (1, "boom"),
                            clock=lambda: t[0])
    d.tick()                        # failure 1 -> wait 60
    t[0] += 59
    d.tick()
    assert len(calls) == 1
    t[0] += 2
    d.tick()                        # failure 2 -> wait 120
    t[0] += 119
    d.tick()
    assert len(calls) == 2
    t[0] += 2
    d.tick()                        # failure 3 -> escalated
    assert len(calls) == 3
    assert labels_of(gh, 1) >= {"status:blocked", "agent:editor"}
    t[0] += 10_000
    d.tick()
    assert len(calls) == 3          # retry limit respected after escalation
    assert "boom" in gh.comments[-1][2]


def test_state_survives_dispatcher_restart(tmp_path):
    gh = FakeGH([issue(1, READY)])
    d = make(tmp_path, gh, lambda *a, **k: (1, "boom"), NEWSROOM_RETRY_BACKOFF="600")
    d.tick()
    calls = []
    d2 = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (1, "boom"),
              NEWSROOM_RETRY_BACKOFF="600")
    d2.tick()
    assert calls == [] and d2.state.load("issue-1")["failures"] == 1


# ---- full pipeline: copydesk rejection, factcheck failure, final gate -------------------
def pipeline(tmp_path, copydesk_ok=True, factcheck_ok=True):
    gh = FakeGH([issue(1, READY)])
    log = []

    def runner(agent, n, prompt, pr=""):
        log.append(agent)
        if agent == "reporter":
            reporter_handoff(gh)
        elif agent == "copydesk":
            gh.prs[0]["labels"].append({"name": "review:approved" if copydesk_ok
                                        else "review:changes-requested"})
            if copydesk_ok:
                gh.edit_labels("issue", 1, ["status:in-test", "agent:factcheck"],
                               ["status:in-review", "agent:copydesk"])
            gh.comment("pr", 10, "review")
        elif agent == "factcheck":
            gh.prs[0]["labels"].append({"name": "test:passed" if factcheck_ok
                                        else "test:failed"})
            if factcheck_ok:
                gh.edit_labels("issue", 1, ["status:ready-to-merge"],
                               ["status:in-test", "agent:factcheck"])
            gh.comment("pr", 10, "tests")
        return 0, "ok"

    return gh, log, make(tmp_path, gh, runner)


def test_full_pipeline_reaches_ready_to_merge_and_never_merges(tmp_path):
    gh, log, d = pipeline(tmp_path)
    for _ in range(4):
        d.tick()
    assert log == ["reporter", "copydesk", "factcheck"]
    assert "status:ready-to-merge" in labels_of(gh, 1)
    assert {x["name"] for x in gh.prs[0]["labels"]} >= {"review:approved", "test:passed"}
    assert 1 in gh.open and len(gh.prs) == 1  # still open: a human merges


def test_copydesk_rejection_does_not_advance_to_factcheck(tmp_path):
    gh, log, d = pipeline(tmp_path, copydesk_ok=False)
    for _ in range(3):
        d.tick()
    assert "factcheck" not in log
    assert "status:ready-to-merge" not in labels_of(gh, 1)


def test_factcheck_failure_never_reaches_ready_to_merge(tmp_path):
    gh, log, d = pipeline(tmp_path, factcheck_ok=False)
    for _ in range(5):
        d.tick()
    assert "status:ready-to-merge" not in labels_of(gh, 1)
    assert "factcheck" in log
