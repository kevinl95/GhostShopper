"""Shared helpers. Imports only the standard library."""

from ghostshopper.common.clock import Clock, FakeClock, SystemClock
from ghostshopper.common.mac import normalize_mac
from ghostshopper.common.money import from_cents, to_cents
from ghostshopper.common.redaction import RedactionFilter, install_redaction, redact

AGENT_TOKEN = "Agent/ghostshopper"
# Sent on every outbound request (Amazon Agent Terms, Requirement 15.1).
USER_AGENT = f"ghostshopper/0.1 {AGENT_TOKEN}"

__all__ = [
    "AGENT_TOKEN",
    "USER_AGENT",
    "Clock",
    "FakeClock",
    "RedactionFilter",
    "SystemClock",
    "from_cents",
    "install_redaction",
    "normalize_mac",
    "redact",
    "to_cents",
]
