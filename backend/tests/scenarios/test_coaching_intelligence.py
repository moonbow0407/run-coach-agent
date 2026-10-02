"""Phase 3 教练智能场景：分析 Tools 与计划调整提案（PlanChange）生命周期。

模拟疲劳偏高的跑者请求负荷/课次分析并提出降负荷调整：
验证提案从 DRAFT 到确认的完整边界，失败或取消时正确放弃。
"""

import asyncio
from datetime import date, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from app.coaching.domain.athlete.models import FatigueLevel, RecoveryLevel
from app.coaching.domain.plan.models import PlanChangeStatus, PlanStatus
from app.common.errors import ReasonerError
from app.common.ids import new_id
from app.infrastructure.database.models.coaching import (
    PlanChangeRow,
    PlannedSessionRow,
    TrainingPlanRow,
)
from app.infrastructure.database.session import short_session
from tests.conftest import token_for
from tests.durable import drain_durable_tasks
from tests.helpers import request_context_for


def _call(tool: str, arguments: dict, call_id: str) -> ToolCallAction:
    """构造脚本中的一步：一次模型 Tool 调用动作。"""
    return ToolCallAction(tool=tool, arguments=arguments, model_call_id=call_id)


def _observation_for_tool(reasoner: ScriptedReasoner, tool: str):
    """倒序查找指定 Tool 最近一次的执行观察（Observation），找不到即断言失败。"""
    for context in reversed(reasoner.seen_contexts):
        for item in context.state.interactions:
            if getattr(item, "source", None) == tool:
                return item
    raise AssertionError(f"missing observation for {tool}")


async def _latest_change(sessions, user_id) -> PlanChangeRow:
    """查询该用户最新一条落库的计划调整提案（PlanChange）记录。"""
    async with short_session(sessions) as session:
        row = await session.scalar(
            select(PlanChangeRow)
            .where(PlanChangeRow.user_id == user_id)
            .order_by(PlanChangeRow.created_at.desc())
        )
        assert row is not None
        return row


@pytest.mark.asyncio
async def test_query_does_not_compute_without_snapshot(make_app, user_id, clock) -> None:
    """场景：无任何状态快照的用户问「我状态怎么样」→ 期望：读取 Tool 成功返回空数据，不凭空计算。"""
    reasoner = ScriptedReasoner(
        [
            _call("search_tools", {"query": "跑者状态 疲劳"}, "c1"),
            _call("get_latest_athlete_state", {}, "c2"),
            FinalAction(content="没有快照。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    await app.state.chat_service.send_message(
        request_context=request_context_for(user_id, clock),
        thread_id=None,
        content="我现在状态怎么样",
    )
    observation = _observation_for_tool(reasoner, "get_latest_athlete_state")
    assert observation.status == "success"
    assert observation.data is None


@pytest.mark.asyncio
async def test_hidden_analyze_training_load_rejected(make_app, slice_seed, clock) -> None:
    """场景：模型未经发现直接点名隐藏 Tool → 期望：报错 tool_not_available，隐藏即不可用。"""
    reasoner = ScriptedReasoner(
        [
            _call("analyze_training_load", {}, "c1"),
            FinalAction(content="工具不可见。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="分析负荷",
    )
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "tool_not_available"


@pytest.mark.asyncio
async def test_analyze_training_load_observation_is_partial(
    make_app, slice_seed, clock
) -> None:
    """场景：分析近 7 天负荷但部分训练缺 sRPE → 期望：标记部分覆盖并给出可信的覆盖率。"""
    reasoner = ScriptedReasoner(
        [
            _call("search_tools", {"query": "analyze_training_load srpe coverage", "limit": 5}, "c1"),
            _call("analyze_training_load", {}, "c2"),
            FinalAction(content="负荷是部分覆盖。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="分析最近训练负荷",
    )
    observation = _observation_for_tool(reasoner, "analyze_training_load")
    assert observation.status == "success"
    current = observation.data["current"]
    assert current["total_duration_s"] > 0
    assert current["total_distance_m"] > 0
    assert current["is_partial"] is True
    assert current["partial_srpe_load"] is not None
    assert current["srpe_coverage"] is not None
    # seed 四次训练里只有间歇课有 sRPE 反馈，覆盖率必然不到一半。
    assert current["srpe_coverage"] < 0.5


@pytest.mark.asyncio
async def test_analyze_workout_returns_facts_not_completed(
    make_app, slice_seed, clock, sessions
) -> None:
    """场景：分析上次间歇课 → 期望：只回原始事实（反馈、sRPE 负荷、心率），不替教练下「完成」结论。"""
    last_id = slice_seed.workout_ids[-1]
    async with short_session(sessions, commit=True) as session:
        # 手工补一条与间歇同日（8/27）的计划课次，验证分析结果能带出当日计划。
        session.add(
            PlannedSessionRow(
                id=new_id(),
                plan_id=slice_seed.plan_id,
                scheduled_date=date(2026, 8, 27),
                session_type="interval",
                title="当日间歇计划",
                prescription={"reps": 6},
            )
        )
    reasoner = ScriptedReasoner(
        [
            _call("search_tools", {"query": "analyze_workout session_rpe", "limit": 5}, "c1"),
            _call("analyze_workout", {"workout_id": str(last_id)}, "c2"),
            FinalAction(content="分析完成。"),
        ]
    )
    app = make_app(reasoner=reasoner)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="分析上次间歇",
    )
    observation = _observation_for_tool(reasoner, "analyze_workout")
    assert observation.status == "success"
    data = observation.data
    assert data["workout"]["workout_type"] == "interval"
    assert data["feedback"]["perceived_exertion"] == 8
    assert data["feedback"]["note"] == "最后两组间歇明显掉速"
    # sRPE 负荷 = 时长（分钟）× 主观用力分值：间歇 42 分钟 × 用力 8 = 336。
    assert data["session_rpe_load"] == (2520 / 60.0) * 8
    assert data["quality_session"] is True
    assert data["heart_rate"]["avg"] == 168
    assert "completed" not in data
    assert any(item["title"] == "当日间歇计划" for item in data["same_day_planned_sessions"])


@pytest.mark.asyncio
async def test_recompute_then_working_context_sees_v2(make_app, slice_seed, clock) -> None:
    """场景：先重算状态快照再对话 → 期望：推理器在工作上下文中看到 v2 最新快照。"""
    setup = make_app(reasoner=ScriptedReasoner([FinalAction(content="unused")]))
    snapshot = await setup.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    # seed 已含 v1 快照，重算后版本推进为 2；间歇跑崩 + 高负荷使疲劳判定为 high、恢复一般。
    assert snapshot.version == 2
    assert snapshot.fatigue_level is FatigueLevel.HIGH
    assert snapshot.recovery_level is RecoveryLevel.FAIR
    reasoner = ScriptedReasoner([FinalAction(content="看到最新状态。")])
    app = make_app(reasoner=reasoner)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="我现在怎么样",
    )
    state = reasoner.seen_contexts[0].context_bundle.working_context.latest_athlete_state
    assert state is not None
    assert state.version == 2
    assert state.fatigue_level == "high"
    assert state.algorithm_version == "phase3.v1"


async def _propose_turn(make_app, slice_seed, clock, *, final: bool):
    """准备一轮「发现工具→提出降负荷提案」的对话；final 决定脚本是否以 FinalAction 收尾。"""
    actions: list = [
        _call("search_tools", {"query": "降负荷 调整草案", "limit": 5}, "c1"),
        _call(
            "propose_plan_adaptation",
            {
                "based_on_plan_version": 1,
                "based_on_state_version": 2,
                "horizon_days": 7,
                "reason": "高疲劳，把节奏课改成休息",
            },
            "c2",
        ),
    ]
    if final:
        actions.append(FinalAction(content="已提出草案。"))
    reasoner = ScriptedReasoner(actions)
    app = make_app(reasoner=reasoner)
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    return app, reasoner


@pytest.mark.asyncio
async def test_propose_keeps_draft_until_commit(
    make_app, slice_seed, clock, sessions
) -> None:
    """场景：只提出提案、Turn 未提交 → 期望：提案停留在 DRAFT，现行计划保持 v1 不动。"""
    # 先提出但不 Final：用单独 service 调用来检查 DRAFT，避免 TurnCommitted。
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="noop")]))
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    change, _ = await app.state.plan_adaptation_service.propose_reduce_upcoming_load(
        user_id=slice_seed.user_id,
        turn_id=new_id(),
        run_id=new_id(),
        as_of=clock.now(),
        based_on_plan_version=1,
        based_on_state_version=2,
        horizon_days=7,
        reason="高疲劳，把节奏课改成休息",
    )
    assert change.status is PlanChangeStatus.DRAFT
    async with short_session(sessions) as session:
        plan = await session.get(TrainingPlanRow, slice_seed.plan_id)
        assert plan is not None
        assert plan.status == PlanStatus.ACTIVE.value
        assert plan.version == 1


@pytest.mark.asyncio
async def test_turn_committed_promotes_draft(
    make_app, slice_seed, clock, sessions
) -> None:
    """场景：提案后 Turn 正常提交 → 期望：DRAFT 被晋升为 PENDING_CONFIRMATION 等待用户确认。"""
    app, reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    observation = _observation_for_tool(reasoner, "propose_plan_adaptation")
    assert observation.status == "success"
    assert observation.data["plan_change"]["status"] == "draft"
    assert observation.data["active_plan_unchanged"] is True
    # drain_durable_tasks：等提交后的后台任务跑完，DRAFT 在此期间被晋升为待确认。
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    assert row.status == PlanChangeStatus.PENDING_CONFIRMATION.value


@pytest.mark.asyncio
async def test_failed_turn_abandons_draft(make_app, slice_seed, clock, sessions) -> None:
    """场景：提案后 Turn 推理失败 → 期望：未确认的提案被置为 ABANDONED。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=False)
    # 脚本无 FinalAction：脚本耗尽时推理器抛 ReasonerError，模拟推理失败。
    with pytest.raises(ReasonerError):
        await app.state.chat_service.send_message(
            request_context=request_context_for(slice_seed.user_id, clock),
            thread_id=None,
            content="帮我降负荷",
        )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    assert row.status == PlanChangeStatus.ABANDONED.value


@pytest.mark.asyncio
async def test_cancelled_turn_abandons_draft(make_app, slice_seed, clock, sessions) -> None:
    """场景：提案后用户取消仍在执行的 Tool → 期望：提案同样被放弃（ABANDONED）。"""
    from pydantic import BaseModel, ConfigDict

    from app.common.errors import TurnCancelled as TurnCancelledError
    from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource

    started = asyncio.Event()

    class SlowArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class SlowTool:
        """提案后的慢 Tool：睡 30 秒，为「取消」留出操作窗口。"""

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="slow_after_propose",
                description="提出草案后等待取消",
                tags=("probe",),
                search_hint="probe",
                always_on=True,
                risk=ToolRisk.READ_ONLY,
                source=ToolSource.SYSTEM,
                timeout_s=30.0,
            )

        @property
        def args_model(self) -> type[SlowArgs]:
            return SlowArgs

        async def execute(self, *, args, context):
            started.set()
            await asyncio.sleep(30)
            return {}

    reasoner = ScriptedReasoner(
        [
            _call("search_tools", {"query": "降负荷 调整草案", "limit": 5}, "c1"),
            _call(
                "propose_plan_adaptation",
                {
                    "based_on_plan_version": 1,
                    "based_on_state_version": 2,
                    "horizon_days": 7,
                    "reason": "高疲劳",
                },
                "c2",
            ),
            _call("slow_after_propose", {}, "c3"),
        ]
    )
    app = make_app(reasoner=reasoner)
    app.state.tool_registry.register(SlowTool())
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    task = asyncio.create_task(
        app.state.chat_service.send_message(
            request_context=request_context_for(slice_seed.user_id, clock),
            thread_id=None,
            content="提出后取消",
        )
    )
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, TurnCancelledError)):
        await task
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    assert row.status == PlanChangeStatus.ABANDONED.value


@pytest.mark.asyncio
async def test_mutating_tool_is_not_authorized(make_app, slice_seed, clock) -> None:
    """场景：调用已注册但属写操作（MUTATING）的 Tool → 期望：被拒 tool_not_authorized，不执行。"""
    from pydantic import BaseModel, ConfigDict

    from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource

    class MutArgs(BaseModel):
        model_config = ConfigDict(extra="forbid")

    class MutatingTool:
        """声明为 MUTATING（写操作）风险的探测 Tool，验证默认不被授权。"""

        @property
        def definition(self) -> ToolDefinition:
            return ToolDefinition(
                name="mutating_probe",
                description="突变探测",
                tags=("probe",),
                search_hint="probe",
                always_on=True,
                risk=ToolRisk.MUTATING,
                source=ToolSource.SYSTEM,
                timeout_s=1.0,
            )

        @property
        def args_model(self) -> type[MutArgs]:
            return MutArgs

        async def execute(self, *, args, context):
            return {"ok": True}

    reasoner = ScriptedReasoner(
        [_call("mutating_probe", {}, "c1"), FinalAction(content="不应执行。")]
    )
    app = make_app(reasoner=reasoner)
    app.state.tool_registry.register(MutatingTool())
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="突变",
    )
    observation = reasoner.seen_contexts[1].state.interactions[1]
    assert observation.status == "error"
    assert observation.error_code == "tool_not_authorized"


@pytest.mark.asyncio
async def test_forbidden_tools_are_not_registered(make_app) -> None:
    """场景：检查敏感 Tool 未对模型开放 → 期望：重算与确认 Tool 均不在注册表中。"""
    app = make_app(reasoner=ScriptedReasoner([FinalAction(content="x")]))
    assert app.state.tool_registry.find("recompute_athlete_state") is None
    assert app.state.tool_registry.find("confirm_plan_adaptation") is None


@pytest.mark.asyncio
async def test_race_in_window_is_not_modified(
    make_app, slice_seed, clock, sessions
) -> None:
    """场景：调整窗口内含比赛课次 → 期望：比赛课次原样保留，降负荷不波及比赛。"""
    async with short_session(sessions, commit=True) as session:
        session.add(
            PlannedSessionRow(
                id=new_id(),
                plan_id=slice_seed.plan_id,
                scheduled_date=date(2026, 8, 30),
                session_type="race",
                title="周末比赛",
                prescription={"distance_m": 5000},
            )
        )
    app, reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="降负荷但保留比赛",
    )
    observation = _observation_for_tool(reasoner, "propose_plan_adaptation")
    # 比赛属于不可降负荷的课种，提案必须显式声明未触碰。
    assert observation.data.get("race_session_not_modified") is True
    changes = observation.data["plan_change"]["payload"]["changes"]
    assert all(item["from_type"] != "race" for item in changes)


@pytest.mark.asyncio
async def test_confirm_api_activates_and_is_idempotent(
    make_app, slice_seed, clock, sessions, test_settings, slice_auth_header
) -> None:
    """场景：用户通过 API 确认提案 → 期望：生成 v2 ACTIVE 计划，重复确认幂等，旧计划被取代。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    headers = slice_auth_header
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        fetched = await client.get(f"/api/v1/plan-changes/{row.id}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["status"] == "pending_confirmation"
        first = await client.post(f"/api/v1/plan-changes/{row.id}/confirm", headers=headers)
        assert first.status_code == 200
        body = first.json()
        assert body["plan_change"]["status"] == "confirmed"
        assert body["resulting_plan_id"]
        resulting = body["resulting_plan"]
        assert resulting["version"] == 2
        assert resulting["status"] == "active"
        by_date = {item["scheduled_date"]: item for item in resulting["sessions"]}
        assert by_date["2026-08-29"]["session_type"] == "easy"
        assert by_date["2026-08-31"]["session_type"] == "rest"
        assert by_date["2026-08-31"]["title"].startswith("恢复休息（调整自：")
        assert by_date["2026-08-31"]["prescription"] == {}
        second = await client.post(f"/api/v1/plan-changes/{row.id}/confirm", headers=headers)
        assert second.status_code == 200
        assert second.json()["resulting_plan_id"] == body["resulting_plan_id"]
    async with short_session(sessions) as session:
        old = await session.get(TrainingPlanRow, slice_seed.plan_id)
        assert old is not None
        assert old.status == PlanStatus.SUPERSEDED.value


@pytest.mark.asyncio
async def test_confirm_stale_plan_and_state_return_409(
    make_app, slice_seed, clock, sessions, slice_auth_header
) -> None:
    """场景：确认前状态快照又被重算 → 期望：基于过期版本的提案确认返回 409 stale。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    # 提案确认前快照又被重算，提案依据的状态版本随之过期。
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now() + timedelta(minutes=1)
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/plan-changes/{row.id}/confirm", headers=slice_auth_header
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale"
    assert response.json()["detail"]["status"] == "stale"


@pytest.mark.asyncio
async def test_cross_user_plan_change_http_404(
    make_app, slice_seed, clock, sessions, test_settings
) -> None:
    """场景：另一用户读取/确认他人提案 → 期望：一律 404，不泄露资源存在性。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    other = token_for(slice_seed.user_id, test_settings)
    # 另一个用户：再 seed 一个账号。
    from app.infrastructure.database.models.user import UserRow

    other_id = new_id()
    async with short_session(sessions, commit=True) as session:
        session.add(UserRow(id=other_id, created_at=clock.now(), updated_at=clock.now()))
    other = token_for(other_id, test_settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        gotten = await client.get(
            f"/api/v1/plan-changes/{row.id}",
            headers={"Authorization": f"Bearer {other}"},
        )
        confirmed = await client.post(
            f"/api/v1/plan-changes/{row.id}/confirm",
            headers={"Authorization": f"Bearer {other}"},
        )
    assert gotten.status_code == 404
    assert confirmed.status_code == 404


@pytest.mark.asyncio
async def test_reject_pending_and_repeat_reject(
    make_app, slice_seed, clock, sessions, slice_auth_header
) -> None:
    """场景：拒绝提案后再拒绝、又想确认 → 期望：拒绝幂等，已拒绝提案不可确认（409）。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/api/v1/plan-changes/{row.id}/reject", headers=slice_auth_header
        )
        assert first.status_code == 200
        assert first.json()["status"] == "rejected"
        second = await client.post(
            f"/api/v1/plan-changes/{row.id}/reject", headers=slice_auth_header
        )
        assert second.status_code == 200
        assert second.json()["status"] == "rejected"
        confirm = await client.post(
            f"/api/v1/plan-changes/{row.id}/confirm", headers=slice_auth_header
        )
        assert confirm.status_code == 409


@pytest.mark.asyncio
async def test_stale_plan_version_http_409(
    make_app, slice_seed, clock, sessions, slice_auth_header
) -> None:
    """场景：提案期间计划被换版 → 期望：基于旧计划版本的确认返回 409 stale。"""
    app, _reasoner = await _propose_turn(make_app, slice_seed, clock, final=True)
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="帮我降负荷",
    )
    await drain_durable_tasks(app)
    row = await _latest_change(sessions, slice_seed.user_id)
    # 手工把现行计划换成 v2，模拟确认前计划已被其他途径替换。
    async with short_session(sessions, commit=True) as session:
        old = await session.get(TrainingPlanRow, slice_seed.plan_id)
        assert old is not None
        old.status = PlanStatus.SUPERSEDED.value
        session.add(
            TrainingPlanRow(
                id=new_id(),
                user_id=slice_seed.user_id,
                version=2,
                goal_id=slice_seed.goal_id,
                status=PlanStatus.ACTIVE.value,
                starts_on=date(2026, 7, 20),
                ends_on=date(2026, 9, 27),
                created_at=clock.now(),
            )
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/plan-changes/{row.id}/confirm", headers=slice_auth_header
        )
    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "stale"
