# order-lifecycle

Declarative state machine for order lifecycles: role-guarded transitions, hooks,
cancellation paths and a readable history.

## Status

Early development. States, transitions, role guards, guard conditions and hooks
can be declared as data and applied through the machine, which keeps an
append-only history of every accepted move.

## Installation

```bash
pip install order-lifecycle
```

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

## Development

```bash
pip install -e .
```

## License

MIT

Maintained by [Shipmind Labs](https://shipmindlabs.com).
