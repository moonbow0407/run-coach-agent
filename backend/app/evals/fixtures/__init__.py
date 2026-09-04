"""Eval Fixture Registry：固定白名单，禁止按 YAML 字符串动态 import 或执行任意 Python。

每个 fixture 声明：
- seed：创建独立用户并播种合成数据，返回 (user_id, alias → UUID 初始映射)；
- extractor_factory：容器装配时注入的确定性记忆抽取器（None 表示 No-op）；
- resolve_ids：drain 后把 alias 解析为当前 Trial 真实 UUID 的读取步骤。
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.bootstrap import AppContainer
from app.evals.environment import EvalClock
from app.evals.fixtures import seeds
from app.evals.fixtures.extractors import (
    AVAILABILITY_DISTRACTOR_RULES,
    SCHEDULE_PREFERENCE_RULES,
    NoopSemanticMemoryExtractor,
    RuleSemanticMemoryExtractor,
    TrainingFrequencyExtractor,
    build_rule_extractor,
)
from app.memory.ports.extractor import SemanticMemoryExtractor

# 干扰 fixture 的 12 轮播种输入：逐条对应 AVAILABILITY_DISTRACTOR_RULES 的 needle。
AVAILABILITY_DISTRACTOR_INPUTS: tuple[str, ...] = (
    "跟你同步一下我的时间安排：工作日早上通常没时间，只有晚上能训练。",
    "每周三晚上都有课，那天没法安排训练。",
    "我更喜欢按距离而不是按时间来安排训练。",
    "我不喜欢跑步机，能户外就户外。",
    "我赛后需要两天恢复，才会缓过来。",
    "给我回复尽量简短一些就好。",
    "我连续两天高强度恢复差，第二天一般得休息。",
    "如果下雨，我雨天改在室内做力量训练。",
    "我习惯周末早上训练，工作日起不来。",
    "比赛的时候我喜欢按心率控制强度。",
    "我空腹晨跑容易低血糖。",
    "我更喜欢在凉爽天气跑步。",
)


@dataclass(frozen=True)
class EvalFixtureRefs:
    """fixture 写入结果的句柄：alias → 当前 Trial 的真实 UUID。"""

    user_id: UUID  # 本 Case / Trial 的独立用户
    ids: dict[str, UUID]  # 稳定逻辑名 → 真实 UUID（seed 初始映射 + resolve 合并）


class FixtureDrain(Protocol):
    """durable 一致性屏障的调用形态：排空当前容器的全部 Outbox 事件。"""

    async def __call__(self) -> None: ...


@dataclass(frozen=True)
class FixtureContext:
    """fixture 执行环境：容器 + 可推进时钟 + 一致性屏障。"""

    container: AppContainer
    clock: EvalClock
    drain: FixtureDrain


@dataclass(frozen=True)
class EvalFixtureSpec:
    """一个白名单 fixture 的装配与执行契约。"""

    seed: Callable[[AppContainer, EvalClock], Awaitable[tuple[UUID, dict[str, UUID]]]]
    extractor_factory: Callable[[], SemanticMemoryExtractor] | None  # None → No-op
    resolve_ids: Callable[[AppContainer, UUID], Awaitable[dict[str, UUID]]] | None  # drain 后解析 alias


# 固定白名单：新增 fixture 必须在这里显式注册，YAML 引用其他名字一律拒绝。
FIXTURES: dict[str, EvalFixtureSpec] = {
    "runner_vertical_slice": EvalFixtureSpec(
        seed=seeds.seed_runner_vertical_slice,
        extractor_factory=None,
        resolve_ids=None,
    ),
    "runner_normal_fatigue": EvalFixtureSpec(
        seed=seeds.seed_runner_normal_fatigue,
        extractor_factory=None,
        resolve_ids=None,
    ),
    "runner_without_state": EvalFixtureSpec(
        seed=seeds.seed_runner_without_state,
        extractor_factory=None,
        resolve_ids=None,
    ),
    "semantic_memory_distractors": EvalFixtureSpec(
        seed=seeds.seed_semantic_memory_distractors,
        extractor_factory=lambda: build_rule_extractor(AVAILABILITY_DISTRACTOR_RULES),
        resolve_ids=seeds.resolve_availability_distractor_ids,
    ),
    "fatigue_episode_history": EvalFixtureSpec(
        seed=seeds.seed_fatigue_episode_history,
        extractor_factory=None,
        resolve_ids=None,
    ),
    "schedule_preference_correction": EvalFixtureSpec(
        seed=seeds.seed_schedule_preference_correction,
        extractor_factory=lambda: build_rule_extractor(SCHEDULE_PREFERENCE_RULES),
        resolve_ids=seeds.resolve_schedule_correction_ids,
    ),
    "training_frequency_correction": EvalFixtureSpec(
        seed=seeds.seed_training_frequency_correction,
        extractor_factory=TrainingFrequencyExtractor,
        resolve_ids=seeds.resolve_training_frequency_ids,
    ),
}


def noop_memory_extractor() -> NoopSemanticMemoryExtractor:
    """real_agent Case 的默认抽取器：TurnCommitted 不触发任何抽取调用。"""
    return NoopSemanticMemoryExtractor()


def rule_extractor_for(fixture: str) -> RuleSemanticMemoryExtractor:
    """取 fixture 声明的规则抽取器（仅限注册了规则表的 fixture）。"""
    spec = FIXTURES[fixture]
    if spec.extractor_factory is None:
        raise KeyError(f"fixture {fixture} 未声明确定性抽取器")
    extractor = spec.extractor_factory()
    if not isinstance(extractor, RuleSemanticMemoryExtractor):
        raise KeyError(f"fixture {fixture} 的抽取器不是规则表实现")
    return extractor


__all__ = [
    "AVAILABILITY_DISTRACTOR_INPUTS",
    "FIXTURES",
    "EvalFixtureRefs",
    "EvalFixtureSpec",
    "FixtureContext",
    "noop_memory_extractor",
]
