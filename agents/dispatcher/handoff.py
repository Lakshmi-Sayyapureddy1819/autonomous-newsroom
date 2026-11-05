"""Task-specific hand-off validation (pure functions, no GitHub or model access).

A hand-off comment only counts when it proves it belongs to THIS task. Incident (Issue #48 /
PR #49): Copydesk posted a stale review of Issue #41 / PR #42 on Issue #48 / PR #49 and the
dispatcher accepted it because "a new comment appeared". The rules here make that impossible:

* every accepted comment carries the protocol header `Ticket: #<issue> · PR: #<pr>`;
* a comment whose header names a DIFFERENT ticket or PR poisons the whole hand-off;
* reviews cite the current PR head SHA, evaluate every acceptance criterion, check the
  out-of-scope section and agree with the verdict label they came with;
* test reports cite the exact head SHA and show ruff + pytest evidence.
"""

from __future__ import annotations

import re

TICKET_REF = re.compile(r"Ticket:\s*#(\d+)")
PR_REF = re.compile(r"\bPR:\s*#(\d+)")
SHA_MIN = 7  # a short SHA is fine, but at least this many hex chars
VERDICT_LINE = re.compile(r"\b(PASS|FAIL)\b")
CRITERION = re.compile(r"^\s*[-*]\s*\[[ xX]\]\s+\S")


def criteria(issue_body: str) -> list[str]:
    """The checklist items of the Issue's `Acceptance criteria` section."""
    items, inside = [], False
    for line in (issue_body or "").splitlines():
        if re.match(r"^\s*#{1,6}\s*acceptance criteria", line, re.IGNORECASE):
            inside = True
        elif inside and re.match(r"^\s*#{1,6}\s", line):
            break
        elif inside and CRITERION.match(line):
            items.append(line.strip())
    return items


def foreign_refs(text: str, issue: int, pr: int | None) -> list[str]:
    """`Ticket:`/`PR:` header references in `text` that are not this task."""
    bad = [f"Ticket #{n}" for n in TICKET_REF.findall(text) if int(n) != issue]
    if pr is not None:
        bad += [f"PR #{n}" for n in PR_REF.findall(text) if int(n) != pr]
    return bad


def names_task(text: str, issue: int, pr: int | None) -> bool:
    """True if the header names this Issue and (when there is one) this PR, and nothing else."""
    if foreign_refs(text, issue, pr):
        return False
    if not any(int(n) == issue for n in TICKET_REF.findall(text)):
        return False
    return pr is None or any(int(n) == pr for n in PR_REF.findall(text))


def cites_head(text: str, head: str | None) -> bool:
    if not head:
        return True
    return head[:SHA_MIN].lower() in text.lower()


def latest_handoff(texts: list[str], issue: int, pr: int | None, senders: tuple[str, ...],
                   limit: int = 6000) -> str:
    """The most recent hand-off written by one of `senders` for THIS task ('' if none).
    Comments that belong to another task are ignored, so a stale review can never be shown to
    a Reporter or Copydesk as if it were current."""
    pattern = re.compile(r"Handoff\s+(" + "|".join(senders) + r")\b", re.IGNORECASE)
    for text in reversed(texts):
        if pattern.search(text) and names_task(text, issue, pr):
            return text.strip()[:limit]
    return ""


def validate(agent: str, issue: int, pr: int | None, head: str | None, new_texts: list[str],
             issue_body: str, verdict: str = "") -> str:
    """'' if `new_texts` (comments/reviews added during the run) are a valid hand-off from
    `agent` for this task, else a one-line reason. `verdict` is 'approved'/'changes' for
    Copydesk and 'passed'/'failed' for Factcheck, taken from the PR label."""
    if agent not in ("reporter", "copydesk", "factcheck"):
        return ""
    foreign = sorted({ref for text in new_texts for ref in foreign_refs(text, issue, pr)})
    if foreign:
        return (f"hand-off refers to another task ({', '.join(foreign)}); this run is "
                f"Issue #{issue}" + (f" / PR #{pr}" if pr else ""))
    mine = [t for t in new_texts if names_task(t, issue, pr)]
    if not mine:
        return (f"no new comment names `Ticket: #{issue}`" + (f" and `PR: #{pr}`" if pr else "")
                + " (a generic comment is not a hand-off)")
    if agent == "reporter":
        return ""
    if not any(cites_head(t, head) for t in mine):
        return f"{agent} comment does not cite the current PR head {(head or '')[:SHA_MIN]}"
    # The same review is normally posted on the PR and on the Issue: judge ONE comment (the one
    # with the most verdict lines) so a duplicate can never make up for a missing criterion.
    best = max(mine, key=lambda t: len(VERDICT_LINE.findall(t)))
    if agent == "copydesk":
        return _review_problem(best, issue_body, verdict)
    return _test_problem("\n".join(mine))


OUT_OF_SCOPE_HEADING = re.compile(r"^\s*(#{1,6}|\*\*)\s*out[ -]of[ -]scope", re.IGNORECASE | re.MULTILINE)


def restrictions(issue_body: str) -> list[str]:
    """The bullet items of the Issue's `Out of scope` section."""
    items, inside = [], False
    for line in (issue_body or "").splitlines():
        if re.match(r"^\s*#{1,6}\s*out[ -]of[ -]scope", line, re.IGNORECASE):
            inside = True
        elif inside and re.match(r"^\s*#{1,6}\s", line):
            break
        elif inside and re.match(r"^\s*[-*]\s+\S", line):
            items.append(line.strip())
    return items


def _review_problem(text: str, issue_body: str, verdict: str) -> str:
    heading = OUT_OF_SCOPE_HEADING.search(text)
    if not heading:
        return "review has no `Out of scope` section checking the Issue's restrictions"
    criteria_part, scope_part = text[:heading.start()], text[heading.start():]
    wanted, found = len(criteria(issue_body)), len(VERDICT_LINE.findall(criteria_part))
    if found < wanted:
        return (f"review evaluates {found} PASS/FAIL lines but the Issue has {wanted} "
                "acceptance criteria")
    wanted_scope = len(restrictions(issue_body))
    if len(VERDICT_LINE.findall(scope_part)) < wanted_scope:
        return (f"review checks {len(VERDICT_LINE.findall(scope_part))} of the {wanted_scope} "
                "out-of-scope restrictions")
    fails = len(re.findall(r"\bFAIL\b", text))
    if verdict == "approved" and fails:
        return f"review:approved contradicts {fails} FAIL line(s) in the review"
    if verdict == "changes" and not fails:
        return "review:changes-requested but the review lists no FAIL line"
    return ""


def _test_problem(text: str) -> str:
    low = text.lower()
    missing = [w for w in ("ruff", "pytest") if w not in low]
    if missing:
        return f"test report shows no {' / '.join(missing)} evidence"
    return ""
