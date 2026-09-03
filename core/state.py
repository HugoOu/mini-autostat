"""分析会话状态定义与终止检查（T2.1 / T2.4）。

AnalysisState 是 LangGraph 主图的唯一共享状态：Leader 与 4 个 Worker
（D-007）通过读写该状态协作。所有字段均为可选更新（total=False），
节点只需返回变更的字段，LangGraph 负责合并。

字段分组沿承根 README 设计，并按项目决策扩展：
- chart_requests：图表需求单（D-007，两个分析 Worker → 可视化 Worker 的协作载体）
- data_profile：数据体检报告结构化存放
- iteration / stop_reason：终止机制（T2.4）所需字段
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AnalysisState(TypedDict, total=False):
    """一次分析会话的完整状态。"""

    # ---- 对话历史（supervisor 消息流，add_messages 自动累积而非覆盖）----
    messages: Annotated[list[Any], add_messages]

    # ---- 用户假设与问题 ----
    current_hypothesis: str
    analysis_questions: list[str]

    # ---- 数据状态 ----
    data_path: str
    data_profile: dict        # 数据体检报告：变量类型/缺失/异常/国家年份覆盖
    data_cleaned: bool

    # ---- 分析进度 ----
    planned_steps: list[str]          # Leader 的当前计划（可被重规划覆盖）
    completed_steps: list[dict]       # {"step", "worker", "status", "summary"}
    current_worker: str | None
    iteration: int                    # supervisor 循环轮次，对照 max_turns

    # ---- 结果存储 ----
    chart_requests: list[dict]        # 图表需求单：{"chart_type","x","y","hue","title","intent","requester"}
    statistical_results: dict         # 各统计检验的结构化结果
    visualizations: list[dict]        # {"image_path", "text_table"}
    final_report: str | None

    # ---- 流程控制 ----
    interrupted: bool
    interruption_reason: str | None
    stop_reason: str | None           # 终止后写入：正常完成 / 达到上限 / 用户停止

    # ---- M4 编排控制（D-018）----
    rejection_counts: dict            # {"worker_name": 被打回次数}，上限 2
    outer_loops: int                  # 外层回环计数，上限 3，防止过早 FINISH 死循环
    synced_msg_count: int             # 消息游标：sync 节点增量解析 Worker 输出
    tool_usage: dict                  # {"worker": 本会话真实工具调用次数}（D-024 工具证据检查）
    remaining_steps: int              # langgraph 1.x ReactAgent 要求的运行时注入字段

    # ---- M5 中断/确认点（D-022）----
    user_directive: str | None        # checkpoint 节点的本轮用户决策：None=出报告，文本=注入新指令


def check_termination(state: AnalysisState, max_turns: int) -> tuple[bool, str | None]:
    """终止机制（T2.4）：三重条件检查，返回 (是否终止, 原因)。

    调用时机：Leader 每轮调度前检查。优先级：
    1. 已有显式 stop_reason（正常完成 / 用户停止 / 严重错误）；
    2. 用户主动中断（interrupted=True）；
    3. 达到 max_turns 硬上限（强制收敛，避免无限循环——考核终止机制要求）。
    """
    stop_reason = state.get("stop_reason")
    if stop_reason:
        return True, stop_reason

    if state.get("interrupted"):
        return True, state.get("interruption_reason") or "用户主动中断"

    iteration = state.get("iteration") or 0
    if max_turns and iteration >= max_turns:
        return True, f"达到最大调度轮次 {max_turns}，强制收敛输出已有结论"

    return False, None


def record_step(
    state: AnalysisState,
    step: str,
    worker: str,
    status: str,
    summary: str,
) -> list[dict]:
    """向 completed_steps 追加一条记录的纯函数（返回新列表，供节点返回值使用）。"""
    completed = list(state.get("completed_steps") or [])
    completed.append({"step": step, "worker": worker, "status": status, "summary": summary})
    return completed
