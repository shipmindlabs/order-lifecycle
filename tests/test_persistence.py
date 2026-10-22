"""Rehydration: a stored record becomes a machine without replaying it."""

import json

import pytest

from order_lifecycle import (
    COURIER,
    CUSTOMER,
    SUPPORT,
    WAREHOUSE,
    Entry,
    History,
    Machine,
    State,
    Transition,
    TransitionTable,
    Trigger,
    UnknownName,
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

PAYMENT_CONFIRMED = flag(
    "payment_confirmed",
    name="payment confirmed",
    requires="the payment must be confirmed",
)

READY = {"payment_confirmed": True}


@pytest.fixture()
def fired():
    return []


@pytest.fixture()
def table(fired):
    def reserve_stock(move):
        fired.append(f"before {move.trigger.name}")

    def notify_customer(move):
        fired.append(f"after {move.trigger.name}")

    return TransitionTable(
        (
            Transition(NEW, PAID, PAY, roles=CUSTOMER, after=notify_customer),
            Transition(
                PAID,
                SHIPPED,
                SHIP,
                roles=WAREHOUSE,
                conditions=PAYMENT_CONFIRMED,
                before=reserve_stock,
                after=notify_customer,
            ),
            Transition(
                SHIPPED, DELIVERED, DELIVER, roles=COURIER, after=notify_customer
            ),
            Transition(NEW, CANCELLED, CANCEL),
            Transition(PAID, CANCELLED, CANCEL, roles={CUSTOMER, SUPPORT}),
        )
    )


@pytest.fixture()
def shipped(table, fired):
    machine = Machine(table, NEW)
    machine = machine.apply(PAY, role=CUSTOMER)
    machine = machine.apply(SHIP, role=WAREHOUSE, context=READY, reason="packed today")
    fired.clear()
    return machine


def test_a_machine_survives_a_round_trip(table, shipped, fired):
    back = Machine.from_record(table, shipped.as_record())

    assert back.state == SHIPPED
    assert back.history == shipped.history
    assert back == shipped
    assert fired == []


def test_the_record_is_plain_data(shipped):
    record = shipped.as_record()

    assert json.loads(json.dumps(record)) == record
    assert record["state"] == "shipped"
    assert [row["trigger"] for row in record["history"]] == ["pay", "ship"]
    assert record["history"][1] == {
        "source": "paid",
        "target": "shipped",
        "trigger": "ship",
        "role": "warehouse",
        "reason": "packed today",
        "at": shipped.history.last.at.isoformat(),
    }


def test_a_rehydrated_machine_keeps_moving(table, shipped, fired):
    delivered = Machine.from_record(table, shipped.as_record()).apply(
        DELIVER, role=COURIER
    )

    assert delivered.state == DELIVERED
    assert fired == ["after deliver"]
    assert len(delivered.history) == 3
    assert delivered.history.states == (NEW, PAID, SHIPPED, DELIVERED)


def test_a_record_without_a_history_rehydrates_a_machine_that_has_not_moved(table):
    machine = Machine.from_record(table, {"state": "new"})

    assert machine.state == NEW
    assert not machine.history


def test_an_unknown_state_names_the_field(table):
    with pytest.raises(UnknownName) as refusal:
        Machine.from_record(table, {"state": "packed", "history": []})

    assert refusal.value.kind == "state"
    assert refusal.value.name == "packed"
    assert refusal.value.field == "state"
    assert "unknown state 'packed' at 'state'" in str(refusal.value)
    assert "new, paid, shipped" in str(refusal.value)


def test_an_unknown_state_in_the_history_names_the_row(table, shipped):
    record = shipped.as_record()
    record["history"][1]["target"] = "packed"

    with pytest.raises(UnknownName) as refusal:
        Machine.from_record(table, record)

    assert refusal.value.field == "history[1].target"


def test_an_unknown_trigger_in_the_history_names_the_row(table, shipped):
    record = shipped.as_record()
    record["history"][0]["trigger"] = "prepay"

    with pytest.raises(UnknownName) as refusal:
        Machine.from_record(table, record)

    assert refusal.value.kind == "trigger"
    assert refusal.value.field == "history[0].trigger"


def test_the_table_resolves_the_names_it_declares(table):
    assert table.state("delivered") == DELIVERED
    assert table.trigger("cancel") == CANCEL
    assert [state.name for state in table.states] == [
        "new",
        "paid",
        "shipped",
        "delivered",
        "cancelled",
    ]
    assert [trigger.name for trigger in table.triggers] == [
        "pay",
        "ship",
        "deliver",
        "cancel",
    ]

    with pytest.raises(UnknownName):
        table.trigger("reject")


def test_a_history_round_trips_without_a_machine(table, shipped):
    rows = shipped.history.as_dicts()

    assert History.from_dicts(table, rows) == shipped.history


def test_an_open_move_stores_no_role(table):
    entry = Entry(NEW, CANCELLED, CANCEL)

    row = entry.as_dict()

    assert row["role"] is None
    assert Entry.from_dict(table, row) == entry
    assert Entry.from_dict(table, row).actor == "anyone"


def test_two_states_may_not_share_a_name():
    with pytest.raises(ValueError):
        TransitionTable(
            (
                Transition(NEW, PAID, PAY),
                Transition(SHIPPED, State("paid", terminal=True), SHIP),
            )
        )


def test_two_triggers_may_not_share_a_name():
    with pytest.raises(ValueError):
        TransitionTable(
            (
                Transition(NEW, PAID, PAY),
                Transition(PAID, SHIPPED, Trigger("pay", "pay once more")),
            )
        )
