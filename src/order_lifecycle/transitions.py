"""Edges of a lifecycle: where a trigger leads, who may fire it, and when."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

from .audit import Audit
from .conditions import ALWAYS, Condition, ConditionResult, as_conditions, evaluate
from .errors import UnknownName
from .hooks import NO_HOOKS, Hook, as_hooks
from .roles import ANYONE, Role, as_roles
from .states import State, Trigger

__all__ = ["Transition", "TransitionTable"]

_Named = TypeVar("_Named", State, Trigger)


def _declare(known: dict[str, _Named], kind: str, value: _Named) -> None:
    """Record ``value`` under its name, refusing two meanings for one name."""
    present = known.setdefault(value.name, value)
    if present != value:
        raise ValueError(
            f"two different {kind}s are named {value.name!r}; a stored name "
            "cannot be resolved to one of them"
        )


@dataclass(frozen=True, slots=True)
class Transition:
    """One row of a lifecycle: ``source --trigger--> target``, guarded by roles."""

    source: State
    target: State
    trigger: Trigger
    roles: frozenset[Role] = ANYONE
    conditions: tuple[Condition, ...] = ALWAYS
    before: tuple[Hook, ...] = NO_HOOKS
    after: tuple[Hook, ...] = NO_HOOKS

    def __post_init__(self) -> None:
        if self.source.terminal:
            raise ValueError(
                f"state {self.source.name!r} is terminal; no transition may leave it"
            )
        object.__setattr__(self, "roles", as_roles(self.roles))
        object.__setattr__(self, "conditions", as_conditions(self.conditions))
        object.__setattr__(self, "before", as_hooks(self.before))
        object.__setattr__(self, "after", as_hooks(self.after))

    @property
    def guarded(self) -> bool:
        """Report whether only named actors may fire this transition."""
        return bool(self.roles)

    @property
    def conditional(self) -> bool:
        """Report whether predicates must hold before this transition fires."""
        return bool(self.conditions)

    @property
    def hooked(self) -> bool:
        """Report whether any callback runs around this transition."""
        return bool(self.before or self.after)

    @property
    def hooks(self) -> tuple[Hook, ...]:
        """Return every hook of this transition, before ones first."""
        return self.before + self.after

    def permits(self, role: Role | str | None) -> bool:
        """Report whether ``role`` may fire this transition."""
        if not self.roles:
            return True
        if role is None:
            return False
        name = role.name if isinstance(role, Role) else str(role).strip()
        return any(allowed.name == name for allowed in self.roles)

    def check(self, context: Any = None) -> tuple[ConditionResult, ...]:
        """Check every condition against ``context`` and return all results."""
        return evaluate(self.conditions, context)

    def unmet(self, context: Any = None) -> tuple[ConditionResult, ...]:
        """Return the results of the conditions ``context`` fails to satisfy."""
        return tuple(result for result in self.check(context) if not result.ok)

    def holds(self, context: Any = None) -> bool:
        """Report whether every condition accepts ``context``.

        A conditional row refuses an absent context the way a guarded row
        refuses an absent role, before any predicate runs.
        """
        return not self.unmet(context)

    def allows(self, role: Role | str | None = None, context: Any = None) -> bool:
        """Report whether ``role`` may fire this transition for ``context``."""
        return self.permits(role) and self.holds(context)

    def __str__(self) -> str:
        edge = f"{self.source.name} --{self.trigger.name}--> {self.target.name}"
        if self.roles:
            edge = f"{edge} [{', '.join(sorted(r.name for r in self.roles))}]"
        if self.conditions:
            edge = f"{edge} {{{', '.join(c.name for c in self.conditions)}}}"
        return edge


@dataclass(frozen=True, slots=True)
class TransitionTable:
    """Every transition of a lifecycle, indexed by source state and trigger."""

    transitions: tuple[Transition, ...] = ()
    _index: dict[tuple[State, Trigger], Transition] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _states: dict[str, State] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _triggers: dict[str, Trigger] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        rows = tuple(self.transitions)
        index: dict[tuple[State, Trigger], Transition] = {}
        states: dict[str, State] = {}
        triggers: dict[str, Trigger] = {}
        for row in rows:
            key = (row.source, row.trigger)
            if key in index:
                raise ValueError(
                    f"duplicate transition for state {row.source.name!r} "
                    f"and trigger {row.trigger.name!r}"
                )
            index[key] = row
            _declare(states, "state", row.source)
            _declare(states, "state", row.target)
            _declare(triggers, "trigger", row.trigger)
        object.__setattr__(self, "transitions", rows)
        object.__setattr__(self, "_index", index)
        object.__setattr__(self, "_states", states)
        object.__setattr__(self, "_triggers", triggers)

    def find(self, state: State, trigger: Trigger) -> Transition | None:
        """Return the transition leaving ``state`` on ``trigger``, if any."""
        return self._index.get((state, trigger))

    def outgoing(self, state: State) -> tuple[Transition, ...]:
        """Return every transition declared to leave ``state``."""
        return tuple(row for row in self.transitions if row.source == state)

    def incoming(self, state: State) -> tuple[Transition, ...]:
        """Return every transition declared to arrive at ``state``."""
        return tuple(row for row in self.transitions if row.target == state)

    def available(
        self,
        state: State,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> tuple[Transition, ...]:
        """Return the transitions ``role`` may fire from ``state`` on ``context``.

        ``None`` means absent rather than unfiltered: a guarded row needs a
        role and a conditional row needs a context, so the listing holds
        exactly the rows the machine would accept for the same arguments.
        """
        return tuple(
            row
            for row in self.transitions
            if row.source == state and row.allows(role, context)
        )

    @property
    def states(self) -> tuple[State, ...]:
        """Return every state this table mentions, in declaration order."""
        return tuple(self._states.values())

    @property
    def triggers(self) -> tuple[Trigger, ...]:
        """Return every trigger this table declares, in declaration order."""
        return tuple(self._triggers.values())

    @property
    def terminals(self) -> tuple[State, ...]:
        """Return every state an order may end in, in declaration order."""
        return tuple(state for state in self.states if state.terminal)

    def state(self, name: str, *, field: str = "") -> State:
        """Return the state called ``name``, or refuse the name.

        ``field`` names the place the name came from, so a stored row that no
        longer matches the declarations says which cell is at fault.
        """
        found = self._states.get(name)
        if found is None:
            raise UnknownName("state", name, tuple(self._states), field)
        return found

    def trigger(self, name: str, *, field: str = "") -> Trigger:
        """Return the trigger called ``name``, or refuse the name."""
        found = self._triggers.get(name)
        if found is None:
            raise UnknownName("trigger", name, tuple(self._triggers), field)
        return found

    @property
    def roles(self) -> frozenset[Role]:
        """Return every role this table guards a transition with."""
        return frozenset(role for row in self.transitions for role in row.roles)

    @property
    def conditions(self) -> tuple[Condition, ...]:
        """Return every condition this table guards a transition with."""
        seen: dict[Condition, None] = {}
        for row in self.transitions:
            for condition in row.conditions:
                seen.setdefault(condition, None)
        return tuple(seen)

    def for_role(self, role: Role | str) -> tuple[Transition, ...]:
        """Return every transition ``role`` may fire, guarded or open."""
        return tuple(row for row in self.transitions if row.permits(role))

    def reachable(self, start: State) -> tuple[State, ...]:
        """Return the states an order can arrive in from ``start``.

        Role guards and conditions are ignored: this asks what the table
        declares, not what an actor may do at a given moment. ``start`` comes
        first, the rest follow in the declaration order of the table.
        """
        found = {start}
        pending = [start]
        while pending:
            for row in self.outgoing(pending.pop()):
                if row.target not in found:
                    found.add(row.target)
                    pending.append(row.target)
        return (start,) + tuple(
            state for state in self.states if state in found and state != start
        )

    def dead_ends(self) -> tuple[State, ...]:
        """Return the states that are not terminal and that nothing leaves."""
        return tuple(
            state
            for state in self.states
            if not state.terminal and not self.outgoing(state)
        )

    def audit(self, start: State) -> Audit:
        """Read the table from ``start`` and report what it gets wrong.

        Two mistakes a table can hold are visible without running anything: a
        state no row leads to, and a state an order enters but cannot leave.
        """
        reachable = self.reachable(start)
        return Audit(
            start,
            reachable,
            tuple(state for state in self.states if state not in reachable),
            self.dead_ends(),
        )

    def __iter__(self):
        return iter(self.transitions)

    def __len__(self) -> int:
        return len(self.transitions)
