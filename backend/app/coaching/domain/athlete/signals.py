"""Athlete State 的可解释依据：Signal 只描述证据，不单独构成医疗诊断。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AthleteStateSignal:
    """结构化状态依据，持久化在 AthleteStateSnapshot.signals。"""

    code: str
    severity: str
    message: str
    evidence_refs: tuple[str, ...]
