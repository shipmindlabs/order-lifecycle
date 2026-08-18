# order-lifecycle

Declarative state machine for order lifecycles: role-guarded transitions, hooks,
cancellation paths and a readable history.

## Status

Early development. States and transitions can be declared as data and applied
through the machine; hooks and history are not implemented yet.

## Installation

```bash
pip install order-lifecycle
```

## Declaring a lifecycle

A lifecycle is a table of `(from-state, trigger, to-state)` rows, not a pile of
method calls:

```python
from order_lifecycle import State, Transition, TransitionTable, Trigger

NEW = State("new")
PAID = State("paid")
SHIPPED = State("shipped")
CANCELLED = State("cancelled", terminal=True)

PAY = Trigger("pay")
SHIP = Trigger("ship")
CANCEL = Trigger("cancel")

TABLE = TransitionTable(
    (
        Transition(NEW, PAID, PAY),
        Transition(PAID, SHIPPED, SHIP, roles=frozenset({"warehouse"})),
        Transition(NEW, CANCELLED, CANCEL),
        Transition(PAID, CANCELLED, CANCEL, roles=frozenset({"support"})),
    )
)

TABLE.find(NEW, PAY)                      # -> Transition(new --pay--> paid)
TABLE.available(PAID, role="warehouse")   # -> (paid --ship--> shipped,)
```

Every type is a frozen dataclass, so tables are hashable, comparable and safe to
share as module-level constants.

## Running a lifecycle

`Machine` pairs a table with the state an order sits in. Applying a trigger
returns a new machine; the table stays the single source of truth:

```python
from order_lifecycle import IllegalTransition, Machine, RoleNotPermitted

order = Machine(TABLE, NEW)
order = order.apply(PAY)                  # -> Machine(state=paid)
order.can(SHIP, role="warehouse")         # -> True
order.allowed(role="support")             # -> (paid --cancel--> cancelled,)
```

A refused trigger raises a typed error that names the current state and what
would have been accepted instead:

```python
order.apply(PAY)
# IllegalTransition: cannot apply trigger 'pay' in state 'paid':
#                    allowed here: cancel, ship

order.apply(SHIP)
# RoleNotPermitted: trigger 'ship' in state 'paid' requires one of: warehouse;
#                   no role was supplied
```

Both derive from `LifecycleError` and carry the offending state, trigger and the
allowed transitions as attributes, so callers can render their own message.

## Development

```bash
pip install -e .
```

## License

MIT

Maintained by [Shipmind Labs](https://shipmindlabs.com).
