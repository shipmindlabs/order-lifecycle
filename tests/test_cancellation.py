"""Cancellation from several actors: different states, reasons and follow-ups."""

import pytest

from order_lifecycle import (
    CHANGED_MIND,
    COURIER,
    CUSTOMER,
    DAMAGED,
    DUPLICATE,
    OUT_OF_STOCK,
    SUPPORT,
    UNDELIVERABLE,
    WAREHOUSE,
    CancellationPath,
    CancellationPolicy,
    CannotCancel,
    Machine,
    ReasonNotAccepted,
    RoleNotPermitted,
    State,
    Transition,
    TransitionTable,
    Trigger,
)

NEW = State("new")
PAID = State("paid")
SHIPPED = State("shipped")
RETURNED = State("returned")
DELIVERED = State("delivered", terminal=True)
CANCELLED = State("cancelled", terminal=True)

PAY = Trigger("pay")
SHIP = Trigger("ship")
DELIVER = Trigger("deliver")
CANCEL = Trigger("cancel")
REJECT = Trigger("reject")
FAIL = Trigger("fail")
WRITE_OFF = Trigger("write off")

CORE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER),
        Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE),
        Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
    )
)


@pytest.fixture()
def done():
    return []


@pytest.fixture()
def policy(done):
    def refund(move):
        done.append("refund")

    def restock(move):
        done.append("restock")

    def collect_parcel(move):
        done.append("collect parcel")

    return CancellationPolicy(
        (
            CancellationPath(
                NEW,
                CANCELLED,
                CANCEL,
                roles={CUSTOMER, SUPPORT},
                reasons=(CHANGED_MIND, DUPLICATE),
            ),
            CancellationPath(
                PAID,
                CANCELLED,
                CANCEL,
                roles={CUSTOMER, SUPPORT},
                reasons=(CHANGED_MIND, DUPLICATE),
                follow_up=refund,
            ),
            CancellationPath(
                PAID,
                CANCELLED,
                REJECT,
                roles=WAREHOUSE,
                reasons=(OUT_OF_STOCK, DAMAGED),
                follow_up=(refund, restock),
            ),
            CancellationPath(
                SHIPPED,
                RETURNED,
                FAIL,
                roles=COURIER,
                reasons=(UNDELIVERABLE, DAMAGED),
                follow_up=collect_parcel,
            ),
            CancellationPath(RETURNED, CANCELLED, WRITE_OFF, roles=WAREHOUSE),
        )
    )


@pytest.fixture()
def table(policy):
    return policy.extend(CORE)


def test_paths_join_the_table_as_ordinary_rows(policy, table):
    assert len(table) == len(CORE) + len(policy)
    assert table.find(PAID, REJECT).target == CANCELLED


def test_customer_cancels_a_paid_order(policy, table, done):
    machine = policy.cancel(Machine(table, PAID), role=CUSTOMER, reason=CHANGED_MIND)

    assert machine.state == CANCELLED
    assert done == ["refund"]
    assert machine.history.last.role == CUSTOMER
    assert machine.history.last.trigger == CANCEL
    assert machine.history.last.reason == CHANGED_MIND.sentence


def test_warehouse_rejects_the_same_state_on_its_own_trigger(policy, table, done):
    machine = policy.cancel(Machine(table, PAID), role=WAREHOUSE, reason="out_of_stock")

    assert machine.state == CANCELLED
    assert machine.history.last.trigger == REJECT
    assert done == ["refund", "restock"]


def test_courier_failure_leads_somewhere_else(policy, table, done):
    machine = policy.cancel(Machine(table, SHIPPED), role=COURIER, reason=UNDELIVERABLE)

    assert machine.state == RETURNED
    assert done == ["collect parcel"]


def test_an_actor_without_a_path_here_is_refused(policy, table):
    with pytest.raises(CannotCancel) as error:
        policy.cancel(Machine(table, PAID), role=COURIER, reason=UNDELIVERABLE)

    assert error.value.actors == frozenset({CUSTOMER, SUPPORT, WAREHOUSE})
    assert "courier" in str(error.value)


def test_a_reason_from_another_path_is_refused(policy, table):
    with pytest.raises(ReasonNotAccepted) as error:
        policy.cancel(Machine(table, PAID), role=CUSTOMER, reason=OUT_OF_STOCK)

    assert error.value.accepted == (CHANGED_MIND, DUPLICATE)


def test_a_path_with_reasons_demands_one(policy, table):
    with pytest.raises(ReasonNotAccepted) as error:
        policy.cancel(Machine(table, PAID), role=CUSTOMER)

    assert "no reason was given" in str(error.value)


def test_a_path_without_reasons_records_free_text(policy, table):
    machine = policy.cancel(Machine(table, RETURNED), role=WAREHOUSE, reason="unsellable")

    assert machine.state == CANCELLED
    assert machine.history.last.reason == "unsellable"


def test_the_offer_can_be_read_off_the_policy(policy):
    assert policy.reasons_for(PAID, role=CUSTOMER) == (CHANGED_MIND, DUPLICATE)
    assert policy.reasons_for(PAID, role=WAREHOUSE) == (OUT_OF_STOCK, DAMAGED)
    assert [str(path) for path in policy.available(SHIPPED, role=COURIER)] == [
        "shipped --fail--> returned [courier] (undeliverable, damaged) "
        "-> collect parcel"
    ]


def test_the_role_guard_still_applies_to_the_move(table):
    with pytest.raises(RoleNotPermitted):
        Machine(table, PAID).apply(REJECT, role=CUSTOMER)


def test_two_paths_may_not_share_a_state_and_a_trigger():
    with pytest.raises(ValueError):
        CancellationPolicy(
            (
                CancellationPath(PAID, CANCELLED, CANCEL, roles=CUSTOMER),
                CancellationPath(PAID, CANCELLED, CANCEL, roles=WAREHOUSE),
            )
        )


def test_nothing_is_cancelled_from_a_terminal_state():
    with pytest.raises(ValueError):
        CancellationPath(DELIVERED, CANCELLED, CANCEL)
