"""Callbacks fired around a transition, and the context they are handed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Iterable

from .roles import Role
from .states import State, Trigger

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .transitions import Transition

__all__ = [
    "Hook",
    "TransitionContext",
    "NO_HOOKS",
    "as_hook",
    "as_hooks",
]


@dataclass(frozen=True, slots=True)
class TransitionContext:
    """Everything a hook is told about the move it is wrapped around."""

    transition: "Transition"
    phase: str
    role: Role | str | None = None
    subject: Any = None

    @property
    def source(self) -> State:
        """Return the state the order is leaving."""
        return self.transition.source

    @property
    def target(self) -> State:
        """Return the state the order is heading for."""
        return self.transition.target

    @property
    def trigger(self) -> Trigger:
        """Return the trigger that asked for the move."""
        return self.transition.trigger

    def __str__(self) -> str:
        return f"{self.phase} {self.transition}"


@dataclass(frozen=True, slots=True)
class Hook:
    """A named callback invoked with the context of a single move."""

    name: str
    callback: Callable[[TransitionContext], Any]

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not cleaned:
            raise ValueError("hook name must be a non-empty string")
        if not callable(self.callback):
            raise TypeError("hook callback must be callable")
        object.__setattr__(self, "name", cleaned)

    def __call__(self, context: TransitionContext) -> Any:
        return self.callback(context)

    def __str__(self) -> str:
        return self.name


#: An empty phase: nothing runs around the transition.
NO_HOOKS: tuple[Hook, ...] = ()


def as_hook(value: Hook | Callable[[TransitionContext], Any]) -> Hook:
    """Accept a hook or a bare callable and return a :class:`Hook`."""
    if isinstance(value, Hook):
        return value
    if not callable(value):
        raise TypeError("a hook must be a Hook or a callable")
    name = getattr(value, "__name__", "").replace("_", " ").strip() or "hook"
    return Hook(name, value)


def as_hooks(
    value: Hook
    | Callable[[TransitionContext], Any]
    | Iterable[Hook | Callable[[TransitionContext], Any]]
    | None,
) -> tuple[Hook, ...]:
    """Accept one hook, a callable, or any iterable of them, in order."""
    if value is None:
        return NO_HOOKS
    if isinstance(value, Hook) or callable(value):
        return (as_hook(value),)
    return tuple(as_hook(item) for item in value)
