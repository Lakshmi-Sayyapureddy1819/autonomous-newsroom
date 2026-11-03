"""Regression tests for the four-agent flow: every hand-off is validated against GitHub.

Real failures these pin (Issues #29/#31/#33, PRs #30/#32/#34):
* the Reporter left `status:ready` AND `status:in-review` on the Issue plus `status:*` /
  `agent:*` labels on the PR; the dispatcher counted that as "labels moved", then skipped the
  ticket as malformed forever, so Copydesk and Factcheck were never woken;
* nothing escalated, the loop just went quiet;
* the Reporter committed unrelated files from a dirty shared checkout.

Fake GitHub + scripted agents, no network, no sleeping (an injected clock).
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch

SHA1, SHA2 = "a" * 40, "b" * 40


class Repo:
    """One Issue (#1), its open PR(s) and comments. No merge method exists at all."""

    def __init__(self, labels=("status:ready", "agent:reporter", "attempt:1")):
        self.issue_labels = list(labels)
        self.prs = {}
        self.comments = []
        self.state = "open"
        self.created = []

    # --- interface used by the dispatcher
    def _issue(self):
        return {"number": 1, "title": "demo", "body": "Goal: x", "updatedAt": "2026-01-01T00:00:00Z",
                "labels": [{"name": n} for n in self.issue_labels]}

    def issues(self, state):
        return [self._issue()] if state == self.state else []

    def open_prs(self):
        return [{"number": n, "labels": [{"name": x} for x in p["labels"]],
                 "closingIssuesReferences": [{"number": c} for c in p["closes"]],
                 "headRefOid": p["head"]} for n, p in self.prs.items()]

    def edit_labels(self, kind, number, add=(), remove=()):
        cur = self.issue_labels if kind == "issue" else self.prs[number]["labels"]
        cur[:] = [x for x in cur if x not in remove] + [a for a in add if a not in cur]

    def comment(self, kind, number, body):
        self.comments.append((kind, number, body))

    def activity(self, issue, pr):
        return len(self.comments)

    def create_issue(self, title, body, labels):
        self.created.append((title, labels))

    # --- helpers
    def open_pr(self, n=7, closes=(1,), labels=(), head=SHA1):
        self.prs[n] = {"labels": list(labels), "closes": list(closes), "head": head}

    def issue(self):
        return set(self.issue_labels)

    def pr(self, n=7):
        return set(self.prs[n]["labels"])


class Clock:
    def __init__(self, start=1_800_000_000.0):  # after the fake Issue's updatedAt (2026-01-01)
        self.t = start

    def __call__(self):
        return self.t


def make(tmp_path, repo, runner, clock=None, **env):
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "0",
                           **env})
    return dispatch.Dispatcher(cfg, repo, runner=runner, clock=clock or Clock())


def failures(d, key="issue-1"):
    return d.state.load(key).get("failures", 0)


# ---- scripted agents ----------------------------------------------------------------------
def good_reporter(repo):
    repo.open_pr()
    repo.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                     ["status:ready", "agent:reporter"])
    repo.comment("issue", 1, "### Handoff reporter -> copydesk")


def good_copydesk(repo):
    repo.edit_labels("pr", 7, ["review:approved"])
    repo.edit_labels("issue", 1, ["status:in-test", "agent:factcheck"],
                     ["status:in-review", "agent:copydesk"])
    repo.comment("pr", 7, "### Review: every criterion pass")


def good_factcheck(repo):
    repo.edit_labels("pr", 7, ["test:passed"])
    repo.edit_labels("issue", 1, ["status:ready-to-merge"], ["status:in-test", "agent:factcheck"])
    repo.comment("pr", 7, "### Test: ruff + pytest pass")


def scripted(repo, **behaviours):
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append((agent, issue_no, pr))
        behaviours[agent](repo)
        return 0, "ok"

    runner.calls = calls
    return runner


def test_full_cycle_every_handoff_is_valid_and_nothing_is_skipped(tmp_path):
    repo = Repo()
    runner = scripted(repo, reporter=good_reporter, copydesk=good_copydesk,
                      factcheck=good_factcheck)
    d = make(tmp_path, repo, runner)
    for _ in range(4):
        d.tick()
        assert failures(d) == 0, "a valid hand-off must never count as a failure"
    assert [c[0] for c in runner.calls] == ["reporter", "copydesk", "factcheck"]
    assert runner.calls[1][2] == "7" and runner.calls[2][2] == "7"  # reviewers get the PR
    assert repo.issue() == {"status:ready-to-merge", "attempt:1"}
    assert repo.pr() == {"review:approved", "test:passed"}
    assert not hasattr(repo, "merge")


def test_reporter_stale_and_pr_labels_are_repaired_and_copydesk_is_woken(tmp_path):
    """The #29/#31/#33 bug: conflicting Issue labels and status/agent labels on the PR."""
    repo = Repo()

    def sloppy_reporter(r):
        r.open_pr(labels=["status:in-review", "agent:copydesk"])           # labels on the PR
        r.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"])  # forgot to remove
        r.comment("issue", 1, "Handoff to copydesk")

    runner = scripted(repo, reporter=sloppy_reporter, copydesk=good_copydesk)
    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0
    assert repo.issue() == {"status:in-review", "agent:copydesk", "attempt:1"}
    assert repo.pr() == set(), "status:*/agent:* never stay on the PR"
    assert any("Dispatcher note" in c[2] for c in repo.comments)
    d.tick()
    assert [c[0] for c in runner.calls] == ["reporter", "copydesk"]


@pytest.mark.parametrize("labels", [
    ["status:in-progress", "agent:reporter"],      # claimed, never handed off
    ["status:ready", "agent:reporter"],            # nothing moved
    ["status:in-review"],                          # no owner
    ["status:in-review", "agent:factcheck"],       # wrong owner
])
def test_reporter_wrong_handoff_is_a_failure_not_progress(tmp_path, labels):
    repo = Repo()

    def reporter(r):
        r.open_pr()
        r.issue_labels[:] = labels + ["attempt:1"]
        r.comment("issue", 1, "done")

    d = make(tmp_path, repo, scripted(repo, reporter=reporter))
    d.tick()
    assert failures(d) == 1, "a wrong hand-off is a recorded failure, not progress"
    assert "expected" in d.state.load("issue-1")["last_error"]
    assert "agent:copydesk" not in repo.issue(), "the dispatcher must not fabricate the hand-off"


def test_reporter_without_pr_or_with_two_prs_fails(tmp_path):
    for setup in (lambda r: None, lambda r: (r.open_pr(7), r.open_pr(8))):
        repo = Repo()

        def reporter(r, setup=setup):
            setup(r)
            r.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                          ["status:ready", "agent:reporter"])
            r.comment("issue", 1, "done")

        d = make(tmp_path / str(len(repo.prs)), repo, scripted(repo, reporter=reporter))
        d.tick()
        assert "exactly one open PR" in d.state.load("issue-1")["last_error"]


def test_reporter_silent_handoff_without_a_comment_fails(tmp_path):
    repo = Repo()

    def silent(r):
        r.open_pr()
        r.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                      ["status:ready", "agent:reporter"])

    d = make(tmp_path, repo, scripted(repo, reporter=silent))
    d.tick()
    assert "no handoff comment" in d.state.load("issue-1")["last_error"]


def test_nonzero_exit_with_a_valid_handoff_is_accepted_and_not_rerun(tmp_path):
    """Gateway drop after the work was done: read GitHub, do not blindly run it twice."""
    repo = Repo()
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        good_reporter(repo)
        return 1, "ConnectionClosedError: 1011 keepalive ping timeout"

    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0 and repo.issue() >= {"status:in-review", "agent:copydesk"}
    assert calls == ["reporter"]


def test_copydesk_without_verdict_conflicting_verdicts_or_no_pr(tmp_path):
    cases = {
        "no verdict": (lambda r: r.comment("pr", 7, "looks fine"), "no review:approved"),
        "conflict": (lambda r: (r.edit_labels("pr", 7, ["review:approved",
                                                         "review:changes-requested"]),
                                r.comment("pr", 7, "?")), "conflicting"),
    }
    for i, (name, (act, why)) in enumerate(cases.items()):
        repo = Repo(["status:in-review", "agent:copydesk", "attempt:1"])
        repo.open_pr()
        d = make(tmp_path / str(i), repo, scripted(repo, copydesk=act))
        d.tick()
        assert why in d.state.load("issue-1")["last_error"], name
        assert "review:approved" not in repo.issue()


def test_copydesk_rejection_routes_back_to_reporter_on_the_same_pr(tmp_path):
    repo = Repo(["status:in-review", "agent:copydesk", "attempt:1"])
    repo.open_pr()

    def rejecting(r):
        r.edit_labels("pr", 7, ["review:changes-requested"])
        r.comment("pr", 7, "criterion 2 fails: extra file")

    runner = scripted(repo, copydesk=rejecting, reporter=lambda r: None)
    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0, "a rejection is a valid outcome"
    d.tick()  # editor duty re-routes (attempt + 1) before anything else
    assert repo.issue() >= {"status:ready", "agent:reporter", "attempt:2"}
    assert repo.pr() == set(), "stale verdict stripped; same PR kept"
    assert list(repo.prs) == [7]


def test_factcheck_passes_only_with_both_verdicts_and_a_ready_to_merge_issue(tmp_path):
    repo = Repo(["status:in-test", "agent:factcheck", "attempt:1"])
    repo.open_pr(labels=["review:approved"])
    d = make(tmp_path, repo, scripted(repo, factcheck=good_factcheck))
    d.tick()
    assert failures(d) == 0 and repo.issue() == {"status:ready-to-merge", "attempt:1"}

    repo = Repo(["status:in-test", "agent:factcheck", "attempt:1"])
    repo.open_pr(labels=[])  # Copydesk never approved
    d = make(tmp_path / "x", repo, scripted(repo, factcheck=good_factcheck))
    d.tick()
    assert "without review:approved" in d.state.load("issue-1")["last_error"]


def test_factcheck_head_moved_during_the_run_drops_the_verdict(tmp_path):
    repo = Repo(["status:in-test", "agent:factcheck", "attempt:1"])
    repo.open_pr(labels=["review:approved"])

    def racing(r):
        good_factcheck(r)
        r.prs[7]["head"] = SHA2  # the Reporter pushed while the tester was running

    d = make(tmp_path, repo, scripted(repo, factcheck=racing))
    d.tick()
    assert "head moved" in d.state.load("issue-1")["last_error"]
    assert "test:passed" not in repo.pr(), "a stale verdict must not reach the gate"
    assert repo.issue() >= {"status:in-test", "agent:factcheck"}, "same agent re-runs"
    assert "status:ready-to-merge" not in repo.issue()


def test_endless_failures_escalate_once_and_stop(tmp_path):
    repo = Repo(["status:in-review", "agent:copydesk", "attempt:1"])
    repo.open_pr()
    runner = scripted(repo, copydesk=lambda r: None)
    d = make(tmp_path, repo, runner)
    for _ in range(8):
        d.tick()
    assert len(runner.calls) == 3
    assert repo.issue() >= {"status:blocked", "agent:editor"}
    assert sum("Escalation" in c[2] for c in repo.comments) == 1


def test_label_flapping_cannot_loop_forever(tmp_path):
    """Each wake 'moves' the labels back and forth; the overall wake cap must stop it."""
    repo = Repo()
    seen = []

    def flapper(agent, issue_no, prompt, pr=""):
        seen.append(agent)
        repo.open_pr(labels=[]) if not repo.prs else None
        repo.issue_labels[:] = (["status:ready", "agent:reporter", "attempt:1"]
                                if len(seen) % 2 else
                                ["status:in-progress", "agent:reporter", "attempt:1"])
        repo.comment("issue", 1, "x")
        return 0, "ok"

    clock = Clock()
    d = make(tmp_path, repo, flapper, clock, NEWSROOM_MAX_WAKES="4", NEWSROOM_STALE_MINUTES="0")
    for _ in range(12):
        clock.t += 3600
        d.tick()
    assert len(seen) <= 4
    assert repo.issue() >= {"status:blocked", "agent:editor"}


# ---- malformed labels are escalated, never skipped silently ---------------------------------
def test_persistently_malformed_labels_are_escalated_after_the_grace(tmp_path):
    repo = Repo(["status:ready", "status:in-review", "agent:reporter", "attempt:1"])  # real #33
    runner = scripted(repo, reporter=good_reporter)
    clock = Clock()
    d = make(tmp_path, repo, runner, clock, NEWSROOM_MALFORMED_GRACE="120")
    d.tick()
    assert repo.issue() >= {"status:ready", "status:in-review"}, "grace: maybe mid-edit"
    clock.t += 60
    d.tick()
    assert "status:blocked" not in repo.issue()
    clock.t += 90
    d.tick()
    assert repo.issue() >= {"status:blocked", "agent:editor"}
    assert "status:ready" not in repo.issue() and runner.calls == []
    assert any("inconsistent" in c[2] or "multiple status" in c[2] for c in repo.comments)


@pytest.mark.parametrize("labels", [
    ["status:in-review", "attempt:1"],
    ["agent:copydesk", "attempt:1"],
    ["status:ready", "agent:copydesk", "attempt:1"],
    ["status:ready", "agent:reporter", "agent:factcheck", "attempt:1"],
    ["status:in-test", "agent:editor", "attempt:1"],
])
def test_label_problem_detects_undispatchable_sets(labels):
    t = dispatch.parse_ticket({"number": 1, "title": "t", "body": "",
                               "labels": [{"name": n} for n in labels]}, set())
    assert dispatch.label_problem(t)


@pytest.mark.parametrize("labels", [
    ["status:ready", "agent:reporter"], ["status:in-review", "agent:copydesk"],
    ["status:in-test", "agent:factcheck"], ["status:ready-to-merge"],
    ["status:blocked", "agent:editor"], ["agent:editor"], [],
])
def test_label_problem_accepts_every_protocol_state(labels):
    t = dispatch.parse_ticket({"number": 1, "title": "t", "body": "",
                               "labels": [{"name": n} for n in labels]}, set())
    assert dispatch.label_problem(t) == ""


def test_valid_label_recovery_clears_the_malformed_timer(tmp_path):
    repo = Repo(["status:ready", "status:in-review", "agent:reporter"])
    clock = Clock()
    d = make(tmp_path, repo, scripted(repo, reporter=good_reporter), clock)
    d.tick()
    repo.issue_labels[:] = ["status:ready-to-merge"]
    d.tick()
    assert d.state.load("malformed-1") == {}


# ---- uncertain timeouts and shared-checkout safety --------------------------------------------
def test_timeout_keeps_the_lock_so_no_duplicate_invocation_starts(tmp_path):
    repo = Repo()
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        return 124, "timed out; outcome uncertain"

    clock = Clock()
    d = make(tmp_path, repo, runner, clock)
    d.tick()
    assert calls == ["reporter"] and failures(d) == 1
    # a fresh dispatcher process (next timer tick) must not start a second Reporter yet
    make(tmp_path, repo, runner, clock).tick()
    assert calls == ["reporter"]


def test_timeout_that_still_produced_the_handoff_is_accepted(tmp_path):
    repo = Repo()

    def runner(agent, issue_no, prompt, pr=""):
        good_reporter(repo)
        return 124, "timed out; outcome uncertain"

    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0 and repo.issue() >= {"status:in-review", "agent:copydesk"}


def test_runner_kills_the_whole_process_tree_on_timeout(tmp_path):
    repo = Repo()
    marker = tmp_path / "survived.txt"
    child = (f"import subprocess,sys,time;"
             f"subprocess.Popen([sys.executable,'-c',"
             f"'import time,pathlib;time.sleep(6);pathlib.Path(r\"{marker}\").write_text(\"x\")']);"
             "time.sleep(60)")
    d = make(tmp_path, repo, None,
             NEWSROOM_CMD_REPORTER=f'"{sys.executable}" -c "{child}"')
    d.cfg.timeout = -29  # subprocess timeout = 1 s
    code, text = d._run_subprocess("reporter", "1", "p")
    assert code == 124 and "uncertain" in text
    import time
    time.sleep(8)
    assert not marker.exists(), "the grandchild must have been killed with its parent"


def test_reporter_refuses_to_start_in_a_dirty_checkout(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "local_edit.sh").write_text("wip")
    repo = Repo()
    runner = scripted(repo, reporter=good_reporter)
    d = make(tmp_path, repo, runner)
    d.tick()
    assert runner.calls == [] and "not clean" in d.state.load("issue-1")["last_error"]


def test_prompts_name_the_checkout_pr_and_label_rules(tmp_path):
    t = dispatch.parse_ticket(Repo()._issue(), set())
    rep = dispatch.prompt_for("reporter", 1, t, tmp_path)
    assert str(tmp_path) in rep and "never open a second pr" in rep.lower()
    assert "Never put status:* or agent:* labels on the PR" in rep
    cop = dispatch.prompt_for("copydesk", 1, t, tmp_path, "7")
    assert "PR #7" in cop and "--name-only" in cop and "review:approved" in cop
    fac = dispatch.prompt_for("factcheck", 1, t, tmp_path, "7")
    assert "EXACT head SHA" in fac and "test:passed" in fac


def test_editor_bootstrap_is_judged_by_github_not_the_exit_code(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "brief.md").write_text("brief")
    repo = Repo(["status:ready", "agent:reporter", "attempt:1"])
    repo.state = "none"  # no tickets yet when the tick starts

    def runner(agent, issue_no, prompt, pr=""):
        repo.state = "open"  # the editor created the ticket, then its session dropped
        return 1, "gateway closed"

    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d, "editor-bootstrap") == 0
