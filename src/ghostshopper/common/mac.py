"""MAC address normalization."""

from __future__ import annotations

import re

_HEX12 = re.compile(r"^[0-9a-f]{12}$")


def normalize_mac(value: str) -> str:
    """Return `aa:bb:cc:dd:ee:ff` for any case and for colon, hyphen, dot or no separators.

    Raises ValueError if the value is not exactly 12 hex digits.
    """
    if not isinstance(value, str):
        raise ValueError("MAC address must be a string")
    stripped = re.sub(r"[:\-.]", "", value.strip().lower())
    if not _HEX12.match(stripped):
        raise ValueError(f"invalid MAC address: {value!r}")
    return ":".join(stripped[i : i + 2] for i in range(0, 12, 2))
