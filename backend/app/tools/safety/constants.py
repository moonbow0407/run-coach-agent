"""安全策略可配置常量：伤痛关键词、回看窗口与工具分类。"""

# 近期反馈备注扫描窗口（天）。
RECENT_FEEDBACK_LOOKBACK_DAYS = 14

# 伤痛 / 损伤关键词（中英混写）；英文匹配时做大小写不敏感。
INJURY_KEYWORDS: frozenset[str] = frozenset(
    {
        "伤",
        "疼",
        "痛",
        "肿",
        "拉伤",
        "扭伤",
        "knee",
        "injury",
        "injured",
        "pain",
        "sore",
        "swelling",
        "sprain",
        "strain",
    }
)

# 降负荷（高强度→休息）提案工具。
REDUCE_LOAD_TOOLS: frozenset[str] = frozenset({"propose_plan_adaptation"})

# 转轻松跑提案工具（保留出勤、降低强度）。
CONVERT_EASY_TOOLS: frozenset[str] = frozenset({"propose_convert_hard_sessions_to_easy"})

# 疲劳高 + 恢复差时允许的草案工具。
ALLOWED_UNDER_FATIGUE_CONSTRAINT: frozenset[str] = REDUCE_LOAD_TOOLS | CONVERT_EASY_TOOLS

# 伤痛信号时仅允许「减负荷 / 改休息」类提案（不含转轻松跑）。
ALLOWED_UNDER_INJURY: frozenset[str] = REDUCE_LOAD_TOOLS

# 明确会加负荷的工具名（当前无实现，预留给未来加量提案）。
INCREASE_LOAD_TOOLS: frozenset[str] = frozenset()

# 工具 tags 命中任一时视为加负荷意图。
INCREASE_LOAD_TAGS: frozenset[str] = frozenset({"increase_load", "intensify", "加负荷", "提强度"})

# 安全状态 flag 码。
FLAG_HIGH_FATIGUE_POOR_RECOVERY = "high_fatigue_poor_recovery"
FLAG_INJURY_KEYWORDS = "injury_keywords"

# 拦截原因码（写入 Observation.error 的可读前缀旁，error_code 另用 safety_blocked）。
REASON_FATIGUE_BLOCKS_NON_REDUCE = "fatigue_blocks_non_reduce"
REASON_INJURY_BLOCKS_NON_REST = "injury_blocks_non_rest"
REASON_INCREASE_LOAD_FORBIDDEN = "increase_load_forbidden"
