#!/usr/bin/env python3
"""Spike 4: Live View hand-off. Can the owner take over a Buyer-started session, finish a
verification, release control, and can the Buyer's CDP connection reconnect afterwards?

Resolves the Live View items in design.md ("Verification notice", "Orchestrator polling").

This spike is interactive. You play the user who got the "verify in Live View" notification.

Pinned requirements (throwaway venv, Python 3.10+):
    bedrock-agentcore>=1.0
    websockets>=13,<16
    boto3>=1.35

Usage:
    python infra/spikes/spike4_verification_handoff.py --region us-east-1 [--profile-id <id>]

Run it under the same AWS account the Buyer role belongs to. The script runs as your own
identity here, which is a limit of the spike: it cannot prove that a session started by the
Buyer's execution role shows up in the console for the owner. Repeat step 2 once after the
runtime is deployed (task 13) by triggering a real run and looking for its session ID.

Steps:
 1. Start a session, attach over CDP, navigate to a page.
 2. Print region and session ID. Open the AWS console, Bedrock AgentCore, Built-in tools,
    Browser, find the session, open Live View, take over, change the page (for example go to
    https://example.com/?handoff=1), then release control.
 3. Press Enter here. The script checks the original CDP connection, then opens a new one
    with fresh SigV4 headers, and reads the URL the operator left the page on.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _common import write_result

START_URL = "https://example.com/"


async def eval_in_first_page(ws_url: str, headers: dict, expression: str, ws=None):
    """Attach to the first page target and evaluate. Opens its own socket if none is given."""
    import websockets

    async def run(sock):
        async def call(i, method, params=None, session=None):
            msg = {"id": i, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = session
            await sock.send(json.dumps(msg))
            while True:
                reply = json.loads(await asyncio.wait_for(sock.recv(), 30))
                if reply.get("id") == i:
                    if "error" in reply:
                        raise RuntimeError(str(reply["error"]))
                    return reply.get("result", {})

        targets = (await call(1, "Target.getTargets"))["targetInfos"]
        page = next(t for t in targets if t["type"] == "page")
        sid = (
            await call(2, "Target.attachToTarget", {"targetId": page["targetId"], "flatten": True})
        )["sessionId"]
        res = await call(
            3, "Runtime.evaluate", {"expression": expression, "returnByValue": True}, sid
        )
        return res["result"]["value"]

    if ws is not None:
        return await run(ws)
    async with websockets.connect(ws_url, additional_headers=headers, max_size=None) as sock:
        return await run(sock)


async def navigate(ws_url: str, headers: dict, url: str):
    await eval_in_first_page(ws_url, headers, f"location.href = {json.dumps(url)}; true")
    await asyncio.sleep(3)


async def main_async(args) -> tuple[bool | None, str]:
    import websockets
    from bedrock_agentcore.tools.browser_client import browser_session

    lines: list[str] = []
    kwargs = {}
    if args.profile_id:
        kwargs["profile_configuration"] = {"profileIdentifier": args.profile_id}

    with browser_session(args.region, **kwargs) as client:
        ws_url, headers = client.generate_ws_headers()
        lines.append(f"- Session ID: `{client.session_id}` (region {args.region})")
        # Hold a long-lived connection the way the Buyer's waiter would.
        held = await websockets.connect(ws_url, additional_headers=headers, max_size=None)
        try:
            await navigate(ws_url, headers, START_URL)
            print("\nSession is running.")
            print(f"  Region:     {args.region}")
            print(f"  Session ID: {client.session_id}")
            print(
                "  Console:    Bedrock AgentCore > Built-in tools > Browser > this session > Live View"
            )
            print(f"  Start page: {START_URL}")
            print("Take over, go to https://example.com/?handoff=1, then release control.")
            await asyncio.get_running_loop().run_in_executor(None, input, "Press Enter when done: ")

            # 1. Is the old connection still usable?
            try:
                url_old = await eval_in_first_page(ws_url, headers, "location.href", ws=held)
                lines.append(
                    f"- Original CDP connection still open after hand-off: yes (url `{url_old}`)"
                )
                old_ok = True
            except Exception as exc:
                lines.append(
                    f"- Original CDP connection after hand-off: closed or failed (`{type(exc).__name__}`)"
                )
                old_ok = False

            # 2. Reconnect with fresh SigV4 headers.
            try:
                ws2, headers2 = client.generate_ws_headers()
                url_new = await eval_in_first_page(ws2, headers2, "location.href")
                lines.append(f"- Reconnect with fresh headers: yes (url `{url_new}`)")
                reconnect_ok = True
                saw_change = "handoff=1" in url_new
                lines.append(
                    f"- Operator's page change visible to the Buyer: {'yes' if saw_change else 'NO (url unchanged)'}"
                )
            except Exception as exc:
                lines.append(
                    f"- Reconnect with fresh headers: FAILED (`{type(exc).__name__}: {exc}`)"
                )
                reconnect_ok = False
                saw_change = False
        finally:
            try:
                await held.close()
            except Exception:
                pass

    lines.append(
        "\nDesign rule confirmed: the waiter must tolerate connection errors and re-attach."
        if (not old_ok and reconnect_ok)
        else "\nNote: the original connection survived. The re-attach path is still required for safety."
    )
    return (reconnect_ok and saw_change), "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--profile-id", default=None)
    args = ap.parse_args()
    try:
        passed, body = asyncio.run(main_async(args))
    except Exception as exc:
        passed, body = False, f"Spike aborted: `{type(exc).__name__}: {exc}`"
    path = write_result("spike4", passed, "Spike 4: Live View verification hand-off", body)
    print(f"spike 4: {'PASS' if passed else 'FAIL'} (see {path})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
