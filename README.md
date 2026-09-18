# order-lifecycle

Declarative state machine for order lifecycles: role-guarded transitions, hooks,
cancellation paths and a readable history.

## Status

Early development. States, transitions, role guards, guard conditions, hooks and
cancellation paths can be declared as data and applied through the machine,
which keeps an append-only history of every accepted move.

## Installation

```bash
pip install order-lifecycle
```

## Why a table instead of scattered ifs

The rules of an order lifecycle are easy to state and hard to keep. They usually
end up spread across the handlers that move an order:

```python
def ship(order, user):
    if order.status != "paid":
        raise ValueError(f"cannot ship an order in {order.status}")
    if user.role != "warehouse":
        raise PermissionError("only the warehouse may ship")
    if not order.payment_confirmed:
        raise ValueError("payment is not confirmed")
    order.status = "shipped"
    reserve_stock(order)
    mailer.send(order, "shipped")
    log.info("order %s shipped by %s", order.id, user.id)
```

One handler per trigger, each re-deriving the same facts. Three things go wrong,
usually in this order:

- **The rules are duplicated.** The admin panel, the mobile API and the nightly
  job grow their own copy of the same `if`, and the copies drift.
- **Nothing can be asked.** "What may support do with this order right now?" has
  no answer except reading every handler, so the UI hard-codes a second, parallel
  guess of the same matrix.
- **The reason is lost.** The status changed; why it changed lives in a log line
  that is rotated away before anyone asks.

The same lifecycle as data is a list of rows, and each of those questions becomes
a lookup:

```python
Transition(
    PAID,
    SHIPPED,
    SHIP,
    roles=WAREHOUSE,
    conditions=(PAYMENT_CONFIRMED, IN_STOCK),
    before=reserve_stock,
    after=notify_customer,
)
```

The handler shrinks to `machine.apply(SHIP, role=user.role, context=order)`, the
UI reads its buttons off `machine.allowed(role=...)`, a refusal arrives as a
typed error naming what was required, and the accepted move is appended to a
history that travels with the order. Adding a state means editing one table
instead of auditing every caller.

## Declaring a lifecycle

A lifecycle is a table of `(from-state, trigger, to-state)` rows, not a pile of
method calls:

```python
from order_lifecycle import (
    COURIER,
    CUSTOMER,
    SUPPORT,
    State,
    Transition,
    TransitionTable,
    Trigger,
    WAREHOUSE,
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

TABLE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER),
        Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE),
        Transition(SHIPPED, DELIVERED, DELIVER, roles=COURIER),
        Transition(NEW, CANCELLED, CANCEL),
        Transition(PAID, CANCELLED, CANCEL, roles={CUSTOMER, SUPPORT}),
    )
)

str(TABLE.find(NEW, PAY))                 # 'new --pay--> paid [customer]'
TABLE.available(PAID, role=WAREHOUSE)     # -> (paid --ship--> shipped [warehouse],)
```

Every type is a frozen dataclass, so tables are hashable, comparable and safe to
share as module-level constants.

## Role guards

A transition names the actors allowed to fire it. The rule lives in the table,
once, instead of being re-implemented by every endpoint that touches an order:

```python
Transition(PAID, SHIPPED, SHIP, roles=WAREHOUSE)                # a single actor
Transition(PAID, CANCELLED, CANCEL, roles={CUSTOMER, SUPPORT})  # either of two
Transition(NEW, CANCELLED, CANCEL)                              # open to anyone
```

`CUSTOMER`, `WAREHOUSE`, `COURIER` and `SUPPORT` ship as constants; any other
actor is a `Role("...")` away, and plain names are accepted and converted:

```python
from order_lifecycle import Role

Transition(PAID, SHIPPED, SHIP, roles="warehouse").roles
# -> frozenset({Role(name='warehouse')})
```

A guarded transition refuses every actor it does not name — including a caller
that supplied no role at all:

```python
ship = TABLE.find(PAID, SHIP)
ship.guarded              # -> True
ship.permits(WAREHOUSE)   # -> True
ship.permits(CUSTOMER)    # -> False
ship.permits(None)        # -> False
```

Because the guard is data, the permission matrix can be read off the table
instead of grepping views:

```python
TABLE.roles               # -> frozenset({Role('customer'), Role('warehouse'), ...})
TABLE.for_role(SUPPORT)   # -> every transition support may fire, guarded or open
```

## Guard conditions

Being the right actor is not always enough: the warehouse may ship, but only
once the payment is confirmed and the goods are in stock. A `Condition` is a
named predicate over the order, and it carries the sentence it will use when it
refuses:

```python
from order_lifecycle import Condition, flag

PAYMENT_CONFIRMED = flag(
    "payment_confirmed",
    name="payment confirmed",
    requires="the payment must be confirmed",
)
IN_STOCK = Condition(
    "in stock",
    lambda order: order["units_available"] > 0,
    "every line item must be in stock",
)

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

str(TABLE.find(PAID, SHIP))
# 'paid --ship--> shipped [warehouse] {payment confirmed, in stock}'
```

The order itself is the context. It can be any object; `flag()` reads a mapping
key or an attribute of the same name, while a hand-written `Condition` receives
the context and decides for itself.

A failed condition explains itself instead of returning a bare `False`:

```python
ship = TABLE.find(PAID, SHIP)

ship.holds({"payment_confirmed": True, "units_available": 3})   # -> True
[str(result) for result in ship.unmet({"payment_confirmed": False, "units_available": 0})]
# -> ['payment confirmed: the payment must be confirmed',
#     'in stock: every line item must be in stock']
```

Conditions sit on top of roles rather than replacing them; `allows()` asks both
questions at once:

```python
ready = {"payment_confirmed": True, "units_available": 3}

ship.allows(WAREHOUSE, ready)   # -> True
ship.allows(CUSTOMER, ready)    # -> False, wrong actor
ship.allows(WAREHOUSE, {"payment_confirmed": False, "units_available": 3})
# -> False, right actor, wrong moment
```

## Hooks

Something usually has to happen when an order moves: stock is reserved, a label
is printed, a customer is told. A `Hook` hangs that work on the transition
itself instead of on every call site that fires it:

```python
from order_lifecycle import Hook

def reserve_stock(move):
    warehouse.reserve(move.subject, units=1)

NOTIFY = Hook("notify customer", lambda move: mailer.send(move.subject, move.trigger.name))

Transition(
    PAID,
    SHIPPED,
    SHIP,
    roles=WAREHOUSE,
    conditions=(PAYMENT_CONFIRMED, IN_STOCK),
    before=reserve_stock,
    after=NOTIFY,
)
```

A bare callable is wrapped into a `Hook` named after the function; several run
in declaration order (`before=(reserve_stock, print_label)`). Each one is called
with a `TransitionContext` describing the move — the transition, the phase, the
acting role and the order that was passed as `context`:

```python
def audit(move):
    move.phase       # -> 'before' or 'after'
    move.source      # -> paid
    move.target      # -> shipped
    move.trigger     # -> ship
    move.role        # -> customer, warehouse, ... or None
    move.subject     # -> the order handed to apply(context=...)
```

`apply()` runs the before hooks once both guards have passed and the after hooks
once the target state is settled. A hook that raises is wrapped in `HookFailed`,
and `apply()` never returns — the machine the caller holds is still the one in
the source state, so a failing hook cannot leave an order half-moved:

```python
from order_lifecycle import HookFailed

machine = Machine(TABLE, PAID)
try:
    machine = machine.apply(SHIP, role=WAREHOUSE, context=order)
except HookFailed as error:
    error.phase        # -> 'before'
    error.hook.name    # -> 'reserve stock'
    error.cause        # -> the exception the hook raised
    error.completed    # -> the hooks of this phase that already ran

machine.state          # -> paid, untouched
```

Side effects an earlier hook already performed are the caller's to undo; the
error names them in `completed` so a compensating step knows exactly how far the
move got.

## Running a lifecycle

`Machine` pairs a table with the state an order sits in. Applying a trigger
returns a new machine; the table stays the single source of truth:

```python
from order_lifecycle import ConditionNotMet, IllegalTransition, Machine, RoleNotPermitted

order = {"payment_confirmed": True, "units_available": 3}

machine = Machine(TABLE, NEW)
machine = machine.apply(PAY, role=CUSTOMER)        # -> Machine(state=paid)
machine.can(SHIP, role=WAREHOUSE, context=order)   # -> True
machine.allowed(role=SUPPORT)                      # -> (paid --cancel--> cancelled [customer, support],)
```

A refused trigger raises a typed error that names the current state and what
would have been accepted instead:

```python
machine.apply(PAY, role=CUSTOMER)
# IllegalTransition: cannot apply trigger 'pay' in state 'paid':
#                    allowed here: cancel, ship

machine.apply(SHIP, role=CUSTOMER)
# RoleNotPermitted: trigger 'ship' in state 'paid' requires one of: warehouse;
#                   role 'customer' is not one of them

machine.apply(SHIP, role=WAREHOUSE, context={"payment_confirmed": False, "units_available": 3})
# ConditionNotMet: trigger 'ship' in state 'paid' requires:
#                  the payment must be confirmed
```

Both guards are checked in `resolve()`, before the machine moves — the role
first, then the conditions — so a wrong actor or an unready order never reaches
a side effect. A conditional transition applied without a context is refused the
same way a guarded one refuses a missing role. Every error derives from
`LifecycleError` and carries the offending state, trigger, roles and unmet
conditions as attributes, so callers can render their own message:

```python
try:
    machine.apply(SHIP, role=WAREHOUSE, context={"payment_confirmed": False, "units_available": 0})
except ConditionNotMet as error:
    [result.detail for result in error.failures]
    # -> ['the payment must be confirmed', 'every line item must be in stock']
```

## Cancellation paths

Cancel is not one transition. A customer changes their mind, the warehouse
rejects an order it cannot pack, the courier fails to hand a parcel over and the
goods travel back. Different states, different actors, different reasons and
different follow-ups. A `CancellationPath` declares one of those ways out, and a
`CancellationPolicy` collects them:

```python
from order_lifecycle import (
    CHANGED_MIND,
    DAMAGED,
    DUPLICATE,
    OUT_OF_STOCK,
    UNDELIVERABLE,
    CancellationPath,
    CancellationPolicy,
)

RETURNED = State("returned")
REJECT = Trigger("reject")
FAIL = Trigger("fail")
WRITE_OFF = Trigger("write off")

def refund(move): payments.refund(move.subject)
def restock(move): warehouse.release(move.subject)
def collect_parcel(move): courier.schedule_pickup(move.subject)

POLICY = CancellationPolicy(
    (
        CancellationPath(
            NEW, CANCELLED, CANCEL,
            roles={CUSTOMER, SUPPORT},
            reasons=(CHANGED_MIND, DUPLICATE),
        ),
        CancellationPath(
            PAID, CANCELLED, CANCEL,
            roles={CUSTOMER, SUPPORT},
            reasons=(CHANGED_MIND, DUPLICATE),
            follow_up=refund,
        ),
        CancellationPath(
            PAID, CANCELLED, REJECT,
            roles=WAREHOUSE,
            reasons=(OUT_OF_STOCK, DAMAGED),
            follow_up=(refund, restock),
        ),
        CancellationPath(
            SHIPPED, RETURNED, FAIL,
            roles=COURIER,
            reasons=(UNDELIVERABLE, DAMAGED),
            follow_up=collect_parcel,
        ),
        CancellationPath(RETURNED, CANCELLED, WRITE_OFF, roles=WAREHOUSE),
    )
)

TABLE = POLICY.extend(CORE)
```

`CORE` here is a table holding the forward rows — pay, ship, deliver — and
nothing else. A path is an ordinary transition wearing a policy hat: `extend()`
appends every path to a table as a normal row, `follow_up=` becomes the after
phase of that row, and each actor leaving a shared state gets its own trigger —
the customer `cancel`s a paid order, the warehouse `reject`s it. Not every path
ends in `cancelled`: a failed delivery moves to `returned`, which the warehouse
later writes off.

Because the policy is data, the offer a UI has to render can be read off it
instead of being hard-coded per screen:

```python
POLICY.actors(PAID)                       # -> frozenset({customer, support, warehouse})
POLICY.reasons_for(PAID, role=CUSTOMER)   # -> (changed_mind, duplicate)
POLICY.reasons_for(PAID, role=WAREHOUSE)  # -> (out_of_stock, damaged)

str(POLICY.available(SHIPPED, role=COURIER)[0])
# 'shipped --fail--> returned [courier] (undeliverable, damaged) -> collect parcel'
```

`cancel()` picks the path the actor may take, checks the reason against the ones
that path offers, and then moves through the machine, so role guards, conditions,
hooks and history behave exactly as they do for any other trigger:

```python
machine = POLICY.cancel(Machine(TABLE, PAID), role=WAREHOUSE, reason=OUT_OF_STOCK)

machine.state                 # -> cancelled
machine.history.last.trigger  # -> reject
machine.history.last.reason   # -> 'the goods are not in the warehouse'
```

A path that declares reasons takes only those and demands one; a path that
declares none — writing off a returned order — records whatever sentence the
caller wrote. `CHANGED_MIND`, `DUPLICATE`, `PAYMENT_FAILED`, `OUT_OF_STOCK`,
`DAMAGED` and `UNDELIVERABLE` ship as constants, and any other is a
`CancellationReason("code", "detail")` away.

Both refusals are typed and say who could have cancelled, and with what:

```python
POLICY.cancel(Machine(TABLE, PAID), role=COURIER, reason=UNDELIVERABLE)
# CannotCancel: role 'courier' cannot cancel an order in state 'paid':
#               here only customer, support, warehouse may cancel

POLICY.cancel(Machine(TABLE, PAID), role=CUSTOMER, reason=OUT_OF_STOCK)
# ReasonNotAccepted: cancelling 'paid' with trigger 'cancel' requires one of:
#                    changed_mind, duplicate;
#                    reason 'out_of_stock' is not one of them
```

When an actor has several ways out of a state, the first declared one wins; pass
`trigger=` to name another.

## History

A support agent asking "why is this order cancelled?" should not have to read
application logs. Every accepted move is appended to the machine's history, so
what changed, when and by whom travels with the order:

```python
machine = Machine(TABLE, NEW)
machine = machine.apply(PAY, role=CUSTOMER)
machine = machine.apply(CANCEL, role=SUPPORT, reason="duplicate order")

print(machine.timeline())
# 2026-05-04T09:12:31+00:00 new --pay--> paid by customer
# 2026-05-04T09:14:02+00:00 paid --cancel--> cancelled by support: duplicate order
```

The history is append-only: `apply()` returns a new machine whose history is the
old one plus a single `Entry`. Nothing rewrites or drops a past move, and a
refused trigger or a failing hook records nothing at all, because the machine
carrying the new entry is never handed back.

An entry is data, not a formatted string, so a timeline can be rendered however
the caller likes:

```python
last = machine.history.last
last.source        # -> paid
last.target        # -> cancelled
last.trigger       # -> cancel
last.role          # -> Role('support'), or None when the transition is open
last.actor         # -> 'support', or 'anyone'
last.reason        # -> 'duplicate order'
last.at            # -> a timezone-aware datetime, UTC
```

The record answers the questions an order timeline is usually asked:

```python
len(machine.history)                # -> 2
machine.history.states              # -> (new, paid, cancelled)
machine.history.roles               # -> frozenset({Role('customer'), Role('support')})
machine.history.by_role(SUPPORT)    # -> every move support made
machine.history.for_trigger(CANCEL) # -> every cancellation
machine.history.since(this_morning) # -> the moves recorded since a moment
```

The timestamp defaults to the moment of the move; pass `at=` to `apply()` when
the caller owns the clock, for backfills or reproducible tests. A machine can
also be built with a history it already has, which is how an order is rehydrated
from storage:

```python
from order_lifecycle import Entry, History

machine = Machine(TABLE, PAID, History((Entry(NEW, PAID, PAY, CUSTOMER),)))
```

## An order, end to end

The sections above are one lifecycle, taken a piece at a time. Here it is whole:
a parcel that is paid for, packed, shipped and handed over, with the ways out
declared next to the ways forward.

```python
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
    Condition,
    Machine,
    State,
    Transition,
    TransitionTable,
    Trigger,
    flag,
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

PAYMENT_CONFIRMED = flag(
    "payment_confirmed",
    name="payment confirmed",
    requires="the payment must be confirmed",
)
IN_STOCK = Condition(
    "in stock",
    lambda order: order["units_available"] > 0,
    "every line item must be in stock",
)
ADDRESS_KNOWN = flag(
    "address",
    name="address known",
    requires="the delivery address must be known",
)

def reserve_stock(move):
    move.subject["units_available"] -= 1

def notify_customer(move):
    print(f"mail: your order is {move.target.name}")

def refund(move):
    move.subject["refunded"] = True

def restock(move):
    move.subject["units_available"] += 1

def collect_parcel(move):
    print("courier: pickup scheduled")

CORE = TransitionTable(
    (
        Transition(NEW, PAID, PAY, roles=CUSTOMER, after=notify_customer),
        Transition(
            PAID,
            SHIPPED,
            SHIP,
            roles=WAREHOUSE,
            conditions=(PAYMENT_CONFIRMED, IN_STOCK),
            before=reserve_stock,
            after=notify_customer,
        ),
        Transition(
            SHIPPED,
            DELIVERED,
            DELIVER,
            roles=COURIER,
            conditions=ADDRESS_KNOWN,
            after=notify_customer,
        ),
    )
)

POLICY = CancellationPolicy(
    (
        CancellationPath(
            NEW, CANCELLED, CANCEL,
            roles={CUSTOMER, SUPPORT},
            reasons=(CHANGED_MIND, DUPLICATE),
        ),
        CancellationPath(
            PAID, CANCELLED, CANCEL,
            roles={CUSTOMER, SUPPORT},
            reasons=(CHANGED_MIND, DUPLICATE),
            follow_up=refund,
        ),
        CancellationPath(
            PAID, CANCELLED, REJECT,
            roles=WAREHOUSE,
            reasons=(OUT_OF_STOCK, DAMAGED),
            follow_up=(refund, restock),
        ),
        CancellationPath(
            SHIPPED, RETURNED, FAIL,
            roles=COURIER,
            reasons=(UNDELIVERABLE, DAMAGED),
            follow_up=collect_parcel,
        ),
        CancellationPath(RETURNED, CANCELLED, WRITE_OFF, roles=WAREHOUSE),
    )
)

TABLE = POLICY.extend(CORE)
```

That is the whole specification: six states, seven triggers, four actors and
every rule about who may do what, when, and what follows. Walking a parcel
through it touches nothing else:

```python
order = {
    "payment_confirmed": False,
    "units_available": 3,
    "address": "12 Dock Road",
}

machine = Machine(TABLE, NEW)
[t.trigger.name for t in machine.allowed(role=CUSTOMER)]   # -> ['pay', 'cancel']

machine = machine.apply(PAY, role=CUSTOMER, context=order)
machine.state                                              # -> paid

machine.apply(SHIP, role=WAREHOUSE, context=order)
# ConditionNotMet: trigger 'ship' in state 'paid' requires:
#                  the payment must be confirmed

order["payment_confirmed"] = True
machine = machine.apply(SHIP, role=WAREHOUSE, context=order)
order["units_available"]                                   # -> 2, the before hook reserved one

machine = machine.apply(DELIVER, role=COURIER, context=order)
machine.state                                              # -> delivered

print(machine.timeline())
# 2026-05-04T09:12:31+00:00 new --pay--> paid by customer
# 2026-05-04T09:31:08+00:00 paid --ship--> shipped by warehouse
# 2026-05-04T14:02:55+00:00 shipped --deliver--> delivered by courier
```

The branch that did not happen is declared in the same place. A parcel the
courier cannot hand over travels back and is written off later, by a different
actor, with a different reason:

```python
returned = POLICY.cancel(
    Machine(TABLE, SHIPPED), role=COURIER, reason=UNDELIVERABLE, context=order
)
returned.state                     # -> returned

written_off = POLICY.cancel(returned, role=WAREHOUSE, reason="unsellable")
written_off.state                  # -> cancelled

print(written_off.timeline())
# 2026-05-04T14:40:12+00:00 shipped --fail--> returned by courier: the courier could not hand the order over
# 2026-05-06T10:05:44+00:00 returned --write off--> cancelled by warehouse: unsellable
```

No handler in this example knows the rules of another. The endpoint that ships
an order does not check payment, the screen that offers a cancel button does not
know who may press it, and the support tool that answers "why?" reads the
history rather than the logs — all three read the same table.

## Persistence

A `Machine` is a table, a state and a history. The table is code, so only two
things have to survive a restart: the name of the state the order sits in, and
the entries it has already recorded. Everything else is rebuilt by looking names
up in the declarations above:

```sql
create table orders (
    id       text    primary key,
    state    text    not null,
    history  jsonb   not null default '[]',
    version  integer not null default 0
);
```

The codec is two functions. `dump()` turns a machine into plain data, `load()`
rebuilds one; `Machine(table, state, history)` and `Entry(...)` are the only
constructors involved, and `Entry` accepts a role name as a string, so a stored
row needs no lookup table of its own:

```python
from datetime import datetime

from order_lifecycle import Entry, History, Machine

STATES = {s.name: s for s in (NEW, PAID, SHIPPED, RETURNED, DELIVERED, CANCELLED)}
TRIGGERS = {t.name: t for t in (PAY, SHIP, DELIVER, CANCEL, REJECT, FAIL, WRITE_OFF)}


def dump(machine):
    return {
        "state": machine.state.name,
        "history": [
            {
                "source": entry.source.name,
                "target": entry.target.name,
                "trigger": entry.trigger.name,
                "role": None if entry.role is None else entry.role.name,
                "reason": entry.reason,
                "at": entry.at.isoformat(),
            }
            for entry in machine.history
        ],
    }


def load(record):
    return Machine(
        TABLE,
        STATES[record["state"]],
        History(
            tuple(
                Entry(
                    STATES[row["source"]],
                    STATES[row["target"]],
                    TRIGGERS[row["trigger"]],
                    row["role"],
                    row["reason"],
                    datetime.fromisoformat(row["at"]),
                )
                for row in record["history"]
            )
        ),
    )
```

A request handler then has one shape, whatever the trigger is:

```python
def handle(order_id, trigger, role, reason=""):
    record, order = repository.read(order_id)
    machine = load(record)
    machine = machine.apply(TRIGGERS[trigger], role=role, context=order, reason=reason)
    repository.write(order_id, dump(machine), if_version=record["version"])
```

Four properties make that loop safe:

- **Nothing is written until you write it.** `apply()` builds a new machine and
  leaves the old one alone, so a refusal raises before `write()` is reached and
  the stored row is untouched. There is no half-applied move to clean up.
- **A stale read is cheap to retry.** The machine is a value, not a session; on
  a version conflict, read again, `load()` again and apply the trigger again.
- **`load()` is not a replay.** Rehydration builds the machine directly, so no
  hook fires and no entry is appended for moves that already happened.
- **The history is the audit trail.** It is stored with the order rather than
  derived at read time, so an entry written last year still reads the same after
  the table gains a state.

Hooks that write to the same database as the order commit together with the
move. Hooks that leave it — mail, labels, payment calls — run inside `apply()`,
before the caller has stored anything, so a crash in between leaves an effect
without a recorded move. Have those hooks append to an outbox that is saved in
the same transaction as `dump(machine)` and delivered afterwards.

Renaming a state or a trigger changes the strings in `STATES` and `TRIGGERS`,
which means stored rows have to be migrated the same way any stored enum does.
Adding rows, roles, conditions or paths does not: old histories keep reading
correctly, and only the offer a state makes changes.

## Development

```bash
pip install -e .
```

## License

MIT

Maintained by [Shipmind Labs](https://shipmindlabs.com).
