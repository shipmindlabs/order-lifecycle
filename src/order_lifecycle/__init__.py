"""Declarative state machine for order lifecycles."""

from .conditions import ALWAYS, Condition, ConditionResult, flag
from .errors import (
    ConditionNotMet,
    HookFailed,
    IllegalTransition,
    LifecycleError,
    RoleNotPermitted,
)
from .hooks import NO_HOOKS, Hook, TransitionContext
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
    "Hook",
    "TransitionContext",
    "NO_HOOKS",
    "Transition",
    "TransitionTable",
    "Machine",
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "ConditionNotMet",
    "HookFailed",
    "__version__",
]

__version__ = "0.1.0"
