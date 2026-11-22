"""Approval tokens (Requirement 7).

A token is `secrets.token_urlsafe(32)` (256 bits). Only its SHA-256 hash is stored. It expires
10 minutes after creation and is accepted for exactly one reply. Accepting a reply and the
Order transition happen in one transaction.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from ghostshopper.agent.store import Store, ts
from ghostshopper.rules import State

log = logging.getLogger(__name__)

APPROVAL_TTL = timedelta(minutes=10)
SWEEP_INTERVAL = 5.0

RejectReason = Literal[
    "unknown", "used", "expired", "order_mismatch", "bad_decision", "order_not_awaiting"
]


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Reply:
    """A parsed reply. `decision` is kept raw so a bad value can be rejected and logged."""

    order_id: str
    token: str
    decision: str


@dataclass(frozen=True)
class Accepted:
    order_id: str
    decision: Literal["approve", "deny"]


@dataclass(frozen=True)
class Rejected:
    order_id: str
    reason: RejectReason


ReplyOutcome = Accepted | Rejected


class Approvals:
    def __init__(self, store: Store) -> None:
        self.store = store

    def request_approval(self, order_id: str) -> str | None:
        """Create a token and move the Order `quoted -> awaiting_approval` in one transaction.

        Returns the raw token (for the notification only) or None if the transition is illegal.
        """
        token = secrets.token_urlsafe(32)
        now = self.store.clock.now()
        with self.store.tx() as c:
            if not self.store.transition_in_tx(c, order_id, State.AWAITING_APPROVAL, None, {}):
                return None
            c.execute(
                "INSERT INTO approvals(token_hash, order_id, created_at, expires_at)"
                " VALUES (?,?,?,?)",
                (hash_token(token), order_id, ts(now), ts(now + APPROVAL_TTL)),
            )
        return token

    def expires_at(self, order_id: str) -> datetime | None:
        return self.store.approval_expiry(order_id)

    def handle_reply(self, reply: Reply) -> ReplyOutcome:
        outcome = self._handle(reply)
        if isinstance(outcome, Rejected):
            # Never log the token itself.
            log.warning("ignored reply for order %s: %s", outcome.order_id, outcome.reason)
        else:
            log.info("accepted %s for order %s", outcome.decision, outcome.order_id)
        return outcome

    def _handle(self, reply: Reply) -> ReplyOutcome:
        now = self.store.clock.now()
        with self.store.tx() as c:
            row = c.execute(
                "SELECT order_id, expires_at, used_at FROM approvals WHERE token_hash = ?",
                (hash_token(reply.token),),
            ).fetchone()
            if row is None:
                return Rejected(reply.order_id, "unknown")
            if row["order_id"] != reply.order_id:
                return Rejected(reply.order_id, "order_mismatch")
            if row["used_at"] is not None:
                return Rejected(reply.order_id, "used")
            if now >= datetime.fromisoformat(row["expires_at"]):
                return Rejected(reply.order_id, "expired")
            if reply.decision not in ("approve", "deny"):
                return Rejected(reply.order_id, "bad_decision")
            target, reason = (
                (State.APPROVED, None)
                if reply.decision == "approve"
                else (State.DENIED, "user_denied")
            )
            if not self.store.transition_in_tx(c, reply.order_id, target, reason, {}):
                return Rejected(reply.order_id, "order_not_awaiting")
            c.execute(
                "UPDATE approvals SET used_at = ? WHERE token_hash = ?",
                (ts(now), hash_token(reply.token)),
            )
            return Accepted(reply.order_id, reply.decision)  # type: ignore[arg-type]

    def sweep(self) -> list[str]:
        """Move every `awaiting_approval` Order past its expiry to `expired`. Returns their IDs."""
        now = ts(self.store.clock.now())
        expired: list[str] = []
        with self.store.tx() as c:
            rows = c.execute(
                "SELECT o.id FROM orders o WHERE o.state = 'awaiting_approval' AND NOT EXISTS ("
                " SELECT 1 FROM approvals a WHERE a.order_id = o.id AND a.used_at IS NULL"
                " AND a.expires_at > ?)",
                (now,),
            ).fetchall()
            for r in rows:
                if self.store.transition_in_tx(c, r["id"], State.EXPIRED, "approval_timeout", {}):
                    expired.append(r["id"])
        for order_id in expired:
            log.info("approval for order %s expired", order_id)
        return expired

    async def run_sweeper(
        self,
        on_expired: Callable[[str], Awaitable[None]],
        interval: float = SWEEP_INTERVAL,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        while True:
            for order_id in await asyncio.to_thread(self.sweep):
                try:
                    await on_expired(order_id)
                except Exception:
                    log.exception("expiry notification failed for order %s", order_id)
            await sleep(interval)
