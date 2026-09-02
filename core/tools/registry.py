"""工具注册表（D-008）。

Worker 的全部工具在此统一注册与发现。当前所有工具为原生 @tool
（provider="native"）；注册表同时作为 **MCP 适配点**——未来某个工具
迁移到 MCP server 时，仅需在注册处替换为 adapter 包装对象并标注
provider="mcp"，Worker 构建逻辑（get_tools）零改动。
"""
from __future__ import annotations

from langchain_core.tools import BaseTool

_REGISTRY: dict[str, dict] = {}


def register_tool(tool: BaseTool, provider: str = "native") -> BaseTool:
    """注册一个工具，key 取工具自身的 name 属性。"""
    _REGISTRY[tool.name] = {"tool": tool, "provider": provider}
    return tool


def get_tools(*names: str) -> list[BaseTool]:
    """按名称批量取工具；缺名时报错并列出可用项。"""
    missing = [n for n in names if n not in _REGISTRY]
    if missing:
        available = ", ".join(sorted(_REGISTRY)) or "(空)"
        raise KeyError(f"工具未注册: {missing}；可用工具: {available}")
    return [_REGISTRY[n]["tool"] for n in names]


def registry_overview() -> dict[str, str]:
    """返回 {工具名: provider}，供调试与全链路记录引用。"""
    return {name: meta["provider"] for name, meta in _REGISTRY.items()}
