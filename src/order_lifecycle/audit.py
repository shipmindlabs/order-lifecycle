"""Reading a declared table before anything runs: reachability and dead ends."""

from __future__ import annotations

from dataclasses import dataclass

from .states import State

__all__ = ["Audit"]


@dataclass(frozen=True, slots=True)
class Audit:
    """What a reading of a table found: where an order can go, and get stuck."""

    start: State
    reachable: tuple[State, ...] = ()
    unreachable: tuple[State, ...] = ()
    dead_ends: tuple[State, ...] = ()

    @property
    def ok(self) -> bool:
        """Report whether every state is reached and every state leads on."""
        return not self.unreachable and not self.dead_ends

    @property
    def problems(self) -> tuple[str, ...]:
        """Return one sentence per state the table never reaches or traps."""
        return tuple(
            f"{state.name} is never reached from {self.start.name}"
            for state in self.unreachable
        ) + tuple(
            f"{state.name} is not terminal and nothing leaves it"
            for state in self.dead_ends
        )

    def __bool__(self) -> bool:
        return self.ok

    def __str__(self) -> str:
        if self.ok:
            return (
                f"{len(self.reachable)} states reachable from "
                f"{self.start.name}, none of them a dead end"
            )
        return "\n".join(self.problems)
