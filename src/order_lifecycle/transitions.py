"""The transition table: the whole state machine expressed as plain data."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .states import State, Trigger

__all__ = ["Transition", "TransitionTable"]


@dataclass(frozen=True, slots=True)
class Transition:
    """A single edge: from a state, via a trigger, to another state."""

    source: State
    target: State
    trigger: Trigger
    roles: frozenset[str] = frozenset()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "roles", frozenset(self.roles))
        if self.source.terminal:
            raise ValueError(
                f"state {self.source.name!r} is terminal and cannot have outgoing transitions"
            )

    def permits(self, role: str | None) -> bool:
        # An empty role set means the transition is open to every caller.
        if not self.roles:
            return True
        return role is not None and role in self.roles

    def __str__(self) -> str:
        return f"{self.source.name} --{self.trigger.name}--> {self.target.name}"


@dataclass(frozen=True, slots=True)
class TransitionTable:
    """An immutable collection of transitions, indexed by state and trigger."""

    transitions: tuple[Transition, ...]
    _index: Mapping[tuple[str, str], Transition] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "transitions", tuple(self.transitions))
        index: dict[tuple[str, str], Transition] = {}
        for transition in self.transitions:
            key = (transition.source.name, transition.trigger.name)
            if key in index:
                raise ValueError(
                    f"duplicate transition from {key[0]!r} on trigger {key[1]!r}"
                )
            index[key] = transition
        object.__setattr__(self, "_index", MappingProxyType(index))

    def find(self, source: State, trigger: Trigger) -> Transition | None:
        """Return the transition leaving ``source`` on ``trigger``, if declared."""
        return self._index.get((source.name, trigger.name))

    def available(
        self, source: State, *, role: str | None = None
    ) -> tuple[Transition, ...]:
        """Return the transitions leaving ``source`` that ``role`` may take."""
        return tuple(
            transition
            for transition in self.transitions
            if transition.source.name == source.name and transition.permits(role)
        )

    @property
    def states(self) -> frozenset[State]:
        """Every state mentioned by the table, as source or as target."""
        return frozenset(
            state
            for transition in self.transitions
            for state in (transition.source, transition.target)
        )

    @property
    def triggers(self) -> frozenset[Trigger]:
        return frozenset(transition.trigger for transition in self.transitions)

    def __iter__(self) -> Iterator[Transition]:
        return iter(self.transitions)

    def __len__(self) -> int:
        return len(self.transitions)
