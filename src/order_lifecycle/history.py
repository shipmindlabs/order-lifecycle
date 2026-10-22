"""An append-only record of the moves an order has already made."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping

from .roles import Role, as_role
from .states import State, Trigger

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from .transitions import Transition, TransitionTable

__all__ = ["Entry", "History", "EMPTY_HISTORY"]


def _now() -> datetime:
    """Return the moment a move is recorded at, in UTC."""
    return datetime.now(timezone.utc)


def _as_moment(value: str | datetime | None) -> datetime:
    """Accept a stored timestamp, as text or already parsed by the driver."""
    if isinstance(value, datetime):
        return value
    if value:
        return datetime.fromisoformat(value)
    return _now()


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

    def as_dict(self) -> dict[str, Any]:
        """Return this move as plain data: names, a sentence and a timestamp."""
        return {
            "source": self.source.name,
            "target": self.target.name,
            "trigger": self.trigger.name,
            "role": None if self.role is None else self.role.name,
            "reason": self.reason,
            "at": self.at.isoformat(),
        }

    @classmethod
    def from_dict(
        cls,
        table: "TransitionTable",
        row: Mapping[str, Any],
        *,
        field: str = "entry",
    ) -> "Entry":
        """Rebuild a move from ``row``, resolving its names in ``table``."""
        return cls(
            table.state(row["source"], field=f"{field}.source"),
            table.state(row["target"], field=f"{field}.target"),
            table.trigger(row["trigger"], field=f"{field}.trigger"),
            row.get("role"),
            row.get("reason", ""),
            _as_moment(row.get("at")),
        )

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

    def as_dicts(self) -> tuple[dict[str, Any], ...]:
        """Return every recorded move as plain data, oldest first."""
        return tuple(entry.as_dict() for entry in self.entries)

    @classmethod
    def from_dicts(
        cls,
        table: "TransitionTable",
        rows: Iterable[Mapping[str, Any]],
        *,
        field: str = "history",
    ) -> "History":
        """Rebuild a history from ``rows``, resolving their names in ``table``.

        A name the table does not declare is refused with the index of the row
        carrying it, so a stored history says which move no longer reads.
        """
        return cls(
            tuple(
                Entry.from_dict(table, row, field=f"{field}[{position}]")
                for position, row in enumerate(rows)
            )
        )

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
