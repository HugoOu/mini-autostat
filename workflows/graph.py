"""主图组装（T4.2/T4.3，D-018）。

结构：外层控制图包住 langgraph-supervisor 子图——

    START → init → team(supervisor 子图) → sync → gate ─┬→ team（回环：QC 打回）
                                                        ├→ report → END（终止收敛）
                                                        └→ END（已有报告）

- team：create_supervisor 返回的图（state_schema=AnalysisState），
  内部 Leader 与 4 Worker 循环直到 Leader 输出 FINISH；
- sync：增量解析本轮新增消息，把 Worker 的 JSON 结果写回状态字段；
  校验不合格则计数并注入反馈消息（确定性 QC，T4.3 第二层）；
- gate：三重终止检查（T2.4）+ 回环决策；
- report：出口节点（M4 为确定性最小实现，M5 替换为 LLM 六要素报告）。

PostgresSaver 升级路径（D-003）：本文件唯一需要改动的是 compile 处
——替换 MemorySaver() 为 PostgresSaver.from_conn_string(...) 并执行
一次 checkpointer.setup()，状态定义与其余逻辑零改动。
"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.leader import MAX_REJECTIONS, build_leader_prompt
from agents.reporter import generate_report
from agents.workers import build_workers
from core.config import AppConfig
from core.llm import get_llm, parse_json_block
from core.state import AnalysisState, check_termination
from core.tools import register_all_tools
from core.tracer import RunTracer
from knowledge.retriever import build_context_block, create_retriever

# Worker JSON 输出的识别特征 → (展示名, 分类键, 校验必需字段)
# 分类键用于归属（出现即认定是该 Worker）；校验字段用于合格性判定（T4.3）
_WORKER_SIGNATURES = {
    "data_preprocessor": ("数据预处理", "data_overview",
                          ("data_overview", "working_set")),
    "descriptive_analyst": ("描述统计", "findings", ("findings",)),
    "modeling_analyst": ("建模分析", "analyses", ("analyses",)),
    "visualizer": ("可视化", "charts", ("charts",)),
}


def _clip(text, limit: int = 500):
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def classify_worker(content: str) -> str | None:
    """按 JSON 分类键识别 Worker 归属（D-018 第 5 条，不依赖 msg.name）。

    分类键与校验必需字段分离（T4.3）：缺字段的输出也能归属到 Worker
    并被打回，而不是被静默忽略。
    """
    data = parse_json_block(content)
    if not data or not isinstance(data, dict):
        return None
    for worker, (_, key, _required) in _WORKER_SIGNATURES.items():
        if key in data:
            return worker
    return None


def pending_rejections(state: AnalysisState) -> list[str]:
    """未达到打回上限的 Worker（仍有挽回机会，需 Leader 处理）。"""
    counts = state.get("rejection_counts") or {}
    return [w for w, n in counts.items() if 0 < n < MAX_REJECTIONS]


def chart_request(r: dict, requester: str) -> dict:
    """规范化一条图表需求单（D-007 协作载体）。"""
    return {"requester": requester, **{k: r.get(k) for k in
            ("chart_type", "x", "y", "hue", "title", "intent")}}


def process_new_messages(state: AnalysisState, tracer: RunTracer) -> dict:
    """增量解析本轮新增消息（sync 节点主体，独立成函数便于离线测试）。

    返回状态增量：completed_steps / rejection_counts / statistical_results /
    visualizations / chart_requests / synced_msg_count，不合格时附带
    反馈 SystemMessage 交 Leader 处理（T4.3 确定性校验层）。
    """
    msgs = list(state.get("messages") or [])
    cursor = state.get("synced_msg_count") or 0
    new_msgs: list[AnyMessage] = msgs[cursor:]
    updates: dict = {"synced_msg_count": len(msgs)}
    if not new_msgs:
        return updates

    completed = list(state.get("completed_steps") or [])
    rejections = dict(state.get("rejection_counts") or {})
    results = dict(state.get("statistical_results") or {})
    viz = list(state.get("visualizations") or [])
    chart_reqs = list(state.get("chart_requests") or [])
    feedback: list[SystemMessage] = []

    for msg in new_msgs:
        content = getattr(msg, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        for tc in getattr(msg, "tool_calls", None) or []:
            tracer.log("leader", "tool_call",
                       tool={"name": tc["name"], "provider": "native",
                             "args": _clip(tc.get("args"))})

        worker = classify_worker(content)
        if worker is None:
            continue
        label, _key, required = _WORKER_SIGNATURES[worker]
        data = parse_json_block(content)

        if data and all(k in data for k in required):
            completed.append({"step": label, "worker": worker, "status": "ok",
                              "summary": _clip(content, 300)})
            if worker == "data_preprocessor":
                updates["data_cleaned"] = True
                updates["data_profile"] = data
            elif worker == "descriptive_analyst":
                results.setdefault("descriptive", []).append(data)
                chart_reqs += [chart_request(r, worker)
                               for r in data.get("chart_requests", [])]
            elif worker == "modeling_analyst":
                results.setdefault("modeling", []).append(data)
                chart_reqs += [chart_request(r, worker)
                               for r in data.get("chart_requests", [])]
            elif worker == "visualizer":
                viz += [{"title": c.get("title"), "image_path": c.get("image_path"),
                         "status": c.get("status", "ok"),
                         "text_table": _clip(c.get("text_table"), 1200)}
                        for c in data.get("charts", [])]
            tracer.log(worker, "check", decision="结果合格",
                       output_summary=_clip(content, 200), next_action="写回状态字段")
        else:
            n = rejections.get(worker, 0) + 1
            rejections[worker] = n
            completed.append({"step": label, "worker": worker, "status": "rejected",
                              "summary": _clip(content, 200)})
            if n >= MAX_REJECTIONS:
                feedback.append(SystemMessage(content=(
                    f"[sync 校验] {worker} 已连续 {n} 次结果不合格，达到上限 "
                    f"{MAX_REJECTIONS}。请不要再打回该任务：换用其他方法或跳过，"
                    "并在最终结论中说明。")))
                tracer.log("leader", "check",
                           decision=f"{worker} 第 {n} 次不合格，达到上限，要求换方法",
                           error=_clip(content, 200))
            else:
                feedback.append(SystemMessage(content=(
                    f"[sync 校验] {worker} 的结果不合格（缺少 {required}），"
                    f"第 {n}/{MAX_REJECTIONS} 次打回。请重新调度该 Worker，"
                    "并明确指出需修正的问题。")))
                tracer.log("leader", "check",
                           decision=f"{worker} 第 {n} 次不合格，打回",
                           error=_clip(content, 200))

    updates.update(completed_steps=completed, rejection_counts=rejections,
                   statistical_results=results, visualizations=viz,
                   chart_requests=chart_reqs)
    if feedback:
        updates["messages"] = feedback
    return updates


def build_app(
    config: AppConfig,
    tracer: RunTracer,
    checkpointer=None,
    interrupt_before: bool = False,
    user_checkpoint: bool = False,
):
    """组装并编译主图。tracer 由调用方创建（一次运行一个）。

    checkpointer：demo 采用 SqliteSaver（D-020）——实测 MemorySaver 与
    supervisor 子图嵌套组合会死锁，SqliteSaver 的文件级持久化还让 M5
    中断恢复可跨进程续跑。传 None 则无持久化（仅诊断用）。
    升级 PostgresSaver 只改 compile 处（D-003 终态不变）。

    interrupt_before=True（T5.1）：在每次进入 team 前静态暂停，供
    CLI（app.py）注入新指令或终止——配合 checkpointer 的 resume
    能力实现「任意轮次之间可中断、可重规划」。

    user_checkpoint=True（T5.1 / D-022）：在 gate 的报告路径上启用
    checkpoint 节点（动态 interrupt）——Leader 每轮 FINISH 后询问用户
    「出报告结束 or 追加任务」；追加则回注 team 基于已完成工作继续。
    该节点位于外层图，动态中断由外层 checkpointer 持久化，不触碰
    子图嵌套（无 D-020 死锁风险）。仅交互式 CLI 启用；e2e 直通。
    """
    register_all_tools()
    workers = build_workers(config)

    # ---- RAG 预留接口注入点（T5.3 / D-021）----
    # provider 由配置决定（null/static/未来向量检索），工作流零改动
    retriever = create_retriever(config.retriever)

    # ---- supervisor 子图（架构核心件，来自 langgraph-supervisor）----
    # checkpointer=False（D-020 根因修正）：LangGraph 子图默认继承父图
    # checkpointer，嵌套 checkpoint 写入引发死锁（MemorySaver/SqliteSaver
    # 均复现）。持久化只需外层图级别——子图消息经 add_messages 已汇入
    # 主状态，外层 checkpoint 足以支撑 M5 中断恢复。
    from langgraph_supervisor import create_supervisor

    team = create_supervisor(
        agents=workers,
        model=get_llm(config),
        prompt=build_leader_prompt(config),
        supervisor_name="leader",
        state_schema=AnalysisState,
    ).compile(checkpointer=False)

    # ---- 控制节点 ----
    def init(state: AnalysisState) -> dict:
        """入口：登记用户假设与数据路径；按假设检索方法知识注入
        （T5.3 唯一注入点，provider 由配置决定，空结果则不注入）。"""
        context = build_context_block(retriever,
                                      state.get("current_hypothesis") or "")
        updates: dict = {"data_path": state.get("data_path") or config.data_path,
                         "iteration": 0}
        if context:
            updates["messages"] = [SystemMessage(content=context)]
            tracer.log("system", "route", decision=f"注入检索知识（{retriever.name}）",
                       output_summary=_clip(context, 200))
        tracer.log("user", "route",
                   input_summary=state.get("current_hypothesis") or "",
                   next_action="进入 supervisor 团队循环")
        return updates

    def sync(state: AnalysisState) -> dict:
        return process_new_messages(state, tracer)

    def gate(state: AnalysisState) -> dict:
        """终止检查（T2.4 三重条件）与回环决策。"""
        iteration = len(state.get("completed_steps") or [])
        scoped = {**state, "iteration": iteration}
        should_stop, reason = check_termination(scoped, config.max_turns)

        loops = state.get("outer_loops") or 0
        if not should_stop and pending_rejections(state) and loops < 3:
            tracer.log("leader", "replan",
                       decision=f"存在未处理的不合格结果 {pending_rejections(state)}，"
                                "回环交 Leader 处理")
            return {"outer_loops": loops + 1, "iteration": iteration}

        if not should_stop:
            should_stop, reason = True, (
                state.get("stop_reason")
                or "所有计划步骤完成且合格，Leader 已确认 FINISH")
        tracer.log("leader", "finish", decision=reason,
                   next_action="生成报告" if not state.get("final_report") else "结束")
        return {"stop_reason": reason, "iteration": iteration}

    def checkpoint(state: AnalysisState) -> dict:
        """用户确认点（T5.1 / D-022）：Leader FINISH 后询问「出报告 or 追加任务」。

        user_checkpoint=False 时为直通节点（e2e / 离线无交互场景）。
        启用时用动态 interrupt 挂起（由外层 checkpointer 持久化，
        不触碰子图嵌套，无 D-020 死锁风险），恢复值：
        - 空 / go / stop / 继续 等 → 确认结束，路由 report；
        - 其他文本 → 作为新指令注入对话，路由 team 续跑（同时清掉
          stop_reason，让 gate 下一轮重新评估终止条件）。
        """
        if not user_checkpoint:
            return {"user_directive": None}
        answer = interrupt({
            "steps": len(state.get("completed_steps") or []),
            "question": "回车/go=生成报告结束；输入文本=追加任务继续分析",
        })
        text = answer.strip() if isinstance(answer, str) else ""
        if not text or text.lower() in ("go", "continue", "继续",
                                        "stop", "结束"):
            tracer.log("user", "checkpoint", decision="确认结束，生成报告")
            return {"user_directive": None}
        tracer.log("user", "replan", input_summary=text,
                   decision="确认点注入新指令，回注 team 续跑")
        return {"user_directive": text, "stop_reason": None,
                "messages": [HumanMessage(content=text)]}

    def report(state: AnalysisState) -> dict:
        """出口节点：六要素结构化报告（T5.2，agents/reporter.py）——
        LLM 基于实际运行素材生成，校验缺项重试一次，失败确定性兜底。"""
        report_md = generate_report(state, config, tracer)
        out = Path(config.output_dir) / "report.md"
        out.write_text(report_md, encoding="utf-8")
        tracer.log("reporter", "finish", output_summary=_clip(report_md, 300),
                   next_action=f"报告已保存 {out}")
        return {"final_report": report_md}

    # ---- 外层控制图 ----
    g = StateGraph(AnalysisState)
    g.add_node("init", init)
    g.add_node("team", team)          # supervisor 子图（架构核心件）
    g.add_node("sync", sync)
    g.add_node("gate", gate)
    g.add_node("checkpoint", checkpoint)  # 用户确认点（D-022，默认直通）
    g.add_node("report", report)
    g.add_edge(START, "init")
    g.add_edge("init", "team")
    g.add_edge("team", "sync")
    g.add_edge("sync", "gate")
    # gate：QC 打回→team 直连；Leader FINISH→checkpoint（D-022）
    g.add_conditional_edges(
        "gate",
        lambda s: "checkpoint" if s.get("stop_reason") else "team",
        {"team": "team", "checkpoint": "checkpoint"},
    )
    # checkpoint：用户追加任务→team（基于已完成工作继续）；确认→report
    g.add_conditional_edges(
        "checkpoint",
        lambda s: "team" if s.get("user_directive") else "report",
        {"team": "team", "report": "report"},
    )
    g.add_edge("report", END)

    # Checkpointer（D-020）：demo 用 SqliteSaver（子图 checkpointer=False 防死锁）；
    # 升级 PostgresSaver 只改此处（D-003 终态不变）。
    # interrupt_before（T5.1）：每次进入 team 前暂停，供 CLI 注入指令/终止
    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["team"] if interrupt_before else None,
    )


def invoke_budget(config: AppConfig) -> int:
    """外层 invoke 的 recursion_limit 硬预算（D-018 第 3 条）。"""
    return config.max_turns * 8 + 30
