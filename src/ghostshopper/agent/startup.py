"""Startup: environment checks and restart recovery (Requirements 8.8, 10.5, 10.6)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ghostshopper.agent.store import Order, Store
from ghostshopper.rules import State

log = logging.getLogger(__name__)

NTFY_TOKEN_VAR = "NTFY_ACCESS_TOKEN"

# Orders found in these states at startup cannot continue: the in-memory task that drove them
# is gone. `ordering` is special because a purchase may or may not have happened.
INTERRUPTED_STATES = frozenset({State.PRESSED, State.QUOTED, State.APPROVED, State.ORDERING})


class StartupError(SystemExit):
    """Exit with a message (non-zero status)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def require_env(environ: Mapping[str, str]) -> str:
    """Return the ntfy access token, or exit naming the variable."""
    token = environ.get(NTFY_TOKEN_VAR, "").strip()
    if not token:
        raise StartupError(f"{NTFY_TOKEN_VAR} is not set. Put it in /etc/ghostshopper/env.")
    return token


@dataclass(frozen=True)
class Interrupted:
    order: Order  # now failed/interrupted
    was: State  # state found at startup

    @property
    def outcome_unknown(self) -> bool:
        """True if a purchase may have been placed (Requirement 10.5)."""
        return self.was is State.ORDERING


@dataclass(frozen=True)
class Recovery:
    failed: list[Interrupted]
    kept_awaiting: list[Order]  # still awaiting_approval with their original expiry


def recover(store: Store, notify: Callable[[Interrupted], object] | None = None) -> Recovery:
    """Fail interrupted Orders; keep `awaiting_approval` Orders and their tokens untouched.

    `notify` is called once per failed Order (after its transition). A failed notification
    is logged and does not undo the transition.
    """
    failed: list[Interrupted] = []
    for order in store.orders_in(INTERRUPTED_STATES):
        if store.transition(order.id, State.FAILED, "interrupted"):
            updated = store.get_order(order.id)
            assert updated is not None
            failed.append(Interrupted(updated, order.state))
            log.warning(
                "order %s was %s at startup; marked failed/interrupted", order.id, order.state.value
            )
    for item in failed:
        if notify is not None:
            try:
                notify(item)
            except Exception:
                log.exception("restart notification failed for order %s", item.order.id)
    kept = store.orders_in({State.AWAITING_APPROVAL})
    return Recovery(failed=failed, kept_awaiting=kept)
