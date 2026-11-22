"""Money helpers. All arithmetic uses Decimal or integer cents, never float."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def to_cents(amount: Decimal) -> int:
    """Convert a dollar Decimal to integer cents, rounding half up."""
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    return int((amount.quantize(_CENT, rounding=ROUND_HALF_UP) * 100).to_integral_value())


def from_cents(cents: int) -> Decimal:
    """Convert integer cents to a dollar Decimal with two places."""
    return (Decimal(cents) / 100).quantize(_CENT)
