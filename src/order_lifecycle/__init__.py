"""Declarative state machine for order lifecycles."""

from .cancellation import (
    CHANGED_MIND,
    DAMAGED,
    DUPLICATE,
    NO_REASONS,
    OUT_OF_STOCK,
    PAYMENT_FAILED,
    UNDELIVERABLE,
    CancellationPath,
    CancellationPolicy,
    CancellationReason,
)
from .conditions import ALWAYS, Condition, ConditionResult, flag
from .errors import (
    CannotCancel,
    ConditionNotMet,
    HookFailed,
    IllegalTransition,
    LifecycleError,
    ReasonNotAccepted,
    RoleNotPermitted,
)
from .history import EMPTY_HISTORY, Entry, History
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
    "Entry",
    "History",
    "EMPTY_HISTORY",
    "Transition",
    "TransitionTable",
    "Machine",
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
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "ConditionNotMet",
    "HookFailed",
    "CannotCancel",
    "ReasonNotAccepted",
    "__version__",
]

__version__ = "0.1.0"
