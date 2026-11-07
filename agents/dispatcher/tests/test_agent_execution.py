"""Tests that run real subprocesses (agent invocation) and the real gate.yml script."""

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch
from test_dispatcher import FakeGH, issue, labels_of, make

ROOT = Path(__file__).resolve().parents[3]


def real_dispatcher(tmp_path, code_snippet, **env):
    """Dispatcher whose reporter command is a REAL child process (no runner mock)."""
    cmd = f'"{sys.executable}" -c "{code_snippet}" {{issue}} {{prompt}}'
    gh = FakeGH([issue(7, ["status:ready", "agent:reporter", "attempt:1"])])
    return gh, make(tmp_path, gh, None, NEWSROOM_CMD_REPORTER=cmd, **env)


def test_real_subprocess_captures_output_and_exit_code(tmp_path):
    _, d = real_dispatcher(
        tmp_path, "import sys;print('issue=' + sys.argv[1]);print('boom',file=sys.stderr);sys.exit(3)")
    code, text = d.run_agent("reporter", "7", "do the thing")
    assert code == 3
    assert "issue=7" in text and "boom" in text
    assert list((d.state.dir / "logs").glob("reporter-7-*.log"))


def test_real_subprocess_failure_counts_and_is_not_success(tmp_path):
    gh, d = real_dispatcher(tmp_path, "import sys;sys.exit(1)")
    d.tick()
    assert d.state.load("issue-7")["failures"] == 1
    assert labels_of(gh, 7) == {"status:ready", "agent:reporter", "attempt:1"}


def test_real_subprocess_timeout_returns_124(tmp_path):
    _, d = real_dispatcher(tmp_path, "import time;time.sleep(30)")
    d.cfg.timeout = -29  # subprocess timeout = timeout + 30 = 1 s
    code, text = d.run_agent("reporter", "7", "x")
    assert code == 124 and "timed out" in text


def test_missing_agent_binary_returns_127(tmp_path):
    gh = FakeGH([issue(7, ["status:ready", "agent:reporter", "attempt:1"])])
    d = make(tmp_path, gh, None, NEWSROOM_CMD_REPORTER="definitely-not-a-real-binary-xyz {issue}")
    code, text = d.run_agent("reporter", "7", "x")
    assert code == 127 and "could not start" in text


def test_prompt_names_the_ticket_and_forbids_merging():
    t = dispatch.lifecycle.Ticket(12, "Fix RSS", "", {"status:ready", "agent:reporter"})
    prompt = dispatch.prompt_for("reporter", 12, t)
    assert "Issue #12" in prompt and "never merge" in prompt


def test_stale_ready_label_next_to_in_progress_is_repaired(tmp_path):
    """Issue #12 in the real repo carried status:ready AND status:in-progress and was skipped."""
    gh = FakeGH([issue(12, ["status:ready", "status:in-progress", "agent:reporter", "attempt:2"],
                       updated=datetime.now(UTC).isoformat())])
    woken = []
    make(tmp_path, gh, lambda *a: woken.append(a) or (0, "")).tick()
    assert labels_of(gh, 12) == {"status:in-progress", "agent:reporter", "attempt:2"}
    assert woken == []  # freshly claimed work is only woken once stale
    assert "label repair" in gh.comments[-1][2]


def test_malformed_ticket_is_never_woken(tmp_path):
    gh = FakeGH([issue(5, ["status:ready", "status:in-test", "agent:reporter"])])
    woken = []
    d = make(tmp_path, gh, lambda *a: woken.append(a) or (0, ""))
    for _ in range(3):
        d.tick()
    assert woken == []
    assert labels_of(gh, 5) == {"status:ready", "status:in-test", "agent:reporter"}


def test_next_ticket_is_woken_in_the_same_tick_after_merge(tmp_path):
    """#1 merged (closed); #2 waits on it with agent:editor and no status."""
    gh = FakeGH([issue(1, [], state="closed"),
                 issue(2, ["agent:editor", "attempt:1"], body="Depends on: #1")])
    woken = []
    make(tmp_path, gh, lambda a, n, p: woken.append((a, n)) or (0, "")).tick()
    assert woken == [("reporter", "2")]
    assert {"status:ready", "agent:reporter"} <= labels_of(gh, 2)


def test_next_ticket_not_started_while_dependency_open(tmp_path):
    gh = FakeGH([issue(1, ["status:ready-to-merge"]),
                 issue(2, ["agent:editor", "attempt:1"], body="Depends on: #1")])
    woken = []
    make(tmp_path, gh, lambda *a: woken.append(a) or (0, "")).tick()
    assert woken == []
    assert "status:ready" not in labels_of(gh, 2)


def test_dispatcher_never_calls_merge(tmp_path):
    src = (ROOT / "agents" / "dispatcher" / "dispatch.py").read_text()
    assert not re.search(r'"merge"|pr merge|\bmerge_pr\b', src)


# ---- gate.yml: run the real step script against fabricated event payloads -------------
GATE = (ROOT / ".github" / "workflows" / "gate.yml").read_text()
SCRIPT = GATE.split("run: |\n", 1)[1]
SCRIPT = "\n".join(line[10:] for line in SCRIPT.splitlines())
BASH = shutil.which("bash")
JQ = shutil.which("jq")


def run_gate(tmp_path, labels):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"labels": [{"name": n} for n in labels]}}))
    script = tmp_path / "gate.sh"
    script.write_text(SCRIPT, newline="\n")
    out = subprocess.run([BASH, str(script)], capture_output=True, text=True, check=False,
                         env={**os.environ, "GITHUB_EVENT_PATH": str(event)})
    return out.returncode, out.stdout


needs_tools = pytest.mark.skipif(not (BASH and JQ), reason="bash and jq required")


@needs_tools
def test_gate_passes_with_both_verdicts(tmp_path):
    assert run_gate(tmp_path, ["review:approved", "test:passed"])[0] == 0


@needs_tools
@pytest.mark.parametrize("labels", [
    [], ["review:approved"], ["test:passed"], ["status:ready-to-merge"],
    ["review:approved", "test:passed", "test:failed"],
    ["review:approved", "test:passed", "review:changes-requested"],
])
def test_gate_blocks_missing_or_contradicted_verdicts(tmp_path, labels):
    assert run_gate(tmp_path, labels)[0] == 1


def test_ci_runs_dispatcher_tests_with_repo_root_on_path():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "agents/dispatcher/tests/" in ci
    assert "python -m pytest" in ci
    assert "ruff check app/ agents/dispatcher/" in ci
