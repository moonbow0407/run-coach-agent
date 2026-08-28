"""关键词规范化：查询与文档字段共用同一套口径。

- 英文：统一小写，按非字母数字切分为 token；工具名 snake_case 天然被
  切成词元（get_workout_detail -> get / workout / detail）。
- 中文：连续 CJK 段切成 bigram（长度 1 时保留单字），支持子串匹配。
"""

import re

# 连续的 ASCII 字母数字段与连续的 CJK 段分别成组
_ASCII_RUN = re.compile(r"[a-z0-9]+")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def _is_cjk(text: str) -> bool:
    return all("\u4e00" <= ch <= "\u9fff" for ch in text)


def extract_tokens(text: str) -> set[str]:
    """把文本规范化为 token 集合：ASCII 词元（小写）+ CJK bigram/单字。"""
    lowered = text.lower()
    tokens = set(_ASCII_RUN.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def token_matches(token: str, field_tokens: set[str], field_text: str) -> bool:
    """判断一个查询 token 是否命中某个检索字段。

    命中口径（与字段无关，保证各字段可比）：
    - 精确 token 命中；
    - CJK token 以子串命中字段文本（中文子串/单字）；
    - ASCII token 长度 >= 4 时允许与字段 token 互为子串
      （覆盖 workout/workouts 一类的形态变体），过短的词元不做子串匹配，
      避免 get 命中 target 之类的误报。
    """
    if token in field_tokens:
        return True
    if _is_cjk(token):
        return token in field_text
    if len(token) < 4:
        return False
    if token in field_text:
        return True
    return any(
        len(candidate) >= 4 and (token in candidate or candidate in token)
        for candidate in field_tokens
    )
