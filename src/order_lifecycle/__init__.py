"""Declarative state machine for order lifecycles."""

from .errors import IllegalTransition, LifecycleError, RoleNotPermitted
from .machine import Machine
from .states import State, Trigger
from .transitions import Transition, TransitionTable

__all__ = [
    "State",
    "Trigger",
    "Transition",
    "TransitionTable",
    "Machine",
    "LifecycleError",
    "IllegalTransition",
    "RoleNotPermitted",
    "__version__",
]

__version__ = "0.1.0"
