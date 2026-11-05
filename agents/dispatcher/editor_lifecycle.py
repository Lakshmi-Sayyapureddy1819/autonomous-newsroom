"""Deterministic editor duties from agents/PROTOCOL.md. No LLM, plain label logic.

The Hermes editor is only needed to *author* tickets from the brief. Everything
mechanical lives here and runs on every dispatcher tick:

* reroute  - review:changes-requested / test:failed -> attempt+1, back to reporter
* escalate - attempt would exceed MAX_ATTEMPTS -> status:blocked, agent:editor, comment
* promote  - open ticket with agent:editor and no status:* whose "Depends on"
             tickets are all closed becomes status:ready + agent:reporter, but only
             while no other ticket is in the reporter -> copydesk -> factcheck pipeline.

Queue convention (small addition to PROTOCOL): a ticket waiting on dependencies carries
`agent:editor` and *no* `status:*` label.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_ATTEMPTS = 3
ACTIVE = {"status:ready", "status:in-progress", "status:in-review", "status:in-test"}
VERDICT_PREFIXES = ("review:", "test:")


@dataclass
class Ticket:
    number: int
    title: str
    body: str
    labels: set[str]
    pr_labels: set[str] = field(default_factory=set)

    @property
    def all_labels(self) -> set[str]:
        return self.labels | self.pr_labels

    def with_prefix(self, prefix: str) -> list[str]:
        return sorted(label for label in self.labels if label.startswith(prefix))

    @property
    def attempt(self) -> int:
        nums = [int(label.split(":")[1]) for label in self.with_prefix("attempt:")]
        return max(nums, default=1)


def dependencies(body: str) -> list[int]:
    """Issue numbers on the 'Depends on' line(s) of a ticket body."""
    found: list[int] = []
    for line in body.splitlines():
        if re.search(r"depends\s+on", line, re.IGNORECASE):
            found += [int(n) for n in re.findall(r"#(\d+)", line)]
    return found


def verdict_labels(ticket: Ticket) -> list[str]:
    return sorted(label for label in ticket.all_labels if label.startswith(VERDICT_PREFIXES))


def plan_actions(open_tickets: list[Ticket], closed_numbers: set[int]) -> list[dict]:
    """Return label/comment actions. Each action is
    {"issue": n, "add": [...], "remove": [...], "comment": str, "pr_remove": [...]}.
    """
    actions: list[dict] = []
    pipeline_busy = False

    for t in sorted(open_tickets, key=lambda x: x.number):
        status = t.with_prefix("status:")
        failed = [v for v in verdict_labels(t) if v in ("review:changes-requested", "test:failed")]

        if failed and "status:blocked" not in status:
            nxt = t.attempt + 1
            stale = [label for label in verdict_labels(t)]
            if nxt > MAX_ATTEMPTS:
                actions.append({
                    "issue": t.number,
                    "add": ["status:blocked", "agent:editor"],
                    "remove": status + t.with_prefix("agent:") + t.with_prefix("attempt:"),
                    "pr_remove": stale,
                    "comment": (
                        f"### Escalation  editor → human\nTicket: #{t.number} · Attempt: "
                        f"{t.attempt}\nDid: {', '.join(failed)} on the last allowed attempt "
                        f"(max {MAX_ATTEMPTS}).\nKnown gaps: needs a human decision; status set "
                        "to blocked. The dispatcher will not wake any agent for this ticket."
                    ),
                })
            else:
                actions.append({
                    "issue": t.number,
                    "add": ["status:ready", "agent:reporter", f"attempt:{nxt}"],
                    "remove": status + t.with_prefix("agent:") + t.with_prefix("attempt:"),
                    "pr_remove": stale,
                    "comment": (
                        f"### Handoff  editor → reporter\nTicket: #{t.number} · Attempt: {nxt}\n"
                        f"Did: re-routed after {', '.join(failed)}; same branch and PR.\n"
                        "How to verify: read the review/test comment on the PR and fix every "
                        "failed criterion.\nKnown gaps: n/a (deterministic routing, no tokens "
                        "used)."
                    ),
                })
            pipeline_busy = True
            continue

        if set(status) & ACTIVE:
            pipeline_busy = True

    if pipeline_busy:
        return actions

    for t in sorted(open_tickets, key=lambda x: x.number):
        if t.with_prefix("status:") or t.with_prefix("agent:") != ["agent:editor"]:
            continue
        deps = dependencies(t.body)
        if any(d not in closed_numbers for d in deps):
            continue
        actions.append({
            "issue": t.number,
            "add": ["status:ready", "agent:reporter", "attempt:1"],
            "remove": ["agent:editor"] + t.with_prefix("attempt:"),
            "pr_remove": [],
            "comment": (
                f"### Handoff  editor → reporter\nTicket: #{t.number} · Attempt: 1\n"
                f"Did: dependencies {deps or 'none'} are merged; ticket is next ready.\n"
                "How to verify: acceptance criteria in this Issue.\nKnown gaps: n/a."
            ),
        })
        break  # one in-progress ticket for the reporter
    return actions
