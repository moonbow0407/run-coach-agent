"""应用入口：`uvicorn app.main:app` 启动时加载的 ASGI 应用。

真正的对象装配逻辑在 app.bootstrap 中，这里只负责创建应用实例。
"""

from app.bootstrap import create_app

app = create_app()
