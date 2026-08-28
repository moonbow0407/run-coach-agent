"""结构化日志：以 JSON 行输出，字段与可观测性契约（request_id / run_id 等）对齐。"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    """把日志记录展开成单行 JSON，标准字段之外的信息放入固定追踪键。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key in (
            "request_id",
            "trace_id",
            "user_id",
            "thread_id",
            "turn_id",
            "run_id",
            "capability",
            "duration_ms",
            "status",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
