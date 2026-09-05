"""AgentRun 轻量检查点：支持失败后从最后一次成功 Observation 继续 Reason–Act。"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from app.common.ids import new_id


@dataclass(frozen=True)
class AgentRunCheckpoint:
    """一次可恢复的运行快照：不含完整 Prompt，只含续跑所需工作状态。"""

    id: UUID
    run_id: UUID
    turn_id: UUID
    user_id: UUID
    thread_id: UUID
    step_index: int  # 下一轮 Reason 的步序号（已完成 observation 之后）
    current_input: str  # 本轮用户原文，续跑时重新装配上下文
    interactions: tuple[dict[str, Any], ...]  # 序列化后的 ToolCall/Observation 轨迹
    discovered_tool_names: tuple[str, ...]  # Run-local 已解锁工具名
    created_at: datetime


def new_checkpoint(
    *,
    run_id: UUID,
    turn_id: UUID,
    user_id: UUID,
    thread_id: UUID,
    step_index: int,
    current_input: str,
    interactions: list[dict[str, Any]],
    discovered_tool_names: list[str] | tuple[str, ...],
    created_at: datetime,
) -> AgentRunCheckpoint:
    """组装一条新检查点（生成新 id）。"""
    return AgentRunCheckpoint(
        id=new_id(),
        run_id=run_id,
        turn_id=turn_id,
        user_id=user_id,
        thread_id=thread_id,
        step_index=step_index,
        current_input=current_input,
        interactions=tuple(interactions),
        discovered_tool_names=tuple(discovered_tool_names),
        created_at=created_at,
    )
