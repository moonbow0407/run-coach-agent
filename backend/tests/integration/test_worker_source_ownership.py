"""Worker 重新读取 canonical source 并拒绝跨用户事件。"""

from datetime import timedelta

import pytest

from app.coaching.contracts.durable_events import (
    ChangeKind,
    WorkoutChangedV1,
    new_workout_changed_event,
)
from app.coaching.domain.workout.models import WorkoutSource, WorkoutType
from app.coaching.ports.workout_mutation_store import WorkoutMutation
from app.common.events import EventMetadata
from app.common.ids import new_id
from app.infrastructure.database.models.user import UserRow
from app.infrastructure.database.session import short_session
from app.infrastructure.outbox.repository import SqlAlchemyConsumptionRepository
from app.workers.consumer import ConsumerRunner
from app.workers.handlers import DurableTaskHandlers
from app.workers.routing import route_event


@pytest.mark.asyncio
async def test_recompute_handler_dead_letters_cross_user_source(
    make_app, sessions, user_id, clock
) -> None:
    """验证：事件声明的 user 与 canonical source 真实归属不一致时，消费端 dead letter 拒绝处理。"""
    other_user_id = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_user_id, created_at=clock.now(), updated_at=clock.now()))
    app = make_app()
    # 课次真实归属于 other_user，但事件却以 user_id 的名义发出——构造跨用户伪造场景。
    workout = await app.state.workout_command_service.record(
        user_id=other_user_id,
        mutation=WorkoutMutation(
            started_at=clock.now() - timedelta(days=1),
            distance_m=5000,
            duration_s=1800,
            avg_heart_rate=140,
            max_heart_rate=155,
            workout_type=WorkoutType.EASY,
            source=WorkoutSource.MANUAL,
        ),
        event_metadata=EventMetadata(correlation_id=new_id()),
    )
    event = new_workout_changed_event(
        user_id=user_id,
        payload=WorkoutChangedV1(
            workout_id=workout.id,
            change_kind=ChangeKind.RECORDED,
            source_fact_at=workout.started_at,
            available_at=workout.updated_at,
        ),
        metadata=EventMetadata(correlation_id=new_id()),
    )
    handlers = DurableTaskHandlers(
        terminal_turn_finalization=app.state.container.terminal_turn_finalization_service,
        athlete_recompute=app.state.athlete_recompute_service,
        semantic_projection=app.state.semantic_memory_projection_service,
        episode_projection=app.state.episode_projection_service,
        memory_projector_version=app.state.settings.memory_projector_version,
    )
    runner = ConsumerRunner(
        receipts=SqlAlchemyConsumptionRepository(sessions),
        handlers=handlers.mapping(),
        clock=clock,
        worker_id="source-owner-test",
    )
    result = await runner.consume(route_event(event, enqueued_at=clock.now())[0])
    # 归属校验失败必须走死信而不是静默丢弃或照常处理。
    assert result.status == "dead_lettered"

