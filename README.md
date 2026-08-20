# order-lifecycle

Declarative state machine for order lifecycles: role-guarded transitions, hooks,
cancellation paths and a readable history.

## Status

Early development. States, transitions and role guards can be declared as data
and applied through the machine; hooks and history are not implemented yet.

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

## Running a lifecycle

`Machine` pairs a table with the state an order sits in. Applying a trigger
returns a new machine; the table stays the single source of truth:

```python
from order_lifecycle import IllegalTransition, Machine, RoleNotPermitted

order = Machine(TABLE, NEW)
order = order.apply(PAY, role=CUSTOMER)   # -> Machine(state=paid)
order.can(SHIP, role=WAREHOUSE)           # -> True
order.allowed(role=SUPPORT)               # -> (paid --cancel--> cancelled [customer, support],)
```

A refused trigger raises a typed error that names the current state and what
would have been accepted instead:

```python
order.apply(PAY, role=CUSTOMER)
# IllegalTransition: cannot apply trigger 'pay' in state 'paid':
#                    allowed here: cancel

order.apply(SHIP, role=CUSTOMER)
# RoleNotPermitted: trigger 'ship' in state 'paid' requires one of: warehouse;
#                   role 'customer' is not one of them
```

The guard is checked in `resolve()`, before the machine moves — a wrong actor
never reaches a side effect. Both errors derive from `LifecycleError` and carry
the offending state, trigger, roles and allowed transitions as attributes, so
callers can render their own message.

## Development

```bash
pip install -e .
```

## License

MIT

Maintained by [Shipmind Labs](https://shipmindlabs.com).
