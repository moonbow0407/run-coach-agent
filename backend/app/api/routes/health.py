"""健康检查接口：供容器编排与探活使用。"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """探活端点：进程存活即返回 ok，供容器编排轮询。"""
    return {"status": "ok"}
