"""Publish notifications to ntfy.

ntfy accepts JSON publishing at the server root URL with a `topic` field. Every request
carries the access token and the Agent user agent (Requirements 8.3, 15.1).
Publishing is synchronous; the orchestrator calls it through `asyncio.to_thread`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from ghostshopper.common import USER_AGENT, Clock, SystemClock, from_cents
from ghostshopper.notifier import messages as m

log = logging.getLogger(__name__)

PUBLISH_RETRIES = 3
RETRY_SPACING = 2.0


class NtfyPublisher:
    def __init__(
        self,
        url: str,
        access_token: str,
        *,
        client: httpx.Client | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self._token = access_token
        self.clock = clock or SystemClock()
        self._client = client or httpx.Client(timeout=10.0)

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "User-Agent": USER_AGENT}

    def publish(self, payload: dict[str, Any]) -> bool:
        """POST the payload. Retry 3 times at 2-second spacing. Returns False if all fail."""
        for attempt in range(PUBLISH_RETRIES + 1):
            try:
                resp = self._client.post(self.url + "/", json=payload, headers=self.headers())
                if resp.status_code < 300:
                    return True
                log.warning("ntfy publish returned HTTP %s", resp.status_code)
            except httpx.HTTPError as exc:
                log.warning("ntfy publish failed: %s", type(exc).__name__)
            if attempt < PUBLISH_RETRIES:
                self.clock.sleep(RETRY_SPACING)
        log.error("ntfy publish to topic %s gave up", payload.get("topic"))
        return False


class Notifier:
    """High-level notifications for an Order. Takes plain values so it does not import Store."""

    def __init__(
        self,
        publisher: NtfyPublisher,
        *,
        ntfy_url: str,
        notification_topic: str,
        reply_topic: str,
        access_token: str,
    ) -> None:
        self.publisher = publisher
        self.ntfy_url = ntfy_url
        self.topic = notification_topic
        self.reply_topic = reply_topic
        self._token = access_token

    def approval(
        self,
        *,
        order_id: str,
        token: str,
        button_name: str,
        title: str,
        price: Decimal,
        delivery: str,
        substitute: bool,
    ) -> bool:
        return self.publisher.publish(
            m.approval_payload(
                notification_topic=self.topic,
                ntfy_url=self.ntfy_url,
                reply_topic=self.reply_topic,
                access_token=self._token,
                order_id=order_id,
                token=token,
                button_name=button_name,
                title=title,
                price=price,
                delivery=delivery,
                substitute=substitute,
            )
        )

    def final(
        self, button_name: str, state: str, reason: str | None, *, check_account: bool = False
    ) -> bool:
        text = m.final_text(button_name, state, reason, check_account=check_account)
        return self.publisher.publish(m.simple_payload(self.topic, button_name, text, ["x"]))

    def placed(
        self,
        button_name: str,
        title: str | None,
        total_cents: int | None,
        order_number: str | None,
        dry_run: bool,
    ) -> bool:
        total = None if total_cents is None else from_cents(total_cents)
        text = m.placed_text(button_name, title, total, order_number, dry_run)
        return self.publisher.publish(m.simple_payload(self.topic, button_name, text, ["package"]))

    def verification(
        self, button_name: str, region: str, browser_session_id: str, deadline: datetime
    ) -> bool:
        text = m.verification_text(region, browser_session_id, deadline)
        return self.publisher.publish(
            m.simple_payload(self.topic, f"{button_name}: verify", text, ["key"])
        )
