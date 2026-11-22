"""Shared helpers for spikes 2 to 4. Standalone: no ghostshopper imports."""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def write_result(name: str, passed: bool | None, title: str, body: str) -> Path:
    """Write infra/spikes/results/<name>.md. passed=None means 'inconclusive / manual'."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    label = {True: "PASS", False: "FAIL", None: "INCONCLUSIVE"}[passed]
    path = RESULTS / f"{name}.md"
    path.write_text(
        f"# {title}\n\n- Result: **{label}**\n"
        f"- Run at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n\n{body.strip()}\n"
    )
    return path


async def cdp_call(ws_url: str, headers: dict, method: str, params: dict | None = None):
    """Open a CDP websocket, run one browser-level command, and return its result."""
    import websockets

    async with websockets.connect(ws_url, additional_headers=headers, max_size=None) as ws:
        call_id = next(itertools.count(1))
        await ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
            if msg.get("id") == call_id:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})
