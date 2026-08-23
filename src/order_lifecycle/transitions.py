"""Edges of a lifecycle: where a trigger leads, who may fire it, and when."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conditions import ALWAYS, Condition, ConditionResult, as_conditions, evaluate
from .roles import ANYONE, Role, as_roles
from .states import State, Trigger

__all__ = ["Transition", "TransitionTable"]


@dataclass(frozen=True, slots=True)
class Transition:
    """One row of a lifecycle: ``source --trigger--> target``, guarded by roles."""

    source: State
    target: State
    trigger: Trigger
    roles: frozenset[Role] = ANYONE
    conditions: tuple[Condition, ...] = ALWAYS

    def __post_init__(self) -> None:
        if self.source.terminal:
            raise ValueError(
                f"state {self.source.name!r} is terminal; no transition may leave it"
            )
        object.__setattr__(self, "roles", as_roles(self.roles))
        object.__setattr__(self, "conditions", as_conditions(self.conditions))

    @property
    def guarded(self) -> bool:
        """Report whether only named actors may fire this transition."""
        return bool(self.roles)

    @property
    def conditional(self) -> bool:
        """Report whether predicates must hold before this transition fires."""
        return bool(self.conditions)

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
        """Report whether every condition accepts ``context``."""
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

    def __post_init__(self) -> None:
        rows = tuple(self.transitions)
        index: dict[tuple[State, Trigger], Transition] = {}
        for row in rows:
            key = (row.source, row.trigger)
            if key in index:
                raise ValueError(
                    f"duplicate transition for state {row.source.name!r} "
                    f"and trigger {row.trigger.name!r}"
                )
            index[key] = row
        object.__setattr__(self, "transitions", rows)
        object.__setattr__(self, "_index", index)

    def find(self, state: State, trigger: Trigger) -> Transition | None:
        """Return the transition leaving ``state`` on ``trigger``, if any."""
        return self._index.get((state, trigger))

    def available(
        self,
        state: State,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> tuple[Transition, ...]:
        """Return the transitions leaving ``state``.

        ``role`` and ``context`` narrow the result when given; conditions are
        only evaluated once a context is supplied.
        """
        rows = tuple(row for row in self.transitions if row.source == state)
        if role is not None:
            rows = tuple(row for row in rows if row.permits(role))
        if context is not None:
            rows = tuple(row for row in rows if row.holds(context))
        return rows

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

    def __iter__(self):
        return iter(self.transitions)

    def __len__(self) -> int:
        return len(self.transitions)
