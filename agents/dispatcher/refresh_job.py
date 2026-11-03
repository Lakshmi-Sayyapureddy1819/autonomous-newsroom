#!/usr/bin/env python3
"""Dispatcher-managed product refresh job (no LLM). See agents/PROTOCOL.md.

Runs the product refresh (collector, then summarizer) on behalf of the dispatcher, with the
same safety rules as agent wakes: one run at a time (lock file), a timeout, sanitized logs,
persisted state, and escalation to the human after MAX_FAILURES consecutive failed refreshes
(one Issue, status:blocked + agent:editor; reset by the next successful refresh).

  python agents/dispatcher/dispatch.py --refresh      # one refresh, intended for the timer

Environment: NEWSROOM_DISPATCH_STATE_DIR, NEWSROOM_REPO_DIR, GITHUB_REPOSITORY,
NEWSROOM_REFRESH_TIMEOUT (s per step, default 600), NEWSROOM_APP_PYTHON (default: this python).
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dispatch

STEPS = (("collector", "newsroom.collector"), ("summarizer", "newsroom.summarizer"))
MAX_FAILURES = 3


def run_step(argv: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        out = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                             check=False)
        return out.returncode, (out.stdout or "") + (out.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as exc:
        return 127, f"could not start {argv[0]}: {exc}"


class RefreshJob:
    def __init__(self, cfg: dispatch.Config, gh, runner=None, clock=time.time, log=print):
        self.cfg, self.gh, self.now, self.log = cfg, gh, clock, log
        self.state = dispatch.State(cfg.state_dir)
        self.runner = runner or run_step
        self.timeout = int(cfg.env.get("NEWSROOM_REFRESH_TIMEOUT", "600"))
        self.python = cfg.env.get("NEWSROOM_APP_PYTHON", sys.executable)

    def run(self) -> int:
        """0 = refreshed, 1 = a step failed, 2 = another refresh is already running."""
        lock = dispatch.AgentLock(self.state.dir, "refresh", self.timeout * len(STEPS) + 60)
        if not lock.acquire():
            self.log("refresh is already running; not starting another")
            return 2
        try:
            st = self.state.load("refresh")
            failed = ""
            for name, module in STEPS:
                code, output = self.runner([self.python, "-m", module], self.cfg.root / "app",
                                           self.timeout)
                self.log(f"refresh {name}: exit {code}")
                if code != 0:
                    failed = f"{name} exited {code}: {dispatch.sanitize(output)}"
                    break  # do not summarize after a failed collection
            if not failed:
                self.state.save("refresh", {"failures": 0, "last_ok": self.now()})
                return 0
            st["failures"] = st.get("failures", 0) + 1
            st["last_error"], st["last_attempt"] = failed, self.now()
            self.log(f"refresh failure {st['failures']}/{MAX_FAILURES}: {failed[:120]}")
            if st["failures"] >= MAX_FAILURES and not st.get("escalated"):
                self.gh.create_issue(
                    "Escalation: product refresh keeps failing",
                    f"### Escalation  dispatcher → human\nThe product refresh failed "
                    f"{st['failures']} consecutive times.\nLast error: `{failed}`\n"
                    "The dispatcher raised this once and will not repeat it until a refresh "
                    "succeeds. Fix the cause (providers, feed URLs, VM).",
                    ["status:blocked", "agent:editor"])
                st["escalated"] = True
            self.state.save("refresh", st)
            return 1
        finally:
            lock.release()


def main() -> int:
    cfg = dispatch.Config()
    return RefreshJob(cfg, dispatch.GitHub(cfg.repo)).run()


if __name__ == "__main__":
    sys.exit(main())
