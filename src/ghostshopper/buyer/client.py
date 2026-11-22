"""Workflow_Client: how the Agent_Service talks to the deployed Buyer.

The Agent_Service depends on the `WorkflowClient` protocol only. `AgentCoreWorkflowClient`
uses boto3 `invoke_agent_runtime` with the invoke-only credential from the environment.
boto3 is imported lazily so tests run without it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from ghostshopper.buyer.schemas import Action, BuyerRequest, JobStatus, job_id_for
from ghostshopper.common import USER_AGENT, Clock, SystemClock

log = logging.getLogger(__name__)

THROTTLING_CODES = frozenset(
    {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}
)
START_RETRIES = 3
START_RETRY_DELAY = 2.0


class BuyerUnavailable(Exception):
    """Any boto3, network or protocol error talking to the Buyer."""

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class JobRef:
    order_id: str
    action: Action
    job_id: str
    session_id: str


def session_id_for(order_id: str, action: Action) -> str:
    """One runtime session per order and action (at least 33 characters)."""
    return f"gs-{order_id}-{action}"


class WorkflowClient(Protocol):
    def start(self, request: BuyerRequest) -> JobRef: ...
    def poll(self, ref: JobRef) -> JobStatus: ...


def _error_code(exc: BaseException) -> str | None:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return code if isinstance(code, str) else None
    return None


class AgentCoreWorkflowClient:
    def __init__(
        self,
        runtime_arn: str,
        endpoint_name: str,
        region: str,
        *,
        boto_client: Any | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.runtime_arn = runtime_arn
        self.endpoint_name = endpoint_name
        self.clock = clock or SystemClock()
        if boto_client is None:
            import boto3
            from botocore.config import Config

            boto_client = boto3.client(
                "bedrock-agentcore",
                region_name=region,
                config=Config(
                    user_agent_extra=USER_AGENT,
                    retries={"max_attempts": 1, "mode": "standard"},
                    read_timeout=30,
                    connect_timeout=10,
                ),
            )
        self._client = boto_client

    def _invoke(self, session_id: str, request: BuyerRequest) -> JobStatus:
        try:
            resp = self._client.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                qualifier=self.endpoint_name,
                runtimeSessionId=session_id,
                contentType="application/json",
                accept="application/json",
                payload=request.model_dump_json().encode(),
            )
            body = resp["response"]
            raw = body.read() if hasattr(body, "read") else body
            return JobStatus.model_validate(json.loads(raw))
        except ValidationError as exc:
            raise BuyerUnavailable(
                f"invalid response from Buyer: {exc.error_count()} errors"
            ) from None
        except BuyerUnavailable:
            raise
        except Exception as exc:
            code = _error_code(exc)
            label = f"{type(exc).__name__} ({code})" if code else type(exc).__name__
            raise BuyerUnavailable(label, code) from None

    def start(self, request: BuyerRequest) -> JobRef:
        if request.action == "status":
            raise ValueError("use poll() for status")
        action: Action = request.action
        ref = JobRef(
            order_id=request.order_id,
            action=action,
            job_id=job_id_for(request.order_id, action),
            session_id=session_id_for(request.order_id, action),
        )
        # Retry only throttling: the service rejected the call before running it, so a retry
        # cannot start a second purchase. Any other error is final.
        for attempt in range(START_RETRIES + 1):
            try:
                status = self._invoke(ref.session_id, request)
                break
            except BuyerUnavailable as exc:
                if exc.code in THROTTLING_CODES and attempt < START_RETRIES:
                    log.warning("buyer start throttled for %s, retrying", ref.job_id)
                    self.clock.sleep(START_RETRY_DELAY * (attempt + 1))
                    continue
                raise
        if status.job_id != ref.job_id:
            raise BuyerUnavailable("Buyer returned a different job id")
        return ref

    def poll(self, ref: JobRef) -> JobStatus:
        status = self._invoke(
            ref.session_id,
            BuyerRequest(
                action="status", order_id=ref.order_id, job_id=ref.job_id, user_agent=USER_AGENT
            ),
        )
        if status.job_id != ref.job_id:
            raise BuyerUnavailable("Buyer returned a different job id")
        return status
