"""Outbound subscription to the ntfy reply topic (Requirement 8).

`GET {url}/{reply_topic}/json?since=<last_id>` as a long-lived streaming response. The Pi
opens the connection, so it needs no inbound reachability, tunnel or public callback URL.
The first run uses `since=latest`. After each processed message the ID is stored in `meta`.
Disconnects are logged and retried after `min(2**n, 60)` seconds; `n` resets after a message.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import httpx

from ghostshopper.agent.store import Store
from ghostshopper.common import USER_AGENT

log = logging.getLogger(__name__)

META_LAST_ID = "ntfy_last_id"
MAX_BACKOFF = 60.0


def backoff_delay(failures: int) -> float:
    """Delay before reconnect attempt number `failures` (0-based): 1, 2, 4, ... capped at 60."""
    return min(2.0 ** min(failures, 16), MAX_BACKOFF)


class ReplyStream:
    def __init__(
        self,
        *,
        url: str,
        reply_topic: str,
        access_token: str,
        store: Store,
        handler: Callable[[str], Awaitable[None]],
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.endpoint = f"{url.rstrip('/')}/{reply_topic}/json"
        self._token = access_token
        self.store = store
        self.handler = handler
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
        )
        self._sleep = sleep
        self.failures = 0

    def since(self) -> str:
        return self.store.get_meta(META_LAST_ID) or "latest"

    async def _process_line(self, line: str) -> bool:
        """Handle one stream line. Returns True if it was a message event."""
        line = line.strip()
        if not line:
            return False
        try:
            event = json.loads(line)
        except ValueError:
            log.warning("ntfy stream sent a line that is not JSON")
            return False
        if not isinstance(event, dict) or event.get("event") != "message":
            return False  # open, keepalive, poll_request
        message_id = event.get("id")
        try:
            await self.handler(str(event.get("message", "")))
        except Exception:
            log.exception("reply handler failed for ntfy message %s", message_id)
        if isinstance(message_id, str) and message_id:
            await asyncio.to_thread(self.store.set_meta, META_LAST_ID, message_id)
        return True

    async def run_once(self) -> None:
        """One connection: stream until the server or network ends it."""
        headers = {"Authorization": f"Bearer {self._token}", "User-Agent": USER_AGENT}
        async with self._client_factory() as client:
            async with client.stream(
                "GET", self.endpoint, params={"since": self.since()}, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}", request=resp.request, response=resp
                    )
                async for line in resp.aiter_lines():
                    if await self._process_line(line):
                        self.failures = 0

    async def run(self, stop: asyncio.Event | None = None) -> None:
        while stop is None or not stop.is_set():
            try:
                await self.run_once()
                log.warning("ntfy stream closed by the server")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("ntfy stream disconnected: %s", type(exc).__name__)
            delay = backoff_delay(self.failures)
            self.failures += 1
            log.info("reconnecting to ntfy in %.0f s", delay)
            await self._sleep(delay)
