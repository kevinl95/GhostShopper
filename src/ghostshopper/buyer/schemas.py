"""Wire protocol between the Agent_Service and the cloud Buyer.

Shared by both sides. Must not import nova_act, playwright or bedrock_agentcore.
There is deliberately no field for a password, card number or one-time code (Req 13.1).
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ghostshopper.common import AGENT_TOKEN

ASIN_PATTERN = r"^[A-Z0-9]{10}$"
ORDER_ID_PATTERN = r"^[0-9a-f]{32}$"

Action = Literal["quote", "substitute", "purchase"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Quote(_Model):
    """Product page facts. Also the schema passed to Nova Act `act_get`."""

    title: str = Field(min_length=1, max_length=500)
    price: Decimal = Field(ge=Decimal(0), max_digits=10, decimal_places=2)  # unit price, USD
    availability: Literal["in_stock", "out_of_stock"]
    delivery_estimate: str = Field(min_length=1, max_length=200)


class Substitute(Quote):
    asin: str = Field(pattern=ASIN_PATTERN)


class PurchaseResult(_Model):
    order_number: str | None = Field(default=None, min_length=1, max_length=64)
    reached_place_order: bool

    @model_validator(mode="after")
    def _consistent(self) -> PurchaseResult:
        if self.order_number is None and not self.reached_place_order:
            raise ValueError("a purchase result needs an order number or reached_place_order")
        return self


def job_id_for(order_id: str, action: Action) -> str:
    return f"{order_id}-{action}"


class BuyerRequest(_Model):
    action: Literal["quote", "substitute", "purchase", "status"]
    order_id: str = Field(pattern=ORDER_ID_PATTERN)
    job_id: str | None = None
    asin: str | None = Field(default=None, pattern=ASIN_PATTERN)
    quantity: int | None = Field(default=None, ge=1, le=99)
    is_substitute: bool = False
    approved_unit_price: Decimal | None = Field(default=None, ge=Decimal(0))
    dry_run: bool | None = None
    user_agent: str

    @field_validator("user_agent")
    @classmethod
    def _has_agent_token(cls, value: str) -> str:
        if AGENT_TOKEN not in value:
            raise ValueError(f"user_agent must contain {AGENT_TOKEN}")
        return value

    @model_validator(mode="after")
    def _fields_for_action(self) -> BuyerRequest:
        need: dict[str, tuple[str, ...]] = {
            "quote": ("asin",),
            "substitute": ("asin",),
            "purchase": ("asin", "quantity", "approved_unit_price", "dry_run"),
            "status": ("job_id",),
        }
        missing = [f for f in need[self.action] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.action} request is missing: {', '.join(missing)}")
        return self


ErrorCode = Literal[
    "invalid_quote",
    "user_agent_unverified",
    "verification_timeout",
    "price_changed",
    "purchase_error",
]

_SAFE_DETAIL = re.compile(r"[^\w .,:;()/#'-]")


class JobStatus(_Model):
    job_id: str
    state: Literal["running", "verification_required", "succeeded", "failed"]
    browser_session_id: str | None = None
    verification_deadline: datetime | None = None
    result: PurchaseResult | Substitute | Quote | None = None
    error_code: ErrorCode | None = None
    error_detail: str | None = Field(default=None, max_length=300)

    @field_validator("error_detail")
    @classmethod
    def _plain_detail(cls, value: str | None) -> str | None:
        # Short plain text only: no markup or page content survives.
        return None if value is None else _SAFE_DETAIL.sub("", value)[:300]

    @model_validator(mode="after")
    def _consistent(self) -> JobStatus:
        if self.state == "failed" and self.error_code is None:
            raise ValueError("a failed job needs an error_code")
        if self.state == "verification_required" and self.browser_session_id is None:
            raise ValueError("verification_required needs a browser_session_id")
        return self
