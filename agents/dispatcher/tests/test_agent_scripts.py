"""Offline tests for the deterministic Copydesk / Factcheck scripts (gh is faked)."""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import copydesk_agent  # noqa: E402
import factcheck_agent  # noqa: E402
import ghlib  # noqa: E402

SHA = "a" * 40
APPROVED = ("review:approved",)


def pr(labels=(), ci="SUCCESS", status="COMPLETED", closes=(14,), draft=False,
       mergeable="MERGEABLE", sha=SHA):
    checks = [] if ci is None else [
        {"name": "ci", "status": status, "conclusion": ci},
        {"name": "gate", "status": "COMPLETED", "conclusion": "FAILURE"},
    ]
    return {"number": 21, "labels": [{"name": x} for x in labels], "headRefOid": sha,
            "isDraft": draft, "mergeable": mergeable, "statusCheckRollup": checks,
            "closingIssuesReferences": [{"number": c} for c in closes]}


class Rec:
    def __init__(self):
        self.records, self.comments, self.details = [], [], []


@pytest.fixture
def gh(monkeypatch):
    rec = Rec()
    monkeypatch.setattr(ghlib, "pr_details", lambda n: rec.details.pop(0) if rec.details else None)

    def record(pr_number, issue, **kw):
        rec.records.append((pr_number, issue, kw))
        return True

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(ghlib, "record", record)
    monkeypatch.setattr(ghlib, "run", lambda cmd, **kw: rec.comments.append(cmd) or Done())
    return rec


def test_gate_failure_does_not_confuse_ci_state():
    assert ghlib.ci_state(pr()) == "success"
    assert ghlib.ci_state(pr(ci=None)) == "missing"
    assert ghlib.ci_state(pr(ci="", status="IN_PROGRESS")) == "pending"
    assert ghlib.ci_state(pr(ci="FAILURE")) == "failure"


def test_linked_issue_requires_exactly_one():
    assert ghlib.linked_issue(pr()) == 14
    assert ghlib.linked_issue(pr(closes=())) is None
    assert ghlib.linked_issue(pr(closes=(1, 2))) is None


@pytest.mark.parametrize("kw, verdict", [
    ({}, "approved"), ({"ci": "FAILURE"}, "changes"), ({"draft": True}, "changes"),
    ({"mergeable": "CONFLICTING"}, "changes"), ({"closes": ()}, "changes"),
    ({"ci": None}, "wait"), ({"ci": "", "status": "QUEUED"}, "wait"),
])
def test_copydesk_evaluate(kw, verdict):
    assert copydesk_agent.evaluate(pr(**kw))[0] == verdict


def test_copydesk_approves_only_when_criteria_pass(gh):
    gh.details = [pr()]
    assert copydesk_agent.main(21) == 0
    _, issue, kw = gh.records[0]
    assert issue == 14 and kw["pr_add"] == ["review:approved"]
    assert kw["issue_add"] == ["status:in-test", "agent:factcheck"]


def test_copydesk_requests_changes_on_failed_ci(gh):
    gh.details = [pr(ci="FAILURE")]
    assert copydesk_agent.main(21) == 0
    kw = gh.records[0][2]
    assert kw["pr_add"] == ["review:changes-requested"] and "ci check failed" in kw["comment"]
    assert "status:in-test" not in kw["issue_add"]


def test_copydesk_writes_no_verdict_while_ci_pending(gh):
    gh.details = [pr(ci="", status="IN_PROGRESS")]
    assert copydesk_agent.main(21) == 2 and gh.records == []


def test_copydesk_missing_pr_is_error(gh):
    assert copydesk_agent.main(21) == 1 and gh.records == []


def test_copydesk_record_failure_is_error(gh, monkeypatch):
    gh.details = [pr()]
    monkeypatch.setattr(ghlib, "record", lambda *a, **k: False)
    assert copydesk_agent.main(21) == 1


@pytest.mark.parametrize("kw", [
    {"labels": ()},
    {"labels": APPROVED, "ci": "FAILURE"},
    {"labels": APPROVED, "closes": ()},
])
def test_factcheck_ineligible_writes_nothing(gh, monkeypatch, kw):
    gh.details = [pr(**kw)]
    monkeypatch.setattr(factcheck_agent, "run_local_tests",
                        lambda *a: pytest.fail("must not test an ineligible PR"))
    assert factcheck_agent.main(21) == 2 and gh.records == []


def test_factcheck_tests_exact_head_and_records_pass(gh, monkeypatch):
    gh.details = [pr(labels=APPROVED), pr(labels=APPROVED)]
    seen = []
    monkeypatch.setattr(factcheck_agent, "run_local_tests",
                        lambda n, sha: seen.append((n, sha)) or (True, "ok"))
    assert factcheck_agent.main(21) == 0
    assert seen == [(21, SHA)]
    kw = gh.records[0][2]
    assert kw["pr_add"] == ["test:passed"] and kw["issue_add"] == ["status:ready-to-merge"]
    assert SHA in kw["comment"]


def test_factcheck_records_genuine_failure(gh, monkeypatch):
    gh.details = [pr(labels=APPROVED), pr(labels=APPROVED)]
    monkeypatch.setattr(factcheck_agent, "run_local_tests", lambda n, sha: (False, "Pytest failed"))
    assert factcheck_agent.main(21) == 0
    kw = gh.records[0][2]
    assert kw["pr_add"] == ["test:failed"] and "test:passed" not in kw["pr_add"]


def test_factcheck_cannot_run_checks_writes_no_verdict(gh, monkeypatch):
    gh.details = [pr(labels=APPROVED), pr(labels=APPROVED)]
    monkeypatch.setattr(factcheck_agent, "run_local_tests", lambda n, sha: (None, "no uv"))
    assert factcheck_agent.main(21) == 2 and gh.records == []


def test_factcheck_discards_result_if_head_moved(gh, monkeypatch):
    gh.details = [pr(labels=APPROVED), pr(labels=APPROVED, sha="b" * 40)]
    monkeypatch.setattr(factcheck_agent, "run_local_tests", lambda n, sha: (True, "ok"))
    assert factcheck_agent.main(21) == 2 and gh.records == []
