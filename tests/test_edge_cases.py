"""Edge cases of the latest rows: hooks, cancellation paths and stored records."""

import json
from datetime import datetime, timezone
from functools import partial

import pytest

from order_lifecycle import (
    CHANGED_MIND,
    COURIER,
    CUSTOMER,
    DAMAGED,
    DUPLICATE,
    EMPTY_HISTORY,
    SUPPORT,
    UNDELIVERABLE,
    WAREHOUSE,
    CancellationPath,
    CancellationPolicy,
    CancellationReason,
    CannotCancel,
    Entry,
    History,
    Hook,
    Machine,
    ReasonNotAccepted,
    State,
    Transition,
    TransitionTable,
    Trigger,
    UnknownName,
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
FAIL = Trigger("fail")
WRITE_OFF = Trigger("write off")

CORE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER),
        Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE),
        Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
    )
)

MOMENT = datetime(2026, 5, 4, 9, 12, 31, tzinfo=timezone.utc)
LATER = datetime(2026, 5, 4, 9, 31, 8, tzinfo=timezone.utc)


def test_a_hook_needs_a_name_and_something_to_call():
    with pytest.raises(ValueError):
        Hook("   ", lambda move: None)

    with pytest.raises(TypeError):
        Hook("notify customer", "mailer.send")

    assert Hook("  notify customer  ", lambda move: None).name == "notify customer"

    with pytest.raises(TypeError):
        Transition(PAID, SHIPPED, SHIP, before=(lambda move: None, "mailer.send"))


def test_a_callable_the_name_of_which_cannot_be_read_is_still_a_hook():
    def reserve_stock(move):
        return None

    row = Transition(
        PAID, SHIPPED, SHIP, before=reserve_stock, after=partial(reserve_stock)
    )

    assert [hook.name for hook in row.before] == ["reserve stock"]
    assert [hook.name for hook in row.after] == ["hook"]
    assert row.hooks == row.before + row.after
    assert row.hooked
    assert not Transition(PAID, SHIPPED, SHIP).hooked


def test_a_hook_is_told_which_move_it_wraps():
    seen = []

    def watch(move):
        seen.append(move)

    row = Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE, before=watch, after=watch)
    order = {"id": 7}

    moved = Machine(TransitionTable((row,)), PAID).apply(
        SHIP, role=WAREHOUSE, context=order
    )
    before, after = seen

    assert moved.state == SHIPPED
    assert [move.phase for move in seen] == ["before", "after"]
    assert before.transition is row
    assert before.source == PAID
    assert before.target == SHIPPED
    assert before.trigger == SHIP
    assert before.role == WAREHOUSE
    assert before.subject is order
    assert str(before) == "before paid --ship--> shipped [warehouse]"
    assert str(after) == "after paid --ship--> shipped [warehouse]"


def test_an_open_move_tells_its_hook_that_nobody_asked():
    seen = []

    def watch(move):
        seen.append(move)

    table = TransitionTable((Transition(NEW, CANCELLED, CANCEL, before=watch),))

    Machine(table, NEW).apply(CANCEL)

    assert seen[0].role is None
    assert seen[0].subject is None


def test_what_a_hook_returns_is_not_an_answer():
    table = TransitionTable((Transition(PAID, SHIPPED, SHIP, before=lambda m: False),))

    assert Machine(table, PAID).apply(SHIP).state == SHIPPED


def test_an_interrupt_is_not_dressed_up_as_a_hook_failure():
    def give_up(move):
        raise KeyboardInterrupt

    machine = Machine(
        TransitionTable((Transition(PAID, SHIPPED, SHIP, before=give_up),)), PAID
    )

    with pytest.raises(KeyboardInterrupt):
        machine.apply(SHIP)

    assert machine.state == PAID
    assert not machine.history


def test_a_timestamp_the_driver_already_parsed_is_kept():
    row = {
        "source": "new",
        "target": "paid",
        "trigger": "pay",
        "role": "customer",
        "reason": "",
        "at": MOMENT,
    }

    assert Entry.from_dict(CORE, row).at == MOMENT


def test_a_row_without_a_timestamp_is_stamped_on_arrival():
    entry = Entry.from_dict(CORE, {"source": "new", "target": "paid", "trigger": "pay"})

    assert entry.at.tzinfo is not None
    assert entry.role is None
    assert entry.actor == "anyone"
    assert entry.reason == ""


def test_only_an_absent_role_means_an_open_move():
    with pytest.raises(ValueError):
        Entry.from_dict(
            CORE,
            {"source": "new", "target": "paid", "trigger": "pay", "role": ""},
        )


def test_a_reason_is_recorded_without_its_padding():
    entry = Entry(NEW, PAID, PAY, "customer", "  packed today  ", MOMENT)

    assert entry.role == CUSTOMER
    assert entry.reason == "packed today"
    assert entry.as_dict()["reason"] == "packed today"
    assert (
        str(entry)
        == "2026-05-04T09:12:31+00:00 new --pay--> paid by customer: packed today"
    )


def test_a_role_name_is_accepted_wherever_a_role_is():
    machine = Machine(CORE, NEW).apply(PAY, role="customer")

    assert machine.history.last.role == CUSTOMER
    assert machine.history.by_role("customer") == machine.history.entries
    assert machine.history.roles == frozenset({CUSTOMER})


def test_a_record_is_a_copy_the_caller_may_mutate():
    machine = Machine(CORE, NEW).apply(PAY, role=CUSTOMER)

    record = machine.as_record()
    record["state"] = "shipped"
    record["history"].clear()

    assert machine.state == PAID
    assert len(machine.history) == 1
    assert machine.as_record()["state"] == "paid"
    assert isinstance(machine.history.as_dicts(), tuple)


def test_an_unknown_name_names_the_cell_of_the_row_at_fault():
    rows = (
        {
            "source": "packed",
            "target": "paid",
            "trigger": "pay",
            "role": None,
            "reason": "",
            "at": MOMENT.isoformat(),
        },
    )

    with pytest.raises(UnknownName) as refusal:
        History.from_dicts(CORE, rows)

    assert refusal.value.field == "history[0].source"

    with pytest.raises(UnknownName) as named:
        History.from_dicts(CORE, rows, field="moves")

    assert named.value.field == "moves[0].source"


def test_an_empty_table_declares_nothing_and_says_so():
    empty = TransitionTable()

    assert len(empty) == 0
    assert empty.states == ()
    assert empty.triggers == ()

    with pytest.raises(UnknownName) as refusal:
        empty.state("paid")

    assert refusal.value.field == ""
    assert "the table declares no state" in str(refusal.value)


def test_a_stored_history_still_reads_after_the_table_gains_a_row():
    machine = Machine(CORE, NEW).apply(PAY, role=CUSTOMER)
    wider = TransitionTable(
        CORE.transitions + (Transition(PAID, CANCELLED, CANCEL, roles=SUPPORT),)
    )

    back = Machine.from_record(wider, machine.as_record())

    assert back.state == PAID
    assert back.history == machine.history
    assert [row.trigger.name for row in back.allowed(role=SUPPORT)] == ["cancel"]


def test_an_open_move_round_trips_through_json():
    table = TransitionTable((Transition(NEW, CANCELLED, CANCEL),))
    machine = Machine(table, NEW).apply(CANCEL)

    back = Machine.from_record(table, json.loads(json.dumps(machine.as_record())))

    assert back == machine
    assert back.history.last.role is None
    assert back.history.last.at == machine.history.last.at


def test_a_reason_needs_a_code_and_speaks_for_itself():
    with pytest.raises(ValueError):
        CancellationReason("   ")

    assert CancellationReason("  duplicate  ").code == "duplicate"
    assert CancellationReason("out_of_stock").sentence == "out of stock"
    assert str(CHANGED_MIND) == "the customer no longer wants the order"


def test_a_reason_is_matched_by_code_against_the_declaration():
    path = CancellationPath(
        PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons=(CHANGED_MIND, DUPLICATE)
    )

    assert path.codes == ("changed_mind", "duplicate")
    assert path.accept("duplicate") == DUPLICATE.sentence
    assert path.accept(CancellationReason("duplicate", "sent twice")) == (
        DUPLICATE.sentence
    )
    assert path.accepts(None) is False

    with pytest.raises(ReasonNotAccepted) as refusal:
        path.accept("out_of_stock")

    assert refusal.value.path is path
    assert refusal.value.accepted == (CHANGED_MIND, DUPLICATE)
    assert "requires one of: changed_mind, duplicate" in str(refusal.value)
    assert "reason 'out_of_stock' is not one of them" in str(refusal.value)


def test_a_reason_declared_as_a_bare_code_borrows_its_sentence():
    path = CancellationPath(
        PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons="changed_mind"
    )

    assert path.codes == ("changed_mind",)
    assert path.accept("changed_mind") == "changed mind"


def test_a_path_without_reasons_takes_anything_and_demands_nothing():
    path = CancellationPath(RETURNED, CANCELLED, WRITE_OFF, roles=WAREHOUSE)

    assert path.reasons == ()
    assert path.accepts(None)
    assert path.accepts("unsellable")
    assert path.accept() == ""
    assert path.accept(DAMAGED) == DAMAGED.sentence
    assert path.outcome == "nothing follows"
    assert str(path) == "returned --write off--> cancelled [warehouse]"


def test_free_text_reaches_the_history_trimmed_or_not_at_all():
    policy = CancellationPolicy(
        (CancellationPath(RETURNED, CANCELLED, WRITE_OFF, roles=WAREHOUSE),)
    )
    table = policy.extend(
        TransitionTable((Transition(SHIPPED, RETURNED, FAIL, roles=COURIER),))
    )

    written = policy.cancel(
        Machine(table, RETURNED), role=WAREHOUSE, reason="  unsellable  "
    )
    silent = policy.cancel(Machine(table, RETURNED), role=WAREHOUSE)

    assert written.history.last.reason == "unsellable"
    assert silent.history.last.reason == ""
    assert str(silent.history.last).endswith("by warehouse")


def test_the_first_declared_path_wins_even_when_another_fits_the_reason():
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons=CHANGED_MIND
            ),
            CancellationPath(PAID, RETURNED, FAIL, roles=CUSTOMER, reasons=DAMAGED),
        )
    )
    machine = Machine(policy.extend(CORE), PAID)

    assert policy.resolve(PAID, role=CUSTOMER).trigger == CANCEL
    assert policy.resolve(PAID, role=CUSTOMER, trigger=FAIL).trigger == FAIL
    assert policy.reasons_for(PAID, role=CUSTOMER) == (CHANGED_MIND, DAMAGED)

    with pytest.raises(ReasonNotAccepted):
        policy.cancel(machine, role=CUSTOMER, reason=DAMAGED)

    returned = policy.cancel(machine, role=CUSTOMER, reason=DAMAGED, trigger=FAIL)

    assert returned.state == RETURNED
    assert returned.history.last.reason == DAMAGED.sentence


def test_a_trigger_this_actor_may_not_take_is_refused():
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons=CHANGED_MIND
            ),
            CancellationPath(PAID, RETURNED, FAIL, roles=COURIER, reasons=DAMAGED),
        )
    )

    with pytest.raises(CannotCancel) as refusal:
        policy.resolve(PAID, role=CUSTOMER, trigger=FAIL)

    assert refusal.value.actors == frozenset({CUSTOMER, COURIER})
    assert "here only courier, customer may cancel" in str(refusal.value)


def test_a_state_no_path_leaves_says_so():
    policy = CancellationPolicy(
        (CancellationPath(PAID, CANCELLED, CANCEL, roles=CUSTOMER),)
    )

    assert policy.actors(SHIPPED) == frozenset()

    with pytest.raises(CannotCancel) as refusal:
        policy.resolve(SHIPPED, role=COURIER)

    assert "no cancellation path leaves 'shipped'" in str(refusal.value)


def test_an_empty_policy_leaves_a_table_as_it_was():
    policy = CancellationPolicy()

    assert len(policy) == 0
    assert policy.reasons == ()
    assert str(policy) == ""
    assert policy.extend(CORE).transitions == CORE.transitions


def test_a_path_may_not_shadow_a_row_the_table_already_has():
    policy = CancellationPolicy(
        (CancellationPath(PAID, CANCELLED, SHIP, roles=WAREHOUSE),)
    )

    with pytest.raises(ValueError) as refusal:
        policy.extend(CORE)

    assert "duplicate transition" in str(refusal.value)


def test_the_policy_lists_every_reason_once():
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons=(CHANGED_MIND, DAMAGED)
            ),
            CancellationPath(
                SHIPPED,
                RETURNED,
                FAIL,
                roles=COURIER,
                reasons=(DAMAGED, UNDELIVERABLE),
            ),
        )
    )

    assert policy.reasons == (CHANGED_MIND, DAMAGED, UNDELIVERABLE)
    assert len(policy) == 2
    assert [path.trigger for path in policy] == [CANCEL, FAIL]


def test_a_cancellation_may_be_backdated():
    policy = CancellationPolicy(
        (
            CancellationPath(
                PAID, CANCELLED, CANCEL, roles=CUSTOMER, reasons=CHANGED_MIND
            ),
        )
    )
    machine = policy.cancel(
        Machine(policy.extend(CORE), PAID),
        role=CUSTOMER,
        reason=CHANGED_MIND,
        at=MOMENT,
    )

    assert machine.history.last.at == MOMENT


def test_an_order_that_has_not_moved_has_an_empty_record():
    machine = Machine(CORE, NEW)

    assert not machine.history
    assert len(machine.history) == 0
    assert machine.history.first is None
    assert machine.history.last is None
    assert machine.history.states == ()
    assert machine.history.roles == frozenset()
    assert machine.timeline() == ""
    assert str(EMPTY_HISTORY) == "(no transitions yet)"
    assert machine.as_record() == {"state": "new", "history": []}


def test_a_machine_may_start_with_the_history_it_already_has():
    before = History([Entry(NEW, PAID, PAY, CUSTOMER, "", MOMENT)])
    machine = Machine(CORE, PAID, before)

    moved = machine.apply(SHIP, role=WAREHOUSE, at=LATER)

    assert isinstance(before.entries, tuple)
    assert machine.history is before
    assert len(before) == 1
    assert len(moved.history) == 2
    assert moved.history[0] == before[0]
    assert moved.history.states == (NEW, PAID, SHIPPED)
    assert moved.history.since(LATER) == (moved.history.last,)
    assert len(moved.history.since(MOMENT)) == 2
    assert moved.history.for_trigger(DELIVER) == ()
