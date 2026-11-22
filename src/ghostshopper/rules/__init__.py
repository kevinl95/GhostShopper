"""Order rules and state machine. Plain Python; imports only `ghostshopper.common`."""

from ghostshopper.rules.decisions import (
    Accept,
    Allow,
    Fail,
    Ignore,
    NeedSubstitute,
    RequestApproval,
    decide_press,
    decide_quote,
    decide_spend,
    decide_substitute,
)
from ghostshopper.rules.state_machine import (
    ALLOWED,
    IN_FLIGHT,
    TERMINAL,
    IllegalTransition,
    State,
    apply,
)

__all__ = [
    "ALLOWED",
    "IN_FLIGHT",
    "TERMINAL",
    "Accept",
    "Allow",
    "Fail",
    "IllegalTransition",
    "Ignore",
    "NeedSubstitute",
    "RequestApproval",
    "State",
    "apply",
    "decide_press",
    "decide_quote",
    "decide_spend",
    "decide_substitute",
]
