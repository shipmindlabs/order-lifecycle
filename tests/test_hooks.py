"""Atomicity: a hook that raises leaves neither a state change nor an entry."""

import pytest

from order_lifecycle import (
    CHANGED_MIND,
    CUSTOMER,
    WAREHOUSE,
    CancellationPath,
    CancellationPolicy,
    Hook,
    HookFailed,
    LifecycleError,
    Machine,
    State,
    Transition,
    TransitionTable,
    Trigger,
)

NEW = State("new")
PAID = State("paid")
SHIPPED = State("shipped")
CANCELLED = State("cancelled", terminal=True)

PAY = Trigger("pay")
SHIP = Trigger("ship")
CANCEL = Trigger("cancel")

RESERVE = "reserve stock"
PRINT_LABEL = "print label"
NOTIFY = "notify customer"
PUBLISH = "publish event"
STOP_PICKING = "stop picking"
REFUND = "refund"
CLOSE_TICKET = "close ticket"

ORDER = {"units_available": 3}


@pytest.fixture()
def log():
    return []


def _records(log, name):
    return Hook(name, lambda move: log.append(f"{move.phase} {name}"))


def _raises(log, name):
    def fail(move):
        log.append(f"{move.phase} {name}")
        raise RuntimeError(f"{name} is offline")

    return Hook(name, fail)


def _shipping(log, failing):
    before = [_records(log, RESERVE)]
    after = [_records(log, NOTIFY)]
    (before if failing == "before" else after).append(
        _raises(log, PRINT_LABEL if failing == "before" else PUBLISH)
    )
    return Transition(
        PAID, SHIPPED, SHIP, roles=WAREHOUSE, before=tuple(before), after=tuple(after)
    )


def _paid(table):
    return Machine(table, NEW).apply(PAY, role=CUSTOMER)


PHASES = {
    "a before hook raises": (
        "before",
        PRINT_LABEL,
        [RESERVE],
        [f"before {RESERVE}", f"before {PRINT_LABEL}"],
    ),
    "an after hook raises": (
        "after",
        PUBLISH,
        [NOTIFY],
        [f"before {RESERVE}", f"after {NOTIFY}", f"after {PUBLISH}"],
    ),
}


@pytest.mark.parametrize(
    "phase, failed, completed, fired", PHASES.values(), ids=list(PHASES)
)
def test_a_failing_hook_leaves_no_trace(log, phase, failed, completed, fired):
    row = _shipping(log, phase)
    table = TransitionTable((Transition(NEW, PAID, PAY, roles=CUSTOMER), row))
    machine = _paid(table)

    with pytest.raises(HookFailed) as failure:
        machine.apply(SHIP, role=WAREHOUSE, context=ORDER, reason="packed today")

    refusal = failure.value

    assert isinstance(refusal, LifecycleError)
    assert refusal.phase == phase
    assert refusal.hook.name == failed
    assert [hook.name for hook in refusal.completed] == completed
    assert isinstance(refusal.cause, RuntimeError)
    assert refusal.cause.args == (f"{failed} is offline",)
    assert refusal.__cause__ is refusal.cause
    assert refusal.transition is row
    assert refusal.context.phase == phase
    assert refusal.context.role == WAREHOUSE
    assert refusal.context.subject is ORDER
    assert (
        f"{phase} hook {failed!r} failed for trigger 'ship' in state 'paid'"
        in str(refusal)
    )
    assert f"RuntimeError: {failed} is offline" in str(refusal)
    assert "the order stays in 'paid'" in str(refusal)

    assert log == fired
    assert machine.state == PAID
    assert len(machine.history) == 1
    assert machine.history.last.trigger == PAY
    assert machine.history.for_trigger(SHIP) == ()
    assert machine.can(SHIP, role=WAREHOUSE, context=ORDER)


def test_nothing_of_the_after_phase_runs_once_a_before_hook_failed(log):
    row = _shipping(log, "before")
    table = TransitionTable((Transition(NEW, PAID, PAY, roles=CUSTOMER), row))

    with pytest.raises(HookFailed):
        _paid(table).apply(SHIP, role=WAREHOUSE, context=ORDER)

    assert [entry for entry in log if entry.startswith("after")] == []


def test_a_failing_follow_up_abandons_the_cancellation(log):
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID,
                CANCELLED,
                CANCEL,
                roles=CUSTOMER,
                reasons=CHANGED_MIND,
                before=_records(log, STOP_PICKING),
                follow_up=(_records(log, REFUND), _raises(log, CLOSE_TICKET)),
            ),
        )
    )
    table = policy.extend(
        TransitionTable((Transition(NEW, PAID, PAY, roles=CUSTOMER),))
    )
    machine = _paid(table)

    with pytest.raises(HookFailed) as failure:
        policy.cancel(machine, role=CUSTOMER, reason=CHANGED_MIND)

    assert failure.value.phase == "after"
    assert failure.value.hook.name == CLOSE_TICKET
    assert [hook.name for hook in failure.value.completed] == [REFUND]
    assert log == [
        f"before {STOP_PICKING}",
        f"after {REFUND}",
        f"after {CLOSE_TICKET}",
    ]
    assert machine.state == PAID
    assert len(machine.history) == 1
    assert machine.history.for_trigger(CANCEL) == ()


def test_a_cancellation_stopped_in_the_before_phase_refunds_nothing(log):
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID,
                CANCELLED,
                CANCEL,
                roles=CUSTOMER,
                reasons=CHANGED_MIND,
                before=_raises(log, STOP_PICKING),
                follow_up=_records(log, REFUND),
            ),
        )
    )
    table = policy.extend(
        TransitionTable((Transition(NEW, PAID, PAY, roles=CUSTOMER),))
    )
    machine = _paid(table)

    with pytest.raises(HookFailed) as failure:
        policy.cancel(machine, role=CUSTOMER, reason=CHANGED_MIND)

    assert failure.value.phase == "before"
    assert failure.value.hook.name == STOP_PICKING
    assert failure.value.completed == ()
    assert log == [f"before {STOP_PICKING}"]
    assert machine.state == PAID
    assert len(machine.history) == 1
    assert policy.reasons_for(PAID, role=CUSTOMER) == (CHANGED_MIND,)
