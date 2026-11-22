"""Order state machine (Requirement 10)."""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    PRESSED = "pressed"
    QUOTED = "quoted"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    ORDERING = "ordering"
    PLACED = "placed"
    DENIED = "denied"
    EXPIRED = "expired"
    FAILED = "failed"

    def __str__(self) -> str:
        return self.value


S = State

ALLOWED: frozenset[tuple[State, State]] = frozenset(
    {
        (S.PRESSED, S.QUOTED),
        (S.PRESSED, S.FAILED),
        (S.QUOTED, S.AWAITING_APPROVAL),
        (S.QUOTED, S.FAILED),
        (S.AWAITING_APPROVAL, S.APPROVED),
        (S.AWAITING_APPROVAL, S.DENIED),
        (S.AWAITING_APPROVAL, S.EXPIRED),
        (S.APPROVED, S.ORDERING),
        (S.APPROVED, S.FAILED),
        (S.ORDERING, S.PLACED),
        (S.ORDERING, S.FAILED),
    }
)

TERMINAL: frozenset[State] = frozenset({S.PLACED, S.DENIED, S.EXPIRED, S.FAILED})
IN_FLIGHT: frozenset[State] = frozenset(State) - TERMINAL


class IllegalTransition(Exception):
    def __init__(self, current: State, target: State) -> None:
        self.current = current
        self.target = target
        super().__init__(f"illegal transition {current.value} -> {target.value}")


def apply(current: State | str, target: State | str) -> State:
    """Return `target` if the pair is allowed, else raise IllegalTransition."""
    cur, tgt = State(current), State(target)
    if (cur, tgt) not in ALLOWED:
        raise IllegalTransition(cur, tgt)
    return tgt
