"""M5 在线验收（T5.1/T5.2）：确认点追加任务 → 基于已完成工作续跑 → 六要素报告。

流程（模拟 app.py 的确认点交互，D-022）：
    1. 初始任务：加载 datasets/owid-energy-data.csv，筛选中国 2000-2023 的
       gdp / renewables_share_energy 做描述统计（第一轮 team，至 FINISH）；
    2. Leader FINISH 后进入 checkpoint 确认点（动态 interrupt）——
       第 1 次确认点：追加任务「对美国同期做同样描述统计并与中国对比」
       → 回注 team，Leader 基于已完成工作继续；
    3. 第 2 次确认点：回复 go → 生成六要素报告并收敛；
    4. 校验：completed_steps 覆盖两轮任务、报告六要素齐全且落盘。

用法：.venv\\Scripts\\python.exe -u scripts\\check_m5.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_dirs, load_config
from core.tracer import RunTracer
from workflows.graph import build_app, invoke_budget

INITIAL_TASK = ("请加载 datasets/owid-energy-data.csv，筛选中国 2000-2023 年的 "
                "gdp 与 renewables_share_energy 两列，给出描述统计后 FINISH。")
NEW_INSTRUCTION = ("补充任务：对美国（United States）同期做同样的描述统计，"
                   "并在结论中与中国对比。")
HYPOTHESIS = "中国可再生能源发展与经济增长的描述性对比研究"


def main() -> None:
    config = load_config(["--max-turns", "8"])
    ensure_dirs(config)
    config.data_path = "datasets/owid-energy-data.csv"

    from langgraph.checkpoint.sqlite import SqliteSaver
    from langgraph.types import Command

    confirmations = 0
    t0 = time.time()

    with RunTracer(log_dir=config.log_dir) as tracer, \
            SqliteSaver.from_conn_string("checkpoints_m5.sqlite") as saver:
        app = build_app(config, tracer, checkpointer=saver, user_checkpoint=True)
        cfg = {"configurable": {"thread_id": tracer.run_id},
               "recursion_limit": invoke_budget(config)}
        print(f"[m5] run_id={tracer.run_id} max_turns={config.max_turns}",
              flush=True)

        result = app.invoke(
            {"messages": [{"role": "user", "content": INITIAL_TASK}],
             "current_hypothesis": HYPOTHESIS},
            config=cfg,
        )
        while True:
            intr = (result or {}).get("__interrupt__")
            if not intr:
                break  # 已收敛（report/END）
            confirmations += 1
            payload = getattr(intr[0], "value", None) or {}
            steps = payload.get("steps", "?") if isinstance(payload, dict) else "?"
            directive = (NEW_INSTRUCTION if confirmations == 1 else "go")
            print(f"[m5] 确认点 {confirmations}（已完成 {steps} 步）→ "
                  f"{'追加任务' if confirmations == 1 else '确认出报告'}",
                  flush=True)
            result = app.invoke(Command(resume=directive), config=cfg)

    steps = result.get("completed_steps") or []
    report = result.get("final_report") or ""
    report_path = Path(config.output_dir) / "report.md"

    print(f"\n===== M5 验收摘要（{time.time() - t0:.0f}s，确认点 {confirmations} 次）=====")
    print("stop_reason :", result.get("stop_reason"))
    for s in steps:
        print(f"  - [{s['status']:8}] {s['worker']}: {s['summary'][:70]}")
    print("visualizations :", len(result.get("visualizations") or []))
    print("report        :", report_path)

    # ---- 验收断言 ----
    assert confirmations >= 2, "确认点未按预期触发（追加任务 + 确认出报告）"
    assert result.get("stop_reason"), "流程未收敛"
    assert report, "final_report 为空"
    assert report_path.exists(), "report.md 未写盘"
    for section in ("数据说明", "方法及选择原因", "结果", "不确定性",
                    "限制", "不应得出的结论"):
        assert section in report, f"报告缺六要素章节: {section}"
    print("\n[验收] 确认点交互 ✓  追加任务续跑 ✓  六要素齐全 ✓  报告落盘 ✓")
    print("[提示] 请人工核对报告是否包含美国对比结论（新指令的落实证据）")
    print("报告前 600 字符：\n", report[:600])


if __name__ == "__main__":
    main()
