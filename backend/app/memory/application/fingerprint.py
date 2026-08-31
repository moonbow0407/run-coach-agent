"""Projection 输入身份：只保存 source identity / version，不保存私密原文。"""

import hashlib
import json


def fingerprint(checkpoint: dict[str, object]) -> str:
    raw = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
