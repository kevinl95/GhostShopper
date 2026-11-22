"""Pydantic models for the YAML config file (Requirement 17).

The file holds no secrets. `extra="forbid"` rejects unknown keys, which includes keys such as
`password` or `api_key`. Secrets come from environment variables.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from ghostshopper.common.mac import normalize_mac

ASIN_PATTERN = r"^[A-Z0-9]{10}$"
TOPIC_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"
ARN_PATTERN = r"^arn:aws[a-z-]*:bedrock-agentcore:[a-z0-9-]+:\d{12}:runtime/[A-Za-z0-9_-]+$"
URL_PATTERN = r"^https?://[^\s/?#]+(/[^\s]*)?$"


def _to_decimal(value: Any) -> Decimal:
    """Accept int, float, str or Decimal. Reject bool and anything else. Floats go via str."""
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(value.strip() if isinstance(value, str) else value)
        except InvalidOperation as exc:
            raise ValueError("must be a decimal number") from exc
    elif isinstance(value, float):
        result = Decimal(str(value))
    else:
        raise ValueError("must be a number")
    if not result.is_finite():
        raise ValueError("must be a finite number")
    return result


def _check_two_places(value: Decimal) -> Decimal:
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("must have at most 2 decimal places")
    return value


Money = Annotated[Decimal, BeforeValidator(_to_decimal), AfterValidator(_check_two_places)]
Mac = Annotated[str, AfterValidator(normalize_mac)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ButtonConfig(_Strict):
    name: str = Field(min_length=1, max_length=200)
    asin: str = Field(pattern=ASIN_PATTERN)
    quantity: int = Field(ge=1, le=99)
    max_price: Money = Field(gt=Decimal(0))
    cooldown_days: int = Field(ge=0)
    allow_substitutes: bool
    debounce_seconds: int | None = Field(default=None, ge=1, le=3600)


class NtfyConfig(_Strict):
    url: str = Field(pattern=URL_PATTERN)
    notification_topic: str = Field(pattern=TOPIC_PATTERN)
    reply_topic: str = Field(pattern=TOPIC_PATTERN)

    @model_validator(mode="after")
    def _topics_differ(self) -> NtfyConfig:
        if self.notification_topic == self.reply_topic:
            raise ValueError("reply_topic must differ from notification_topic")
        return self


class BuyerConfig(_Strict):
    region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-\d$")
    runtime_arn: str = Field(pattern=ARN_PATTERN)
    endpoint_name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,47}$")


class Config(_Strict):
    dry_run: bool = True
    daily_spend_cap: Money = Field(ge=Decimal(0))
    ntfy: NtfyConfig
    buyer: BuyerConfig
    buttons: dict[Mac, ButtonConfig] = Field(default_factory=dict)

    @field_validator("buttons", mode="before")
    @classmethod
    def _reject_duplicate_macs(cls, raw: Any) -> Any:
        """Two keys that normalize to the same MAC are rejected (Requirement 17.6)."""
        if not isinstance(raw, dict):
            return raw
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for key in raw:
            try:
                normalized = normalize_mac(key)
            except (ValueError, TypeError):
                continue  # reported per key by the Mac validator
            if normalized in seen:
                duplicates.append(f"{seen[normalized]!r} and {key!r} are both {normalized}")
            else:
                seen[normalized] = key
        if duplicates:
            raise ValueError("duplicate button MAC address: " + "; ".join(duplicates))
        return raw
