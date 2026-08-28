"""Dynamic Tool Runtime。

Phase 2 起以正式 Tool 术语承载 Agent 的可调用领域能力：
Registry 是 Tool 存在性的唯一事实来源；Search Index 是 Registry 的进程内
派生状态；Discovery 只属于当前 AgentRun；执行轨迹复用 RunStep。
AgentRuntime 只通过 ToolRuntime 外观访问本包，不直接接触内部组件。
"""
