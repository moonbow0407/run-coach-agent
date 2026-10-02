"""AthleteStateEvaluatorV1：纯领域逻辑，不依赖仓储、时钟或 LLM。"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.coaching.domain.analysis.models import TrainingLoadAnalysis
from app.coaching.domain.analysis.training_load import is_quality_workout
from app.coaching.domain.athlete.models import (
    ALGORITHM_VERSION_V1,
    FatigueLevel,
    RecoveryLevel,
)
from app.coaching.domain.athlete.signals import AthleteStateSignal
from app.coaching.domain.workout.models import Workout, WorkoutFeedback, WorkoutType

# 疲劳 / 恢复只看最近 72 小时内的主观反馈（recency 窗口）。
_FATIGUE_LOOKBACK = timedelta(hours=72)
# "恢复良好"要求最近 24 小时没有质量课冲击。
_QUALITY_LOOKBACK = timedelta(hours=24)
# 置信度加分项的回看窗口：最近 14 天的训练样本。
_WORKOUT_LOOKBACK = timedelta(days=14)
# 置信度加分门槛：14 天内至少 3 次训练。
_MIN_WORKOUTS_FOR_CONFIDENCE = 3
# 高强度课型：疲劳 HIGH 判定中"较高疲劳 + 高强度课"组合规则的依据。
_HIGH_INTENSITY_TYPES = frozenset(
    {WorkoutType.TEMPO, WorkoutType.INTERVAL, WorkoutType.RACE}
)


@dataclass(frozen=True)
class AthleteStateEvidence:
    """Evaluator 的输入。Phase 3 不把计划完成率塞进 Evidence。"""

    as_of: datetime  # 评估基准时间：只使用此时间点之前的证据
    recent_workouts: tuple[Workout, ...]  # 近期训练记录
    recent_feedback: tuple[WorkoutFeedback, ...]  # 近期主观反馈
    training_load_analysis: TrainingLoadAnalysis  # 两窗负荷分析结果


@dataclass(frozen=True)
class AthleteStateAssessment:
    """Evaluator 输出。Application 再把它写成 Snapshot。"""

    fatigue_level: FatigueLevel | None  # 疲劳等级；证据不足为 None
    recovery_level: RecoveryLevel | None  # 恢复等级；证据不足为 None
    recent_training_load: float | None  # 当前 7 日窗可用 sRPE 负荷
    workout_completion_rate: None  # Phase 3 未实现计划完成率，恒为 None
    training_load_coverage: float | None  # 当前窗 sRPE 覆盖率
    confidence: float  # 结论置信度 0.2–1.0，由证据丰富程度决定
    algorithm_version: str  # 评估算法版本标识
    signals: tuple[AthleteStateSignal, ...]  # 可解释依据：结论来自哪些证据


class AthleteStateEvaluatorV1:
    """algorithm_version = phase3.v1。只读 Evidence，不做 I/O。"""

    algorithm_version = ALGORITHM_VERSION_V1

    def evaluate(self, evidence: AthleteStateEvidence) -> AthleteStateAssessment:
        """把负荷分析与主观反馈综合为疲劳 / 恢复结论与可解释信号。"""
        as_of = evidence.as_of
        # 未来训练（开始时间晚于基准时间）不参与评估。
        workouts = tuple(
            workout for workout in evidence.recent_workouts if workout.started_at <= as_of
        )
        workouts_by_id = {workout.id: workout for workout in workouts}
        # 防御性上界：即使仓储漏掉 created_at 过滤，未来报告也进不了评估。
        feedbacks = tuple(
            feedback
            for feedback in evidence.recent_feedback
            if feedback.created_at <= as_of
        )
        # 只保留 72 小时窗口内的反馈参与疲劳 / 恢复判定。
        feedback_72h = _feedback_in_window(
            feedbacks,
            start=as_of - _FATIGUE_LOOKBACK,
            as_of=as_of,
        )
        fatigue = _fatigue_level(feedback_72h, workouts_by_id)
        recovery = _recovery_level(feedback_72h, workouts, as_of)
        coverage = evidence.training_load_analysis.current.srpe_coverage
        recent_load = evidence.training_load_analysis.current.usable_srpe_load()
        # 收集可解释信号，供用户理解结论从何而来。
        signals = _signals(
            as_of=as_of,
            feedback_72h=feedback_72h,
            workouts=workouts,
            analysis=evidence.training_load_analysis,
            coverage=coverage,
        )
        return AthleteStateAssessment(
            fatigue_level=fatigue,
            recovery_level=recovery,
            recent_training_load=recent_load,
            workout_completion_rate=None,
            training_load_coverage=coverage,
            confidence=_confidence(as_of, feedback_72h, workouts, coverage),
            algorithm_version=self.algorithm_version,
            signals=signals,
        )


def _feedback_in_window(
    feedbacks: Sequence[WorkoutFeedback],
    *,
    start: datetime,
    as_of: datetime,
) -> tuple[WorkoutFeedback, ...]:
    """疲劳 / 恢复的 recency 语义：反馈在 start <= created_at <= as_of 内才算"最近"。

    用户"什么时候报告"才是主观状态的时间锚点；训练发生在哪天只决定
    该反馈关联的 workout 类型（HIGH 规则里的 quality 课判断），不决定 recency。
    """
    return tuple(
        feedback for feedback in feedbacks if start <= feedback.created_at <= as_of
    )


def _fatigue_level(
    feedback_72h: Sequence[WorkoutFeedback],
    workouts_by_id: dict,
) -> FatigueLevel | None:
    """按"高 → 中 → 低"的优先级从 72h 反馈推导疲劳等级。"""
    # 任一条反馈命中 HIGH 规则即判 HIGH（最保守优先）。
    if any(_is_high_fatigue(item, workouts_by_id) for item in feedback_72h):
        return FatigueLevel.HIGH
    if any(_is_moderate_fatigue(item) for item in feedback_72h):
        return FatigueLevel.MODERATE
    # 只有全部反馈都明确偏低才判 LOW；否则证据不足返回 None。
    explicit_low = [item for item in feedback_72h if _is_explicit_low(item)]
    if explicit_low and len(explicit_low) == len(feedback_72h):
        return FatigueLevel.LOW
    return None


def _is_high_fatigue(feedback: WorkoutFeedback, workouts_by_id: dict) -> bool:
    """HIGH 疲劳规则：极高单项、疲劳+酸痛双高、或较高疲劳叠加高强度课。"""
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    # 单项自评达到 8 即视为极高。
    if fatigue is not None and fatigue >= 8:
        return True
    if soreness is not None and soreness >= 8:
        return True
    # 疲劳与酸痛双高（7 + 6）的组合也判 HIGH。
    if fatigue is not None and fatigue >= 7 and soreness is not None and soreness >= 6:
        return True
    # 较高疲劳（7）叠加关联课次为高强度课时，判 HIGH。
    workout = workouts_by_id.get(feedback.workout_id)
    return (
        fatigue is not None
        and fatigue >= 7
        and workout is not None
        and workout.workout_type in _HIGH_INTENSITY_TYPES
    )


def _is_moderate_fatigue(feedback: WorkoutFeedback) -> bool:
    """MODERATE 疲劳规则：疲劳或酸痛任一自评达到 6。"""
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    return (fatigue is not None and fatigue >= 6) or (
        soreness is not None and soreness >= 6
    )


def _is_explicit_low(feedback: WorkoutFeedback) -> bool:
    """"明确偏低"：疲劳与酸痛都报告了且都不超过 4。"""
    fatigue = feedback.subjective_fatigue
    soreness = feedback.soreness
    return (
        fatigue is not None
        and soreness is not None
        and fatigue <= 4
        and soreness <= 4
    )


def _recovery_level(
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    as_of: datetime,
) -> RecoveryLevel | None:
    """按"差 → 一般 → 良好"的优先级推导恢复等级。"""
    # 任一极高自评（≥8）直接判恢复差。
    if any(
        (item.subjective_fatigue is not None and item.subjective_fatigue >= 8)
        or (item.soreness is not None and item.soreness >= 8)
        for item in feedback_72h
    ):
        return RecoveryLevel.POOR
    # 任一中等自评（≥6）判恢复一般。
    if any(
        (item.subjective_fatigue is not None and item.subjective_fatigue >= 6)
        or (item.soreness is not None and item.soreness >= 6)
        for item in feedback_72h
    ):
        return RecoveryLevel.FAIR
    # 全部反馈明确偏低，且最近 24 小时没有质量课冲击，才判恢复良好。
    explicit_low = [item for item in feedback_72h if _is_explicit_low(item)]
    if explicit_low and len(explicit_low) == len(feedback_72h):
        quality_start = as_of - _QUALITY_LOOKBACK
        has_recent_quality = any(
            is_quality_workout(workout.workout_type)
            and quality_start <= workout.started_at <= as_of
            for workout in workouts
        )
        if not has_recent_quality:
            return RecoveryLevel.GOOD
    return None


def _confidence(
    as_of: datetime,
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    coverage: float | None,
) -> float:
    """置信度从 0.2 起步，按证据丰富程度累加，封顶 1.0。"""
    value = 0.20
    # 有 72h 内反馈：+0.4（主观状态是疲劳 / 恢复的核心证据）。
    if feedback_72h:
        value += 0.40
    lookback_start = as_of - _WORKOUT_LOOKBACK
    recent_count = sum(
        1 for workout in workouts if lookback_start <= workout.started_at <= as_of
    )
    # 最近 14 天训练样本充足：+0.2。
    if recent_count >= _MIN_WORKOUTS_FOR_CONFIDENCE:
        value += 0.20
    # 负荷覆盖达标：+0.2（负荷数据可信）。
    if coverage is not None and coverage >= 0.5:
        value += 0.20
    return min(1.0, max(0.20, value))


def _signals(
    *,
    as_of: datetime,
    feedback_72h: Sequence[WorkoutFeedback],
    workouts: Sequence[Workout],
    analysis: TrainingLoadAnalysis,
    coverage: float | None,
) -> tuple[AthleteStateSignal, ...]:
    """从证据中收集可解释信号；每条信号描述一项事实，不单独构成诊断。"""
    signals: list[AthleteStateSignal] = []
    quality_start = as_of - _FATIGUE_LOOKBACK
    # 逐条反馈映射为疲劳 / 酸痛 / 高 RPE 信号。
    for feedback in feedback_72h:
        refs = _feedback_refs(feedback)
        if feedback.subjective_fatigue is not None and feedback.subjective_fatigue >= 8:
            signals.append(
                AthleteStateSignal(
                    code="high_subjective_fatigue",
                    severity="high",
                    message="最近 72 小时报告了很高的主观疲劳。",
                    evidence_refs=refs,
                )
            )
        elif feedback.subjective_fatigue is not None and feedback.subjective_fatigue >= 6:
            signals.append(
                AthleteStateSignal(
                    code="moderate_subjective_fatigue",
                    severity="moderate",
                    message="最近 72 小时报告了中等主观疲劳。",
                    evidence_refs=refs,
                )
            )
        if feedback.soreness is not None and feedback.soreness >= 8:
            signals.append(
                AthleteStateSignal(
                    code="high_soreness",
                    severity="high",
                    message="最近 72 小时报告了很高的酸痛。",
                    evidence_refs=refs,
                )
            )
        if feedback.perceived_exertion is not None and feedback.perceived_exertion >= 8:
            signals.append(
                AthleteStateSignal(
                    code="hard_session",
                    severity="info",
                    message="最近存在高 RPE 课次；高 RPE 本身不单独推出 HIGH 疲劳。",
                    evidence_refs=refs,
                )
            )
    # 72h 内存在质量课（节奏 / 间歇 / 比赛）→ info 信号。
    quality_workouts = [
        workout
        for workout in workouts
        if is_quality_workout(workout.workout_type)
        and quality_start <= workout.started_at <= as_of
    ]
    if quality_workouts:
        signals.append(
            AthleteStateSignal(
                code="recent_quality_session",
                severity="info",
                message="最近 72 小时存在质量课（节奏 / 间歇 / 比赛）。",
                evidence_refs=tuple(f"workout:{item.id}" for item in quality_workouts),
            )
        )
    # 覆盖不足 → 警告：部分负荷不能当成完整训练负荷使用。
    if coverage is None or coverage < 0.5:
        signals.append(
            AthleteStateSignal(
                code="low_training_load_coverage",
                severity="warning",
                message="近期 sRPE 覆盖不足，不能把部分负荷当成完整训练负荷。",
                evidence_refs=("training_load:current",),
            )
        )
    # 负荷上升趋势 → 警告（仅描述性，不是伤病风险结论）。
    ratio = analysis.load_change_ratio
    if ratio is not None and ratio > 1.0:
        signals.append(
            AthleteStateSignal(
                code="recent_load_increase",
                severity="warning",
                message="近期训练负荷相对前一窗口上升。这是描述性趋势，不是伤病风险。",
                evidence_refs=("training_load:current", "training_load:previous"),
            )
        )
    # 72h 内没有任何反馈 → 警告：疲劳与恢复无法确定。
    if not feedback_72h:
        signals.append(
            AthleteStateSignal(
                code="insufficient_recent_feedback",
                severity="warning",
                message="最近 72 小时缺少主观反馈，疲劳与恢复无法确定。",
                evidence_refs=(),
            )
        )
    # 去重：同一 code 只保留第一次出现，避免多条 Feedback 重复堆叠。
    seen: set[str] = set()
    unique: list[AthleteStateSignal] = []
    for signal in signals:
        if signal.code in seen:
            continue
        seen.add(signal.code)
        unique.append(signal)
    return tuple(unique)


def _feedback_refs(feedback: WorkoutFeedback) -> tuple[str, ...]:
    """构造证据引用：指向反馈本身与其关联的训练课次。"""
    return (f"feedback:{feedback.id}", f"workout:{feedback.workout_id}")
