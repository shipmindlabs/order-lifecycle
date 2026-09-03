"""Cancellation as data: who may cancel, from where, why and what follows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Iterable

from .conditions import ALWAYS, Condition, as_conditions
from .errors import CannotCancel, ReasonNotAccepted
from .hooks import NO_HOOKS, Hook, as_hooks
from .roles import ANYONE, Role, as_roles
from .states import State, Trigger
from .transitions import Transition, TransitionTable

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .machine import Machine

__all__ = [
    "CancellationReason",
    "CancellationPath",
    "CancellationPolicy",
    "NO_REASONS",
    "CHANGED_MIND",
    "DUPLICATE",
    "PAYMENT_FAILED",
    "OUT_OF_STOCK",
    "DAMAGED",
    "UNDELIVERABLE",
    "as_reason",
    "as_reasons",
]


@dataclass(frozen=True, slots=True)
class CancellationReason:
    """Why an order was cancelled, in the words the actor was offered."""

    code: str
    detail: str = ""

    def __post_init__(self) -> None:
        cleaned = self.code.strip()
        if not cleaned:
            raise ValueError("cancellation reason code must be a non-empty string")
        object.__setattr__(self, "code", cleaned)

    @property
    def sentence(self) -> str:
        """Return the phrase a history entry should quote."""
        return self.detail or self.code.replace("_", " ")

    def __str__(self) -> str:
        return self.sentence


CHANGED_MIND = CancellationReason(
    "changed_mind", "the customer no longer wants the order"
)
DUPLICATE = CancellationReason("duplicate", "the order duplicates another one")
PAYMENT_FAILED = CancellationReason(
    "payment_failed", "the payment could not be captured"
)
OUT_OF_STOCK = CancellationReason("out_of_stock", "the goods are not in the warehouse")
DAMAGED = CancellationReason("damaged", "the goods were damaged before hand-over")
UNDELIVERABLE = CancellationReason(
    "undeliverable", "the courier could not hand the order over"
)

#: An open vocabulary: the path records whatever sentence the caller supplies.
NO_REASONS: tuple[CancellationReason, ...] = ()


def as_reason(value: CancellationReason | str) -> CancellationReason:
    """Accept a reason or its code and return a :class:`CancellationReason`."""
    return value if isinstance(value, CancellationReason) else CancellationReason(value)


def as_reasons(
    value: CancellationReason | str | Iterable[CancellationReason | str] | None,
) -> tuple[CancellationReason, ...]:
    """Accept one reason, a code, or any iterable of them, in order."""
    if value is None:
        return NO_REASONS
    if isinstance(value, (CancellationReason, str)):
        return (as_reason(value),)
    return tuple(as_reason(item) for item in value)


@dataclass(frozen=True, slots=True)
class CancellationPath:
    """One way out of a lifecycle: an actor, a state, a reason and what follows."""

    source: State
    target: State
    trigger: Trigger
    roles: frozenset[Role] = ANYONE
    reasons: tuple[CancellationReason, ...] = NO_REASONS
    conditions: tuple[Condition, ...] = ALWAYS
    before: tuple[Hook, ...] = NO_HOOKS
    follow_up: tuple[Hook, ...] = NO_HOOKS

    def __post_init__(self) -> None:
        if self.source.terminal:
            raise ValueError(
                f"state {self.source.name!r} is terminal; "
                "an order can no longer be cancelled from it"
            )
        object.__setattr__(self, "roles", as_roles(self.roles))
        object.__setattr__(self, "reasons", as_reasons(self.reasons))
        object.__setattr__(self, "conditions", as_conditions(self.conditions))
        object.__setattr__(self, "before", as_hooks(self.before))
        object.__setattr__(self, "follow_up", as_hooks(self.follow_up))

    @property
    def transition(self) -> Transition:
        """Return this path as an ordinary row of a transition table."""
        return Transition(
            self.source,
            self.target,
            self.trigger,
            roles=self.roles,
            conditions=self.conditions,
            before=self.before,
            after=self.follow_up,
        )

    @property
    def codes(self) -> tuple[str, ...]:
        """Return the reason codes this path offers, in declaration order."""
        return tuple(reason.code for reason in self.reasons)

    @property
    def outcome(self) -> str:
        """Return a readable summary of what follows this cancellation."""
        if not self.follow_up:
            return "nothing follows"
        return ", ".join(hook.name for hook in self.follow_up)

    def permits(self, role: Role | str | None) -> bool:
        """Report whether ``role`` may take this path."""
        return self.transition.permits(role)

    def find(self, reason: CancellationReason | str | None) -> CancellationReason | None:
        """Return the declared reason matching ``reason`` by code, if any."""
        if reason is None:
            return None
        code = (
            reason.code
            if isinstance(reason, CancellationReason)
            else str(reason).strip()
        )
        for candidate in self.reasons:
            if candidate.code == code:
                return candidate
        return None

    def accepts(self, reason: CancellationReason | str | None) -> bool:
        """Report whether ``reason`` is one this path may be cancelled with."""
        if not self.reasons:
            return True
        return self.find(reason) is not None

    def accept(self, reason: CancellationReason | str | None = None) -> str:
        """Return the sentence to record, or refuse ``reason``.

        A path that declares reasons takes only those, and demands one; a path
        that declares none records whatever the caller wrote.
        """
        if not self.reasons:
            return "" if reason is None else str(reason)
        found = self.find(reason)
        if found is None:
            raise ReasonNotAccepted(self, reason, self.reasons)
        return found.sentence

    def __str__(self) -> str:
        line = str(self.transition)
        if self.reasons:
            line = f"{line} ({', '.join(self.codes)})"
        if self.follow_up:
            line = f"{line} -> {self.outcome}"
        return line


@dataclass(frozen=True, slots=True)
class CancellationPolicy:
    """Every way an order may be cancelled, and by whom."""

    paths: tuple[CancellationPath, ...] = ()

    def __post_init__(self) -> None:
        rows = tuple(self.paths)
        seen: set[tuple[State, Trigger]] = set()
        for path in rows:
            key = (path.source, path.trigger)
            if key in seen:
                raise ValueError(
                    f"duplicate cancellation path for state {path.source.name!r} "
                    f"and trigger {path.trigger.name!r}; give each actor its own "
                    "trigger"
                )
            seen.add(key)
        object.__setattr__(self, "paths", rows)

    @property
    def transitions(self) -> tuple[Transition, ...]:
        """Return every path as an ordinary transition, in declaration order."""
        return tuple(path.transition for path in self.paths)

    @property
    def reasons(self) -> tuple[CancellationReason, ...]:
        """Return every reason this policy offers, without repetition."""
        seen: dict[CancellationReason, None] = {}
        for path in self.paths:
            for reason in path.reasons:
                seen.setdefault(reason, None)
        return tuple(seen)

    def extend(self, table: TransitionTable) -> TransitionTable:
        """Return ``table`` with the cancellation rows appended to it."""
        return TransitionTable(table.transitions + self.transitions)

    def available(
        self,
        state: State,
        *,
        role: Role | str | None = None,
        context: Any = None,
    ) -> tuple[CancellationPath, ...]:
        """Return the paths leaving ``state``, narrowed by role and context."""
        rows = tuple(path for path in self.paths if path.source == state)
        if role is not None:
            rows = tuple(path for path in rows if path.permits(role))
        if context is not None:
            rows = tuple(path for path in rows if path.transition.holds(context))
        return rows

    def actors(self, state: State) -> frozenset[Role]:
        """Return every actor a path leaving ``state`` names."""
        return frozenset(
            role for path in self.paths if path.source == state for role in path.roles
        )

    def reasons_for(
        self, state: State, *, role: Role | str | None = None
    ) -> tuple[CancellationReason, ...]:
        """Return the reasons ``role`` may cancel an order in ``state`` with."""
        seen: dict[CancellationReason, None] = {}
        for path in self.available(state, role=role):
            for reason in path.reasons:
                seen.setdefault(reason, None)
        return tuple(seen)

    def resolve(
        self,
        state: State,
        *,
        role: Role | str | None = None,
        trigger: Trigger | None = None,
    ) -> CancellationPath:
        """Return the path ``role`` would take out of ``state``, or refuse.

        When an actor has several ways out, the first declared one wins; pass
        ``trigger`` to name another.
        """
        for path in self.paths:
            if path.source != state:
                continue
            if trigger is not None and path.trigger != trigger:
                continue
            if path.permits(role):
                return path
        raise CannotCancel(state, role, self.actors(state))

    def cancel(
        self,
        machine: "Machine",
        *,
        role: Role | str | None = None,
        reason: CancellationReason | str | None = None,
        trigger: Trigger | None = None,
        context: Any = None,
        at: datetime | None = None,
    ) -> "Machine":
        """Return a new machine cancelled along the path ``role`` may take.

        The move itself goes through the machine, so role guards, conditions,
        hooks and history behave exactly as they do for any other trigger.
        """
        path = self.resolve(machine.state, role=role, trigger=trigger)
        recorded = path.accept(reason)
        return machine.apply(
            path.trigger, role=role, context=context, reason=recorded, at=at
        )

    def __iter__(self):
        return iter(self.paths)

    def __len__(self) -> int:
        return len(self.paths)

    def __str__(self) -> str:
        return "\n".join(str(path) for path in self.paths)
