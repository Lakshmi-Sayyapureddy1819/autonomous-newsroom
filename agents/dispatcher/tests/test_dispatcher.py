"""Offline tests for the dispatcher and editor lifecycle (fake GitHub, fake agents)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch  # noqa: E402
import editor_lifecycle as lc  # noqa: E402


class FakeGH:
    def __init__(self, issues=(), prs=()):
        self.open = {i["number"]: i for i in issues if i.get("state", "open") == "open"}
        self.closed = {i["number"]: i for i in issues if i.get("state") == "closed"}
        self.prs = list(prs)
        self.comments, self.created = [], []

    def issues(self, state):
        return list((self.open if state == "open" else self.closed).values())

    def open_prs(self):
        return self.prs

    def edit_labels(self, kind, number, add=(), remove=()):
        target = self.open[number] if kind == "issue" else None
        if target is None:
            for pr in self.prs:
                if pr["number"] == number:
                    pr["labels"] = [x for x in pr["labels"] if x["name"] not in remove]
            return
        names = [x["name"] for x in target["labels"] if x["name"] not in remove]
        target["labels"] = [{"name": n} for n in names + [a for a in add if a not in names]]

    def comment(self, kind, number, body):
        self.comments.append((kind, number, body))

    def activity(self, issue_no, pr):
        return len(self.comments)

    def create_issue(self, title, body, labels):
        self.created.append((title, labels))


def issue(n, labels, body="", state="open", updated="2026-01-01T00:00:00Z"):
    return {"number": n, "title": f"T{n}", "body": body, "state": state, "updatedAt": updated,
            "labels": [{"name": x} for x in labels]}


def labels_of(gh, n):
    return {x["name"] for x in gh.open[n]["labels"]}


def make(tmp_path, gh, runner, **env):
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "0",
                           **env})
    return dispatch.Dispatcher(cfg, gh, runner=runner)


def test_wakes_only_the_assigned_agent(tmp_path):
    gh = FakeGH([issue(1, ["status:in-review", "agent:copydesk"]),
                 issue(2, ["status:blocked", "agent:editor"]),
                 issue(3, ["status:ready-to-merge"]),
                 issue(4, ["status:ready", "agent:reporter", "agent:factcheck"])],
                prs=[{"number": 10, "labels": [], "closingIssuesReferences": [{"number": 1}]}])
    woken = []

    def runner(agent, issue_no, prompt, pr=""):
        woken.append((agent, issue_no))
        gh.prs[0]["labels"].append({"name": "review:approved"})
        gh.edit_labels("issue", 1, ["status:in-test", "agent:factcheck"],
                       ["status:in-review", "agent:copydesk"])
        gh.comment("pr", 10, "review")
        return 0, "ok"

    make(tmp_path, gh, runner).tick()
    assert woken == [("copydesk", "1")]


def test_no_double_wake_while_agent_lock_held(tmp_path):
    gh = FakeGH([issue(1, ["status:ready", "agent:reporter", "attempt:1"])])
    woken = []
    d = make(tmp_path, gh, lambda *a: woken.append(a) or (0, ""))
    lock = dispatch.AgentLock(d.state.dir, "reporter", 3600)
    assert lock.acquire()
    d.tick()
    assert woken == []
    lock.release()


def test_three_failures_escalate_and_stop(tmp_path):
    gh = FakeGH([issue(1, ["status:ready", "agent:reporter", "attempt:1"])])
    calls = []
    d = make(tmp_path, gh, lambda *a: calls.append(a) or (1, "boom ghp_abcdefgh12345"))
    for _ in range(5):
        d.tick()
    assert len(calls) == 3
    assert labels_of(gh, 1) == {"status:blocked", "agent:editor", "attempt:1"}
    assert "ghp_" not in gh.comments[-1][2]
    assert d.state.load("issue-1")["escalated"] is True


def test_exit_zero_without_label_change_counts_as_failure(tmp_path):
    gh = FakeGH([issue(1, ["status:ready", "agent:reporter", "attempt:1"])])
    d = make(tmp_path, gh, lambda *a: (0, "done"))
    d.tick()
    assert d.state.load("issue-1")["failures"] == 1


def test_retry_state_persists_across_instances(tmp_path):
    gh = FakeGH([issue(1, ["status:ready", "agent:reporter", "attempt:1"])])
    make(tmp_path, gh, lambda *a: (1, "x")).tick()
    make(tmp_path, gh, lambda *a: (1, "x")).tick()
    assert make(tmp_path, gh, lambda *a: (1, "x")).state.load("issue-1")["failures"] == 2


def test_backoff_blocks_immediate_retry(tmp_path):
    gh = FakeGH([issue(1, ["status:ready", "agent:reporter", "attempt:1"])])
    calls = []
    d = make(tmp_path, gh, lambda *a: calls.append(a) or (1, "x"), NEWSROOM_RETRY_BACKOFF="600")
    d.tick()
    d.tick()
    assert len(calls) == 1


def test_editor_bootstrap_when_brief_and_no_tickets(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "brief.md").write_text("brief")
    gh = FakeGH()
    woken = []
    make(tmp_path, gh, lambda a, n, p: woken.append(a) or (0, "")).tick()
    assert woken == ["editor"]


def test_editor_not_woken_when_tickets_exist(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "brief.md").write_text("brief")
    gh = FakeGH([issue(1, ["status:ready-to-merge"], state="closed")])
    woken = []
    make(tmp_path, gh, lambda a, n, p: woken.append(a) or (0, "")).tick()
    assert woken == []


# ---- editor lifecycle ------------------------------------------------------------

def test_reroute_after_changes_requested():
    t = lc.Ticket(5, "t", "", {"status:in-review", "agent:copydesk", "attempt:1"},
                  {"review:changes-requested"})
    (a,) = lc.plan_actions([t], set())
    assert a["add"] == ["status:ready", "agent:reporter", "attempt:2"]
    assert "review:changes-requested" in a["remove"] and "attempt:1" in a["remove"]


def test_escalate_after_third_attempt():
    t = lc.Ticket(5, "t", "", {"status:in-test", "agent:factcheck", "attempt:3"},
                  {"test:failed"})
    (a,) = lc.plan_actions([t], set())
    assert a["add"] == ["status:blocked", "agent:editor"]


def test_promote_next_ticket_after_dependency_merged():
    waiting = lc.Ticket(2, "t", "Goal\nDepends on: #1", {"agent:editor"})
    assert lc.plan_actions([waiting], set()) == []
    (a,) = lc.plan_actions([waiting], {1})
    assert a["issue"] == 2 and "status:ready" in a["add"]


def test_no_promotion_while_pipeline_busy():
    busy = lc.Ticket(1, "t", "", {"status:in-review", "agent:copydesk"})
    waiting = lc.Ticket(2, "t", "Depends on: #0", {"agent:editor"})
    assert lc.plan_actions([busy, waiting], {0}) == []


def test_tick_reroutes_and_clears_pr_verdict(tmp_path):
    gh = FakeGH([issue(7, ["status:in-review", "agent:copydesk", "attempt:1"])],
                prs=[{"number": 70, "labels": [{"name": "review:changes-requested"}],
                      "closingIssuesReferences": [{"number": 7}]}])
    woken = []
    make(tmp_path, gh, lambda a, n, p: woken.append(a) or (0, "")).tick()
    assert labels_of(gh, 7) >= {"status:ready", "agent:reporter", "attempt:2"}
    assert gh.prs[0]["labels"] == []


@pytest.mark.parametrize("body,expected", [("Depends on: #1, #3", [1, 3]), ("none", [])])
def test_dependency_parsing(body, expected):
    assert lc.dependencies(body) == expected


# ---- issue -> PR resolution and deterministic copydesk/factcheck wiring ----------------------
def pr_of(n, closes, labels=()):
    return {"number": n, "labels": [{"name": x} for x in labels],
            "closingIssuesReferences": [{"number": c} for c in closes]}


def review_ticket():
    return issue(14, ["status:in-review", "agent:copydesk", "attempt:1"])


def test_deterministic_mode_command_uses_script_and_pr_number(tmp_path):
    cfg = dispatch.Config({"NEWSROOM_REPO_DIR": str(tmp_path),
                           "NEWSROOM_REVIEW_MODE": "deterministic"})
    assert cfg.needs_pr("copydesk") and cfg.needs_pr("factcheck")
    assert not cfg.needs_pr("reporter")
    argv = cfg.command("copydesk", "14", "prompt", "21")
    assert argv[1].endswith("copydesk_agent.py") and argv[-1] == "21"
    assert cfg.command("factcheck", "14", "p", "21")[1].endswith("factcheck_agent.py")
    assert cfg.command("reporter", "14", "p", "")[1] == "agent"  # still OpenClaw


def test_default_mode_keeps_llm_agents(tmp_path):
    cfg = dispatch.Config({"NEWSROOM_REPO_DIR": str(tmp_path)})
    # reviewers are always woken with their resolved PR, even when an LLM agent runs
    assert cfg.needs_pr("copydesk") and cfg.needs_pr("factcheck") and not cfg.needs_pr("reporter")
    assert cfg.command("copydesk", "14", "p")[1:3] == ["-p", "copydesk"]
    assert cfg.command("factcheck", "14", "p")[1:3] == ["agent", "--agent"]


def test_explicit_command_override_wins_and_substitutes_pr(tmp_path):
    cfg = dispatch.Config({"NEWSROOM_REPO_DIR": str(tmp_path),
                           "NEWSROOM_REVIEW_MODE": "deterministic",
                           "NEWSROOM_CMD_COPYDESK": "echo issue={issue} pr={pr}"})
    assert cfg.needs_pr("copydesk")
    assert cfg.command("copydesk", "14", "p", "21")[1:] == ["issue=14", "pr=21"]
    cfg = dispatch.Config({"NEWSROOM_REPO_DIR": str(tmp_path),
                           "NEWSROOM_CMD_COPYDESK": "echo {issue}"})
    assert cfg.needs_pr("copydesk") and cfg.command("copydesk", "14", "p", "21")[1:] == ["14"]


def test_resolve_pr_maps_issue_to_its_single_open_pr(tmp_path):
    gh = FakeGH([review_ticket()], prs=[pr_of(20, [3]), pr_of(21, [14]), pr_of(22, [])])
    d = make(tmp_path, gh, lambda *a, **k: (0, ""))
    assert d.resolve_pr(14) == (21, "")
    assert d.resolve_pr(99)[0] is None


def test_deterministic_tick_passes_resolved_pr_not_issue_number(tmp_path):
    gh = FakeGH([review_ticket()], prs=[pr_of(21, [14])])
    seen = []

    def runner(agent, issue_no, prompt, pr=None):
        seen.append((agent, issue_no, pr))
        gh.edit_labels("issue", 14, ["status:in-test", "agent:factcheck"],
                       ["status:in-review", "agent:copydesk"])
        return 0, "ok"

    make(tmp_path, gh, runner, NEWSROOM_REVIEW_MODE="deterministic").tick()
    assert seen == [("copydesk", "14", "21")]


@pytest.mark.parametrize("prs, reason", [
    ([], "no open PR"),
    ([pr_of(21, [14]), pr_of(23, [14])], "ambiguous"),
])
def test_missing_or_ambiguous_pr_is_a_failed_attempt_and_agent_not_started(tmp_path, prs, reason):
    gh = FakeGH([review_ticket()], prs=prs)
    calls = []
    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (0, ""),
             NEWSROOM_REVIEW_MODE="deterministic")
    d.tick()
    st = d.state.load("issue-14")
    assert calls == [] and st["failures"] == 1 and reason in st["last_error"]


def test_missing_pr_still_escalates_after_three_attempts(tmp_path):
    gh = FakeGH([review_ticket()])
    calls = []
    d = make(tmp_path, gh, lambda *a, **k: calls.append(a) or (0, ""),
             NEWSROOM_REVIEW_MODE="deterministic")
    for _ in range(5):
        d.tick()
    assert calls == [] and labels_of(gh, 14) >= {"status:blocked", "agent:editor"}


def test_default_mode_runner_gets_the_resolved_pr(tmp_path):
    gh = FakeGH([review_ticket()], prs=[pr_of(21, [14])])
    got = []

    def runner(*args, **kwargs):
        got.append((args, kwargs))
        return 1, "x"

    make(tmp_path, gh, runner).tick()
    assert got[0][1] == {"pr": "21"} and got[0][0][:2] == ("copydesk", "14")
    assert "PR #21" in got[0][0][2] and "Issue #14" in got[0][0][2]


def test_deterministic_script_failure_counts_and_retries(tmp_path):
    gh = FakeGH([review_ticket()], prs=[pr_of(21, [14])])
    d = make(tmp_path, gh, lambda *a, **k: (2, "ci check is pending"),
             NEWSROOM_REVIEW_MODE="deterministic")
    d.tick()
    d.tick()
    assert d.state.load("issue-14")["failures"] == 2
