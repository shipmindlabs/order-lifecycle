"""Value types describing the vocabulary of a lifecycle: states and triggers."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["State", "Trigger"]


@dataclass(frozen=True, slots=True)
class State:
    """A named position in an order lifecycle."""

    name: str
    terminal: bool = False

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("state name must be a non-empty string")

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Trigger:
    """A named event that may move an order from one state to another."""

    name: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("trigger name must be a non-empty string")

    def __str__(self) -> str:
        return self.name
