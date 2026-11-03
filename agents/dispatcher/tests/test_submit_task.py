"""Offline tests for the Hermes-Editor intake (submit_task.py): fake GitHub, fake editor."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import submit_task as st

TASK = ("Add a new test file app/tests/test_demo_true.py containing a single test named "
        "test_true_is_true that asserts True is True. Do not modify any existing files.")
GOOD_BODY = """## Goal
Add `app/tests/test_demo_true.py` with one test, `test_true_is_true`.

## Acceptance criteria
- [ ] `app/tests/test_demo_true.py` exists
- [ ] it defines `test_true_is_true`, which asserts `True is True`
- [ ] no existing file is modified

## Out of scope
Any change to an existing file.

## Depends on
none
"""
# What Issue #33 really looked like: the shell ate every backticked identifier.
EATEN_BODY = """Goal: Add a new test file app/tests/test_demo_true.py containing a test.

Acceptance criteria:
- File app/tests/test_demo_true.py exists.
- File app/tests/test_demo_true.py contains a test function .
- The test  asserts .

Out of scope:
- Modifying any existing files.

Depends on: none
"""


def issue(n, body=GOOD_BODY, labels=("status:ready", "agent:reporter", "attempt:1"),
          title="Add test_demo_true.py"):
    return {"number": n, "title": title, "body": body, "labels": [{"name": x} for x in labels]}


class GH:
    def __init__(self, existing=(), prs=()):
        self.open_issues, self.closed_issues = list(existing), []
        self.prs = list(prs)

    def issues(self, state):
        return self.open_issues if state == "open" else self.closed_issues

    def open_prs(self):
        return self.prs


def run(gh, behaviour, **kw):
    msgs = []
    calls = []

    def editor(task):
        calls.append(task)
        return behaviour(gh)

    code, number = st.submit(gh, TASK, editor, log=msgs.append, **kw)
    return code, number, msgs, calls


def test_critical_tokens_capture_paths_and_identifiers():
    toks = st.critical_tokens(TASK)
    assert "app/tests/test_demo_true.py" in toks and "test_true_is_true" in toks
    assert "files" not in toks


def test_valid_issue_is_accepted():
    gh = GH([issue(32, "## Goal\nunrelated work", title="old")])
    code, n, _, calls = run(gh, lambda g: (g.open_issues.append(issue(33)), (0, "ok"))[1])
    assert (code, n) == (0, 33) and len(calls) == 1


def test_eaten_backticks_are_rejected():
    gh = GH()
    code, n, msgs, _ = run(gh, lambda g: (g.open_issues.append(issue(33, EATEN_BODY)), (0, ""))[1])
    text = "\n".join(msgs)
    assert code == 1 and "test_true_is_true" in text and "checklist" in text


def test_missing_sections_and_wrong_labels_are_rejected():
    bad = issue(33, "## Goal\nthing test_true_is_true app/tests/test_demo_true.py\n- [ ] x",
                labels=("status:ready", "status:in-review", "agent:reporter", "attempt:1"))
    gh = GH()
    code, _, msgs, _ = run(gh, lambda g: (g.open_issues.append(bad), (0, ""))[1])
    text = "\n".join(msgs)
    assert code == 1 and "labels" in text and "lacks section" in text


def test_zero_issues_is_a_failure_and_is_not_resent():
    gh = GH()
    code, n, msgs, calls = run(gh, lambda g: (1, "boom"))
    assert code == 1 and n == 0 and len(calls) == 1
    assert "Nothing was resent" in "\n".join(msgs)


def test_two_issues_is_a_duplicate_failure():
    gh = GH()

    def twice(g):
        g.open_issues += [issue(33), issue(34)]
        return 0, ""

    code, _, msgs, _ = run(gh, twice)
    assert code == 1 and "2 new Issue" in "\n".join(msgs)


def test_editor_timeout_or_gateway_drop_after_creating_the_issue_is_accepted():
    gh = GH()
    code, n, msgs, _ = run(gh, lambda g: (g.open_issues.append(issue(33)),
                                          (124, "timed out; outcome uncertain"))[1])
    assert (code, n) == (0, 33) and "not re-running" in "\n".join(msgs)


def test_editor_opening_a_pr_is_rejected():
    gh = GH()

    def sneaky(g):
        g.open_issues.append(issue(33))
        g.prs.append({"number": 34})
        return 0, ""

    code, _, msgs, _ = run(gh, sneaky)
    assert code == 1 and "opened PR" in "\n".join(msgs)


def test_possible_duplicate_of_an_open_ticket_is_refused_before_calling_the_editor():
    gh = GH([issue(33)])
    code, n, msgs, calls = run(gh, lambda g: (0, ""))
    assert (code, n) == (3, 33) and calls == [] and "REFUSED" in "\n".join(msgs)
    gh2 = GH([issue(33)])
    code, _, _, calls = run(gh2, lambda g: (g.open_issues.append(issue(34)), (0, ""))[1],
                            allow_duplicate=True)
    assert code == 0 and len(calls) == 1


def test_prompt_demands_one_issue_body_file_and_exact_labels():
    p = st.editor_prompt(TASK, "o/r")
    assert TASK in p and "EXACTLY ONE" in p and "--body-file" in p
    assert "status:ready" in p and "agent:reporter" in p and "attempt:1" in p
    assert "never merge" in p.lower() and "do not create branches" in p.lower()
