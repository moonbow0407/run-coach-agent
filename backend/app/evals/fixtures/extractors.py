"""Eval 确定性语义记忆抽取器：按固定关键词规则产出候选，不调用模型。

- real_agent Case 注入 No-op 抽取器，防止 TurnCommitted 触发与评分无关的
  额外抽取 LLM 调用（PHASE 6 §10）。
- Memory Case 使用规则抽取器产生候选，但候选仍走正式 Projection Service、
  Repository merge 与真实 embedding，生命周期语义不被 Eval 旁路。
"""

import re
from datetime import datetime

from app.agent.models.message import Message
from app.memory.domain.semantic import MemoryOrigin, SemanticMemoryType
from app.memory.ports.extractor import ExtractedSemanticCandidate


class NoopSemanticMemoryExtractor:
    """恒定不产出候选：用于 Tool / Coaching Case，隔离记忆投影噪音。"""

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        return ()


class _Rule:
    """单条确定性抽取规则：命中关键词即产出固定候选。"""

    __slots__ = ("alias", "content", "needle", "subject_key", "type", "value")

    def __init__(
        self,
        *,
        needle: str,
        alias: str,
        type: SemanticMemoryType,
        subject_key: str,
        value: object,
        content: str,
    ) -> None:
        self.needle = needle  # 用户消息包含该子串时命中
        self.alias = alias  # fixture alias：解析为真实记忆 ID 的稳定逻辑名
        self.type = type
        self.subject_key = subject_key
        self.value = value
        self.content = content


class RuleSemanticMemoryExtractor:
    """表驱动确定性抽取器：按声明顺序匹配第一条命中的规则。"""

    def __init__(self, rules: tuple[_Rule, ...]) -> None:
        self._rules = rules

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        for rule in self._rules:
            if rule.needle in user_message.content:
                return (
                    ExtractedSemanticCandidate(
                        type=rule.type,
                        origin=MemoryOrigin.EXPLICIT,
                        subject_key=rule.subject_key,
                        value=rule.value,  # type: ignore[arg-type]
                        content=rule.content,
                        valid_from=committed_at,
                        valid_until=None,
                    ),
                )
        return ()

    @property
    def alias_by_needle(self) -> dict[str, str]:
        """规则命中关键词 → fixture alias，供 fixture 按 message 反查。"""
        return {rule.needle: rule.alias for rule in self._rules}

    @property
    def rules(self) -> tuple[_Rule, ...]:
        return self._rules


# 作息偏好纠正：晚上 → 早上（memory_conflict_schedule_001）。
SCHEDULE_PREFERENCE_RULES = (
    _Rule(
        needle="晚上训练",
        alias="schedule_evening",
        type=SemanticMemoryType.SCHEDULE_PREFERENCE,
        subject_key="preferred_training_time",
        value="evening",
        content="用户长期更喜欢晚上训练",
    ),
    _Rule(
        needle="早上训练",
        alias="schedule_morning",
        type=SemanticMemoryType.SCHEDULE_PREFERENCE,
        subject_key="preferred_training_time",
        value="morning",
        content="用户长期更喜欢早上训练",
    ),
)

# 每周训练频率纠正：3 次 → 5 次（memory_conflict_frequency_001）。
_TRAINING_FREQUENCY_PATTERN = re.compile(r"每周(?:最多训练|可以训练)\s*(\d+)\s*次")


class TrainingFrequencyExtractor:
    """按正则抽取每周可训练次数；新旧断言共享 subject_key 以触发取代。"""

    SUBJECT_KEY = "weekly:training:frequency"
    OLD_VALUE = 3  # 旧断言值（memory_conflict_frequency_001 的旧记忆）
    NEW_VALUE = 5  # 新断言值

    async def extract(
        self,
        *,
        user_message: Message,
        assistant_message: Message,
        committed_at: datetime,
        supported_types: tuple[SemanticMemoryType, ...],
    ) -> tuple[ExtractedSemanticCandidate, ...]:
        match = _TRAINING_FREQUENCY_PATTERN.search(user_message.content)
        if match is None:
            return ()
        value = int(match.group(1))
        return (
            ExtractedSemanticCandidate(
                type=SemanticMemoryType.AVAILABILITY_CONSTRAINT,
                origin=MemoryOrigin.EXPLICIT,
                subject_key=self.SUBJECT_KEY,
                value=value,
                content=f"用户每周可以训练 {value} 次",
                valid_from=committed_at,
                valid_until=None,
            ),
        )


# 可用时间目标记忆 + 11 条干扰项（memory_semantic_recall_001 / context_injection）。
AVAILABILITY_DISTRACTOR_RULES = (
    _Rule(
        needle="只有晚上能训练",
        alias="weekday_evening_availability",
        type=SemanticMemoryType.AVAILABILITY_CONSTRAINT,
        subject_key="weekday:training:window",
        value="evening_only",
        content="用户工作日只有晚上能训练",
    ),
    _Rule(
        needle="周三晚上都有课",
        alias="wednesday_evening_busy",
        type=SemanticMemoryType.AVAILABILITY_CONSTRAINT,
        subject_key="weekly:wednesday:evening",
        value=False,
        content="用户周三晚上长期无法训练",
    ),
    _Rule(
        needle="按距离而不是按时间",
        alias="metric_preference_distance",
        type=SemanticMemoryType.TRAINING_PREFERENCE,
        subject_key="workout:metric:preference",
        value="distance",
        content="用户更喜欢按距离制定训练",
    ),
    _Rule(
        needle="不喜欢跑步机",
        alias="environment_no_treadmill",
        type=SemanticMemoryType.ENVIRONMENT_PREFERENCE,
        subject_key="environment:treadmill",
        value=False,
        content="用户不喜欢跑步机",
    ),
    _Rule(
        needle="赛后需要两天恢复",
        alias="post_race_recovery_two_days",
        type=SemanticMemoryType.RECOVERY_PATTERN,
        subject_key="recovery:post_race:days",
        value=2,
        content="用户赛后通常需要两天恢复",
    ),
    _Rule(
        needle="回复尽量简短",
        alias="communication_brief",
        type=SemanticMemoryType.COMMUNICATION_PREFERENCE,
        subject_key="communication:reply:style",
        value="brief",
        content="用户偏好简短回复",
    ),
    _Rule(
        needle="连续两天高强度恢复差",
        alias="consecutive_hard_poor_recovery",
        type=SemanticMemoryType.TRAINING_RESPONSE_PATTERN,
        subject_key="response:consecutive:hard",
        value="poor_recovery",
        content="用户连续两天高强度后恢复较差",
    ),
    _Rule(
        needle="雨天改在室内做力量",
        alias="rainy_day_indoor_strength",
        type=SemanticMemoryType.ENVIRONMENT_PREFERENCE,
        subject_key="environment:rainy:plan",
        value="indoor_strength",
        content="用户雨天改为室内力量训练",
    ),
    _Rule(
        needle="周末早上训练",
        alias="weekend_morning_training",
        type=SemanticMemoryType.SCHEDULE_PREFERENCE,
        subject_key="schedule:weekend:time",
        value="morning",
        content="用户周末习惯早晨训练",
    ),
    _Rule(
        needle="按心率控制强度",
        alias="race_intensity_heart_rate",
        type=SemanticMemoryType.GOAL_PREFERENCE,
        subject_key="goal:race:intensity",
        value="heart_rate",
        content="用户比赛期间按心率控制强度",
    ),
    _Rule(
        needle="空腹晨跑容易低血糖",
        alias="no_fasted_morning_run",
        type=SemanticMemoryType.TRAINING_PREFERENCE,
        subject_key="training:fasted:run",
        value=False,
        content="用户不空腹晨跑",
    ),
    _Rule(
        needle="凉爽天气跑步",
        alias="prefers_cool_weather",
        type=SemanticMemoryType.ENVIRONMENT_PREFERENCE,
        subject_key="environment:weather",
        value="cool",
        content="用户偏好凉爽天气跑步",
    ),
)


def build_rule_extractor(rules: tuple[_Rule, ...]) -> RuleSemanticMemoryExtractor:
    """按规则表构造确定性抽取器。"""
    return RuleSemanticMemoryExtractor(rules)
