"""The runtime: apply a trigger to a state, or refuse it with a typed error."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .errors import IllegalTransition, RoleNotPermitted
from .states import State, Trigger
from .transitions import Transition, TransitionTable

__all__ = ["Machine"]


@dataclass(frozen=True, slots=True)
class Machine:
    """A transition table paired with the state an order currently sits in."""

    table: TransitionTable
    state: State

    def allowed(self, *, role: str | None = None) -> tuple[Transition, ...]:
        """Return the transitions ``role`` may take from the current state."""
        return self.table.available(self.state, role=role)

    def resolve(self, trigger: Trigger, *, role: str | None = None) -> Transition:
        """Return the transition ``trigger`` would take, or raise a typed error."""
        transition = self.table.find(self.state, trigger)
        if transition is None:
            raise IllegalTransition(self.state, trigger, self.allowed(role=role))
        if not transition.permits(role):
            raise RoleNotPermitted(transition, role)
        return transition

    def can(self, trigger: Trigger, *, role: str | None = None) -> bool:
        """Report whether ``trigger`` would be accepted, without raising."""
        transition = self.table.find(self.state, trigger)
        return transition is not None and transition.permits(role)

    def apply(self, trigger: Trigger, *, role: str | None = None) -> Machine:
        """Return a new machine sitting in the target state of ``trigger``."""
        transition = self.resolve(trigger, role=role)
        return replace(self, state=transition.target)

    def __str__(self) -> str:
        return f"Machine(state={self.state.name})"
