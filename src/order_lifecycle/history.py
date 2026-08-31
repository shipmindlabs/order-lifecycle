"""An append-only record of the moves an order has already made."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Iterator

from .roles import Role, as_role
from .states import State, Trigger

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .transitions import Transition

__all__ = ["Entry", "History", "EMPTY_HISTORY"]


def _now() -> datetime:
    """Return the moment a move is recorded at, in UTC."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Entry:
    """One move that already happened: what changed, when, by whom and why."""

    source: State
    target: State
    trigger: Trigger
    role: Role | None = None
    reason: str = ""
    at: datetime = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.role is not None:
            object.__setattr__(self, "role", as_role(self.role))
        object.__setattr__(self, "reason", self.reason.strip())

    @classmethod
    def of(
        cls,
        transition: "Transition",
        *,
        role: Role | str | None = None,
        reason: str = "",
        at: datetime | None = None,
    ) -> "Entry":
        """Build the entry a completed ``transition`` leaves behind."""
        return cls(
            transition.source,
            transition.target,
            transition.trigger,
            None if role is None else as_role(role),
            reason,
            at if at is not None else _now(),
        )

    @property
    def actor(self) -> str:
        """Return the name of the acting role, or ``'anyone'`` when open."""
        return self.role.name if self.role is not None else "anyone"

    def __str__(self) -> str:
        line = (
            f"{self.at.isoformat(timespec='seconds')} "
            f"{self.source.name} --{self.trigger.name}--> {self.target.name} "
            f"by {self.actor}"
        )
        return f"{line}: {self.reason}" if self.reason else line


@dataclass(frozen=True, slots=True)
class History:
    """Every recorded move of an order, oldest first and only ever appended."""

    entries: tuple[Entry, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))

    def record(self, entry: Entry) -> "History":
        """Return a new history with ``entry`` appended to this one."""
        return History(self.entries + (entry,))

    def log(
        self,
        transition: "Transition",
        *,
        role: Role | str | None = None,
        reason: str = "",
        at: datetime | None = None,
    ) -> "History":
        """Return a new history with a completed ``transition`` appended."""
        return self.record(Entry.of(transition, role=role, reason=reason, at=at))

    @property
    def first(self) -> Entry | None:
        """Return the oldest recorded move, if the order ever moved."""
        return self.entries[0] if self.entries else None

    @property
    def last(self) -> Entry | None:
        """Return the most recent recorded move, if the order ever moved."""
        return self.entries[-1] if self.entries else None

    @property
    def states(self) -> tuple[State, ...]:
        """Return the path the order walked, starting from where it began."""
        if not self.entries:
            return ()
        return (self.entries[0].source,) + tuple(e.target for e in self.entries)

    @property
    def roles(self) -> frozenset[Role]:
        """Return every actor that moved the order."""
        return frozenset(e.role for e in self.entries if e.role is not None)

    def by_role(self, role: Role | str) -> tuple[Entry, ...]:
        """Return the moves ``role`` is recorded as having made."""
        name = as_role(role).name
        return tuple(
            e for e in self.entries if e.role is not None and e.role.name == name
        )

    def for_trigger(self, trigger: Trigger) -> tuple[Entry, ...]:
        """Return the moves ``trigger`` is recorded as having caused."""
        return tuple(e for e in self.entries if e.trigger == trigger)

    def since(self, moment: datetime) -> tuple[Entry, ...]:
        """Return the moves recorded at or after ``moment``."""
        return tuple(e for e in self.entries if e.at >= moment)

    def timeline(self) -> str:
        """Render the history as one readable line per move."""
        return "\n".join(str(entry) for entry in self.entries)

    def __iter__(self) -> Iterator[Entry]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def __getitem__(self, index: int) -> Entry:
        return self.entries[index]

    def __str__(self) -> str:
        return self.timeline() or "(no transitions yet)"


#: A fresh record: the order has not moved yet.
EMPTY_HISTORY: History = History()


def _as_history(entries: Iterable[Entry] | History | None) -> History:
    """Accept a history or any iterable of entries and return a history."""
    if entries is None:
        return EMPTY_HISTORY
    if isinstance(entries, History):
        return entries
    return History(tuple(entries))
