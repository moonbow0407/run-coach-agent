"""Athlete State 的可解释依据：Signal 只描述证据，不单独构成医疗诊断。"""

from dataclasses import dataclass


@dataclass(frozen=True)  # 不可变数据类：信号一经生成不再修改
class AthleteStateSignal:
    """结构化状态依据，持久化在 AthleteStateSnapshot.signals。"""

    code: str  # 信号类型标识，如 high_subjective_fatigue（高主观疲劳）
    severity: str  # 严重程度：info / warning / moderate / high
    message: str  # 面向用户的中文解释，说明这条证据意味着什么
    evidence_refs: tuple[str, ...]  # 证据溯源引用，如 feedback:<id> / workout:<id>
