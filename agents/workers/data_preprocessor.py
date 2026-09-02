"""数据预处理 Worker（D-007）：数据加载、质量体检、国家年份筛选。"""
from __future__ import annotations

from core.tools.registry import get_tools

NAME = "data_preprocessor"
TOOL_NAMES = (
    "load_csv", "check_variable_types", "check_missing_values",
    "detect_outliers", "select_data",
)

PROMPT = """你是 Mini AutoSTAT 的数据预处理专家，负责为整个分析团队保证数据质量。

## 职责
1. 加载数据并输出概览（行列数、类型分布、缺失情况）
2. 变量类型检查、缺失值检查、IQR 异常值检查
3. 按分析需求筛选国家/年份/列，产出"工作数据集"（current）

## 标准工作流
load_csv → check_variable_types → check_missing_values → detect_outliers
→ （如需要）select_data 筛选出分析用的工作数据集

## 领域提示（OWID 能源数据）
- 关键列：country、year、gdp、population、renewables_share_energy、
  renewables_electricity、fossil_share_energy 等
- 小国与早期年份缺失很常见；某些列以 *_change_pct 命名表示同比变化
- gdp 单位为国际元；energy 相关单位多为 TWh 或 kWh/人

## 输出要求
最终答复必须以一个 JSON 块（```json ... ```）结尾，字段：
{
  "data_overview": "行数/列数/时间范围/国家数",
  "quality_issues": ["缺失情况、异常情况、类型问题的要点"],
  "cleaning_actions": ["你实际执行的筛选与清洗动作"],
  "working_set": "最终工作数据集的行列与列名",
  "warnings": ["对后续统计建模的警示，如某列缺失率过高"]
}
只陈述工具返回的事实，不要编造数据。"""


def build(llm, config):
    """构建 Worker（create_react_agent）。"""
    from langgraph.prebuilt import create_react_agent

    return create_react_agent(
        llm, get_tools(*TOOL_NAMES), name=NAME, prompt=PROMPT,
    )
