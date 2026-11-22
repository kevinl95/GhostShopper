#!/usr/bin/env python3
"""Spike 1: can the user agent "Agent/ghostshopper" be set over CDP on AgentCore Browser?

Gates Requirement 15. Run it with your own AWS identity (it starts a browser session).
It does not import the ghostshopper package, so it runs before the scaffold exists.

Pinned requirements (install in a throwaway venv, Python 3.10+):
    bedrock-agentcore>=1.0      # BrowserClient, browser_session, generate_ws_headers
    websockets>=13,<16          # raw CDP, so child sessions can be addressed by sessionId
    boto3>=1.35

Usage:
    python infra/spikes/spike1_user_agent_cdp.py --region us-east-1
    python infra/spikes/spike1_user_agent_cdp.py --region us-east-1 --profile-id <id>

Steps (mirrors design.md, "User agent gate"):
 1. Start an aws.browser.v1 session (optionally from a browser profile).
 2. Open the browser-level CDP websocket with SigV4 headers.
 3. Target.setAutoAttach (autoAttach, waitForDebuggerOnStart, flatten). For every page target
    send Emulation.setUserAgentOverride, then Runtime.runIfWaitingForDebugger.
 4. Apply the override to pages that already exist.
 5. For the first page, a popup (window.open) and a new tab (Target.createTarget), read
    navigator.userAgent and the user-agent header echoed by a header-echo endpoint.
 6. Write infra/spikes/results/spike1.md. Exit non-zero if any value lacks the token.

Nova Act attach (NovaAct(cdp_endpoint_url=..., cdp_headers=...)) is exercised by spike 3,
not here. This spike only decides whether the override mechanism works.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOKEN = "Agent/ghostshopper"
USER_AGENT = f"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 {TOKEN}"
ECHO_URL = "https://httpbin.org/headers"
RESULT_PATH = Path(__file__).parent / "results" / "spike1.md"
CALL_TIMEOUT = 30


class Cdp:
    """Minimal flat-session CDP client over one websocket."""

    def __init__(self, ws):
        self.ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg:
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RuntimeError(f"{msg['error']}"))
                    else:
                        fut.set_result(msg.get("result", {}))
            else:
                await self.events.put(msg)

    async def send(self, method, params=None, session_id=None):
        call_id = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[call_id] = fut
        msg = {"id": call_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        await self.ws.send(json.dumps(msg))
        return await asyncio.wait_for(fut, CALL_TIMEOUT)

    async def close(self):
        self._reader.cancel()


async def override_and_resume(cdp: Cdp, session_id: str):
    await cdp.send("Emulation.setUserAgentOverride", {"userAgent": USER_AGENT}, session_id)
    await cdp.send("Runtime.runIfWaitingForDebugger", session_id=session_id)


async def attach_loop(cdp: Cdp, sessions: dict[str, str]):
    """Consume attachedToTarget events and override every page target before it runs."""
    while True:
        ev = await cdp.events.get()
        if ev.get("method") != "Target.attachedToTarget":
            continue
        p = ev["params"]
        info = p["targetInfo"]
        if info.get("type") != "page":
            # Non-page targets (workers etc.) just need to be resumed.
            try:
                await cdp.send("Runtime.runIfWaitingForDebugger", session_id=p["sessionId"])
            except Exception:
                pass
            continue
        await cdp.send("Page.enable", session_id=p["sessionId"])
        await override_and_resume(cdp, p["sessionId"])
        sessions[info["targetId"]] = p["sessionId"]


async def evaluate(cdp: Cdp, session_id: str, expression: str, user_gesture: bool = False):
    res = await cdp.send(
        "Runtime.evaluate",
        {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
            "userGesture": user_gesture,
        },
        session_id,
    )
    return res.get("result", {}).get("value")


async def navigate_and_wait(cdp: Cdp, session_id: str, url: str):
    await cdp.send("Page.navigate", {"url": url}, session_id)
    for _ in range(60):
        if await evaluate(cdp, session_id, "document.readyState") == "complete":
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"page did not finish loading: {url}")


async def wait_session(sessions: dict[str, str], target_id: str):
    for _ in range(60):
        if target_id in sessions:
            return sessions[target_id]
        await asyncio.sleep(0.25)
    raise TimeoutError(f"no CDP session for target {target_id}")


async def observe(cdp: Cdp, session_id: str, label: str, rows: list[dict]):
    nav_ua = await evaluate(cdp, session_id, "navigator.userAgent")
    await navigate_and_wait(cdp, session_id, ECHO_URL)
    body = await evaluate(cdp, session_id, "document.body.innerText")
    try:
        header_ua = json.loads(body)["headers"].get("User-Agent", "")
    except Exception:
        header_ua = f"<unparseable echo: {str(body)[:80]!r}>"
    rows.append(
        {
            "page": label,
            "navigator.userAgent": nav_ua,
            "header": header_ua,
            "ok": TOKEN in (nav_ua or "") and TOKEN in header_ua,
        }
    )


async def run(ws_url: str, headers: dict, rows: list[dict]):
    import websockets

    async with websockets.connect(ws_url, additional_headers=headers, max_size=None) as ws:
        cdp = Cdp(ws)
        sessions: dict[str, str] = {}
        attach_task = asyncio.create_task(attach_loop(cdp, sessions))
        try:
            await cdp.send(
                "Target.setAutoAttach",
                {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True},
            )
            # Existing pages (the default about:blank page).
            targets = (await cdp.send("Target.getTargets"))["targetInfos"]
            first_id = None
            for t in targets:
                if t["type"] == "page":
                    first_id = first_id or t["targetId"]
                    att = await cdp.send(
                        "Target.attachToTarget", {"targetId": t["targetId"], "flatten": True}
                    )
                    await cdp.send("Page.enable", session_id=att["sessionId"])
                    await override_and_resume(cdp, att["sessionId"])
                    sessions[t["targetId"]] = att["sessionId"]
            if first_id is None:
                first_id = (await cdp.send("Target.createTarget", {"url": "about:blank"}))[
                    "targetId"
                ]
            first = await wait_session(sessions, first_id)
            await observe(cdp, first, "first page", rows)

            # Popup opened by script from the first page.
            before = set(sessions)
            # userGesture=True so Chrome's popup blocker allows the window.open call.
            await evaluate(
                cdp, first, "window.open('about:blank', '_blank'); true", user_gesture=True
            )
            popup_id = None
            for _ in range(60):
                new = set(sessions) - before
                if new:
                    popup_id = new.pop()
                    break
                await asyncio.sleep(0.25)
            if popup_id is None:
                rows.append(
                    {
                        "page": "popup",
                        "navigator.userAgent": "<no popup target seen>",
                        "header": "",
                        "ok": False,
                    }
                )
            else:
                await observe(cdp, sessions[popup_id], "popup", rows)

            # New tab created through the browser.
            tab_id = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
            await observe(cdp, await wait_session(sessions, tab_id), "new tab", rows)
        finally:
            attach_task.cancel()
            await cdp.close()


def write_result(passed: bool, rows: list[dict], note: str, profile_id: str | None):
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Spike 1: user agent over CDP",
        "",
        f"- Result: **{'PASS' if passed else 'FAIL'}**",
        f"- Run at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- Required token: `{TOKEN}`",
        f"- Echo endpoint: `{ECHO_URL}`",
        f"- Profile: `{profile_id or 'none'}`",
        "",
        "| Page | navigator.userAgent | user-agent header | OK |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['page']} | `{r['navigator.userAgent']}` | `{r['header']}` | {'yes' if r['ok'] else 'NO'} |"
        )
    if note:
        lines += ["", "## Notes", "", note]
    if not passed:
        lines += [
            "",
            "Requirement 15 cannot be met with this mechanism. Stop and decide on another one "
            "(see design.md, Risks) before building dependent work.",
        ]
    RESULT_PATH.write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument(
        "--profile-id", default=None, help="AgentCore browser profile identifier (optional)"
    )
    args = ap.parse_args()

    from bedrock_agentcore.tools.browser_client import browser_session

    rows: list[dict] = []
    note = ""
    try:
        kwargs = {}
        if args.profile_id:
            kwargs["profile_configuration"] = {"profileIdentifier": args.profile_id}
        with browser_session(args.region, **kwargs) as client:
            ws_url, headers = client.generate_ws_headers()
            asyncio.run(run(ws_url, headers, rows))
    except Exception as exc:  # report, then fail closed
        note = f"Spike aborted: {type(exc).__name__}: {exc}"
        print(note, file=sys.stderr)

    passed = bool(rows) and len(rows) >= 3 and all(r["ok"] for r in rows) and not note
    write_result(passed, rows, note, args.profile_id)
    print(f"spike 1: {'PASS' if passed else 'FAIL'} (see {RESULT_PATH})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
