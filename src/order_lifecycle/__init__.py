"""Declarative state machine for order lifecycles."""

from .conditions import ALWAYS, Condition, ConditionResult, flag
from .errors import (
    ConditionNotMet,
    IllegalTransition,
    LifecycleError,
    RoleNotPermitted,
)
from .machine import Machine
from .roles import ANYONE, COURIER, CUSTOMER, SUPPORT, WAREHOUSE, Role
from .states import State, Trigger
from .transitions import Transition, TransitionTable

__all__ = [
    "State",
    "Trigger",
    "Role",
    "ANYONE",
    "CUSTOMER",
    "WAREHOUSE",
    "COURIER",
    "SUPPORT",
    "Condition",
    "ConditionResult",
    "ALWAYS",
    "flag",
    "Transition",
    "TransitionTable",
    "Machine",
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "ConditionNotMet",
    "__version__",
]

__version__ = "0.1.0"
