"""Test fakes. Python-level only: there is no mock store or fake web page server."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from ghostshopper.buyer.client import BuyerUnavailable, JobRef, session_id_for
from ghostshopper.buyer.schemas import Action, BuyerRequest, JobStatus, job_id_for

Step = JobStatus | BaseException


class FakeWorkflowClient:
    """Scripted `WorkflowClient`.

    `script(order_id, action, steps)` queues what successive `poll` calls return or raise.
    The last step repeats once the queue is empty. `fail_start` makes `start` raise.
    """

    def __init__(self) -> None:
        self.started: list[BuyerRequest] = []
        self.polls: list[JobRef] = []
        self._steps: dict[str, deque[Step]] = defaultdict(deque)
        self._last: dict[str, Step] = {}
        self._fail_start: dict[str, BaseException] = {}

    def script(self, order_id: str, action: Action, steps: Iterable[Step]) -> None:
        self._steps[job_id_for(order_id, action)].extend(steps)

    def fail_start(self, order_id: str, action: Action, exc: BaseException | None = None) -> None:
        self._fail_start[job_id_for(order_id, action)] = exc or BuyerUnavailable("fake outage")

    def start(self, request: BuyerRequest) -> JobRef:
        assert request.action != "status"
        action: Action = request.action
        job_id = job_id_for(request.order_id, action)
        self.started.append(request)
        if job_id in self._fail_start:
            raise self._fail_start[job_id]
        return JobRef(request.order_id, action, job_id, session_id_for(request.order_id, action))

    def poll(self, ref: JobRef) -> JobStatus:
        self.polls.append(ref)
        queue = self._steps[ref.job_id]
        step = queue.popleft() if queue else self._last.get(ref.job_id)
        if step is None:
            return JobStatus(job_id=ref.job_id, state="running")
        self._last[ref.job_id] = step
        if isinstance(step, BaseException):
            raise step
        return step
