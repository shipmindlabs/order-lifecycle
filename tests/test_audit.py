"""Reading a declared table: what it reaches, and where an order would stick."""

from order_lifecycle import (
    COURIER,
    CUSTOMER,
    SUPPORT,
    WAREHOUSE,
    Audit,
    State,
    Transition,
    TransitionTable,
    Trigger,
)

NEW = State("new")
PAID = State("paid")
SHIPPED = State("shipped")
PACKED = State("packed")
LOST = State("lost")
DELIVERED = State("delivered", terminal=True)
CANCELLED = State("cancelled", terminal=True)

PAY = Trigger("pay")
SHIP = Trigger("ship")
DELIVER = Trigger("deliver")
CANCEL = Trigger("cancel")
WRITE_OFF = Trigger("write off")

TABLE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER),
        Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE),
        Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
        Transition(NEW, CANCELLED, CANCEL),
        Transition(PAID, CANCELLED, CANCEL, roles={CUSTOMER, SUPPORT}),
    )
)


def test_a_sound_table_reaches_every_state_it_declares():
    audit = TABLE.audit(NEW)

    assert isinstance(audit, Audit)
    assert audit.ok
    assert audit
    assert audit.reachable == (NEW, PAID, SHIPPED, DELIVERED, CANCELLED)
    assert audit.unreachable == ()
    assert audit.dead_ends == ()
    assert audit.problems == ()
    assert str(audit) == "5 states reachable from new, none of them a dead end"


def test_a_terminal_state_is_not_a_dead_end():
    assert TABLE.terminals == (DELIVERED, CANCELLED)
    assert TABLE.dead_ends() == ()


def test_a_state_nothing_leads_to_is_reported():
    table = TransitionTable(
        (
            Transition(NEW, PAID, PAY, roles=CUSTOMER),
            Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE),
            Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
            Transition(LOST, CANCELLED, WRITE_OFF, roles=SUPPORT),
        )
    )

    audit = table.audit(NEW)

    assert not audit.ok
    assert not audit
    assert audit.reachable == (NEW, PAID, SHIPPED, DELIVERED)
    assert audit.unreachable == (LOST, CANCELLED)
    assert audit.dead_ends == ()
    assert audit.problems == (
        "lost is never reached from new",
        "cancelled is never reached from new",
    )


def test_a_state_an_order_cannot_leave_is_reported():
    table = TransitionTable(
        (
            Transition(NEW, PAID, PAY, roles=CUSTOMER),
            Transition(PAID, PACKED, SHIP, roles=WAREHOUSE),
        )
    )

    audit = table.audit(NEW)

    assert not audit.ok
    assert audit.unreachable == ()
    assert audit.dead_ends == (PACKED,)
    assert str(audit) == "packed is not terminal and nothing leaves it"


def test_reachability_ignores_the_guards():
    assert TABLE.reachable(PAID) == (PAID, SHIPPED, DELIVERED, CANCELLED)
    assert TABLE.reachable(DELIVERED) == (DELIVERED,)


def test_a_start_the_table_does_not_declare_reaches_nothing():
    audit = TABLE.audit(LOST)

    assert audit.reachable == (LOST,)
    assert audit.unreachable == TABLE.states


def test_the_rows_around_a_state_can_be_read_off_the_table():
    assert [row.trigger for row in TABLE.outgoing(NEW)] == [PAY, CANCEL]
    assert [row.source for row in TABLE.incoming(CANCELLED)] == [NEW, PAID]
    assert TABLE.outgoing(DELIVERED) == ()
    assert TABLE.incoming(NEW) == ()
