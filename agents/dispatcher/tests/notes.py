"""Builders for well-formed hand-off comments (what a correct agent posts), shared by tests."""

SHA_A, SHA_B = "a" * 40, "b" * 40


def reporter_note(n=1, pr=7, attempt=1):
    return (f"### Handoff  reporter → copydesk\nTicket: #{n} · PR: #{pr} · Attempt: {attempt}\n"
            "Did: implemented.\nHow to verify: pytest.\nKnown gaps: none.")


def review_note(n=1, pr=7, head=SHA_A, criteria=0, fails=0, attempt=1):
    """`criteria` PASS/FAIL lines in total, `fails` of them FAIL."""
    lines = [f"- [{'x' if i >= fails else ' '}] criterion {i} — "
             f"{'PASS' if i >= fails else 'FAIL'} (app/x.py:{i})" for i in range(criteria)]
    return (f"### Handoff  copydesk → {'editor' if fails else 'factcheck'}\n"
            f"Ticket: #{n} · PR: #{pr} · Attempt: {attempt}\nHead: {head}\n"
            "#### Acceptance criteria\n" + "\n".join(lines) +
            "\n#### Out of scope\n- no UI changes — PASS\n")


def factcheck_note(n=1, pr=7, head=SHA_A, attempt=1):
    return (f"### Handoff  factcheck → editor\nTicket: #{n} · PR: #{pr} · Attempt: {attempt}\n"
            f"Tested head {head}\n$ ruff check app/ → All checks passed\n"
            "$ pytest → 12 passed\n")
