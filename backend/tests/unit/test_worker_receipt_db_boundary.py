"""receipt claim/complete 的数据库故障必须交给 ARQ delayed retry。"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.agent.contracts.durable_events import (
    TURN_FAILED_V1,
    TurnTerminalV1,
    new_turn_terminal_event,
)
from app.common.clock import FrozenClock
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.outbox.repository import (
    ConsumptionClaim,
    ConsumptionClaimResult,
)
from app.workers.consumer import ConsumerRunner, TaskOutcome
from app.workers.errors import WorkerRetryRequested
from app.workers.routing import FINALIZE_TERMINAL_TURN, route_event

NOW = datetime(2026, 8, 31, 8, 0, tzinfo=UTC)


def _task():
    """构造一条 TURN_FAILED 终态事件对应的 worker 任务。"""
    event = new_turn_terminal_event(
        event_type=TURN_FAILED_V1,
        user_id=new_id(),
        payload=TurnTerminalV1(new_id(), new_id(), new_id(), NOW),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    return route_event(event, enqueued_at=NOW)[0]


class _ClaimFails:
    """receipt 仓储替身：claim（认领回执）阶段抛数据库连接故障。"""

    async def claim(self, **kwargs):
        raise OperationalError("claim", {}, RuntimeError("connection refused"))


class _CompleteFails:
    """receipt 仓储替身：claim 成功，但 complete（写回执完成）阶段抛故障。"""

    async def claim(self, **kwargs):
        return ConsumptionClaimResult(ConsumptionClaim.ACQUIRED, 1)

    async def complete(self, **kwargs):
        raise OperationalError("complete", {}, RuntimeError("connection refused"))


@pytest.mark.asyncio
async def test_claim_database_failure_is_delayed_retry() -> None:
    """验证：claim 阶段数据库故障转为 WorkerRetryRequested，交给 ARQ 延迟重试。"""
    runner = ConsumerRunner(
        receipts=_ClaimFails(),
        handlers={FINALIZE_TERMINAL_TURN: _success},
        clock=FrozenClock(NOW),
        worker_id="claim-db-test",
    )
    with pytest.raises(WorkerRetryRequested, match="database_temporarily_unavailable") as caught:
        await runner.consume(_task())
    # 首次重试延迟固定 5 秒（对照 RETRY_DELAYS 首项）
    assert caught.value.defer_seconds == 5


@pytest.mark.asyncio
async def test_complete_database_failure_is_delayed_retry() -> None:
    """验证：complete 阶段故障同样延迟重试——未写完回执的任务会被重新投递（幂等由 receipt 保证）。"""
    runner = ConsumerRunner(
        receipts=_CompleteFails(),
        handlers={FINALIZE_TERMINAL_TURN: _success},
        clock=FrozenClock(NOW),
        worker_id="complete-db-test",
    )
    with pytest.raises(WorkerRetryRequested, match="database_temporarily_unavailable"):
        await runner.consume(_task())


async def _success(task) -> TaskOutcome:
    """恒成功的 handler 替身：只关心 receipt 边界的故障路径。"""
    return TaskOutcome.SUCCESS
