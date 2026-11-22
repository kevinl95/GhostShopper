#!/usr/bin/env python3
"""Spike 2: does a browser session started from a profile restore the saved Amazon cookies?

Resolves the "Starting a session from the profile" item in design.md.

Prerequisite: you have logged in to amazon.com once through Live View and saved the session
to the profile (infra/tools/login_session.py, or the AWS console). Without that, the cookie
check below can only report "profile started, no Amazon cookies".

Pinned requirements (throwaway venv, Python 3.10+):
    bedrock-agentcore>=1.0
    websockets>=13,<16
    boto3>=1.35

Usage:
    python infra/spikes/spike2_profile_start.py --region us-east-1 --profile-id <id>

Path A: browser_session(region, profile_configuration={"profileIdentifier": id}).
Path B (fallback if A rejects the argument): boto3 start_browser_session(profileConfiguration=...)
plus a manual BrowserClient for generate_ws_headers().

Only cookie names and counts are written to the result file, never values.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from _common import cdp_call, write_result

# Cookies that indicate an Amazon signed-in session. Names only; values are never read out.
SIGNED_IN_NAMES = {"at-main", "sess-at-main", "x-main", "session-token", "ubid-main"}


def cookie_report(cookies: list[dict]) -> tuple[int, list[str]]:
    amazon = [c for c in cookies if "amazon." in c.get("domain", "")]
    names = sorted({c["name"] for c in amazon})
    return len(amazon), names


async def read_cookies(ws_url: str, headers: dict) -> list[dict]:
    res = await cdp_call(ws_url, headers, "Storage.getCookies")
    return res.get("cookies", [])


def path_a(region: str, profile_id: str):
    from bedrock_agentcore.tools.browser_client import browser_session

    with browser_session(region, profile_configuration={"profileIdentifier": profile_id}) as client:
        ws_url, headers = client.generate_ws_headers()
        return asyncio.run(read_cookies(ws_url, headers))


def path_b(region: str, profile_id: str):
    import boto3
    from bedrock_agentcore.tools.browser_client import BrowserClient

    data = boto3.client("bedrock-agentcore", region_name=region)
    resp = data.start_browser_session(
        browserIdentifier="aws.browser.v1",
        name="spike2",
        profileConfiguration={"profileIdentifier": profile_id},
    )
    session_id = resp["sessionId"]
    try:
        client = BrowserClient(region)
        client.identifier = "aws.browser.v1"
        client.session_id = session_id
        ws_url, headers = client.generate_ws_headers()
        return asyncio.run(read_cookies(ws_url, headers))
    finally:
        data.stop_browser_session(browserIdentifier="aws.browser.v1", sessionId=session_id)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--profile-id", required=True, help="AgentCore browser profile identifier")
    args = ap.parse_args()

    used = "A (browser_session helper)"
    notes: list[str] = []
    try:
        try:
            cookies = path_a(args.region, args.profile_id)
        except TypeError as exc:  # helper rejects profile_configuration
            notes.append(f"Path A rejected the argument: {exc}")
            used = "B (start_browser_session + manual BrowserClient)"
            cookies = path_b(args.region, args.profile_id)
    except Exception as exc:
        body = f"Spike aborted: `{type(exc).__name__}: {exc}`\n\n" + "\n".join(notes)
        write_result("spike2", False, "Spike 2: start a session from a profile", body)
        print(body, file=sys.stderr)
        return 1

    count, names = cookie_report(cookies)
    signed_in = sorted(SIGNED_IN_NAMES & set(names))
    passed = bool(signed_in)
    body = (
        f"- Start path that worked: **{used}**\n"
        f"- Amazon cookies restored: {count}\n"
        f"- Signed-in cookie names present: {', '.join(signed_in) or 'none'}\n"
        f"- All Amazon cookie names: {', '.join(names) or 'none'}\n"
    )
    if notes:
        body += "\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    if not passed:
        body += (
            "\nNo signed-in cookie was restored. Either the profile was never saved after login "
            "or the start path does not apply the profile. Save a logged-in session to the "
            "profile and re-run before treating this as a failure of the mechanism.\n"
        )
    path = write_result("spike2", passed, "Spike 2: start a session from a profile", body)
    print(f"spike 2: {'PASS' if passed else 'FAIL'} (see {path})")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
