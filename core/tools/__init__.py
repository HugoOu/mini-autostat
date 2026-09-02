"""工具集：data / stat / viz / code 四类工具与统一注册表。"""


def register_all_tools() -> dict[str, str]:
    """把全部工具注册进 registry（幂等），返回 {工具名: provider} 快照。

    这是 D-008 注册表模式的落地点：Worker 构建时按名取工具
    （get_tools），未来某工具迁移 MCP 只需在此处替换注册对象。
    """
    from core.tools import code_tools, data_tools, stat_tools, viz_tools
    from core.tools.registry import register_tool, registry_overview

    for module in (data_tools, stat_tools, viz_tools, code_tools):
        for t in module.TOOLS:
            register_tool(t)
    return registry_overview()
