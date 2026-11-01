
from agents.dispatcher.editor_lifecycle import Ticket, plan_actions


def test_reroute_on_changes_requested():
    # Simulate a ticket that was reviewed and changes requested
    ticket = Ticket(
        number=1,
        title="Test Ticket",
        body="Goal: Fix something.",
        labels={"status:in-review", "agent:copydesk", "review:changes-requested", "attempt:1"},
        pr_labels={"review:changes-requested"}
    )
    closed_numbers = set()
    actions = plan_actions([ticket], closed_numbers)

    assert len(actions) == 1
    action = actions[0]
    assert action["issue"] == 1
    assert "status:ready" in action["add"]
    assert "agent:reporter" in action["add"]
    assert "attempt:2" in action["add"]
    assert "review:changes-requested" in action["remove"]
    assert "review:changes-requested" in action["pr_remove"]
    assert "rerouted after review:changes-requested" in action["comment"]

def test_escalate_after_max_attempts():
    # Simulate a ticket that has failed max attempts
    ticket = Ticket(
        number=2,
        title="Another Test",
        body="Goal: Another fix.",
        labels={"status:in-review", "agent:copydesk", "review:changes-requested", "attempt:3"},
        pr_labels={"review:changes-requested"}
    )
    closed_numbers = set()
    actions = plan_actions([ticket], closed_numbers)

    assert len(actions) == 1
    action = actions[0]
    assert action["issue"] == 2
    assert "status:blocked" in action["add"]
    assert "agent:editor" in action["add"]
    assert "Escalation" in action["comment"]
    assert "max 3" in action["comment"]

def test_promote_ticket_with_dependencies():
    # Simulate a dependent ticket and a closed dependency
    ticket_dep = Ticket(
        number=3,
        title="Dependency",
        body="Goal: Dependency.",
        labels=set(),
        pr_labels=set()
    )
    ticket_main = Ticket(
        number=4,
        title="Main Ticket",
        body="Depends on: #3\nGoal: Main task.",
        labels={"agent:editor"},
        pr_labels=set()
    )
    closed_numbers = {3} # Dependency #3 is closed
    actions = plan_actions([ticket_dep, ticket_main], closed_numbers)

    # We expect promotion of ticket_main
    assert len(actions) == 1
    action = actions[0]
    assert action["issue"] == 4
    assert "status:ready" in action["add"]
    assert "agent:reporter" in action["add"]
    assert "attempt:1" in action["add"]
    assert "dependencies [3] are merged" in action["comment"]

def test_no_promotion_if_pipeline_busy():
    # Simulate a ticket that should be promoted, but pipeline is busy
    ticket_active = Ticket(
        number=5,
        title="Active Ticket",
        body="Goal: Active task.",
        labels={"status:in-progress", "agent:reporter"},
        pr_labels=set()
    )
    ticket_to_promote = Ticket(
        number=6,
        title="Promote Me",
        body="Goal: Promote me.",
        labels={"agent:editor"},
        pr_labels=set()
    )
    closed_numbers = set()
    actions = plan_actions([ticket_active, ticket_to_promote], closed_numbers)

    # No actions expected for ticket_to_promote because pipeline_busy is True
    assert len(actions) == 0

def test_no_promotion_if_dependencies_not_met():
    # Simulate a ticket waiting on an open dependency
    ticket_dep = Ticket(
        number=7,
        title="Dependency (Open)",
        body="Goal: Dependency.",
        labels={"status:in-progress"},
        pr_labels=set()
    )
    ticket_main = Ticket(
        number=8,
        title="Main Ticket",
        body="Depends on: #7\nGoal: Main task.",
        labels={"agent:editor"},
        pr_labels=set()
    )
    closed_numbers = set() # Dependency #7 is not closed
    actions = plan_actions([ticket_dep, ticket_main], closed_numbers)

    # No actions expected for ticket_main
    assert len(actions) == 0
