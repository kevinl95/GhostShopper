#!/usr/bin/env python3
"""Probe the Live View endpoints of a browser session without the AWS console.

Generates a presigned Live View URL with the bedrock-agentcore SDK and opens the two DCV
WebSocket channels (`/live-view/auth` and `/live-view`), printing only the HTTP status of each
handshake. The presigned URL is never printed, because it grants control of the session.

Usage:
    python infra/spikes/probe_live_view.py --region us-east-1 --session-id <id>
    python infra/spikes/probe_live_view.py --region us-west-2 --new-session   # start, probe, stop
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import urlsplit, urlunsplit


async def probe(url: str) -> str:
    import websockets
    from websockets.exceptions import InvalidStatus

    try:
        async with websockets.connect(url, max_size=None, open_timeout=15):
            return "101 (connected)"
    except InvalidStatus as exc:
        return f"{exc.response.status_code} (rejected)"
    except Exception as exc:
        return f"error: {type(exc).__name__}: {exc}"


def channel(presigned: str, suffix: str) -> str:
    p = urlsplit(presigned)
    return urlunsplit(("wss", p.netloc, p.path.rstrip("/") + suffix, p.query, ""))


def run(client) -> None:
    url = client.generate_live_view_url(expires=300)
    for name, suffix in (("auth channel", "/auth"), ("main channel", "")):
        print(f"{name:13} {asyncio.run(probe(channel(url, suffix)))}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="us-east-1")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--session-id")
    g.add_argument("--new-session", action="store_true")
    args = ap.parse_args()

    from bedrock_agentcore.tools.browser_client import BrowserClient, browser_session

    if args.new_session:
        with browser_session(args.region) as client:
            print(f"session      {client.session_id} ({args.region})")
            run(client)
    else:
        client = BrowserClient(args.region)
        client.identifier = "aws.browser.v1"
        client.session_id = args.session_id
        run(client)
    return 0


if __name__ == "__main__":
    sys.exit(main())
