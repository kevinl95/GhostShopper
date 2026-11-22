"""SQLite store. Owns all Order state.

Every state change goes through `Store.transition` (or a method built on `transition_in_tx`),
which checks the State_Machine and writes the row and a history entry in one transaction.
Timestamps are UTC ISO-8601 text in one fixed format, so text comparison orders them.
Money is integer cents. No column holds a password, card number, one-time code or raw token.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from ghostshopper.common import Clock, SystemClock, from_cents
from ghostshopper.rules import (
    IN_FLIGHT,
    Allow,
    IllegalTransition,
    State,
    apply,
    decide_spend,
)

log = logging.getLogger(__name__)

BUSY_TIMEOUT_MS = 5000

SCHEMA = """
CREATE TABLE IF NOT EXISTS press_log (
    id INTEGER PRIMARY KEY,
    mac TEXT NOT NULL,
    pressed_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted','in_flight','cooldown','unconfigured')),
    order_id TEXT NULL REFERENCES orders(id)
);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    mac TEXT NOT NULL,
    button_name TEXT NOT NULL,
    asin TEXT NOT NULL,
    purchase_asin TEXT NOT NULL,
    is_substitute INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL,
    title TEXT NULL,
    unit_price_cents INTEGER NULL,
    availability TEXT NULL,
    delivery_estimate TEXT NULL,
    state TEXT NOT NULL,
    reason TEXT NULL,
    dry_run INTEGER NOT NULL,
    order_number TEXT NULL,
    buyer_status TEXT NULL,
    browser_session_id TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    placed_at TEXT NULL
);
CREATE TABLE IF NOT EXISTS order_history (
    id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    from_state TEXT NULL,
    to_state TEXT NOT NULL,
    at TEXT NOT NULL,
    reason TEXT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    token_hash TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS orders_mac_state ON orders(mac, state);
CREATE INDEX IF NOT EXISTS orders_spend ON orders(state, dry_run, placed_at);
CREATE INDEX IF NOT EXISTS approvals_order ON approvals(order_id);
CREATE INDEX IF NOT EXISTS press_log_outcome ON press_log(outcome, mac);
"""

# Columns a transition or update may set, besides state/reason/timestamps.
UPDATABLE = frozenset(
    {
        "purchase_asin",
        "is_substitute",
        "title",
        "unit_price_cents",
        "availability",
        "delivery_estimate",
        "order_number",
        "buyer_status",
        "browser_session_id",
    }
)

PressOutcome = Literal["accepted", "in_flight", "cooldown", "unconfigured"]


def ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def parse_ts(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def local_day_bounds(now: datetime, tz: tzinfo | None = None) -> tuple[datetime, datetime]:
    """UTC start and end of the local calendar day containing `now`. Follows DST.

    `tz=None` uses the host time zone (naive local midnight resolved with `astimezone()`).
    """
    if tz is None:
        local = now.astimezone()
        start = datetime(local.year, local.month, local.day).astimezone()
        nxt = local.date() + timedelta(days=1)
        end = datetime(nxt.year, nxt.month, nxt.day).astimezone()
    else:
        local = now.astimezone(tz)
        start = datetime(local.year, local.month, local.day, tzinfo=tz)
        nxt = local.date() + timedelta(days=1)
        end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


@dataclass(frozen=True)
class Order:
    id: str
    mac: str
    button_name: str
    asin: str
    purchase_asin: str
    is_substitute: bool
    quantity: int
    title: str | None
    unit_price_cents: int | None
    availability: str | None
    delivery_estimate: str | None
    state: State
    reason: str | None
    dry_run: bool
    order_number: str | None
    buyer_status: str | None
    browser_session_id: str | None
    created_at: datetime
    updated_at: datetime
    placed_at: datetime | None

    @property
    def unit_price(self) -> Decimal | None:
        return None if self.unit_price_cents is None else from_cents(self.unit_price_cents)

    @property
    def total_cents(self) -> int | None:
        return None if self.unit_price_cents is None else self.unit_price_cents * self.quantity

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Order:
        return cls(
            id=row["id"],
            mac=row["mac"],
            button_name=row["button_name"],
            asin=row["asin"],
            purchase_asin=row["purchase_asin"],
            is_substitute=bool(row["is_substitute"]),
            quantity=row["quantity"],
            title=row["title"],
            unit_price_cents=row["unit_price_cents"],
            availability=row["availability"],
            delivery_estimate=row["delivery_estimate"],
            state=State(row["state"]),
            reason=row["reason"],
            dry_run=bool(row["dry_run"]),
            order_number=row["order_number"],
            buyer_status=row["buyer_status"],
            browser_session_id=row["browser_session_id"],
            created_at=parse_ts(row["created_at"]),  # type: ignore[arg-type]
            updated_at=parse_ts(row["updated_at"]),  # type: ignore[arg-type]
            placed_at=parse_ts(row["placed_at"]),
        )


@dataclass(frozen=True)
class Press:
    id: int
    mac: str
    pressed_at: datetime
    outcome: str
    order_id: str | None


SpendResult = Literal["ordering", "spend_cap", "lock_timeout", "not_approved"]


class Store:
    """Thread-safe wrapper around one SQLite connection.

    Several `Store` objects (threads or processes) may share one file; `BEGIN IMMEDIATE`
    serializes the spend-cap check and transition between them (Requirement 9.10).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Clock | None = None,
        tz: tzinfo | None = None,
        busy_timeout_ms: int = BUSY_TIMEOUT_MS,
    ) -> None:
        self.path = str(path)
        self.clock = clock or SystemClock()
        self.tz = tz
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self.path,
            isolation_level=None,  # explicit BEGIN/COMMIT only
            check_same_thread=False,
            timeout=busy_timeout_ms / 1000,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        self._conn.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- transactions ---------------------------------------------------------------

    @contextmanager
    def tx(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def _now(self) -> str:
        return ts(self.clock.now())

    # --- presses ----------------------------------------------------------------------

    def record_press(
        self, mac: str, pressed_at: datetime, outcome: PressOutcome, order_id: str | None = None
    ) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO press_log(mac, pressed_at, outcome, order_id) VALUES (?,?,?,?)",
                (mac, ts(pressed_at), outcome, order_id),
            )
            return int(cur.lastrowid or 0)

    def recent_presses(self, limit: int = 50) -> list[Press]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM press_log ORDER BY pressed_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            Press(r["id"], r["mac"], parse_ts(r["pressed_at"]), r["outcome"], r["order_id"])  # type: ignore[arg-type]
            for r in rows
        ]

    def unconfigured_presses(self) -> list[tuple[str, int, datetime]]:
        """(mac, count, latest) for every MAC logged as unconfigured."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT mac, COUNT(*) AS n, MAX(pressed_at) AS latest FROM press_log "
                "WHERE outcome = 'unconfigured' GROUP BY mac ORDER BY latest DESC"
            ).fetchall()
        return [(r["mac"], r["n"], parse_ts(r["latest"])) for r in rows]  # type: ignore[misc]

    # --- orders -----------------------------------------------------------------------

    def create_order(
        self,
        *,
        mac: str,
        button_name: str,
        asin: str,
        quantity: int,
        dry_run: bool,
        pressed_at: datetime | None = None,
    ) -> Order:
        """Create an Order in `pressed` and log the accepted press, in one transaction."""
        order_id = uuid.uuid4().hex
        now = self._now()
        with self.tx() as c:
            c.execute(
                "INSERT INTO orders(id, mac, button_name, asin, purchase_asin, quantity, state,"
                " dry_run, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (order_id, mac, button_name, asin, asin, quantity, State.PRESSED.value,
                 int(dry_run), now, now),
            )  # fmt: skip
            c.execute(
                "INSERT INTO order_history(order_id, from_state, to_state, at) VALUES (?,?,?,?)",
                (order_id, None, State.PRESSED.value, now),
            )
            c.execute(
                "INSERT INTO press_log(mac, pressed_at, outcome, order_id) VALUES (?,?,?,?)",
                (mac, ts(pressed_at) if pressed_at else now, "accepted", order_id),
            )
        order = self.get_order(order_id)
        assert order is not None
        return order

    def get_order(self, order_id: str) -> Order | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        return None if row is None else Order.from_row(row)

    def orders_in(self, states: set[State] | frozenset[State]) -> list[Order]:
        marks = ",".join("?" * len(states))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM orders WHERE state IN ({marks}) ORDER BY created_at",
                [s.value for s in states],
            ).fetchall()
        return [Order.from_row(r) for r in rows]

    def recent_orders(self, limit: int = 50) -> list[Order]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Order.from_row(r) for r in rows]

    def history(self, order_id: str) -> list[tuple[str | None, str, datetime, str | None]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT from_state, to_state, at, reason FROM order_history"
                " WHERE order_id = ? ORDER BY id",
                (order_id,),
            ).fetchall()
        return [(r[0], r[1], parse_ts(r[2]), r[3]) for r in rows]  # type: ignore[misc]

    def has_in_flight(self, mac: str) -> bool:
        marks = ",".join("?" * len(IN_FLIGHT))
        with self._lock:
            row = self._conn.execute(
                f"SELECT 1 FROM orders WHERE mac = ? AND state IN ({marks}) LIMIT 1",
                [mac, *(s.value for s in IN_FLIGHT)],
            ).fetchone()
        return row is not None

    def last_real_placed_at(self, mac: str) -> datetime | None:
        """Latest placed, non-dry-run Order for the Button. Dry runs never feed Cooldown."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(placed_at) FROM orders WHERE mac = ? AND state = 'placed'"
                " AND dry_run = 0",
                (mac,),
            ).fetchone()
        return parse_ts(row[0])

    # --- transitions ------------------------------------------------------------------

    def transition_in_tx(
        self,
        c: sqlite3.Connection,
        order_id: str,
        target: State,
        reason: str | None,
        fields: dict[str, Any],
    ) -> bool:
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        row = c.execute("SELECT state FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            log.warning("transition to %s for unknown order %s", target.value, order_id)
            return False
        current = State(row["state"])
        try:
            apply(current, target)
        except IllegalTransition:
            log.warning(
                "rejected transition %s -> %s for order %s", current.value, target.value, order_id
            )
            return False
        now = self._now()
        sets = {"state": target.value, "reason": reason, "updated_at": now, **fields}
        if target is State.PLACED:
            sets["placed_at"] = now
        assignments = ", ".join(f"{k} = ?" for k in sets)
        c.execute(
            f"UPDATE orders SET {assignments} WHERE id = ? AND state = ?",
            [*sets.values(), order_id, current.value],
        )
        c.execute(
            "INSERT INTO order_history(order_id, from_state, to_state, at, reason)"
            " VALUES (?,?,?,?,?)",
            (order_id, current.value, target.value, now, reason),
        )
        return True

    def transition(
        self, order_id: str, target: State, reason: str | None = None, **fields: Any
    ) -> bool:
        """Apply one State_Machine transition. Illegal transitions are logged, return False."""
        with self.tx() as c:
            return self.transition_in_tx(c, order_id, State(target), reason, fields)

    def update(self, order_id: str, **fields: Any) -> None:
        """Set non-state columns (for example buyer_status) without a transition."""
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        if not fields:
            return
        sets = {**fields, "updated_at": self._now()}
        with self.tx() as c:
            c.execute(
                f"UPDATE orders SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                [*sets.values(), order_id],
            )

    # --- spend cap --------------------------------------------------------------------

    def _placed_total_cents(self, c: sqlite3.Connection, now: datetime) -> int:
        start, end = local_day_bounds(now, self.tz)
        row = c.execute(
            "SELECT COALESCE(SUM(unit_price_cents * quantity), 0) FROM orders"
            " WHERE state = 'placed' AND dry_run = 0 AND placed_at >= ? AND placed_at < ?",
            (ts(start), ts(end)),
        ).fetchone()
        return int(row[0])

    def placed_total_today(self) -> Decimal:
        with self._lock:
            return from_cents(self._placed_total_cents(self._conn, self.clock.now()))

    def approved_to_ordering(self, order_id: str, cap: Decimal) -> SpendResult:
        """Spend-cap check and `approved -> ordering` (or `failed/spend_cap`), atomically.

        A lock timeout leaves the Order `approved` and returns "lock_timeout".
        """
        try:
            with self.tx(immediate=True) as c:
                row = c.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
                if row is None or row["state"] != State.APPROVED.value:
                    return "not_approved"
                order = Order.from_row(row)
                if order.total_cents is None:
                    raise ValueError(f"order {order_id} has no price")
                placed = from_cents(self._placed_total_cents(c, self.clock.now()))
                decision = decide_spend(placed, from_cents(order.total_cents), cap)
                if isinstance(decision, Allow):
                    self.transition_in_tx(c, order_id, State.ORDERING, None, {})
                    return "ordering"
                self.transition_in_tx(c, order_id, State.FAILED, decision.reason, {})
                return "spend_cap"
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                log.error(
                    "spend-cap check for order %s hit a lock timeout; left approved", order_id
                )
                return "lock_timeout"
            raise

    def approval_expiry(self, order_id: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT MAX(expires_at) FROM approvals WHERE order_id = ?", (order_id,)
            ).fetchone()
        return parse_ts(row[0])

    # --- meta -------------------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO meta(key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
