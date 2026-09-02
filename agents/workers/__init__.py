"""Worker Agents：数据预处理 / 描述性统计 / 建模分析 / 可视化（D-007）。"""
from __future__ import annotations

from agents.workers import (
    data_preprocessor,
    descriptive_analyst,
    modeling_analyst,
    visualizer,
)

# 顺序即默认调度顺序：预处理 → 描述统计 → 建模 → 可视化
WORKER_MODULES = (
    data_preprocessor,
    descriptive_analyst,
    modeling_analyst,
    visualizer,
)


def build_workers(config) -> list:
    """构建全部 4 个 Worker Agent（共享同一 LLM 客户端与配置）。"""
    from core.llm import get_llm

    llm = get_llm(config)
    return [mod.build(llm, config) for mod in WORKER_MODULES]
