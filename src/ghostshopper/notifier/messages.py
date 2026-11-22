"""Notification text and ntfy payload rendering. Pure functions, no I/O."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from ghostshopper.common import USER_AGENT

SUBSTITUTE_MARKER = "Substitute:"

REASON_TEXT = {
    "invalid_quote": "the product page could not be read",
    "out_of_stock": "the product is out of stock",
    "over_max_price": "the price is above your max_price",
    "no_substitute": "no substitute was offered",
    "spend_cap": "the purchase would exceed today's spend cap",
    "buyer_unavailable": "the buyer could not be reached",
    "user_agent_unverified": "the buyer could not confirm its Agent user agent",
    "verification_timeout": "Amazon verification was not completed within 10 minutes",
    "interrupted": "the service restarted mid-order",
    "price_changed": "the checkout price was higher than the approved price",
    "purchase_error": "Amazon reported an error during checkout",
    "user_denied": "you denied it",
    "approval_timeout": "no reply within 10 minutes",
}

CHECK_ACCOUNT = "Check your Amazon account to see whether an order was placed."


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def approval_text(title: str, price: Decimal, delivery: str) -> str:
    return f"{title} is {money(price)}, arriving {delivery}. Approve?"


def approval_title(button_name: str, substitute: bool) -> str:
    return f"{SUBSTITUTE_MARKER} {button_name}" if substitute else button_name


def reply_body(order_id: str, token: str, decision: str) -> str:
    return json.dumps(
        {"order_id": order_id, "token": token, "decision": decision}, separators=(",", ":")
    )


def approval_payload(
    *,
    notification_topic: str,
    ntfy_url: str,
    reply_topic: str,
    access_token: str,
    order_id: str,
    token: str,
    button_name: str,
    title: str,
    price: Decimal,
    delivery: str,
    substitute: bool,
) -> dict[str, Any]:
    """ntfy JSON publish body with Approve and Deny `http` actions (Requirements 6.2-6.5)."""
    reply_url = f"{ntfy_url.rstrip('/')}/{reply_topic}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }

    def action(label: str, decision: str) -> dict[str, Any]:
        return {
            "action": "http",
            "label": label,
            "url": reply_url,
            "method": "POST",
            "headers": headers,
            "body": reply_body(order_id, token, decision),
            "clear": True,
        }

    message = approval_text(title, price, delivery)
    if substitute:
        message = f"{SUBSTITUTE_MARKER} {message}"
    return {
        "topic": notification_topic,
        "title": approval_title(button_name, substitute),
        "message": message,
        "tags": ["shopping_cart"] + (["warning"] if substitute else []),
        "priority": 4,
        "actions": [action("Approve", "approve"), action("Deny", "deny")],
    }


def final_text(
    button_name: str, state: str, reason: str | None, *, check_account: bool = False
) -> str:
    """Notice for denied, expired and failed Orders (Requirement 6.9).

    `check_account` is set when the Order failed after reaching `ordering`, because the
    purchase may or may not have gone through.
    """
    why = REASON_TEXT.get(reason or "", reason or "no reason given")
    text = f"{button_name}: order {state} ({reason or 'none'}): {why}."
    if check_account:
        text += f" {CHECK_ACCOUNT}"
    return text


def placed_text(
    button_name: str,
    title: str | None,
    total: Decimal | None,
    order_number: str | None,
    dry_run: bool,
) -> str:
    what = title or button_name
    cost = f" for {money(total)}" if total is not None else ""
    if dry_run:
        return f"Dry run: would have ordered {what}{cost}. Stopped before Place Order."
    return f"Ordered {what}{cost}. Amazon order {order_number}."


def verification_text(region: str, browser_session_id: str, deadline: datetime) -> str:
    """Never contains a Live View URL: a presigned URL would grant control of the session."""
    return (
        "Amazon needs you to verify. Open the AWS console, Bedrock AgentCore, Built-in tools, "
        f"Browser. Region {region}, session {browser_session_id}. Take over, finish the "
        "verification, then release control. This expires at "
        f"{deadline.astimezone().strftime('%H:%M')}."
    )


def simple_payload(topic: str, title: str, message: str, tags: list[str]) -> dict[str, Any]:
    return {"topic": topic, "title": title, "message": message, "tags": tags}
