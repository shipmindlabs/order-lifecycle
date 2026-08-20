"""Actors that may fire transitions: the vocabulary of a role guard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

__all__ = [
    "Role",
    "ANYONE",
    "CUSTOMER",
    "WAREHOUSE",
    "COURIER",
    "SUPPORT",
    "as_role",
    "as_roles",
]


@dataclass(frozen=True, slots=True)
class Role:
    """A named actor: whoever is asking the lifecycle to move."""

    name: str

    def __post_init__(self) -> None:
        cleaned = self.name.strip()
        if not cleaned:
            raise ValueError("role name must be a non-empty string")
        object.__setattr__(self, "name", cleaned)

    def __str__(self) -> str:
        return self.name


CUSTOMER = Role("customer")
WAREHOUSE = Role("warehouse")
COURIER = Role("courier")
SUPPORT = Role("support")

#: An empty guard: the transition is open to every actor.
ANYONE: frozenset[Role] = frozenset()


def as_role(value: Role | str) -> Role:
    """Accept a role or its name and return a :class:`Role`."""
    return value if isinstance(value, Role) else Role(value)


def as_roles(value: Role | str | Iterable[Role | str] | None) -> frozenset[Role]:
    """Accept one role, a name, or any iterable of them and return a guard."""
    if value is None:
        return ANYONE
    if isinstance(value, (Role, str)):
        return frozenset({as_role(value)})
    return frozenset(as_role(item) for item in value)
