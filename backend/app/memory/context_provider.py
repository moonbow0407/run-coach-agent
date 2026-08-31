"""真实 MemoryContextProvider：只映射检索结果，不拥有长期数据。"""

from datetime import datetime
from uuid import UUID

from app.agent.context.bundle import EpisodeView, MemoryView
from app.memory.application.retrieval_service import MemoryRetrievalService


class RetrievedMemoryContextProvider:
    def __init__(self, retrieval: MemoryRetrievalService) -> None:
        self._retrieval = retrieval

    async def load(
        self,
        *,
        user_id: UUID,
        current_input: str,
        as_of: datetime,
    ) -> tuple[list[MemoryView], list[EpisodeView]]:
        result = await self._retrieval.retrieve(
            user_id=user_id,
            query=current_input,
            as_of=as_of,
        )
        semantic = [
            MemoryView(
                id=item.id,
                type=item.type.value,
                content=item.content,
                origin=item.origin.value,
                confidence=item.confidence,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
            )
            for item in result.semantic
        ]
        episodic = [
            EpisodeView(
                id=item.id,
                type=item.type.value,
                summary=item.summary,
                started_at=item.started_at,
                ended_at=item.ended_at,
                importance=item.importance,
            )
            for item in result.episodic
        ]
        return semantic, episodic
