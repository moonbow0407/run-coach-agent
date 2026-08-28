"""search_tools 系统工具：当前 AgentRun 内动态发现长尾能力。

搜索、过滤本会话已可见 Tool、Registry 再确认、Discovery 更新与
hits 构造在 execute_for_session 内一次完成（全程同步，无 await 分隔），
保证 Observation 报告的命中集合与实际加入 DiscoveryState 的集合
完全一致。零命中返回 success + 空 hits，且不改变可见集合。
"""

from pydantic import BaseModel, ConfigDict, Field

from app.tools.context import ToolExecutionContext
from app.tools.registry.definition import ToolDefinition, ToolRisk, ToolSource
from app.tools.resolver.resolver import ToolResolver
from app.tools.resolver.session import ToolSession
from app.tools.search.keyword_search import KeywordToolSearch


class SearchToolsArgs(BaseModel):
    """search_tools 参数：查询词与结果数量上限（默认 3，最多 5）。"""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, description="自然语言或关键词")
    # strict：与 JSON Schema 的 integer 声明一致，拒绝字符串/布尔隐式强转。
    limit: int = Field(default=3, ge=1, le=5, strict=True, description="返回结果数量上限")


class SearchToolsTool:
    """发现类系统 Tool。搜索索引是 Registry 派生态，命中即已注册。"""

    def __init__(self, *, search: KeywordToolSearch, resolver: ToolResolver) -> None:
        self._search = search
        self._resolver = resolver

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_tools",
            description=(
                "按关键词搜索当前尚不可见的其他可用工具，"
                "返回工具名称、简短描述与相关性得分。"
            ),
            tags=("search", "discovery", "tool", "工具", "搜索"),
            search_hint="当可见工具不足以完成任务时，用自然语言或能力关键词搜索更多工具",
            always_on=True,
            risk=ToolRisk.READ_ONLY,
            source=ToolSource.SYSTEM,
            timeout_s=2.0,
        )

    @property
    def args_model(self) -> type[SearchToolsArgs]:
        return SearchToolsArgs

    async def execute_for_session(
        self,
        *,
        args: SearchToolsArgs,
        session: ToolSession,
        context: ToolExecutionContext,
    ) -> object:
        # 过滤掉当前已可见（always-on 或已发现）的 Tool，再取 Top-K。
        visible = self._resolver.visible_names(session)
        candidates = [
            hit for hit in self._search.search(args.query) if hit.name not in visible
        ][: args.limit]
        # unlock 内完成 Registry 再确认与 Discovery 更新，返回实际加入集合；
        # hits 只报告实际解锁的 Tool，与 DiscoveryState 保持完全一致。
        added = session.unlock([hit.name for hit in candidates])
        unlocked = [hit for hit in candidates if hit.name in added]
        return {
            "query": args.query,
            "limit": args.limit,
            "hits": [
                {"name": hit.name, "description": hit.description, "score": hit.score}
                for hit in unlocked
            ],
        }
