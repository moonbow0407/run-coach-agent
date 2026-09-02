"""Projection 输入身份：只保存 source identity / version，不保存私密原文。"""

import hashlib
import json


def fingerprint(checkpoint: dict[str, object]) -> str:
    """对投影检查点计算稳定指纹：作为幂等重放判断的输入身份。"""
    # sort_keys 保证相同内容无论键序如何都得到同一指纹。
    raw = json.dumps(checkpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
