"""The runtime: apply a trigger to a state, or refuse it with a typed error."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from .errors import ConditionNotMet, HookFailed, IllegalTransition, RoleNotPermitted
from .hooks import Hook, TransitionContext
from .roles import Role
from .states import State, Trigger
from .transitions import Transition, TransitionTable

__all__ = ["Machine"]


@dataclass(frozen=True, slots=True)
class Machine:
    """A transition table paired with the state an order currently sits in."""

    table: TransitionTable
    state: State

    def allowed(
        self, *, role: Role | str | None = None, context: Any = None
    ) -> tuple[Transition, ...]:
        """Return the transitions ``role`` may take from the current state."""
        return self.table.available(self.state, role=role, context=context)

    def resolve(
        self,
        trigger: Trigger,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> Transition:
        """Return the transition ``trigger`` would take, or raise a typed error.

        The role guard and then the conditions are checked here, before the
        state moves.
        """
        transition = self.table.find(self.state, trigger)
        if transition is None:
            raise IllegalTransition(self.state, trigger, self.allowed(role=role))
        if not transition.permits(role):
            raise RoleNotPermitted(transition, role)
        unmet = transition.unmet(context)
        if unmet:
            raise ConditionNotMet(transition, unmet)
        return transition

    def can(
        self,
        trigger: Trigger,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> bool:
        """Report whether ``trigger`` would be accepted, without raising."""
        transition = self.table.find(self.state, trigger)
        return transition is not None and transition.allows(role, context)

    def apply(
        self,
        trigger: Trigger,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> Machine:
        """Return a new machine sitting in the target state of ``trigger``.

        The before hooks run once both guards have passed, the after hooks once
        the target state is settled. A hook that raises aborts the move: the
        new machine is never handed back, so the caller keeps the source state.
        """
        transition = self.resolve(trigger, role=role, context=context)
        self._fire(transition.before, "before", transition, role, context)
        moved = replace(self, state=transition.target)
        self._fire(transition.after, "after", transition, role, context)
        return moved

    def _fire(
        self,
        hooks: tuple[Hook, ...],
        phase: str,
        transition: Transition,
        role: Role | str | None,
        subject: Any,
    ) -> None:
        done: list[Hook] = []
        for hook in hooks:
            moving = TransitionContext(transition, phase, role, subject)
            try:
                hook(moving)
            except Exception as error:
                raise HookFailed(hook, moving, error, tuple(done)) from error
            done.append(hook)

    def __str__(self) -> str:
        return f"Machine(state={self.state.name})"
