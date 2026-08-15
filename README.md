# order-lifecycle

Declarative state machine for order lifecycles: role-guarded transitions, hooks,
cancellation paths and a readable history.

## Status

Early development. States and transitions can be declared as data; the runtime
engine is not implemented yet.

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

## Development

```bash
pip install -e .
```

## License

MIT
