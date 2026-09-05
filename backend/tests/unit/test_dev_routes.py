"""Scenario Lab dev 路由的挂载门禁：开关决定 /dev 路由是否存在。"""

from fastapi import FastAPI

from app.bootstrap import create_app
from app.infrastructure.config import Settings


def _settings(*, enable_scenario_lab: bool) -> Settings:
    # 引擎懒建立，测试只验证路由装配，不会真正连接该地址。
    return Settings(
        database_url="postgresql+asyncpg://localhost/dummy",
        jwt_secret="test-secret-must-be-at-least-32-bytes",
        enable_scenario_lab=enable_scenario_lab,
    )


def _route_paths(app: FastAPI) -> set[str]:
    # 通过 OpenAPI schema 取路径：新版 FastAPI 的 app.routes 会保留未展开的路由对象。
    return set(app.openapi()["paths"])


def test_dev_routes_absent_by_default() -> None:
    app = create_app(_settings(enable_scenario_lab=False))
    assert "/api/v1/dev/clock" not in _route_paths(app)


def test_dev_routes_mounted_when_lab_enabled() -> None:
    app = create_app(_settings(enable_scenario_lab=True))
    paths = _route_paths(app)
    assert "/api/v1/dev/clock" in paths
    assert "/api/v1/dev/workouts" in paths
    assert "/api/v1/dev/athlete-state/recompute" in paths
    assert "/api/v1/dev/scenarios/{name}/apply" in paths
