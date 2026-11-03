"""Offline end-to-end test of the whole ticket state machine.

Fake GitHub + fake agent runner: no network, no gh, no OpenClaw/Hermes, no sleeping.
The fake agents apply exactly the label transitions in agents/PROTOCOL.md (the real
copydesk/factcheck scripts write the same ones through ghlib.record). The real dispatcher,
the real editor_lifecycle and the real .github/scripts/gate_decide.sh are exercised.

Merging is a human action: the fake GitHub has no merge method at all, so any agent (or the
dispatcher) trying to merge would raise AttributeError and fail the test.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch

GATE = Path(__file__).resolve().parents[3] / ".github" / "scripts" / "gate_decide.sh"
needs_bash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


class FakeGitHub:
    """Issues and PRs with labels; no merge capability."""

    def __init__(self):
        self.issue = {"number": 1, "title": "demo ticket", "body": "Goal: demo", "state": "open",
                      "updatedAt": "2026-01-01T00:00:00Z",
                      "labels": [{"name": n} for n in
                                 ("status:ready", "agent:reporter", "attempt:1")]}
        self.pr = None
        self.comments = []

    # --- interface used by the dispatcher -------------------------------------------
    def issues(self, state):
        return [self.issue] if state == "open" and self.issue["state"] == "open" else (
            [self.issue] if state == "closed" and self.issue["state"] == "closed" else [])

    def open_prs(self):
        return [self.pr] if self.pr else []

    def edit_labels(self, kind, number, add=(), remove=()):
        target = self.issue if kind == "issue" else self.pr
        names = [x["name"] for x in target["labels"] if x["name"] not in remove]
        target["labels"] = [{"name": n} for n in names + [a for a in add if a not in names]]

    def comment(self, kind, number, body):
        self.comments.append((kind, number, body))

    def create_issue(self, *a):  # pragma: no cover - must not be reached
        raise AssertionError("dispatcher must not create issues in this scenario")

    # --- helpers --------------------------------------------------------------------
    def labels(self, kind):
        return {x["name"] for x in (self.issue if kind == "issue" else self.pr)["labels"]}


def gate(gh):
    """Run the real gate decision on the PR's linked-issue count and verdict labels."""
    linked = len(gh.pr["closingIssuesReferences"])
    labels = gh.labels("pr")
    out = subprocess.run([shutil.which("bash"), str(GATE), str(linked),
                          str("review:approved" in labels).lower(),
                          str("test:passed" in labels).lower()],
                         check=False, capture_output=True, text=True)
    return out.returncode, out.stdout


@needs_bash
def test_full_cycle_ticket_to_ready_to_merge(tmp_path):
    gh = FakeGitHub()
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append((agent, issue_no, pr))
        if agent == "reporter":
            # claim, push branch, open PR "Closes #1", hand off to copydesk
            gh.edit_labels("issue", 1, ["status:in-progress"], ["status:ready"])
            gh.pr = {"number": 7, "labels": [], "closingIssuesReferences": [{"number": 1}]}
            gh.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                           ["status:in-progress", "agent:reporter"])
        elif agent == "copydesk":
            gh.edit_labels("pr", 7, ["review:approved"])
            gh.edit_labels("issue", 1, ["status:in-test", "agent:factcheck"],
                           ["status:in-review", "agent:copydesk"])
        elif agent == "factcheck":
            gh.edit_labels("pr", 7, ["test:passed"])
            gh.edit_labels("issue", 1, ["status:ready-to-merge"],
                           ["status:in-test", "agent:factcheck"])
        else:  # pragma: no cover
            raise AssertionError(f"unexpected agent woken: {agent}")
        return 0, "ok"

    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_REPO_DIR": str(tmp_path), "NEWSROOM_RETRY_BACKOFF": "0",
                           "NEWSROOM_REVIEW_MODE": "deterministic"})
    d = dispatch.Dispatcher(cfg, gh, runner=runner)

    # tick 1: eligible Issue wakes ONLY the reporter (with the Issue, not a PR number)
    d.tick()
    assert calls == [("reporter", "1", "")]
    assert gh.labels("issue") == {"status:in-review", "agent:copydesk", "attempt:1"}
    assert gh.pr["closingIssuesReferences"] == [{"number": 1}]
    assert gh.labels("pr") == set()
    assert gate(gh)[0] == 1, "gate must block a newsroom PR with no verdict labels"

    # tick 2: copydesk is woken with the PR resolved from the Issue; records review:approved
    d.tick()
    assert calls[-1] == ("copydesk", "1", "7")
    assert gh.labels("pr") == {"review:approved"}
    assert gh.labels("issue") == {"status:in-test", "agent:factcheck", "attempt:1"}
    assert gate(gh)[0] == 1, "gate must still block with only review:approved"

    # tick 3: factcheck is woken with the same PR; records test:passed -> ready-to-merge
    d.tick()
    assert calls[-1] == ("factcheck", "1", "7")
    assert gh.labels("pr") == {"review:approved", "test:passed"}
    assert gh.labels("issue") == {"status:ready-to-merge", "attempt:1"}
    code, out = gate(gh)
    assert code == 0 and "GATE PASSED" in out

    # terminal: nobody is woken any more; only a human merge moves it from here
    d.tick()
    assert [c[0] for c in calls] == ["reporter", "copydesk", "factcheck"]
    assert not hasattr(gh, "merge")


@needs_bash
def test_gate_requires_both_verdicts_and_passes_maintenance_prs():
    base = {"number": 7, "closingIssuesReferences": [{"number": 1}]}
    for labels, want in ((set(), 1), ({"review:approved"}, 1), ({"test:passed"}, 1),
                         ({"review:approved", "test:passed"}, 0)):
        gh = FakeGitHub()
        gh.pr = {**base, "labels": [{"name": n} for n in labels]}
        assert gate(gh)[0] == want, labels
    gh = FakeGitHub()
    gh.pr = {"number": 8, "labels": [], "closingIssuesReferences": []}
    assert gate(gh)[0] == 0  # maintenance PR: no linked Issue, labels not required
