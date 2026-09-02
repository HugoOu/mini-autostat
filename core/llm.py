"""LLM 客户端封装（D-002）。

通过 OpenAI-compatible 接口接入 OpenCode Go 提供的 GLM-5.3-Flash。
所有 Agent（Leader / Workers / 报告生成）统一从本模块获取客户端，
禁止在各模块内散落构造，保证模型与预算配置单一来源。
"""
from __future__ import annotations

import json
import re

from langchain_openai import ChatOpenAI

from core.config import AppConfig, load_config


def get_llm(
    config: AppConfig | None = None,
    temperature: float = 0.0,
    **kwargs,
) -> ChatOpenAI:
    """获取共享 LLM 客户端（不缓存：各 Agent 可能需要不同的 temperature）。

    timeout/max_retries（D-019）：单次调用 120s 超时 + 2 次重试，
    防止网络劣化时 Agent 无限挂起；可用 kwargs 覆盖。
    """
    cfg = config or load_config()
    return ChatOpenAI(
        model=cfg.model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        temperature=temperature,
        timeout=kwargs.pop("timeout", 120),
        max_retries=kwargs.pop("max_retries", 2),
        **kwargs,
    )


def parse_json_block(text: str | None) -> dict | list | None:
    """从 LLM 输出中提取 JSON（容忍 ```json 围栏与前后缀文本）。

    返回解析结果；解析失败返回 None，由调用方决定重试或降级。
    """
    if text is None:
        return None

    # 优先提取围栏代码块
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    candidate = candidate.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 兜底：截取首个 { 或 [ 到最后一个 } 或 ]
    starts = [i for i in (candidate.find("{"), candidate.find("[")) if i != -1]
    end = max(candidate.rfind("}"), candidate.rfind("]"))
    if not starts or end <= min(starts):
        return None
    try:
        return json.loads(candidate[min(starts) : end + 1])
    except json.JSONDecodeError:
        return None
