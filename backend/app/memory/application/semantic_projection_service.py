"""Semantic Memory 投影：外部模型调用与短持久化事务严格分离。"""

import hashlib
from uuid import UUID

from app.agent.ports.conversation_reader import ConversationReader
from app.common.clock import Clock
from app.common.errors import DomainError, NotFoundError
from app.memory.application.fingerprint import fingerprint
from app.memory.domain.evidence import EvidenceRef, EvidenceSourceType
from app.memory.domain.semantic import MemoryOrigin, SemanticMemoryCandidate, SemanticMemoryType
from app.memory.ports.embedding import EmbeddingProvider
from app.memory.ports.evidence_reader import EvidenceReader, ValidatedEvidence
from app.memory.ports.extractor import ExtractedSemanticCandidate, SemanticMemoryExtractor
from app.memory.ports.repositories import MemoryRepository, ProjectionResult

PROJECTOR_NAME = "semantic_memory"  # 投影器名：仓储端按它区分不同投影器的输出
EMBEDDING_DIMENSIONS = 1536  # 向量维度契约：嵌入结果必须严格一致


class SemanticMemoryProjectionService:
    """语义记忆投影服务：把已提交对话或证据集投影为语义记忆条目。"""

    def __init__(
        self,
        *,
        conversations: ConversationReader,
        evidence_reader: EvidenceReader,
        extractor: SemanticMemoryExtractor,
        embedding: EmbeddingProvider,
        repository: MemoryRepository,
        clock: Clock,
    ) -> None:
        # 依赖全部是端口抽象，便于替换实现与测试注入。
        self._conversations = conversations  # 会话读取端口：取已提交 Turn 的消息
        self._evidence = evidence_reader  # 证据读取端口：读取已确认来源
        self._extractor = extractor  # 语义提取端口：外部模型抽取记忆候选
        self._embedding = embedding  # 向量化端口
        self._repository = repository  # Memory 仓储端口：短事务原子合并
        self._clock = clock  # 时钟端口：统一"当前时间"基准

    async def project_committed_turn(
        self,
        *,
        user_id: UUID,
        turn_id: UUID,
        projector_version: str,
    ) -> ProjectionResult:
        """把一轮已提交对话投影为语义记忆（用户明示偏好的入口）。"""
        committed = await self._conversations.get_committed_turn_messages(
            user_id=user_id, turn_id=turn_id
        )
        # Turn 尚未提交或不存在：无法投影，直接报错而非静默跳过。
        if committed is None:
            raise NotFoundError("committed_turn_not_found")
        # 由外部模型从双方消息中抽取记忆候选（限定在支持的类型内）。
        extracted = await self._extractor.extract(
            user_message=committed.user_message,
            assistant_message=committed.assistant_message,
            committed_at=committed.committed_at,
            supported_types=tuple(SemanticMemoryType),
        )
        # 同一轮对话的多条证据归入同组：独立来源计数只算一次。
        group_key = f"conversation:turn:{turn_id}"
        candidates: list[SemanticMemoryCandidate] = []
        for item in extracted:
            # 对话投影只允许"用户明示"候选；推断候选必须走证据集投影。
            if item.origin is not MemoryOrigin.EXPLICIT:
                raise DomainError("conversation_projection_requires_explicit_candidate")
            candidates.append(
                SemanticMemoryCandidate(
                    type=item.type,
                    origin=item.origin,
                    subject_key=item.subject_key,
                    value=item.value,
                    content=item.content,
                    valid_from=item.valid_from,
                    valid_until=item.valid_until,
                    # 每个候选绑定两条同组证据：用户消息为主证据，Turn 为派生上下文。
                    evidence=(
                        EvidenceRef(
                            source_type=EvidenceSourceType.MESSAGE,
                            source_id=committed.user_message.id,
                            source_occurred_at=committed.user_message.created_at,
                            evidence_group_key=group_key,
                            independence_role=_primary(),
                        ),
                        EvidenceRef(
                            source_type=EvidenceSourceType.TURN,
                            source_id=turn_id,
                            source_occurred_at=committed.committed_at,
                            evidence_group_key=group_key,
                            independence_role=_derived(),
                        ),
                    ),
                )
            )
        # 检查点只含消息身份与内容哈希，不落私密原文，用于幂等重放判断。
        checkpoint = {
            "turn_id": str(turn_id),
            "user_message_id": str(committed.user_message.id),
            "assistant_message_id": str(committed.assistant_message.id),
            "committed_at": committed.committed_at.isoformat(),
            "user_content_hash": hashlib.sha256(
                committed.user_message.content.encode("utf-8")
            ).hexdigest(),
            "assistant_content_hash": hashlib.sha256(
                committed.assistant_message.content.encode("utf-8")
            ).hexdigest(),
        }
        # 外部模型调用（提取/向量化）全部完成后，才进入仓储短事务落库。
        batch = await self._embed(tuple(item.content for item in candidates))
        return await self._repository.apply_semantic_projection(
            user_id=user_id,
            projector_name=PROJECTOR_NAME,
            projector_version=projector_version,
            projection_key=f"turn:{turn_id}",
            input_fingerprint=fingerprint(checkpoint),
            input_checkpoint=checkpoint,
            candidates=tuple(candidates),
            embeddings=batch.vectors,
            embedding_model=batch.model,
            embedding_version=batch.version,
            now=self._clock.now(),
        )

    async def project_evidence_set(
        self,
        *,
        user_id: UUID,
        candidate: ExtractedSemanticCandidate,
        source_ids: tuple[tuple[EvidenceSourceType, UUID], ...],
        projector_version: str,
    ) -> ProjectionResult:
        """把一组已确认证据投影为一条"推断"语义记忆（如从训练数据归纳）。"""
        # 只接受推断候选：明示候选必须走对话投影路径，两条入口不允许混用。
        if candidate.origin is not MemoryOrigin.INFERRED:
            raise DomainError("evidence_set_projection_requires_inferred_candidate")
        sources = await self._evidence.read_many(user_id=user_id, source_ids=source_ids)
        evidence = tuple(_memory_evidence(item) for item in sources)
        semantic = SemanticMemoryCandidate(
            type=candidate.type,
            origin=candidate.origin,
            subject_key=candidate.subject_key,
            value=candidate.value,
            content=candidate.content,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            evidence=evidence,
        )
        # 投影键由来源集合决定：同一来源集合重复投影可幂等重放。
        checkpoint = _source_checkpoint(sources)
        identity = fingerprint({"sources": sorted(str(item) for item in source_ids)})
        batch = await self._embed((semantic.content,))
        return await self._repository.apply_semantic_projection(
            user_id=user_id,
            projector_name=PROJECTOR_NAME,
            projector_version=projector_version,
            projection_key=f"inferred:{candidate.type.value}:{identity}",
            input_fingerprint=fingerprint(checkpoint),
            input_checkpoint=checkpoint,
            candidates=(semantic,),
            embeddings=batch.vectors,
            embedding_model=batch.model,
            embedding_version=batch.version,
            now=self._clock.now(),
        )

    async def _embed(self, texts: tuple[str, ...]):
        """向量化文本并校验维度契约；空输入直接返回占位空批次。"""
        if not texts:
            # 局部导入仅在构造空批次返回值时需要，保持顶层依赖精简。
            from app.memory.ports.embedding import EmbeddingBatch

            return EmbeddingBatch((), "none", "none", EMBEDDING_DIMENSIONS)
        # 供应商返回的批次数与维度必须严格符合契约，不符合即 fail fast。
        batch = await self._embedding.embed(texts)
        if batch.dimensions != EMBEDDING_DIMENSIONS or len(batch.vectors) != len(texts):
            raise DomainError("memory_embedding_contract_mismatch")
        if any(len(vector) != EMBEDDING_DIMENSIONS for vector in batch.vectors):
            raise DomainError("memory_embedding_dimension_mismatch")
        return batch


def _source_checkpoint(sources: tuple[ValidatedEvidence, ...]) -> dict[str, object]:
    """构造来源检查点：只含来源 identity/version（排序后），用于幂等判断。"""
    return {
        "sources": [
            {
                "type": item.source_type.value,
                "id": str(item.source_id),
                "version": item.source_version,
            }
            for item in sorted(
                sources, key=lambda source: (source.source_type.value, str(source.source_id))
            )
        ]
    }


def _memory_evidence(source: ValidatedEvidence) -> EvidenceRef:
    """把校验证据裁剪为记忆可引用的 EvidenceRef（不携带 facts 原文）。"""
    return EvidenceRef(
        source_type=source.source_type,
        source_id=source.source_id,
        source_occurred_at=source.source_occurred_at,
        evidence_group_key=source.evidence_group_key,
        independence_role=source.independence_role,
    )


def _primary():
    """返回主证据角色（局部导入，保持顶层依赖精简）。"""
    from app.memory.domain.evidence import EvidenceIndependenceRole

    return EvidenceIndependenceRole.PRIMARY


def _derived():
    """返回派生上下文角色（局部导入，保持顶层依赖精简）。"""
    from app.memory.domain.evidence import EvidenceIndependenceRole

    return EvidenceIndependenceRole.DERIVED_CONTEXT
