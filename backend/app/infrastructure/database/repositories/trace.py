from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.models.action import CapabilityCallAction, FinalAction
from app.agent.models.observation import Observation
from app.agent.models.run import RunStepKind
from app.common.clock import Clock
from app.common.ids import new_id
from app.infrastructure.database.models.agent import RunStepRow
from app.infrastructure.database.session import short_session
from app.infrastructure.jsonutil import json_ready


class SqlAlchemyAgentTraceRecorder:
    def __init__(self, sessions: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessions = sessions
        self._clock = clock

    async def record_reasoning(
        self,
        *,
        run_id: UUID,
        action_type: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.REASONING,
            call_id=None,
            input_data=None,
            output_data=json_ready({"action_type": action_type, "metadata": metadata or {}}),
            started_at=now,
            completed_at=now,
        )

    async def record_action(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        action: CapabilityCallAction,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.CAPABILITY_CALL,
            call_id=call_id,
            input_data=json_ready(
                {"capability": action.capability, "arguments": action.arguments}
            ),
            output_data=None,
            started_at=now,
            completed_at=now,
        )

    async def record_observation(
        self,
        *,
        run_id: UUID,
        call_id: UUID,
        observation: Observation,
    ) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.OBSERVATION,
            call_id=call_id,
            input_data=None,
            output_data=json_ready(observation.model_dump()),
            started_at=now,
            completed_at=now,
        )

    async def record_final(self, *, run_id: UUID, action: FinalAction) -> None:
        now = self._clock.now()
        await self._insert(
            run_id=run_id,
            kind=RunStepKind.FINAL,
            call_id=None,
            input_data=None,
            output_data=json_ready({"content": action.content}),
            started_at=now,
            completed_at=now,
        )

    async def _insert(
        self,
        *,
        run_id: UUID,
        kind: RunStepKind,
        call_id: UUID | None,
        input_data: dict[str, Any] | None,
        output_data: dict[str, Any] | None,
        started_at: datetime,
        completed_at: datetime | None,
    ) -> None:
        async with short_session(self._sessions, commit=True) as session:
            current = await session.scalar(
                select(func.max(RunStepRow.index)).where(RunStepRow.run_id == run_id)
            )
            index = int(current or 0) + 1
            session.add(
                RunStepRow(
                    id=new_id(),
                    run_id=run_id,
                    index=index,
                    kind=kind.value,
                    call_id=call_id,
                    input_data=input_data,
                    output_data=output_data,
                    started_at=started_at,
                    completed_at=completed_at,
                )
            )
