"""PromptRenderer 的 native 消息序列还原。"""

from datetime import UTC, datetime

from app.agent.context.bundle import (
    ContextBundle,
    MessageView,
    WorkingContext,
)
from app.agent.models.action import ToolCallAction
from app.agent.models.observation import Observation
from app.agent.reasoning.models import (
    AssistantMessage,
    AssistantToolCall,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from app.agent.reasoning.prompt_renderer import PromptRenderer
from app.agent.reasoning.state import ReasoningState
from app.tools.resolver.resolver import VisibleTool


def _bundle(recent: list[MessageView] | None = None) -> ContextBundle:
    """构造空上下文 bundle：无记忆、无状态，只带系统提示与当前输入。"""
    return ContextBundle(
        system="你是教练。",
        working_context=WorkingContext(
            goal=None,
            active_plan=None,
            latest_athlete_state=None,
            critical_constraints=(),
        ),
        recent_messages=recent or [],
        semantic_memories=[],
        episodic_memories=[],
        current_input="最近训练状态怎么样？",
        memory_policy_version="test.v1",
        semantic_truncated=False,
        episodic_truncated=False,
    )


def _visible_tool() -> VisibleTool:
    """构造一个最小可见工具定义。"""
    return VisibleTool(
        name="get_recent_workouts",
        description="读取训练记录",
        parameters_schema={"type": "object", "properties": {"days": {}}},
    )


def test_basic_sequence_system_history_current_input() -> None:
    """验证：无历史时消息序列仅 system + 当前输入；工具走独立 tools 字段而非塞进提示词。"""
    renderer = PromptRenderer()
    request = renderer.render(_bundle(), ReasoningState(), [_visible_tool()])
    kinds = [type(message).__name__ for message in request.messages]
    assert kinds == ["SystemMessage", "UserMessage"]
    assert isinstance(request.messages[0], SystemMessage)
    assert "你是教练。" in request.messages[0].content
    # system 块不含 Tool Schema 与 JSON 输出契约。
    assert "get_recent_workouts" not in request.messages[0].content
    assert "output_contract" not in request.messages[0].content
    assert len(request.tools) == 1
    assert request.tools[0].name == "get_recent_workouts"


def test_history_messages_become_user_assistant_text() -> None:
    """验证：历史消息按 role 还原为 user/assistant 文本，当前输入排在最后。"""
    renderer = PromptRenderer()
    recent = [
        MessageView(role="user", content="之前的问题", created_at=datetime.now(UTC)),
        MessageView(role="assistant", content="之前的回答", created_at=datetime.now(UTC)),
    ]
    request = renderer.render(_bundle(recent), ReasoningState(), [])
    messages = request.messages
    assert isinstance(messages[1], UserMessage) and messages[1].content == "之前的问题"
    assert isinstance(messages[2], AssistantMessage) and messages[2].content == "之前的回答"
    assert isinstance(messages[3], UserMessage) and messages[3].content == "最近训练状态怎么样？"


def test_interactions_become_native_tool_call_and_result() -> None:
    """验证：本次 Run 的工具交互还原为原生 tool call / tool result 消息对。"""
    renderer = PromptRenderer()
    state = ReasoningState()
    state.append(
        ToolCallAction(
            tool="get_recent_workouts",
            arguments={"days": 14},
            model_call_id="call_1",
        )
    )
    state.append(
        Observation(
            source="get_recent_workouts",
            status="success",
            data=[{"distance_m": 8000}],
            model_call_id="call_1",
        )
    )
    request = renderer.render(_bundle(), state, [_visible_tool()])
    messages = request.messages
    # system -> user input -> assistant tool call -> tool result，不打包成 user 文本块。
    assert isinstance(messages[2], AssistantToolCall)
    assert messages[2].tool == "get_recent_workouts"
    assert messages[2].arguments == {"days": 14}
    assert messages[2].model_call_id == "call_1"
    assert isinstance(messages[3], ToolResultMessage)
    assert messages[3].model_call_id == "call_1"
    assert '"status": "success"' in messages[3].content
    # 交互不再以 user 消息表达。
    assert not any(
        isinstance(message, UserMessage) and "已经发生" in message.content
        for message in messages
    )
