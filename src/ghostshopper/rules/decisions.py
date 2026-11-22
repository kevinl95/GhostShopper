"""Order rules (Requirement 3). Pure functions, no model, no I/O.

Imports only `ghostshopper.common`. Inputs are described by protocols so the rules do not
depend on the config or buyer packages; `ButtonConfig`, `Quote` and `Substitute` satisfy them.
Money is Decimal. `max_price` and quote prices are unit prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol


class ButtonLike(Protocol):
    @property
    def asin(self) -> str: ...
    @property
    def max_price(self) -> Decimal: ...
    @property
    def cooldown_days(self) -> int: ...
    @property
    def allow_substitutes(self) -> bool: ...


class QuoteLike(Protocol):
    @property
    def price(self) -> Decimal: ...
    @property
    def availability(self) -> Literal["in_stock", "out_of_stock"]: ...


class SubstituteLike(QuoteLike, Protocol):
    @property
    def asin(self) -> str: ...


# --- decision values -------------------------------------------------------------------


@dataclass(frozen=True)
class Accept:
    pass


@dataclass(frozen=True)
class Ignore:
    reason: Literal["in_flight", "cooldown", "unconfigured"]


@dataclass(frozen=True)
class RequestApproval:
    is_substitute: bool = False


@dataclass(frozen=True)
class NeedSubstitute:
    pass


@dataclass(frozen=True)
class Allow:
    pass


FailReason = Literal["out_of_stock", "over_max_price", "no_substitute", "spend_cap"]


@dataclass(frozen=True)
class Fail:
    reason: FailReason


PressDecision = Accept | Ignore
QuoteDecision = RequestApproval | NeedSubstitute | Fail
SubstituteDecision = RequestApproval | Fail
SpendDecision = Allow | Fail


# --- rules -----------------------------------------------------------------------------


def decide_press(
    button: ButtonLike | None,
    in_flight: bool,
    last_real_placed_at: datetime | None,
    now: datetime,
) -> PressDecision:
    """Precedence: unconfigured, then in flight, then cooldown.

    `last_real_placed_at` must come from placed, non-dry-run Orders only (Requirement 3.6).
    """
    if button is None:
        return Ignore("unconfigured")
    if in_flight:
        return Ignore("in_flight")
    if last_real_placed_at is not None and button.cooldown_days > 0:
        if now < last_real_placed_at + timedelta(days=button.cooldown_days):
            return Ignore("cooldown")
    return Accept()


def decide_quote(quote: QuoteLike, button: ButtonLike) -> QuoteDecision:
    if quote.availability == "out_of_stock":
        return NeedSubstitute() if button.allow_substitutes else Fail("out_of_stock")
    if quote.price > button.max_price:
        return NeedSubstitute() if button.allow_substitutes else Fail("over_max_price")
    return RequestApproval(is_substitute=False)


def decide_substitute(sub: SubstituteLike | None, button: ButtonLike) -> SubstituteDecision:
    """A Substitute always needs approval (Requirement 5.2).

    A "substitute" with the configured ASIN is not an alternative, so it counts as none.
    """
    if sub is None or sub.availability == "out_of_stock" or sub.asin == button.asin:
        return Fail("no_substitute")
    if sub.price > button.max_price:
        return Fail("over_max_price")
    return RequestApproval(is_substitute=True)


def decide_spend(placed_total_today: Decimal, order_total: Decimal, cap: Decimal) -> SpendDecision:
    """`placed_total_today` excludes dry-run and in-flight Orders (Requirements 9.2, 9.3)."""
    if placed_total_today + order_total > cap:
        return Fail("spend_cap")
    return Allow()
