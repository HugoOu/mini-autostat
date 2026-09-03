"""Mini AutoSTAT 交互式 CLI 入口（T5.1，D-021/D-022）。

两类交互暂停点：
1. **中断点**（team 执行前静态暂停，interrupt_before=["team"]）：
    回车            继续执行
    stop            终止流程（收敛到报告，已有成果不丢失）
    其他文本         视为用户新指令注入对话，Leader 重规划后继续
2. **确认点**（Leader 每轮 FINISH 后的 checkpoint 节点，动态 interrupt）：
    回车 / stop     生成报告并结束
    其他文本         追加任务：回注 team，基于已完成工作继续

运行中 Ctrl+C：落点在最近的 super-step 边界，以 as_node="sync" 写入
终止标记跳过当前轮 team，直接收敛到报告。

用法：
    .venv\\Scripts\\python.exe app.py --data owid-energy-data.csv
    （也可 --hypothesis "..." 直接给假设，--retriever static 开启知识注入）
"""
from __future__ import annotations

import sys
from pathlib import Path

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from core.config import ensure_dirs, load_config
from core.tracer import RunTracer
from workflows.graph import build_app, invoke_budget

_END_WORDS = ("stop", "结束")


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:  # 非交互环境（管道/CI）默认继续/结束
        return ""


def _stop(app, cfg: dict, reason: str) -> None:
    """写入终止标记并跳过 team 直达 gate（D-021 第 3 条）。"""
    app.update_state(
        cfg,
        {"interrupted": True, "interruption_reason": reason,
         "stop_reason": reason},
        as_node="sync",
    )
    print(f"…已标记终止（{reason}），收敛至报告")


def _invoke_interruptible(app, state_in: dict, cfg: dict) -> dict:
    """带两类暂停点的 invoke 循环：暂停 → 用户决策 → 恢复，直至收敛。"""
    stop_requested = False

    def _step(value) -> dict:
        nonlocal stop_requested
        try:
            return app.invoke(value, config=cfg)
        except KeyboardInterrupt:
            print("\n[Ctrl+C] 收到中断信号")
            stop_requested = True
            _stop(app, cfg, "用户主动中断（Ctrl+C）")
            return app.invoke(None, config=cfg)

    result = _step(state_in)
    while True:
        intr = result.get("__interrupt__") if isinstance(result, dict) else None
        snap = app.get_state(cfg)
        pending = set(snap.next or ())

        if not intr and not ({"team", "checkpoint"} & pending):
            return result  # 已到 report/END，正常收敛

        if intr:  # ---- 确认点：Leader 已 FINISH（D-022）----
            payload = getattr(intr[0], "value", None)
            steps = payload.get("steps", "?") if isinstance(payload, dict) else "?"
            if stop_requested:
                result = _step(Command(resume="go"))
                continue
            user = _ask(f"\n[确认点] 已完成 {steps} 步。"
                        "回车/stop=生成报告结束 | 输入文本=追加任务 > ")
            directive = user if user and user.lower() not in _END_WORDS else "go"
            result = _step(Command(resume=directive))
        else:  # ---- 中断点：team 执行前（首轮 / QC 回环）----
            steps = len((snap.values or {}).get("completed_steps") or [])
            user = _ask(f"\n[中断点] 已完成 {steps} 步。"
                        "回车=继续 | stop=终止 | 或输入新指令 > ")
            if user.lower() in _END_WORDS:
                stop_requested = True
                _stop(app, cfg, "用户主动中断")
                result = _step(None)
            elif user:
                app.update_state(cfg, {"messages": [HumanMessage(content=user)]})
                print(f"…已注入新指令，Leader 将重规划：{user}")
                result = _step(None)
            else:
                result = _step(None)


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
        else Path("owid-energy-data.csv")
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
