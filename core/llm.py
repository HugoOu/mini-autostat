"""LLM 客户端封装（D-002）。

通过 OpenAI-compatible 接口接入 OpenCode Go 提供的 GLM-5.3-Flash。
所有 Agent（Leader / Workers / 报告生成）统一从本模块获取客户端，
禁止在各模块内散落构造，保证模型与预算配置单一来源。
"""
from __future__ import annotations

import json
import os
import re

from langchain_openai import ChatOpenAI

from core.config import AppConfig, load_config


def get_llm(
    config: AppConfig | None = None,
    temperature: float = 0.0,
    role: str | None = None,
    **kwargs,
) -> ChatOpenAI:
    """获取 LLM 客户端（不缓存：各 Agent 可能需要不同的 temperature）。

    role 分模型（D-026）：
    - role="leader"：取 leader_model（未配置则回退 model）+ leader_extra_body；
    - role="worker"：取 worker_model（未配置则回退 model）+ worker_extra_body；
    - role=None：取通用 model，不附加额外请求字段（向后兼容）。
    报告生成（reporter）为单次调用、质量优先，按约定使用 leader 角色。

    timeout/max_retries（D-019）：单次调用 120s 超时 + 4 次重试（M5 验收
    期间提供方延迟曾超过 3 次尝试的 361s 上限，提升至约 600s），
    防止网络劣化时 Agent 无限挂起；可用 kwargs 覆盖。

    temperature 覆盖（D-023）：设置环境变量 OPENAI_TEMPERATURE 后强制
    覆盖所有调用方的 temperature（部分模型如 kimi-k2.6 仅允许 1）。

    extra_body：随请求体透传的附加字段（如 GLM 系列 `{"thinking":
    {"type": "enabled"/"disabled"}}` 控制思考链），经环境变量
    OPENAI_LEADER_EXTRA_BODY / OPENAI_WORKER_EXTRA_BODY（JSON）配置。
    """
    cfg = config or load_config()
    env_temp = os.getenv("OPENAI_TEMPERATURE")
    if env_temp is not None:
        temperature = float(env_temp)

    model, extra_body = cfg.model, None
    if role == "leader":
        model = cfg.leader_model or cfg.model
        extra_body = cfg.leader_extra_body
    elif role == "worker":
        model = cfg.worker_model or cfg.model
        extra_body = cfg.worker_extra_body

    if extra_body:
        merged = dict(kwargs.pop("extra_body", None) or {})
        merged.update(extra_body)
        kwargs["extra_body"] = merged

    return ChatOpenAI(
        model=model,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        temperature=temperature,
        timeout=kwargs.pop("timeout", 120),
        max_retries=kwargs.pop("max_retries", 4),
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
