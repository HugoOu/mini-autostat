"""Mini AutoSTAT 交互式 CLI 入口（T5.1，D-021/D-022/D-030）。

实时进度展示（D-030）：主循环用 stream(stream_mode="updates",
subgraphs=True) 消费事件流，按实测粒度（scripts/check_stream.py
D-028 实测）转译为一行式进度：
- worker 子图层：`agent` 事件中的 tool_calls → `[执行] worker · 工具名`
- team 层：`leader` 最后一条 AI 消息的工具调用 → `[调度] Leader → worker`；
  worker 节点完成 → `[完成] worker：交接摘要`
- 根层：`sync` → `[质检]`；`gate` → `[系统] 打回/[收敛]`；`report` → `[报告]`

两类交互暂停点（stream 中均以 `__interrupt__` 事件呈现，实测区分）：
1. **中断点**（team 执行前静态暂停，interrupt_before=["team"]，
   呈现为空元组 → input=None 续流；首轮自动继续不打断——D-033，
   仅 QC 回环/追加任务轮询问）：
    回车            继续执行
    stop            终止流程（收敛到报告，已有成果不丢失）
    其他文本         视为用户新指令注入对话，Leader 重规划后继续
2. **确认点**（Leader 每轮 FINISH 后的 checkpoint 节点动态 interrupt，
   呈现为含 Interrupt 对象的元组 → Command(resume=...) 续流）：
    回车 / stop     生成报告并结束
    其他文本         追加任务：回注 team，基于已完成工作继续

运行中 Ctrl+C：落点在最近的 super-step 边界，以 as_node="sync" 写入
终止标记跳过当前轮 team，直接收敛到报告。

用法：
    .venv\\Scripts\\python.exe app.py --data examples/owid-energy-data.csv
    （也可 --hypothesis "..." 直接给假设，--retriever static 开启知识注入）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from core.config import ensure_dirs, load_config
from core.tracer import RunTracer
from workflows.graph import build_app, invoke_budget

_END_WORDS = ("stop", "结束")
_WORKERS = ("data_preprocessor", "descriptive_analyst",
            "modeling_analyst", "visualizer")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:  # 非交互环境（管道/CI）默认继续/结束
        return ""


def _short(text, n: int = 100) -> str:
    line = " ".join(str(text).split())
    return line[:n] + ("…" if len(line) > n else "")


def _handoff_summary(msg) -> str:
    """Worker 交接 JSON 中取 summary；解析失败回退原文。"""
    try:
        data = json.loads(str(msg.content))
        if isinstance(data, dict) and data.get("summary"):
            return str(data["summary"])
    except (ValueError, TypeError):
        pass
    return str(msg.content)


def _emit(ns: tuple, payload: dict) -> None:
    """把一个 stream 更新事件转译为一行实时进度（D-030）。"""
    for node, upd in (payload or {}).items():
        if not isinstance(upd, dict):
            continue
        msgs = upd.get("messages") or []
        # ---- worker 子图内部：agent 步中的工具调用 ----
        if len(ns) == 2 and ns[1].partition(":")[0] in _WORKERS:
            if node != "agent":
                continue  # tools 结果不重复播报
            for m in msgs:
                if type(m).__name__ != "AIMessage":
                    continue
                for tc in getattr(m, "tool_calls", None) or []:
                    print(f"   · {ns[1].partition(':')[0]}：{tc['name']}",
                          flush=True)
            continue
        # ---- team 层：Leader 调度 / Worker 交接 ----
        if len(ns) == 1:
            if node == "leader":
                last = next((m for m in reversed(msgs)
                             if type(m).__name__ == "AIMessage"), None)
                if last is None:
                    continue
                calls = getattr(last, "tool_calls", None) or []
                if calls:
                    for tc in calls:
                        target = tc["name"].replace("transfer_to_", "")
                        task = str((tc.get("args") or {}).get(
                            "task_description", ""))
                        print(f"[调度] Leader → {target}"
                              + (f"：{_short(task, 60)}" if task else ""),
                              flush=True)
                elif last.content:
                    print(f"[Leader] {_short(last.content)}", flush=True)
            elif node in _WORKERS:
                last = next((m for m in reversed(msgs)
                             if type(m).__name__ == "AIMessage"), None)
                if last is not None and last.content:
                    print(f"[完成] {node}：{_short(_handoff_summary(last))}",
                          flush=True)
            continue
        # ---- 根层：质检 / 回环决策 / 报告 ----
        if node == "sync":
            steps = upd.get("completed_steps") or []
            if steps:
                s = steps[-1]
                mark = "ok" if s.get("status") == "ok" else "不合格，打回"
                print(f"[质检] {s.get('step')}（{s.get('worker')}）→ {mark}",
                      flush=True)
        elif node == "gate":
            if upd.get("messages"):
                print(f"[系统] {_short(upd['messages'][-1].content)}",
                      flush=True)
            elif upd.get("stop_reason"):
                print(f"[收敛] {_short(upd['stop_reason'])}", flush=True)
            else:
                print("[系统] 存在未处理项，回环 Leader 重规划", flush=True)
        elif node == "report":
            report = str(upd.get("final_report") or "")
            print(f"[报告] 已生成（约 {len(report)} 字）", flush=True)


def _stop(app, cfg: dict, reason: str) -> None:
    """写入终止标记并跳过 team 直达 gate（D-021 第 3 条）。"""
    app.update_state(
        cfg,
        {"interrupted": True, "interruption_reason": reason,
         "stop_reason": reason},
        as_node="sync",
    )
    print(f"…已标记终止（{reason}），收敛至报告", flush=True)


def _invoke_interruptible(app, state_in: dict, cfg: dict) -> dict:
    """stream 版主循环（D-030）：实时进度 + 两类暂停点，直至收敛。"""
    stop_requested = False
    first_pause = True  # D-033：首轮 team 执行前的静态中断点自动继续
    stream_input = state_in  # 下一段流的输入：初始 state / None / Command

    while True:
        interrupted = False
        try:
            for ns, payload in app.stream(
                    stream_input, cfg, stream_mode="updates", subgraphs=True):
                if isinstance(payload, dict) and "__interrupt__" in payload:
                    interrupted = True
                    intr = payload["__interrupt__"]
                    snap = app.get_state(cfg)
                    if intr:  # ---- 确认点：Leader 已 FINISH（D-022）----
                        value = getattr(intr[0], "value", None)
                        steps = value.get("steps", "?") \
                            if isinstance(value, dict) else "?"
                        if stop_requested:
                            stream_input = Command(resume="go")
                            break
                        user = _ask(
                            f"\n[确认点] 已完成 {steps} 步。"
                            "回车/stop=生成报告结束 | 输入文本=追加任务 > ")
                        directive = user if user and user.lower() \
                            not in _END_WORDS else "go"
                        stream_input = Command(resume=directive)
                        break
                    # ---- 中断点：team 执行前（QC 回环 / 追加任务）----
                    # 首轮不再打断（D-033）：用户刚输入假设，无需确认，
                    # 直接继续执行；后续 QC 回环/追加任务轮仍询问
                    if first_pause:
                        first_pause = False
                        stream_input = None
                        break
                    steps = len((snap.values or {}).get("completed_steps") or [])
                    user = _ask(f"\n[中断点] 已完成 {steps} 步。"
                                "回车=继续 | stop=终止 | 或输入新指令 > ")
                    if user.lower() in _END_WORDS:
                        stop_requested = True
                        _stop(app, cfg, "用户主动中断")
                    elif user:
                        app.update_state(
                            cfg, {"messages": [HumanMessage(content=user)]})
                        print(f"…已注入新指令，Leader 将重规划：{user}",
                              flush=True)
                    stream_input = None
                    break
                _emit(ns, payload)
            else:
                return dict(app.get_state(cfg).values)  # 流耗尽 = 已收敛
        except KeyboardInterrupt:
            print("\n[Ctrl+C] 收到中断信号", flush=True)
            stop_requested = True
            _stop(app, cfg, "用户主动中断（Ctrl+C）")
            stream_input = None
            continue
        if not interrupted:  # 理论不可达（流耗尽已在 else 返回）
            return dict(app.get_state(cfg).values)


def main() -> None:
    args = sys.argv[1:]
    hypothesis = None
    if "--hypothesis" in args:
        i = args.index("--hypothesis")
        hypothesis = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    config = load_config(args)  # 剥离 --hypothesis 后解析其余参数

    if not hypothesis:
        hypothesis = input("请输入分析假设（回车使用内置示例）> ").strip()
    if not hypothesis:
        hypothesis = ("我想研究：2000-2023 年间中国的可再生能源发展"
                      "（renewables_share_energy）与经济增长（gdp）之间的"
                      "关系，请先做描述统计，再做相关性分析。")
    config.data_path = config.data_path if config.data_path.exists() \
        else Path("examples/owid-energy-data.csv")
    ensure_dirs(config)

    from langgraph.checkpoint.sqlite import SqliteSaver

    with RunTracer(log_dir=config.log_dir) as tracer, \
            SqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
        app = build_app(config, tracer, checkpointer=saver,
                        interrupt_before=True, user_checkpoint=True)
        cfg = {"configurable": {"thread_id": tracer.run_id},
               "recursion_limit": invoke_budget(config)}
        print(f"[cli] run_id={tracer.run_id} max_turns={config.max_turns} "
              f"retriever={config.retriever} data={config.data_path}", flush=True)

        result = _invoke_interruptible(
            app,
            {"messages": [{"role": "user", "content": hypothesis}],
             "current_hypothesis": hypothesis},
            cfg,
        )

    print("\n===== 会话结束 =====")
    print("stop_reason :", result.get("stop_reason"))
    for s in result.get("completed_steps") or []:
        print(f"  - [{s['status']:8}] {s['worker']}: {s['summary'][:80]}")
    print("visualizations :", len(result.get("visualizations") or []))
    print("report        :", Path(config.output_dir) / "report.md")


if __name__ == "__main__":
    main()
