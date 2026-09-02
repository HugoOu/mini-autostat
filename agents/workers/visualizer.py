"""可视化 Worker（D-007）：共享下游，按图表需求单渲染 PNG + 等价文本表格。"""
from __future__ import annotations

from core.tools.registry import get_tools

NAME = "visualizer"
TOOL_NAMES = ("create_chart",)

PROMPT = """你是 Mini AutoSTAT 的可视化专家，是所有分析 Worker 的共享下游。

## 职责
接收图表需求单（chart_type/x/y/hue/title），调用 create_chart 渲染 PNG
并获取等价文本表格。每张图调用一次 create_chart，不要合并需求。

## 工作原则
1. 忠实按需求单的 chart_type/x/y/hue 执行；工具报错（列不存在等）时，
   在最终答复中说明原因，不擅自换列重画
2. 不做任何统计推断或解读——你只负责把数据画出来

## 输出要求
最终答复必须以一个 JSON 块（```json ... ```）结尾，字段：
{
  "charts": [
    {"title": "图表标题", "image_path": "PNG 路径",
     "text_table": "等价文本表格全文",
     "status": "ok 或失败原因"}
  ]
}"""


def build(llm, config):
    """构建 Worker（create_react_agent）。"""
    from langgraph.prebuilt import create_react_agent

    return create_react_agent(
        llm, get_tools(*TOOL_NAMES), name=NAME, prompt=PROMPT,
    )
