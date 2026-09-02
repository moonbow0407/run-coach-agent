"""独立于 Agent Reasoner 的严格 JSON Semantic Memory extractor。"""

import json
from datetime import datetime

from openai import APIError, AsyncOpenAI

from app.agent.models.message import Message
from app.common.errors import InfrastructureError
from app.memory.domain.episode import EpisodeCandidate, EpisodeType
from app.memory.domain.semantic import MemoryOrigin, SemanticMemoryType
from app.memory.ports.evidence_reader import ValidatedEvidence
from app.memory.ports.extractor import ExtractedSemanticCandidate

EXTRACTOR_PROMPT = """你负责从已提交对话中提取跑者明确表达的长期约束或偏好。
只提取用户消息中具有持续、重复、周期或明确未来有效语义的内容。
不得把助手建议、复述、猜测、当天临时安排、医疗诊断或训练事实复制成记忆。
无法确定时返回空 candidates。输出必须符合给定 JSON schema。"""


class OpenAISemanticMemoryExtractor:
    """语义记忆抽取器：用 LLM 从已提交对话中抽取用户明确表达的偏好/约束。"""

    def __init__(self, *, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        """抽取一轮对话中的记忆候选；强制 JSON schema 输出，失败即报错。"""
        schema = _extractor_schema(tuple(item.value for item in supported_types))
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": EXTRACTOR_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "user_message": user_message.content,
                                "assistant_message_for_context_only": assistant_message.content,
                                "committed_at": committed_at.isoformat(),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "semantic_memory_candidates",
                        "strict": True,
                        "schema": schema,
                    },
                },
            )
        except APIError as exc:
            raise InfrastructureError("memory_extraction_failed") from exc
        message = response.choices[0].message if response.choices else None
        if message is None or not message.content:  # 模型返回空内容：协议失败
            raise InfrastructureError("memory_extraction_empty_response")
        try:
            payload = json.loads(message.content)
            raw_candidates = payload["candidates"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise InfrastructureError("memory_extraction_invalid_response") from exc  # 非 JSON 或缺字段
        return tuple(_candidate(item, committed_at) for item in raw_candidates)


class UnavailableSemanticMemoryExtractor:
    """未配置外部模型时的显式失败边界；不产出伪造的抽取结果。"""

    async def extract(self, **_: object) -> tuple[ExtractedSemanticCandidate, ...]:
        raise InfrastructureError("memory_extractor_not_configured")


class UnavailableEpisodeDetector:
    """未配置外部模型时的显式失败边界；不产出伪造的情节。"""

    async def detect(
        self,
        *,
        type: EpisodeType,
        started_at: datetime,
        ended_at: datetime,
        evidence: tuple[ValidatedEvidence, ...],
    ) -> EpisodeCandidate | None:
        raise InfrastructureError("episode_detector_not_configured")


def _candidate(raw: dict[str, object], committed_at: datetime) -> ExtractedSemanticCandidate:
    """把 LLM 输出的原始候选规整为领域候选；value 形态不合法直接报错。"""
    valid_until_raw = raw.get("valid_until")
    value = raw["value"]
    if isinstance(value, list):
        value = tuple(value)
    elif isinstance(value, dict) and set(value) == {"entries"}:  # 键值对集合形态的 value
        raw_entries = value["entries"]
        if not isinstance(raw_entries, list):
            raise InfrastructureError("memory_extraction_invalid_response")
        structured_value: dict[str, object] = {}
        for entry in raw_entries:
            if not isinstance(entry, dict) or set(entry) != {"key", "value"}:
                raise InfrastructureError("memory_extraction_invalid_response")
            key = entry["key"]
            if not isinstance(key, str) or key in structured_value:
                raise InfrastructureError("memory_extraction_invalid_response")
            structured_value[key] = entry["value"]
        value = structured_value
    return ExtractedSemanticCandidate(
        type=SemanticMemoryType(str(raw["type"])),
        origin=MemoryOrigin.EXPLICIT,
        subject_key=str(raw["subject_key"]),
        value=value,  # type: ignore[arg-type]
        content=str(raw["content"]),
        valid_from=_parse_time(raw.get("valid_from"), committed_at),
        valid_until=(
            _parse_time(valid_until_raw, committed_at) if valid_until_raw is not None else None
        ),
    )


def _parse_time(raw: object, default: datetime) -> datetime:
    """解析模型给出的时间；缺省时回落到对话提交时间，必须带时区。"""
    if raw is None:
        return default
    value = datetime.fromisoformat(str(raw))
    if value.tzinfo is None:
        raise InfrastructureError("memory_extraction_time_requires_timezone")
    return value


def _extractor_schema(types: tuple[str, ...]) -> dict[str, object]:
    """构造 strict JSON schema：限定 type 枚举与 value 的合法形态。"""
    scalar = {
        "anyOf": [
            {"type": "string"},
            {"type": "number"},
            {"type": "integer"},
            {"type": "boolean"},
            {"type": "null"},
        ]
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "type",
                        "subject_key",
                        "value",
                        "content",
                        "valid_from",
                        "valid_until",
                    ],
                    "properties": {
                        "type": {"type": "string", "enum": list(types)},
                        "subject_key": {"type": "string"},
                        "value": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "number"},
                                {"type": "integer"},
                                {"type": "boolean"},
                                {"type": "null"},
                                {"type": "array", "items": scalar},
                                {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["entries"],
                                    "properties": {
                                        "entries": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "required": ["key", "value"],
                                                "properties": {
                                                    "key": {"type": "string"},
                                                    "value": scalar,
                                                },
                                            },
                                        },
                                    },
                                },
                            ]
                        },
                        "content": {"type": "string"},
                        "valid_from": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                        "valid_until": {
                            "anyOf": [{"type": "string"}, {"type": "null"}]
                        },
                    },
                },
            }
        },
    }
