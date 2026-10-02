"""Eval 模块专用错误族：全部是 RunCoachError 子类，Runner 统一归一化为 ERROR 结果。"""

from app.common.errors import RunCoachError


class EvalError(RunCoachError):
    """Eval 专用错误根类型：CLI 顶层据此返回退出码 2。"""


class EvalConfigError(EvalError):
    """Case YAML / Schema / 过滤配置非法，或 fixture alias 无法解析。"""


class EvalEnvironmentError(EvalError):
    """Eval 数据库守卫、migration、重置或容器装配失败。"""


class EvalTraceError(EvalError):
    """RunStep 轨迹结构损坏：配对失败、顺序非法或终态缺 final。"""


class EvalBarrierError(EvalError):
    """Durable 一致性屏障排空失败：任务死信、隔离或超出有界排空次数。"""


class EvalStateError(EvalError):
    """Domain State（PlanChange / Memory / Plan）读取失败或缺少证据。"""
