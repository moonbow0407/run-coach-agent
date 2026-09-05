"""CoachingSafetyPolicy：根据跑者状态与反馈备注判定工具是否可执行。

纯策略逻辑，不访问 IO；SafetyGate 负责取证后调用本模块。
"""

from dataclasses import dataclass

from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.tools.registry.definition import ToolRisk
from app.tools.safety.constants import (
    ALLOWED_UNDER_FATIGUE_CONSTRAINT,
    ALLOWED_UNDER_INJURY,
    FLAG_HIGH_FATIGUE_POOR_RECOVERY,
    FLAG_INJURY_KEYWORDS,
    INCREASE_LOAD_TAGS,
    INCREASE_LOAD_TOOLS,
    INJURY_KEYWORDS,
    REASON_FATIGUE_BLOCKS_NON_REDUCE,
    REASON_INCREASE_LOAD_FORBIDDEN,
    REASON_INJURY_BLOCKS_NON_REST,
)


@dataclass(frozen=True)
class SafetyStatus:
    """当前用户的安全约束快照，供 get_safety_status 与拦截共用。"""

    ok: bool  # True 表示无限制性 flag
    flags: tuple[str, ...]  # 触发的约束 flag 码
    reasons: tuple[str, ...]  # 面向模型/用户的中文说明


@dataclass(frozen=True)
class SafetyDecision:
    """单次工具调用的放行 / 拦截结果。"""

    allowed: bool
    reason_code: str | None  # 拦截时的结构化原因码；放行为 None
    message: str | None  # 拦截时的可读说明
    status: SafetyStatus  # 判定当时的约束快照


class CoachingSafetyPolicy:
    """可配置常量驱动的最小安全策略。"""

    def evaluate_status(
        self,
        *,
        fatigue_level: FatigueLevel | None,
        recovery_level: RecoveryLevel | None,
        feedback_notes: list[str],
    ) -> SafetyStatus:
        """汇总疲劳/恢复与伤痛关键词，生成 flags 与 reasons。"""
        flags: list[str] = []
        reasons: list[str] = []

        if fatigue_level == FatigueLevel.HIGH and recovery_level == RecoveryLevel.POOR:
            flags.append(FLAG_HIGH_FATIGUE_POOR_RECOVERY)
            reasons.append("最新状态为高疲劳且恢复差：仅允许降负荷/转轻松跑草案与只读工具")

        matched = _matched_injury_keywords(feedback_notes)
        if matched:
            flags.append(FLAG_INJURY_KEYWORDS)
            sample = "、".join(matched[:5])
            reasons.append(f"近期反馈备注含伤痛关键词（{sample}）：调整提案仅可降负荷/改休息")

        return SafetyStatus(ok=not flags, flags=tuple(flags), reasons=tuple(reasons))

    def decide(
        self,
        *,
        tool_name: str,
        risk: ToolRisk,
        tags: tuple[str, ...],
        status: SafetyStatus,
    ) -> SafetyDecision:
        """在已有 SafetyStatus 上判定工具是否允许执行。

        只约束 DRAFT / MUTATING；只读与分析工具一律放行。
        """
        if risk not in {ToolRisk.DRAFT, ToolRisk.MUTATING}:
            return SafetyDecision(allowed=True, reason_code=None, message=None, status=status)

        # 存在安全约束时，拒绝一切加负荷意图（工具名或 tags）。
        if not status.ok and _is_increase_load_intent(tool_name, tags):
            return SafetyDecision(
                allowed=False,
                reason_code=REASON_INCREASE_LOAD_FORBIDDEN,
                message=(
                    f"安全策略拒绝加负荷工具 {tool_name}："
                    + ("；".join(status.reasons) if status.reasons else "不允许提升训练负荷")
                ),
                status=status,
            )

        if status.ok:
            return SafetyDecision(allowed=True, reason_code=None, message=None, status=status)

        flag_set = set(status.flags)

        # 伤痛优先：仅允许减负荷→休息类提案。
        if FLAG_INJURY_KEYWORDS in flag_set and tool_name not in ALLOWED_UNDER_INJURY:
            return SafetyDecision(
                allowed=False,
                reason_code=REASON_INJURY_BLOCKS_NON_REST,
                message=(f"安全策略拦截 {tool_name}：伤痛信号下仅允许降负荷/改休息提案"),
                status=status,
            )

        # 高疲劳 + 差恢复：仅允许降负荷 / 转轻松跑。
        if (
            FLAG_HIGH_FATIGUE_POOR_RECOVERY in flag_set
            and tool_name not in ALLOWED_UNDER_FATIGUE_CONSTRAINT
        ):
            return SafetyDecision(
                allowed=False,
                reason_code=REASON_FATIGUE_BLOCKS_NON_REDUCE,
                message=(f"安全策略拦截 {tool_name}：高疲劳且恢复差时仅允许降负荷或转轻松跑草案"),
                status=status,
            )

        return SafetyDecision(allowed=True, reason_code=None, message=None, status=status)


def _matched_injury_keywords(notes: list[str]) -> list[str]:
    """扫描备注文本，返回命中的关键词（去重、保序）。"""
    hits: list[str] = []
    seen: set[str] = set()
    for note in notes:
        if not note:
            continue
        lowered = note.lower()
        for keyword in sorted(INJURY_KEYWORDS, key=len, reverse=True):
            needle = keyword.lower()
            if needle in lowered and keyword not in seen:
                seen.add(keyword)
                hits.append(keyword)
    return hits


def _is_increase_load_intent(tool_name: str, tags: tuple[str, ...]) -> bool:
    """工具名或 tags 是否表达加负荷意图。"""
    if tool_name in INCREASE_LOAD_TOOLS:
        return True
    return bool(INCREASE_LOAD_TAGS.intersection(tags))
