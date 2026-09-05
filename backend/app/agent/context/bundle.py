"""上下文相关数据结构。

ContextBundle 是发给 Reasoner 的完整上下文合同；各 *View 是领域对象
在上下文中的只读投影（只含 Prompt 需要的字段，不含 ORM 与业务方法）。
Phase 2 起 ContextBundle 不再携带任何 Tool 定义：可见 Tool 由
ReasoningContext.visible_tools 每轮单独提供。
"""

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.agent.models.message import Message


# frozen=True：不可变数据类，视图与 Bundle 组装后只读
@dataclass(frozen=True)
class GoalView:
    """当前训练目标在上下文中的视图。"""

    id: UUID
    goal_type: str  # 目标类型（如 5km / 半马 / 全马）
    race_date: date | None  # 比赛日期
    race_distance_m: int | None  # 比赛距离（米）
    target_time_s: int | None  # 目标完赛时间（秒）
    status: str  # 目标状态


@dataclass(frozen=True)
class PlannedSessionView:
    """计划课次在上下文中的视图。"""

    scheduled_date: date  # 计划训练日期
    session_type: str  # 课次类型（如轻松跑 / 间歇）
    title: str  # 课次标题
    prescription: dict[str, object]  # 训练处方：配速 / 距离等结构化要求


@dataclass(frozen=True)
class PlanSummary:
    """受 Tool Result Budget 约束的计划摘要视图。

    与 get_active_plan Tool 共用同一摘要语义：sessions 只覆盖
    [window_start, window_end]（当前 ISO 周 ∪ 未来 14 天）且不超过
    20 条；truncated 表示超出上限被显式截断。ContextBundle 不携带
    完整长期计划。
    """

    id: UUID
    version: int  # 计划版本号
    starts_on: date  # 计划开始日期
    ends_on: date  # 计划结束日期
    status: str  # 计划状态
    sessions: tuple[PlannedSessionView, ...]  # 窗口内的课次摘要
    window_start: date  # 摘要覆盖窗口的起点
    window_end: date  # 摘要覆盖窗口的终点
    truncated: bool  # 课次超出上限被显式截断时为 True


@dataclass(frozen=True)
class AthleteStateView:
    """最新跑者状态快照在上下文中的视图（已有快照，不是现场计算）。"""

    version: int  # 快照版本号
    as_of: datetime  # 快照生成时间
    fatigue_level: str | None  # 疲劳等级
    recovery_level: str | None  # 恢复等级
    recent_training_load: float | None  # 近期训练负荷
    workout_completion_rate: float | None  # 课次完成率
    confidence: float | None  # 快照置信度
    algorithm_version: str  # 生成快照的算法版本


@dataclass(frozen=True)
class FeedbackSummaryView:
    """近期训练主观反馈摘要：注入热上下文，减少模型为读反馈再搜工具。"""

    workout_id: UUID
    started_on: date  # 训练日期（本地日历日）
    perceived_exertion: int | None  # RPE / 用力程度（1–10）
    subjective_fatigue: int | None  # 主观疲劳（1–10）
    note_snippet: str | None  # 备注截断片段


@dataclass(frozen=True)
class WorkingContext:
    """热上下文：跑者现在怎么样的当前结论。"""

    goal: GoalView | None  # 当前生效目标（新用户可能没有）
    active_plan: PlanSummary | None  # 当前生效计划摘要
    latest_athlete_state: AthleteStateView | None  # 最新跑者状态快照
    recent_feedback: tuple[FeedbackSummaryView, ...]  # 最近若干条反馈摘要
    critical_constraints: tuple[str, ...]  # 必须遵守的硬性约束


@dataclass(frozen=True)
class MessageView:
    """历史 committed 消息在上下文中的视图。"""

    role: str  # user 或 assistant
    content: str  # 消息正文
    created_at: datetime  # 发送时间


@dataclass(frozen=True)
class MemoryView:
    """语义记忆的精简视图，不携带 embedding 或 Evidence graph。"""

    id: UUID
    type: str  # 记忆类型
    content: str  # 记忆内容
    origin: str  # 记忆来源
    confidence: float  # 可信度
    valid_from: datetime  # 生效起始时间
    valid_until: datetime | None  # 失效时间，None 表示长期有效


@dataclass(frozen=True)
class EpisodeView:
    """已完成情节记忆的精简视图。"""

    id: UUID
    type: str  # 情节类型
    summary: str  # 情节摘要
    started_at: datetime  # 情节开始时间
    ended_at: datetime  # 情节结束时间
    importance: float  # 重要度，用于检索排序


@dataclass(frozen=True)
class MemoryContextResult:
    """MemoryContextProvider 的结构化检索结果：视图 + 检索策略元数据。

    policy_version 与 truncation 供 Context Manifest 记录本轮检索口径，
    不作为业务事实参与 Prompt 渲染。
    """

    semantic: tuple[MemoryView, ...]  # 入选的语义记忆视图
    episodic: tuple[EpisodeView, ...]  # 入选的情节记忆视图
    policy_version: str  # 产生本结果的重排与预算策略版本
    semantic_truncated: bool  # 语义记忆是否被条数 / 预算截断
    episodic_truncated: bool  # 情节记忆是否被条数 / 预算截断


@dataclass(frozen=True)
class ContextManifest:
    """本轮注入模型的上下文清单：只记 ID、版本与裁剪元数据。

    禁止持久化完整 Prompt、对话正文、Memory 内容或隐藏推理。
    """

    goal_id: UUID | None  # 当前生效目标 ID
    plan_id: UUID | None  # 当前生效计划 ID
    plan_version: int | None  # 当前生效计划版本号
    athlete_state_version: int | None  # 最新跑者状态快照版本号
    athlete_state_as_of: datetime | None  # 状态快照的证据截止时间
    semantic_memory_ids: tuple[UUID, ...]  # 本轮注入的语义记忆 ID
    episodic_memory_ids: tuple[UUID, ...]  # 本轮注入的情节记忆 ID
    memory_policy_version: str  # 记忆检索策略版本
    semantic_truncated: bool  # 语义记忆是否被截断
    episodic_truncated: bool  # 情节记忆是否被截断


@dataclass(frozen=True)
class ContextBundle:
    """发给 Reasoner 的完整上下文合同。

    semantic/episodic memories 由受预算约束的真实检索 Provider 提供；
    检索元数据（policy_version / truncation）供 Context Manifest 使用。
    """

    system: str  # 教练 system 指令
    working_context: WorkingContext  # 热上下文
    recent_messages: list[MessageView]  # 本线程已提交的历史消息
    semantic_memories: list[MemoryView]  # 语义记忆
    episodic_memories: list[EpisodeView]  # 情节记忆
    current_input: str  # 本轮用户输入原文
    memory_policy_version: str  # 记忆检索策略版本
    semantic_truncated: bool  # 语义记忆是否被截断
    episodic_truncated: bool  # 情节记忆是否被截断

    def context_manifest(self) -> ContextManifest:
        """从装配结果提取上下文清单：只取身份、版本与检索元数据。"""
        state = self.working_context.latest_athlete_state
        plan = self.working_context.active_plan
        goal = self.working_context.goal
        return ContextManifest(
            goal_id=goal.id if goal else None,
            plan_id=plan.id if plan else None,
            plan_version=plan.version if plan else None,
            athlete_state_version=state.version if state else None,
            athlete_state_as_of=state.as_of if state else None,
            semantic_memory_ids=tuple(item.id for item in self.semantic_memories),
            episodic_memory_ids=tuple(item.id for item in self.episodic_memories),
            memory_policy_version=self.memory_policy_version,
            semantic_truncated=self.semantic_truncated,
            episodic_truncated=self.episodic_truncated,
        )


@dataclass(frozen=True)
class ContextAssemblyRequest:
    """一次上下文装配请求。timestamp 是本次请求的可信时间基准。"""

    user_id: UUID
    thread_id: UUID
    turn_id: UUID
    timestamp: datetime
    current_input: str  # 本轮用户输入原文


def message_to_view(message: Message) -> MessageView:
    """领域消息转为上下文只读视图（丢弃 thread / turn 归属等无关字段）。"""
    return MessageView(
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
    )
