"""Logging filter that removes secrets from log records."""

from __future__ import annotations

import logging
import os
import re

REDACTED = "[REDACTED]"
SECRET_ENV_VARS = (
    "NTFY_ACCESS_TOKEN",
    "NOVA_ACT_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)
# Approval tokens are 32 random bytes in URL-safe base64 without padding: 43 characters.
_TOKEN_43 = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{43}(?![A-Za-z0-9_-])")


def redact(text: str) -> str:
    # Longest first so a secret that contains another is removed whole.
    values = sorted(
        {v for name in SECRET_ENV_VARS if (v := os.environ.get(name))},
        key=len,
        reverse=True,
    )
    for value in values:
        text = text.replace(value, REDACTED)
    return _TOKEN_43.sub(REDACTED, text)


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True


def install_redaction(logger: logging.Logger | None = None) -> None:
    """Attach the filter to the root logger's handlers (and the logger itself)."""
    target = logger or logging.getLogger()
    flt = RedactionFilter()
    target.addFilter(flt)
    for handler in target.handlers:
        handler.addFilter(flt)
