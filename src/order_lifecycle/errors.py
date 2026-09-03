"""Typed errors raised when a lifecycle refuses a trigger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable

from .conditions import Condition, ConditionResult
from .hooks import Hook, TransitionContext
from .roles import Role
from .states import State, Trigger
from .transitions import Transition

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .cancellation import CancellationPath, CancellationReason

__all__ = [
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "ConditionNotMet",
    "HookFailed",
    "CannotCancel",
    "ReasonNotAccepted",
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


class HookFailed(LifecycleError):
    """A callback around the transition raised, so the move was abandoned."""

    def __init__(
        self,
        hook: Hook,
        context: TransitionContext,
        cause: BaseException,
        completed: Iterable[Hook] = (),
    ) -> None:
        self.hook = hook
        self.context = context
        self.cause = cause
        self.completed = tuple(completed)
        self.phase = context.phase
        self.transition = context.transition
        transition = context.transition
        super().__init__(
            f"{context.phase} hook {hook.name!r} failed for trigger "
            f"{transition.trigger.name!r} in state {transition.source.name!r}: "
            f"{type(cause).__name__}: {cause}; the order stays in "
            f"{transition.source.name!r}"
        )


class CannotCancel(LifecycleError):
    """No cancellation path leaves the current state for this actor."""

    def __init__(
        self,
        state: State,
        role: Role | str | None = None,
        actors: Iterable[Role] = (),
    ) -> None:
        self.state = state
        self.role = role
        self.actors = frozenset(actors)
        who = f"role {str(role)!r}" if role is not None else "a caller without a role"
        if self.actors:
            names = ", ".join(sorted(r.name for r in self.actors))
            offer = f"here only {names} may cancel"
        else:
            offer = f"no cancellation path leaves {state.name!r}"
        super().__init__(f"{who} cannot cancel an order in state {state.name!r}: {offer}")


class ReasonNotAccepted(LifecycleError):
    """The path offers a closed list of reasons, and this is not one of them."""

    def __init__(
        self,
        path: "CancellationPath",
        reason: "CancellationReason | str | None",
        accepted: Iterable["CancellationReason"] = (),
    ) -> None:
        self.path = path
        self.reason = reason
        self.accepted = tuple(accepted)
        codes = ", ".join(item.code for item in self.accepted)
        given = (
            "no reason was given"
            if reason is None
            else f"reason {str(getattr(reason, 'code', reason))!r} is not one of them"
        )
        super().__init__(
            f"cancelling {path.source.name!r} with trigger {path.trigger.name!r} "
            f"requires one of: {codes}; {given}"
        )
