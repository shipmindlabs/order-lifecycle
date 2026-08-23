"""Predicates that must hold before a transition may fire."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

__all__ = [
    "Condition",
    "ConditionResult",
    "ALWAYS",
    "as_conditions",
    "evaluate",
    "flag",
]


@dataclass(frozen=True, slots=True)
class ConditionResult:
    """The outcome of checking one condition against a context."""

    condition: "Condition"
    ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return f"{self.condition.name}: holds"
        return f"{self.condition.name}: {self.detail or 'does not hold'}"


@dataclass(frozen=True, slots=True)
class Condition:
    """A named predicate over an order, carrying the reason it may refuse."""

    name: str
    predicate: Callable[[Any], bool]
    requires: str = ""

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not cleaned:
            raise ValueError("condition name must be a non-empty string")
        if not callable(self.predicate):
            raise TypeError("condition predicate must be callable")
        object.__setattr__(self, "name", cleaned)

    @property
    def explanation(self) -> str:
        """Return the sentence a refusal should quote."""
        return self.requires or f"{self.name} must hold"

    def holds(self, context: Any = None) -> bool:
        """Report whether the predicate accepts ``context``."""
        return bool(self.predicate(context))

    def check(self, context: Any = None) -> ConditionResult:
        """Check ``context`` and return a result that explains a failure."""
        ok = self.holds(context)
        return ConditionResult(self, ok, "" if ok else self.explanation)

    def __str__(self) -> str:
        return self.name


#: An empty guard: the transition depends on nothing but its role.
ALWAYS: tuple[Condition, ...] = ()


def as_conditions(
    value: Condition | Iterable[Condition] | None,
) -> tuple[Condition, ...]:
    """Accept one condition or any iterable of them and return a guard."""
    if value is None:
        return ALWAYS
    if isinstance(value, Condition):
        return (value,)
    return tuple(value)


def evaluate(
    conditions: Iterable[Condition], context: Any = None
) -> tuple[ConditionResult, ...]:
    """Check every condition against ``context`` and return all results."""
    return tuple(condition.check(context) for condition in conditions)


def flag(
    key: str, *, name: str | None = None, requires: str | None = None
) -> Condition:
    """Build a condition demanding that ``key`` is truthy on the context.

    The context may be a mapping or any object carrying ``key`` as an attribute.
    """
    label = name or key.replace("_", " ")
    reason = requires or f"{key} must be set on the order"
    return Condition(label, lambda context: bool(_lookup(context, key)), reason)


def _lookup(context: Any, key: str) -> Any:
    if isinstance(context, Mapping):
        return context.get(key)
    return getattr(context, key, None)
