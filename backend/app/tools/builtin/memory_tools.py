"""记忆检索 Tool：按需召回语义 / 情景记忆，供模型主动查询长期事实。"""

from pydantic import BaseModel, ConfigDict, Field

from app.common.errors import RunCoachError
from app.memory.application.retrieval_service import MemoryRetrievalService
from app.memory.domain.episode import Episode
from app.memory.domain.semantic import SemanticMemory
from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource


class RecallMemoriesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="记忆检索查询文本")
    semantic_limit: int = Field(
        default=8, ge=0, le=8, strict=True, description="最多返回多少条语义记忆"
    )
    episode_limit: int = Field(
        default=4, ge=0, le=4, strict=True, description="最多返回多少条情景记忆"
    )


class RecallMemoriesTool:
    """按查询召回相关长期记忆；embedding 未配置时返回结构化错误而非崩溃。"""

    def __init__(self, *, memory_retrieval_service: MemoryRetrievalService) -> None:
        self._retrieval = memory_retrieval_service

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="recall_memories",
            description=(
                "按自然语言查询召回当前用户相关的长期记忆"
                "（语义偏好事实与情景片段）。需要时再调用，不是每轮必读。"
            ),
            tags=("memory", "recall", "preference", "记忆", "召回", "偏好"),
            search_hint="检索用户长期偏好、约束与历史情景记忆",
            always_on=False,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.COACHING,  # ToolSource 暂无 MEMORY；归入 coaching 能力面
            timeout_s=15.0,
        )

    @property
    def args_model(self) -> type[RecallMemoriesArgs]:
        return RecallMemoriesArgs

    async def execute(self, *, args: RecallMemoriesArgs, context: ToolExecutionContext) -> object:
        try:
            result = await self._retrieval.retrieve(
                user_id=context.user_id,
                query=args.query,
                as_of=context.timestamp,
                semantic_limit=args.semantic_limit,
                episode_limit=args.episode_limit,
            )
        except RunCoachError as exc:
            # embedding / 检索基础设施失败：结构化错误，供 Reasoner 继续推理。
            return {"error": str(exc), "semantic": [], "episodic": []}
        except Exception as exc:  # noqa: BLE001 — 工具边界归一化，避免拖垮 AgentRun
            return {
                "error": f"memory_recall_failed: {exc.__class__.__name__}",
                "semantic": [],
                "episodic": [],
            }

        return {
            "semantic": [_semantic_payload(item) for item in result.semantic],
            "episodic": [_episode_payload(item) for item in result.episodic],
            "semantic_truncated": result.semantic_truncated,
            "episodic_truncated": result.episodic_truncated,
            "policy_version": result.policy_version,
        }


def _semantic_payload(memory: SemanticMemory) -> dict[str, object]:
    """语义记忆的 JSON 友好摘要（不含 embedding 向量）。"""
    return {
        "id": str(memory.id),
        "type": memory.type.value,
        "content": memory.content,
        "subject_key": memory.subject_key,
        "confidence": memory.confidence,
        "origin": memory.origin.value,
        "status": memory.status.value,
        "valid_from": memory.valid_from.isoformat(),
        "valid_until": memory.valid_until.isoformat() if memory.valid_until else None,
    }


def _episode_payload(episode: Episode) -> dict[str, object]:
    """情景记忆的 JSON 友好摘要（不含 embedding 向量）。"""
    return {
        "id": str(episode.id),
        "type": episode.type.value,
        "summary": episode.summary,
        "importance": episode.importance,
        "status": episode.status.value,
        "started_at": episode.started_at.isoformat(),
        "ended_at": episode.ended_at.isoformat(),
    }
