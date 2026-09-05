"""Eval durable barrier must fail closed on quarantine / dead-letter."""

from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.evals.barrier import CollectingQueue, drain_durable_tasks
from app.evals.errors import EvalBarrierError


@dataclass
class _PublishBatchResult:
    claimed: int
    enqueued: int = 0
    deferred: int = 0
    quarantined: int = 0


@dataclass
class _ConsumeResult:
    status: str
    attempt: int = 1


class _FakeOutbox:
    def __init__(self, batches: list[_PublishBatchResult]) -> None:
        self._batches = list(batches)

    async def claim_pending(self, **kwargs):  # pragma: no cover - not used directly
        return []


@pytest.mark.asyncio
async def test_barrier_raises_on_quarantine(monkeypatch: pytest.MonkeyPatch) -> None:
    batches = [_PublishBatchResult(claimed=0, quarantined=1)]

    class Publisher:
        def __init__(self, **kwargs) -> None:
            self._batches = batches

        async def publish_batch(self) -> _PublishBatchResult:
            return self._batches.pop(0)

    class Runner:
        def __init__(self, **kwargs) -> None:
            pass

        async def consume(self, task):  # pragma: no cover
            raise AssertionError("should not consume after quarantine")

    monkeypatch.setattr("app.evals.barrier.OutboxPublisher", Publisher)
    monkeypatch.setattr("app.evals.barrier.ConsumerRunner", Runner)
    monkeypatch.setattr(
        "app.evals.barrier.SqlAlchemyOutboxRepository", lambda sessions: object()
    )
    monkeypatch.setattr(
        "app.evals.barrier.SqlAlchemyConsumptionRepository", lambda sessions: object()
    )
    monkeypatch.setattr(
        "app.evals.barrier.DurableTaskHandlers",
        lambda **kwargs: SimpleNamespace(mapping=dict),
    )

    container = SimpleNamespace(
        sessions=object(),
        clock=SimpleNamespace(now=lambda: None),
        terminal_turn_finalization_service=object(),
        athlete_recompute_service=object(),
        semantic_memory_projection_service=object(),
        episode_projection_service=object(),
        settings=SimpleNamespace(memory_projector_version="v1"),
    )
    with pytest.raises(EvalBarrierError, match="outbox_quarantined"):
        await drain_durable_tasks(container)


@pytest.mark.asyncio
async def test_barrier_raises_on_dead_letter(monkeypatch: pytest.MonkeyPatch) -> None:
    task = SimpleNamespace(task_name="finalize_terminal_turn", event_id=uuid4())

    class Queue(CollectingQueue):
        def __init__(self) -> None:
            super().__init__()
            self.tasks.append(task)

        async def enqueue(self, task, *, defer_by: timedelta | None = None) -> None:
            self.tasks.append(task)

    class Publisher:
        def __init__(self, **kwargs) -> None:
            self._first = True

        async def publish_batch(self) -> _PublishBatchResult:
            # First round: claim 1 so the pre-seeded queue task is consumed;
            # claimed count only gates the empty-queue exit condition.
            if self._first:
                self._first = False
                return _PublishBatchResult(claimed=1, quarantined=0)
            return _PublishBatchResult(claimed=0, quarantined=0)

    class Runner:
        def __init__(self, **kwargs) -> None:
            pass

        async def consume(self, task) -> _ConsumeResult:
            return _ConsumeResult(status="dead_lettered")

    monkeypatch.setattr("app.evals.barrier.CollectingQueue", Queue)
    monkeypatch.setattr("app.evals.barrier.OutboxPublisher", Publisher)
    monkeypatch.setattr("app.evals.barrier.ConsumerRunner", Runner)
    monkeypatch.setattr(
        "app.evals.barrier.SqlAlchemyOutboxRepository", lambda sessions: object()
    )
    monkeypatch.setattr(
        "app.evals.barrier.SqlAlchemyConsumptionRepository", lambda sessions: object()
    )
    monkeypatch.setattr(
        "app.evals.barrier.DurableTaskHandlers",
        lambda **kwargs: SimpleNamespace(mapping=dict),
    )

    container = SimpleNamespace(
        sessions=object(),
        clock=SimpleNamespace(now=lambda: None),
        terminal_turn_finalization_service=object(),
        athlete_recompute_service=object(),
        semantic_memory_projection_service=object(),
        episode_projection_service=object(),
        settings=SimpleNamespace(memory_projector_version="v1"),
    )
    with pytest.raises(EvalBarrierError, match="dead_lettered"):
        await drain_durable_tasks(container)
