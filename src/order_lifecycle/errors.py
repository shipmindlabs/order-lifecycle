"""Typed errors raised when a lifecycle refuses a trigger."""

from __future__ import annotations

from typing import Iterable

from .conditions import Condition, ConditionResult
from .roles import Role
from .states import State, Trigger
from .transitions import Transition

__all__ = [
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "ConditionNotMet",
]


class LifecycleError(Exception):
    """Base class for every error raised by this package."""


class IllegalTransition(LifecycleError):
    """No transition leaves the current state on the given trigger."""

    def __init__(
        self,
        state: State,
        trigger: Trigger,
        allowed: tuple[Transition, ...] = (),
    ) -> None:
        self.state = state
        self.trigger = trigger
        self.allowed = tuple(allowed)
        super().__init__(
            f"cannot apply trigger {trigger.name!r} in state {state.name!r}: "
            f"{self._offer()}"
        )

    def _offer(self) -> str:
        if self.allowed:
            names = ", ".join(sorted(t.trigger.name for t in self.allowed))
            return f"allowed here: {names}"
        if self.state.terminal:
            return f"{self.state.name!r} is a terminal state"
        return "nothing is allowed here"


class RoleNotPermitted(LifecycleError):
    """The transition exists, but the acting role may not take it."""

    def __init__(self, transition: Transition, role: Role | str | None) -> None:
        self.transition = transition
        self.role = role
        self.required_roles = transition.roles
        required = ", ".join(sorted(r.name for r in transition.roles))
        actor = (
            "no role was supplied"
            if role is None
            else f"role {str(role)!r} is not one of them"
        )
        super().__init__(
            f"trigger {transition.trigger.name!r} in state "
            f"{transition.source.name!r} requires one of: {required}; {actor}"
        )


class ConditionNotMet(LifecycleError):
    """The role may take the transition, but the order is not ready for it."""

    def __init__(
        self, transition: Transition, failures: Iterable[ConditionResult]
    ) -> None:
        self.transition = transition
        self.failures = tuple(failures)
        reasons = "; ".join(
            failure.detail or f"{failure.condition.name} does not hold"
            for failure in self.failures
        )
        super().__init__(
            f"trigger {transition.trigger.name!r} in state "
            f"{transition.source.name!r} requires: {reasons}"
        )

    @property
    def unmet(self) -> tuple[Condition, ...]:
        """Return the conditions that refused, in declaration order."""
        return tuple(failure.condition for failure in self.failures)
