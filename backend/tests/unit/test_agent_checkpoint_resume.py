"""AgentRuntime 检查点：成功 Observation 后落盘，失败后可从 step_index 续跑。"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agent.context.bundle import ContextBundle, WorkingContext
from app.agent.lifecycle.dispatcher import LifecycleDispatcher
from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.models.checkpoint import AgentRunCheckpoint
from app.agent.reasoning.scripted import ScriptedReasoner
from app.agent.runtime.agent_runtime import AgentRuntime
from app.agent.runtime.run_context import AgentTurnCommand
from app.common.clock import FrozenClock
from app.common.errors import ReasonerError
from app.infrastructure.database.repositories.checkpoint import InMemoryAgentCheckpointStore
from app.tools.executor.executor import ToolExecutor
from app.tools.registry.registry import ToolRegistry
from app.tools.resolver.resolver import ToolResolver
from app.tools.runtime import ToolRuntime
from app.tools.search.keyword_search import KeywordToolSearch
from tests.unit.tool_helpers import SampleTool

NOW = datetime(2026, 9, 5, 2, 0, tzinfo=UTC)


class _FakeAssembler:
    """返回固定空上下文，避免依赖真实仓储。"""

    async def assemble(self, request):
        return ContextBundle(
            system="test",
            working_context=WorkingContext(
                goal=None,
                active_plan=None,
                latest_athlete_state=None,
                recent_feedback=(),
                critical_constraints=(),
            ),
            recent_messages=[],
            semantic_memories=[],
            episodic_memories=[],
            current_input=request.current_input,
            memory_policy_version="test",
            semantic_truncated=False,
            episodic_truncated=False,
        )


class _NoopTrace:
    async def record_context(self, **kwargs) -> None:
        return None

    async def record_reasoning(self, **kwargs) -> None:
        return None

    async def record_action(self, **kwargs) -> None:
        return None

    async def record_observation(self, **kwargs) -> None:
        return None

    async def record_final(self, **kwargs) -> None:
        return None


def _tool_runtime() -> ToolRuntime:
    search = KeywordToolSearch()
    registry = ToolRegistry(search=search)
    registry.register(SampleTool("alpha", always_on=True))
    resolver = ToolResolver(registry=registry)
    executor = ToolExecutor(registry=registry, resolver=resolver)
    return ToolRuntime(registry=registry, resolver=resolver, executor=executor)


def _command(*, run_id, turn_id, thread_id, user_id, resume: bool = False) -> AgentTurnCommand:
    return AgentTurnCommand(
        user_id=user_id,
        thread_id=thread_id,
        turn_id=turn_id,
        run_id=run_id,
        request_id=uuid4(),
        trace_id=uuid4(),
        timestamp=NOW,
        current_input="请帮我看看训练",
        resume=resume,
    )


@pytest.mark.asyncio
async def test_checkpoint_saved_after_observation_and_resume_continues() -> None:
    """验证：工具成功后写入检查点；崩溃后续跑时 ReasoningState 已含先前交互。"""
    store = InMemoryAgentCheckpointStore()
    runtime_ids = {
        "user_id": uuid4(),
        "thread_id": uuid4(),
        "turn_id": uuid4(),
        "run_id": uuid4(),
    }

    # 第一段：调一次工具后在下一轮 Reason 崩溃。
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(tool="alpha", arguments={"value": 1}, model_call_id="c1"),
            # 第二步故意失败，模拟 TurnFailed。
        ]
    )

    class CrashAfterToolReasoner:
        def __init__(self, inner: ScriptedReasoner) -> None:
            self._inner = inner
            self.seen_contexts = inner.seen_contexts

        async def reason(self, context, on_text_delta=None):
            if self._inner._index >= 1:
                raise ReasonerError("simulated crash after tool")
            return await self._inner.reason(context, on_text_delta=on_text_delta)

    runtime = AgentRuntime(
        reasoner=CrashAfterToolReasoner(reasoner),
        context_assembler=_FakeAssembler(),  # type: ignore[arg-type]
        tool_runtime=_tool_runtime(),
        lifecycle=LifecycleDispatcher(),
        trace_recorder=_NoopTrace(),  # type: ignore[arg-type]
        max_steps=8,
        checkpoint_store=store,
        clock=FrozenClock(NOW),
    )
    with pytest.raises(ReasonerError, match="simulated crash"):
        await runtime.run(_command(**runtime_ids))

    latest = await store.get_latest(user_id=runtime_ids["user_id"], run_id=runtime_ids["run_id"])
    assert latest is not None
    assert latest.step_index == 1
    assert len(latest.interactions) == 2
    assert latest.interactions[0]["kind"] == "tool_call"
    assert latest.interactions[1]["kind"] == "observation"

    # 第二段：换 ScriptedReasoner 续跑，应看到已有轨迹并直接 Final。
    resume_reasoner = ScriptedReasoner([FinalAction(content="续跑完成")])
    resume_runtime = AgentRuntime(
        reasoner=resume_reasoner,
        context_assembler=_FakeAssembler(),  # type: ignore[arg-type]
        tool_runtime=_tool_runtime(),
        lifecycle=LifecycleDispatcher(),
        trace_recorder=_NoopTrace(),  # type: ignore[arg-type]
        max_steps=8,
        checkpoint_store=store,
        clock=FrozenClock(NOW),
    )
    final = await resume_runtime.run(_command(**runtime_ids, resume=True))
    assert final.content == "续跑完成"
    # 续跑首轮 Reason 时，state 已含先前 tool/observation。
    assert len(resume_reasoner.seen_contexts[0].state.interactions) == 2


@pytest.mark.asyncio
async def test_in_memory_checkpoint_get_latest_by_step() -> None:
    """验证：同 run 多条检查点时 get_latest 取 step_index 最大者。"""
    store = InMemoryAgentCheckpointStore()
    run_id = uuid4()
    user_id = uuid4()
    for step in (1, 3, 2):
        await store.save(
            AgentRunCheckpoint(
                id=uuid4(),
                run_id=run_id,
                turn_id=uuid4(),
                user_id=user_id,
                thread_id=uuid4(),
                step_index=step,
                current_input="x",
                interactions=(),
                discovered_tool_names=(),
                created_at=NOW,
            )
        )
    latest = await store.get_latest(user_id=user_id, run_id=run_id)
    assert latest is not None
    assert latest.step_index == 3
