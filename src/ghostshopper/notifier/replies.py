"""Parse reply messages from the ntfy reply topic."""

from __future__ import annotations

import json
import logging

from ghostshopper.agent.approvals import Reply

log = logging.getLogger(__name__)

MAX_FIELD = 200


def parse_reply(message: str) -> Reply | None:
    """Return a Reply if the message is a JSON object with string order_id, token, decision.

    The decision value is not checked here; Approvals rejects bad values with a logged reason.
    """
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        log.warning("ignored reply: not JSON")
        return None
    if not isinstance(data, dict):
        log.warning("ignored reply: not a JSON object")
        return None
    fields = {k: data.get(k) for k in ("order_id", "token", "decision")}
    if not all(isinstance(v, str) and 0 < len(v) <= MAX_FIELD for v in fields.values()):
        order_id = fields["order_id"] if isinstance(fields["order_id"], str) else "?"
        log.warning("ignored reply for order %s: missing or invalid fields", order_id[:64])
        return None
    return Reply(**fields)  # type: ignore[arg-type]
