"""Regression tests for the Issue #48 / PR #49 failure (no network, no model calls).

Live incident, with the cause of each symptom:
* Reporter retries never fixed PR #49: OpenClaw resumed the Reporter's old session ("still
  awaiting review"), the prompt carried neither the Issue body nor the review, and the dispatcher
  never checked that the retry pushed anything.
* Copydesk posted a review of Issue #41 / PR #42 on Issue #48: its scratch file
  `review_comment.md` from the earlier task could not be overwritten, so `--body-file` published
  the stale file; any new comment counted as a valid hand-off.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch
import handoff
from notes import SHA_A, SHA_B, factcheck_note, reporter_note, review_note
from test_handoff_validation import Clock, Repo, failures, make

BODY = (
    "## Goal\nAdd GET /build-info returning the exact JSON.\n\n"
    "## Acceptance criteria\n- [ ] GET /build-info endpoint exists\n"
    "- [ ] Returns service autonomous-newsroom and status ok\n"
    "- [ ] A pytest asserts the exact JSON\n\n"
    "## Out of scope\n- Modifying the UI or deployment files\n\n## Depends on\nnone\n"
)


class TaskRepo(Repo):
    """Repo whose Issue #1 has a real body and whose PR knows its branch."""

    def _issue(self):
        return {**super()._issue(), "title": "Add build-info", "body": BODY}

    def open_prs(self):
        return [{**p, "headRefName": "t1-build-info"} for p in super().open_prs()]


def prompts_of(repo, **behaviours):
    seen = []

    def runner(agent, issue_no, prompt, pr=""):
        seen.append((agent, issue_no, prompt, pr))
        behaviours[agent](repo)
        return 0, "ok"

    runner.seen = seen
    return runner


def reporter_pushes(attempt, head=SHA_B):
    def act(r):
        if not r.prs:
            r.open_pr()
        r.prs[7]["head"] = head
        r.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                      ["status:ready", "agent:reporter", "status:in-progress"])
        r.comment("issue", 1, reporter_note(attempt=attempt))
        r.comment("pr", 7, reporter_note(attempt=attempt))
    return act


# ---- 1-3: Reporter attempts ------------------------------------------------------------
def test_reporter_attempt_1_creates_one_pr_and_hands_off(tmp_path):
    repo = TaskRepo()
    runner = prompts_of(repo, reporter=reporter_pushes(1, SHA_A))
    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0 and list(repo.prs) == [7]
    assert repo.issue() >= {"status:in-review", "agent:copydesk"}
    prompt = runner.seen[0][2]
    assert BODY.strip() in prompt, "the Reporter must get the COMPLETE Issue body"
    assert "Attempt: 1 of 3" in prompt and "none yet (create exactly one)" in prompt


def test_reporter_attempt_2_updates_the_existing_pr_not_a_new_one(tmp_path):
    repo = TaskRepo(["status:ready", "agent:reporter", "attempt:2"])
    repo.open_pr()
    repo.comment("pr", 7, review_note(criteria=3, fails=1))
    runner = prompts_of(repo, reporter=reporter_pushes(2))
    d = make(tmp_path, repo, runner)
    d.tick()
    assert failures(d) == 0
    assert list(repo.prs) == [7], "a retry must update PR #7, never open another"
    assert repo.prs[7]["head"] == SHA_B
    assert repo.issue() >= {"status:in-review", "agent:copydesk"}


def test_reporter_retry_that_pushes_nothing_is_rejected_and_stays_with_the_reporter(tmp_path):
    """The live failure: the Reporter said 'waiting for review' and changed nothing."""
    repo = TaskRepo(["status:ready", "agent:reporter", "attempt:2"])
    repo.open_pr(head=SHA_A)

    def waits(r):  # moves the labels and posts a proper note but pushes no commit
        reporter_pushes(2, head=SHA_A)(r)

    d = make(tmp_path, repo, prompts_of(repo, reporter=waits))
    d.tick()
    assert failures(d) == 1 and "pushed no new commit" in d.state.load("issue-1")["last_error"]
    assert repo.issue() >= {"status:ready", "agent:reporter"}, "hand-off undone: reporter retries"
    assert "agent:copydesk" not in repo.issue()


def test_reporter_retry_prompt_carries_the_review_branch_and_failed_criteria(tmp_path):
    repo = TaskRepo(["status:ready", "agent:reporter", "attempt:2"])
    repo.open_pr(head=SHA_A)
    stale = review_note(n=41, pr=42, criteria=2, fails=2).replace("criterion", "STALE")
    current = review_note(criteria=3, fails=1) + "#### Required Fixes\n1. return autonomous-newsroom\n"
    repo.comment("pr", 7, current)
    repo.comment("pr", 7, stale)  # newest comment belongs to ANOTHER task
    runner = prompts_of(repo, reporter=reporter_pushes(2))
    make(tmp_path, repo, runner).tick()
    prompt = runner.seen[0][2]
    assert "Required Fixes" in prompt and "return autonomous-newsroom" in prompt
    assert "STALE" not in prompt, "another task's review must never reach the Reporter"
    assert "Attempt: 2 of 3" in prompt and "Pull request: #7 (branch t1-build-info)" in prompt
    assert "no new PR" in prompt and "A retry that pushes no new commit is rejected" in prompt
    assert "Out of scope" in prompt and "pytest asserts the exact JSON" in prompt


# ---- 4-6: Copydesk review validation ----------------------------------------------------
def copydesk_with(note, verdict="review:approved"):
    def act(r):
        r.edit_labels("pr", 7, [verdict])
        if verdict == "review:approved":
            r.edit_labels("issue", 1, ["status:in-test", "agent:factcheck"],
                          ["status:in-review", "agent:copydesk"])
        r.comment("pr", 7, note)
        r.comment("issue", 1, note)
    return act


def review_repo():
    repo = TaskRepo(["status:in-review", "agent:copydesk", "attempt:1"])
    repo.open_pr(head=SHA_A)
    return repo


@pytest.mark.parametrize("note,why", [
    (review_note(n=41, pr=42, head="1c375b1" + "0" * 33, criteria=3), "another task"),
    (review_note(n=1, pr=42, criteria=3), "another task"),
    (review_note(n=41, pr=7, criteria=3), "another task"),
])
def test_copydesk_review_of_an_unrelated_issue_or_pr_is_rejected(tmp_path, note, why):
    repo = review_repo()
    d = make(tmp_path, repo, prompts_of(repo, copydesk=copydesk_with(note)))
    d.tick()
    assert failures(d) == 1 and why in d.state.load("issue-1")["last_error"]
    assert "review:approved" not in repo.pr(), "the stale verdict is dropped from the PR"
    assert repo.issue() >= {"status:in-review", "agent:copydesk"}, "Issue goes back to Copydesk"
    assert "agent:factcheck" not in repo.issue()


def test_copydesk_review_of_a_stale_pr_head_is_rejected(tmp_path):
    repo = review_repo()
    stale_head = review_note(head=SHA_B, criteria=3)  # PR head is SHA_A
    d = make(tmp_path, repo, prompts_of(repo, copydesk=copydesk_with(stale_head)))
    d.tick()
    assert "does not cite the current PR head" in d.state.load("issue-1")["last_error"]
    assert "review:approved" not in repo.pr()


@pytest.mark.parametrize("generic", [
    "Handoff to copydesk for review. PR: #7",   # the exact comment accepted for PR #49
    "### Handoff  copydesk → factcheck\nreviewed, all good",
    "LGTM",
])
def test_generic_comment_does_not_satisfy_the_handoff(tmp_path, generic):
    repo = review_repo()
    d = make(tmp_path, repo, prompts_of(repo, copydesk=copydesk_with(generic)))
    d.tick()
    assert failures(d) == 1 and "generic comment" in d.state.load("issue-1")["last_error"]
    assert "review:approved" not in repo.pr()


def test_generic_reporter_comment_is_rejected_too(tmp_path):
    repo = TaskRepo()

    def reporter(r):
        r.open_pr()
        r.edit_labels("issue", 1, ["status:in-review", "agent:copydesk"],
                      ["status:ready", "agent:reporter"])
        r.comment("issue", 1, "Handoff to copydesk for review. PR: #7")

    d = make(tmp_path, repo, prompts_of(repo, reporter=reporter))
    d.tick()
    assert failures(d) == 1
    assert repo.issue() >= {"status:ready", "agent:reporter"}


def test_review_must_cover_every_criterion_and_the_out_of_scope_section(tmp_path):
    repo = review_repo()
    partial = review_note(criteria=2)  # the Issue has 3 acceptance criteria
    d = make(tmp_path, repo, prompts_of(repo, copydesk=copydesk_with(partial)))
    d.tick()
    assert "3 acceptance criteria" in d.state.load("issue-1")["last_error"]
    no_scope = review_note(criteria=3).replace("Out of scope", "Notes")
    repo2 = review_repo()
    d2 = make(tmp_path / "b", repo2, prompts_of(repo2, copydesk=copydesk_with(no_scope)))
    d2.tick()
    assert "Out of scope" in d2.state.load("issue-1")["last_error"]


def test_a_correct_review_is_accepted_and_a_rejection_must_contain_a_fail(tmp_path):
    repo = review_repo()
    d = make(tmp_path, repo, prompts_of(repo, copydesk=copydesk_with(review_note(criteria=3))))
    d.tick()
    assert failures(d) == 0 and repo.issue() >= {"status:in-test", "agent:factcheck"}
    repo2 = review_repo()
    liar = review_note(criteria=3)  # all PASS yet changes-requested
    d2 = make(tmp_path / "b", repo2,
              prompts_of(repo2, copydesk=copydesk_with(liar, "review:changes-requested")))
    d2.tick()
    assert "lists no FAIL" in d2.state.load("issue-1")["last_error"]
    repo3 = review_repo()
    bad = review_note(criteria=3, fails=1)  # a FAIL line yet approved
    d3 = make(tmp_path / "c", repo3, prompts_of(repo3, copydesk=copydesk_with(bad)))
    d3.tick()
    assert "contradicts" in d3.state.load("issue-1")["last_error"]


def test_factcheck_must_cite_the_head_and_show_ruff_and_pytest(tmp_path):
    def factcheck_with(note):
        def act(r):
            r.edit_labels("pr", 7, ["test:passed"])
            r.edit_labels("issue", 1, ["status:ready-to-merge"],
                          ["status:in-test", "agent:factcheck"])
            r.comment("pr", 7, note)
        return act

    for i, (note, why) in enumerate([
        (factcheck_note(head=SHA_B), "does not cite the current PR head"),
        (factcheck_note().replace("pytest", "tests").replace("ruff", "lint"), "no ruff / pytest"),
        ("tests pass", "generic comment"),
    ]):
        repo = TaskRepo(["status:in-test", "agent:factcheck", "attempt:1"])
        repo.open_pr(labels=["review:approved"], head=SHA_A)
        d = make(tmp_path / str(i), repo, prompts_of(repo, factcheck=factcheck_with(note)))
        d.tick()
        assert why in d.state.load("issue-1")["last_error"], note
        assert "test:passed" not in repo.pr() and "status:ready-to-merge" not in repo.issue()


# ---- 7: labels ---------------------------------------------------------------------------
def test_workflow_labels_never_stay_on_a_pr(tmp_path):
    repo = review_repo()

    def sloppy(r):
        copydesk_with(review_note(criteria=3))(r)
        r.edit_labels("pr", 7, ["status:in-test", "agent:factcheck"])

    d = make(tmp_path, repo, prompts_of(repo, copydesk=sloppy))
    d.tick()
    assert not {x for x in repo.pr() if x.startswith(("status:", "agent:"))}
    assert failures(d) == 0, "stray PR labels are repaired, the valid review stands"


# ---- 8-9: invocations --------------------------------------------------------------------
def test_dispatcher_does_not_launch_a_duplicate_invocation(tmp_path):
    repo = TaskRepo()
    calls = []
    holder = {}

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        holder["d"].tick()  # a second tick while the first agent is still running
        holder["d"].tick()
        reporter_pushes(1, SHA_A)(repo)
        return 0, "ok"

    d = make(tmp_path, repo, runner)
    holder["d"] = d
    d.tick()
    assert calls == ["reporter"], "the per-agent lock must stop concurrent duplicates"


@pytest.mark.parametrize("code,output", [
    (124, "timed out; outcome uncertain"),
    (1, "Gateway disconnected; turn outcome is unknown. Do not resend the work."),
])
def test_uncertain_hermes_or_timeout_outcome_is_not_rerun_immediately(tmp_path, code, output):
    repo = review_repo()
    calls = []
    clock = Clock()

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        return code, output  # nothing happened on GitHub (yet)

    d = make(tmp_path, repo, runner, clock, NEWSROOM_SETTLE_SECONDS="600")
    for _ in range(4):
        d.tick()
        clock.t += 100
    assert calls == ["copydesk"], "uncertain outcome: wait for GitHub, do not run again"
    assert failures(d) == 0 and "uncertain" in d.state.load("issue-1")


def test_uncertain_outcome_that_materialises_is_accepted_without_rerun(tmp_path):
    repo = review_repo()
    clock = Clock()
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        return 1, "Gateway disconnected; turn outcome is unknown"

    d = make(tmp_path, repo, runner, clock)
    d.tick()
    copydesk_with(review_note(criteria=3))(repo)  # the agent actually finished meanwhile
    clock.t += 30
    d.tick()
    assert calls == ["copydesk"] and failures(d) == 0
    assert repo.issue() >= {"status:in-test", "agent:factcheck"}


def test_authentication_error_escalates_at_once_without_retries(tmp_path):
    repo = TaskRepo()
    calls = []

    def runner(agent, issue_no, prompt, pr=""):
        calls.append(agent)
        return 1, "HTTP 401 Unauthorized: API key not valid"

    d = make(tmp_path, repo, runner)
    for _ in range(4):
        d.tick()
    assert calls == ["reporter"], "a retry cannot fix bad credentials"
    assert repo.issue() >= {"status:blocked", "agent:editor"}
    assert d.state.load("issue-1")["escalated"] is True


# ---- prompts and session isolation -------------------------------------------------------
def test_copydesk_prompt_pins_exact_task_facts_and_requires_verification(tmp_path):
    repo = review_repo()
    repo.comment("issue", 1, reporter_note())
    repo.comment("pr", 7, reporter_note(n=41, pr=42))  # another task's note is ignored
    runner = prompts_of(repo, copydesk=copydesk_with(review_note(criteria=3)))
    make(tmp_path, repo, runner).tick()
    prompt = runner.seen[0][2]
    assert "Issue: #1 (Add build-info)" in prompt and "Pull request: #7" in prompt
    assert f"Expected PR head SHA: {SHA_A}" in prompt
    assert BODY.strip() in prompt and "ISSUE #1 BODY (verbatim)" in prompt
    assert "Ticket: #1 · PR: #7" in prompt, "latest reporter hand-off of THIS task"
    assert "PR: #42" not in prompt
    assert "closingIssuesReferences,headRefOid" in prompt and "STOP" in prompt
    assert "Out of scope" in prompt and "Do NOT look at other Issues or PRs" in prompt
    assert "runs" in prompt and "fresh directory" in prompt  # per-run scratch directory


def test_each_invocation_gets_its_own_scratch_directory_and_session(tmp_path, monkeypatch):
    cfg = dispatch.Config({"NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "s"),
                           "NEWSROOM_REPO_DIR": str(tmp_path)})
    clock = Clock()
    d = dispatch.Dispatcher(cfg, TaskRepo(), clock=clock)
    argvs = []

    class Proc:
        returncode = 0

        def communicate(self, timeout=None):
            return "ok", ""

    monkeypatch.setattr(dispatch.subprocess, "Popen",
                        lambda argv, **kw: (argvs.append(argv), Proc())[1])
    for _ in range(2):
        d._run_subprocess("reporter", "1", "PROMPT BODY", "")
        d._run_subprocess("copydesk", "1", "PROMPT BODY", "7")
        clock.t += 1
    rep1, cop1, rep2, cop2 = argvs
    sessions = [a[a.index("--session-id") + 1] for a in (rep1, rep2)]
    assert sessions[0] != sessions[1] and sessions[0].startswith("nr-")
    for argv in (cop1, cop2):
        assert argv[1:5] == ["-p", "copydesk", "chat", "--query-file"]
        assert not {"--resume", "-r", "--continue", "-c"} & set(argv), "never resume a session"
        assert "--oneshot" in argv and argv[argv.index("--source") + 1] == "tool"
        assert "--max-turns" in argv and "--run-budget" in argv
    assert cop1[cop1.index("--query-file") + 1] != cop2[cop2.index("--query-file") + 1]
    assert Path(cop1[cop1.index("--query-file") + 1]).read_text(encoding="utf-8") == "PROMPT BODY"
    assert "--message-file" in rep1 and "--message" not in rep1


# ---- pure validator ----------------------------------------------------------------------
def test_handoff_helpers():
    assert len(handoff.criteria(BODY)) == 3
    assert handoff.criteria("## Goal\nx\n- [ ] not under acceptance") == []
    assert handoff.names_task(reporter_note(), 1, 7)
    assert not handoff.names_task(reporter_note(n=41, pr=42), 1, 7)
    assert not handoff.names_task("Ticket: #1 only", 1, 7)
    assert handoff.names_task("Ticket: #1 and PR: #7", 1, 7)
    assert not handoff.names_task("Ticket: #10 · PR: #7", 1, 7)  # #10 is not #1
    texts = [reporter_note(), review_note(n=41, pr=42)]
    assert handoff.latest_handoff(texts, 1, 7, ("copydesk",)) == ""
    assert handoff.latest_handoff(texts, 1, 7, ("reporter",)).startswith("### Handoff")


# ---- 12: CI and Gate protections untouched ----------------------------------------------
ROOT = Path(__file__).resolve().parents[3]


def test_ci_and_gate_workflows_are_unchanged_from_origin_main():
    diff = subprocess.run(["git", "-C", str(ROOT), "diff", "--stat", "origin/main", "--",
                           ".github"], capture_output=True, text=True, check=False)
    if diff.returncode != 0:
        pytest.skip("origin/main not available")
    assert diff.stdout.strip() == "", f"CI/Gate files must not change:\n{diff.stdout}"


def test_gate_still_requires_ci_review_and_test_labels():
    gate = (ROOT / ".github" / "workflows" / "gate.yml").read_text(encoding="utf-8")
    script = (ROOT / ".github" / "scripts" / "gate_decide.sh").read_text(encoding="utf-8")
    text = gate + script
    for needle in ("review:approved", "test:passed"):
        assert needle in text


def test_the_dispatcher_has_no_merge_or_branch_protection_capability():
    source = (ROOT / "agents" / "dispatcher" / "dispatch.py").read_text(encoding="utf-8")
    for forbidden in ("pr merge", '"merge"', "branch-protection", "--force", "push -f"):
        assert forbidden not in source
