"""The transition matrix, row by row: every legal move and every refusal."""

import pytest

from order_lifecycle import (
    COURIER,
    CUSTOMER,
    SUPPORT,
    WAREHOUSE,
    Condition,
    ConditionNotMet,
    IllegalTransition,
    Machine,
    RoleNotPermitted,
    State,
    Transition,
    TransitionTable,
    Trigger,
    flag,
)

NEW = State("new")
PAID = State("paid")
SHIPPED = State("shipped")
DELIVERED = State("delivered", terminal=True)
CANCELLED = State("cancelled", terminal=True)

PAY = Trigger("pay")
SHIP = Trigger("ship")
DELIVER = Trigger("deliver")
CANCEL = Trigger("cancel")

STATES = (NEW, PAID, SHIPPED, DELIVERED, CANCELLED)
TRIGGERS = (PAY, SHIP, DELIVER, CANCEL)
ROLES = (CUSTOMER, WAREHOUSE, COURIER, SUPPORT)


def _units(order):
    return (order or {}).get("units_available", 0)


PAYMENT_CONFIRMED = flag(
    "payment_confirmed",
    name="payment confirmed",
    requires="the payment must be confirmed",
)
IN_STOCK = Condition(
    "in stock",
    lambda order: _units(order) > 0,
    "every line item must be in stock",
)

READY = {"payment_confirmed": True, "units_available": 3}
UNPAID = {"payment_confirmed": False, "units_available": 3}
EMPTY_SHELF = {"payment_confirmed": True, "units_available": 0}
NOTHING_READY = {"payment_confirmed": False, "units_available": 0}

TABLE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER),
        Transition(
            PAID,
            SHIPPED,
            SHIP,
            roles=WAREHOUSE,
            conditions=(PAYMENT_CONFIRMED, IN_STOCK),
        ),
        Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
        Transition(NEW, CANCELLED, CANCEL),
        Transition(PAID, CANCELLED, CANCEL, roles={CUSTOMER, SUPPORT}),
    )
)

LEGAL = {
    "the customer pays a new order": (NEW, PAY, CUSTOMER, None, PAID),
    "anyone cancels a new order": (NEW, CANCEL, None, None, CANCELLED),
    "the customer cancels a new order": (NEW, CANCEL, CUSTOMER, None, CANCELLED),
    "the courier cancels a new order": (NEW, CANCEL, COURIER, None, CANCELLED),
    "the warehouse ships a ready order": (PAID, SHIP, WAREHOUSE, READY, SHIPPED),
    "the customer cancels a paid order": (PAID, CANCEL, CUSTOMER, None, CANCELLED),
    "support cancels a paid order": (PAID, CANCEL, SUPPORT, None, CANCELLED),
    "the courier delivers a shipped order": (
        SHIPPED,
        DELIVER,
        COURIER,
        None,
        DELIVERED,
    ),
}


@pytest.mark.parametrize(
    "source, trigger, role, context, target", LEGAL.values(), ids=list(LEGAL)
)
def test_a_legal_move_is_accepted(source, trigger, role, context, target):
    machine = Machine(TABLE, source)

    assert machine.can(trigger, role=role, context=context)

    moved = machine.apply(trigger, role=role, context=context)

    assert moved.state == target
    assert machine.state == source
    assert moved.history.last.source == source
    assert moved.history.last.target == target
    assert moved.history.last.trigger == trigger


REFUSALS = {
    "a trigger that does not leave this state": (
        NEW,
        SHIP,
        WAREHOUSE,
        READY,
        IllegalTransition,
        "cannot apply trigger 'ship' in state 'new'",
    ),
    "a delivered order has nowhere left to go": (
        DELIVERED,
        CANCEL,
        SUPPORT,
        None,
        IllegalTransition,
        "'delivered' is a terminal state",
    ),
    "a cancelled order has nowhere left to go": (
        CANCELLED,
        PAY,
        CUSTOMER,
        None,
        IllegalTransition,
        "'cancelled' is a terminal state",
    ),
    "an actor with nothing to fire here": (
        SHIPPED,
        PAY,
        CUSTOMER,
        None,
        IllegalTransition,
        "nothing is allowed here",
    ),
    "the wrong actor ships": (
        PAID,
        SHIP,
        CUSTOMER,
        READY,
        RoleNotPermitted,
        "requires one of: warehouse",
    ),
    "no actor at all ships": (
        PAID,
        SHIP,
        None,
        READY,
        RoleNotPermitted,
        "no role was supplied",
    ),
    "support pays for the customer": (
        NEW,
        PAY,
        SUPPORT,
        None,
        RoleNotPermitted,
        "requires one of: customer",
    ),
    "the warehouse cancels instead of rejecting": (
        PAID,
        CANCEL,
        WAREHOUSE,
        None,
        RoleNotPermitted,
        "requires one of: customer, support",
    ),
    "the customer delivers to themselves": (
        SHIPPED,
        DELIVER,
        CUSTOMER,
        None,
        RoleNotPermitted,
        "requires one of: courier",
    ),
    "the right actor, an unpaid order": (
        PAID,
        SHIP,
        WAREHOUSE,
        UNPAID,
        ConditionNotMet,
        "the payment must be confirmed",
    ),
    "the right actor, an empty shelf": (
        PAID,
        SHIP,
        WAREHOUSE,
        EMPTY_SHELF,
        ConditionNotMet,
        "every line item must be in stock",
    ),
    "a conditional move without a context": (
        PAID,
        SHIP,
        WAREHOUSE,
        None,
        ConditionNotMet,
        "requires: the payment must be confirmed",
    ),
}


@pytest.mark.parametrize(
    "source, trigger, role, context, error, message",
    REFUSALS.values(),
    ids=list(REFUSALS),
)
def test_a_refused_move_raises_and_stays_put(
    source, trigger, role, context, error, message
):
    machine = Machine(TABLE, source)

    assert not machine.can(trigger, role=role, context=context)

    with pytest.raises(error) as refusal:
        machine.apply(trigger, role=role, context=context)

    assert message in str(refusal.value)
    assert machine.state == source
    assert not machine.history


UNDECLARED = tuple(
    (state, trigger)
    for state in STATES
    for trigger in TRIGGERS
    if TABLE.find(state, trigger) is None
)


@pytest.mark.parametrize("state, trigger", UNDECLARED, ids=lambda cell: cell.name)
def test_every_undeclared_cell_of_the_matrix_is_refused(state, trigger):
    machine = Machine(TABLE, state)

    for role in ROLES + (None,):
        assert not machine.can(trigger, role=role, context=READY)
        with pytest.raises(IllegalTransition):
            machine.apply(trigger, role=role, context=READY)


GUARDS = {
    "only the customer pays": (NEW, PAY, frozenset({CUSTOMER})),
    "only the warehouse ships": (PAID, SHIP, frozenset({WAREHOUSE})),
    "only the courier delivers": (SHIPPED, DELIVER, frozenset({COURIER})),
    "anyone cancels a new order": (NEW, CANCEL, frozenset(ROLES)),
    "customer or support cancel a paid one": (
        PAID,
        CANCEL,
        frozenset({CUSTOMER, SUPPORT}),
    ),
}


@pytest.mark.parametrize(
    "source, trigger, permitted", GUARDS.values(), ids=list(GUARDS)
)
def test_the_role_guard_answers_for_every_actor(source, trigger, permitted):
    transition = TABLE.find(source, trigger)

    for role in ROLES:
        assert transition.permits(role) is (role in permitted)
        assert transition.permits(role.name) is (role in permitted)

    assert transition.permits(None) is not transition.guarded


OFFERS = {
    "a new order, seen by the customer": (NEW, CUSTOMER, ("pay", "cancel")),
    "a new order, seen by support": (NEW, SUPPORT, ("cancel",)),
    "a paid order, seen by the warehouse": (PAID, WAREHOUSE, ("ship",)),
    "a paid order, seen by the customer": (PAID, CUSTOMER, ("cancel",)),
    "a paid order, seen by the courier": (PAID, COURIER, ()),
    "a shipped order, seen by the courier": (SHIPPED, COURIER, ("deliver",)),
    "a delivered order, seen by support": (DELIVERED, SUPPORT, ()),
    "a cancelled order, seen by the customer": (CANCELLED, CUSTOMER, ()),
}


@pytest.mark.parametrize("state, role, offered", OFFERS.values(), ids=list(OFFERS))
def test_the_offer_of_a_state_can_be_read_off_the_table(state, role, offered):
    machine = Machine(TABLE, state)

    assert tuple(t.trigger.name for t in machine.allowed(role=role)) == offered


def test_an_unready_order_narrows_the_offer_too():
    machine = Machine(TABLE, PAID)

    assert [t.trigger.name for t in machine.allowed(role=WAREHOUSE, context=READY)] == [
        "ship"
    ]
    assert machine.allowed(role=WAREHOUSE, context=UNPAID) == ()


def test_the_whole_legal_path_is_walked_and_recorded():
    machine = Machine(TABLE, NEW)
    machine = machine.apply(PAY, role=CUSTOMER)
    machine = machine.apply(SHIP, role=WAREHOUSE, context=READY)
    machine = machine.apply(DELIVER, role=COURIER)

    assert machine.state == DELIVERED
    assert machine.history.states == (NEW, PAID, SHIPPED, DELIVERED)
    assert [entry.actor for entry in machine.history] == [
        "customer",
        "warehouse",
        "courier",
    ]


def test_a_refusal_records_nothing():
    machine = Machine(TABLE, NEW).apply(PAY, role=CUSTOMER)

    with pytest.raises(ConditionNotMet):
        machine.apply(SHIP, role=WAREHOUSE, context=UNPAID)

    assert machine.state == PAID
    assert len(machine.history) == 1


def test_the_wrong_actor_is_refused_before_the_order_is_examined():
    with pytest.raises(RoleNotPermitted):
        Machine(TABLE, PAID).apply(SHIP, role=CUSTOMER, context=NOTHING_READY)


def test_an_unready_order_is_told_everything_it_lacks():
    with pytest.raises(ConditionNotMet) as refusal:
        Machine(TABLE, PAID).apply(SHIP, role=WAREHOUSE, context=NOTHING_READY)

    assert refusal.value.unmet == (PAYMENT_CONFIRMED, IN_STOCK)
    assert [result.detail for result in refusal.value.failures] == [
        "the payment must be confirmed",
        "every line item must be in stock",
    ]


def test_a_refusal_offers_what_would_have_been_accepted():
    with pytest.raises(IllegalTransition) as refusal:
        Machine(TABLE, PAID).apply(PAY, role=CUSTOMER)

    assert {t.trigger.name for t in refusal.value.allowed} == {"cancel"}
    assert "allowed here: cancel" in str(refusal.value)
