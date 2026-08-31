"""训练台只读查询 HTTP 边界：JWT 隔离、404 空状态、pending 提案发现。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.agent.models.action import FinalAction, ToolCallAction
from app.agent.reasoning.scripted import ScriptedReasoner
from tests.durable import drain_durable_tasks
from tests.helpers import request_context_for

READ_ROUTES = (
    "/api/v1/goals/active",
    "/api/v1/plans/active",
    "/api/v1/athlete-state/latest",
    "/api/v1/plan-changes/pending",
)


@pytest.mark.asyncio
async def test_coaching_read_bodies_with_seed(
    make_app,
    slice_seed,
    slice_auth_header,
) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        goal = await client.get("/api/v1/goals/active", headers=slice_auth_header)
        assert goal.status_code == 200
        goal_body = goal.json()
        assert goal_body["goal_type"] == "race"
        assert goal_body["race_date"] == "2026-10-18"
        assert goal_body["race_distance_m"] == 21097
        assert goal_body["target_time_s"] == 6600

        plan = await client.get("/api/v1/plans/active", headers=slice_auth_header)
        assert plan.status_code == 200
        plan_body = plan.json()
        assert plan_body["plan"]["version"] == 1
        assert plan_body["plan"]["status"] == "active"
        assert plan_body["truncated"] is False
        # 摘要窗口 = as_of 所在 ISO 周 ∪ 未来 14 天，覆盖 seed 的两节课次。
        by_date = {s["scheduled_date"]: s for s in plan_body["sessions"]}
        assert by_date["2026-08-29"]["session_type"] == "easy"
        assert by_date["2026-08-31"]["session_type"] == "tempo"
        assert by_date["2026-08-31"]["prescription"]["pace"] == "5:10"

        state = await client.get("/api/v1/athlete-state/latest", headers=slice_auth_header)
        assert state.status_code == 200
        state_body = state.json()
        assert state_body["version"] == 1
        assert state_body["fatigue_level"] == "moderate"
        assert state_body["recovery_level"] == "fair"
        assert state_body["recent_training_load"] == 42.0
        assert state_body["signals"] == []
        assert state_body["algorithm_version"] == "seed-fixture"

        workouts = await client.get("/api/v1/workouts?days=30", headers=slice_auth_header)
        assert workouts.status_code == 200
        workouts_body = workouts.json()
        assert workouts_body["count"] == 4
        types = {w["workout_type"] for w in workouts_body["workouts"]}
        assert types == {"easy", "tempo", "long_run", "interval"}

        # seed 只给最后一次间歇训练写了反馈。
        interval = next(w for w in workouts_body["workouts"] if w["workout_type"] == "interval")
        feedback = await client.get(
            f"/api/v1/workouts/{interval['id']}/feedback", headers=slice_auth_header
        )
        assert feedback.status_code == 200
        feedback_body = feedback.json()
        assert feedback_body["perceived_exertion"] == 8
        assert feedback_body["subjective_fatigue"] == 7
        assert feedback_body["note"] == "最后两组间歇明显掉速"

        easy = next(w for w in workouts_body["workouts"] if w["workout_type"] == "easy")
        missing_feedback = await client.get(
            f"/api/v1/workouts/{easy['id']}/feedback", headers=slice_auth_header
        )
        assert missing_feedback.status_code == 404


@pytest.mark.asyncio
async def test_coaching_read_rejects_invalid_days(make_app, slice_auth_header) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for days in ("0", "366", "abc"):
            response = await client.get(f"/api/v1/workouts?days={days}", headers=slice_auth_header)
            assert response.status_code == 422


@pytest.mark.asyncio
async def test_coaching_read_empty_states_and_auth_isolation(
    make_app,
    user_id,
    auth_header,
) -> None:
    """无任何数据的用户：查询按 404 报告，训练列表返回空集；不泄漏他人数据。"""
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for route in READ_ROUTES:
            response = await client.get(route, headers=auth_header)
            assert response.status_code == 404, route
        workouts = await client.get("/api/v1/workouts?days=30", headers=auth_header)
        assert workouts.status_code == 200
        assert workouts.json() == {"count": 0, "workouts": []}


@pytest.mark.asyncio
async def test_coaching_read_requires_auth(make_app) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for route in (*READ_ROUTES, "/api/v1/workouts?days=30"):
            response = await client.get(route)
            assert response.status_code == 401, route


@pytest.mark.asyncio
async def test_pending_plan_change_discovery_and_resolution(
    make_app,
    slice_seed,
    clock,
    slice_auth_header,
) -> None:
    """前端靠 /pending 发现提案；确认后 /pending 转为 404 空状态。"""
    reasoner = ScriptedReasoner(
        [
            ToolCallAction(
                tool="search_tools",
                arguments={"query": "降负荷 调整草案", "limit": 5},
                model_call_id="c0",
            ),
            ToolCallAction(
                tool="propose_plan_adaptation",
                arguments={
                    "based_on_plan_version": 1,
                    "based_on_state_version": 2,
                    "horizon_days": 7,
                    "reason": "高疲劳降低节奏课",
                },
                model_call_id="c1",
            ),
            FinalAction(content="草案已提出。"),
        ]
    )
    app = make_app(reasoner=reasoner)  # seed 的 v1 快照是 moderate/fair，不满足降负荷前置条件；
    # 先按真实反馈重算出高疲劳快照（v2），提案才符合领域规则。
    await app.state.athlete_recompute_service.recompute(
        user_id=slice_seed.user_id, as_of=clock.now()
    )
    await app.state.chat_service.send_message(
        request_context=request_context_for(slice_seed.user_id, clock),
        thread_id=None,
        content="请降低接下来的负荷",
    )
    await drain_durable_tasks(app)


    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        pending = await client.get("/api/v1/plan-changes/pending", headers=slice_auth_header)
        assert pending.status_code == 200
        change = pending.json()
        assert change["status"] == "pending_confirmation"
        assert change["change_type"] == "reduce_upcoming_load"

        confirmed = await client.post(
            f"/api/v1/plan-changes/{change['id']}/confirm", headers=slice_auth_header
        )
        assert confirmed.status_code == 200

        resolved = await client.get("/api/v1/plan-changes/pending", headers=slice_auth_header)
        assert resolved.status_code == 404
