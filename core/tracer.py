"""全链路执行记录器（T2.3，考核要求：状态记录 / 运行记录）。

每次分析运行生成一个 logs/run_<run_id>.jsonl 文件，逐行写入一个 JSON
事件，覆盖每一步的输入摘要、决策、工具调用、输出、错误与下一步动作，
使完整过程可追溯——这也是考核"运行记录"材料的直接来源。

事件 schema（v1，字段固定，向前兼容靠 schema 字段区分）：
    schema          事件结构版本号（当前 1）
    ts              UTC 时间戳（ISO-8601，秒级）
    step            本次运行内的递增序号
    actor           执行者：leader / data_preprocessor / descriptive_analyst /
                    modeling_analyst / visualizer / reporter / user / system
    action          动作类型：route / tool_call / tool_result / replan /
                    check / error / finish / run_start / run_end ...
    input_summary   输入摘要（超长自动截断）
    decision        本步决策说明
    tool            工具调用信息 {"name","provider","args"} 或 None
                    （provider 来自工具注册表，对应 D-008）
    output_summary  输出摘要（超长自动截断）
    error           错误信息（无错误为 None）
    next            下一步动作说明

摘要字段统一经过 _clip 截断（默认 600 字符），防止工具大输出撑爆日志。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

_CLIP_LIMIT = 600

_ACTORS = {
    "leader",
    "data_preprocessor",
    "descriptive_analyst",
    "modeling_analyst",
    "visualizer",
    "reporter",
    "user",
    "system",
}


def _clip(value, limit: int = _CLIP_LIMIT):
    """字符串字段截断；非字符串转字符串处理，None 原样返回。"""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


class RunTracer:
    """单次运行的全链路记录器（一个运行 = 一个 jsonl 文件）。"""

    SCHEMA_VERSION = 1

    def __init__(self, log_dir: Path | str = "logs", run_id: str | None = None):
        self.run_id = run_id or (
            datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
        )
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"run_{self.run_id}.jsonl"
        self._step = 0
        self._fh = self.log_path.open("w", encoding="utf-8")
        self.log("system", "run_start", decision=f"run_id={self.run_id}")

    def log(
        self,
        actor: str,
        action: str,
        *,
        input_summary=None,
        decision=None,
        tool: dict | None = None,
        output_summary=None,
        error=None,
        next_action=None,
    ) -> int:
        """写入一条事件，返回其 step 序号。"""
        if actor not in _ACTORS:
            raise ValueError(f"未知 actor: {actor}；合法值: {sorted(_ACTORS)}")
        if tool is not None and not {"name", "provider"} <= set(tool):
            raise ValueError('tool 字段必须包含 "name" 与 "provider"')

        self._step += 1
        event = {
            "schema": self.SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "step": self._step,
            "actor": actor,
            "action": action,
            "input_summary": _clip(input_summary),
            "decision": _clip(decision),
            "tool": {k: _clip(v) for k, v in tool.items()} if tool else None,
            "output_summary": _clip(output_summary),
            "error": _clip(error),
            "next": _clip(next_action),
        }
        self._fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._fh.flush()  # 即刻落盘：进程异常退出也不丢已记录步骤
        return self._step

    def close(self) -> None:
        if self._fh.closed:
            return
        try:
            self.log("system", "run_end")
        finally:
            self._fh.close()

    def __enter__(self) -> "RunTracer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.log("system", "error", error=f"{exc_type.__name__}: {exc}")
        self.close()
