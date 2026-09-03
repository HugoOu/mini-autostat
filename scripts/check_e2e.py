"""M4 端到端验收（T4.2）：真实 LLM 跑通「假设 → 预处理 → 描述 → 建模 → 可视化 → FINISH → 报告」。

用法：
    .venv\\Scripts\\python.exe -u scripts\\check_e2e.py [--countries China,...] [--max-turns N]

产出：
    logs/run_<run_id>.jsonl   全链路事件
    outputs/report.md         M4 简版报告
    outputs/figures/*.png     图表
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_dirs, load_config  # noqa: E402
from core.tracer import RunTracer  # noqa: E402
from workflows.graph import build_app, invoke_budget  # noqa: E402

DEFAULT_HYPOTHESIS = (
    "我想研究：2000-2023 年间中国的可再生能源发展（renewables_share_energy）"
    "与经济增长（gdp）之间是『先污染后治理』还是『协同发展』关系？"
    "请用描述统计刻画两者演变趋势，用相关性分析衡量关联强度，"
    "并尝试格兰杰因果检验判断方向。"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--countries", default="China")
    ap.add_argument("--hypothesis", default=DEFAULT_HYPOTHESIS)
    args, _unknown = ap.parse_known_args()

    config = load_config([])
    ensure_dirs(config)
    config.data_path = "datasets/owid-energy-data.csv"

    from langgraph.checkpoint.sqlite import SqliteSaver

    with RunTracer(log_dir=config.log_dir) as tracer, \
            SqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
        app = build_app(config, tracer, checkpointer=saver)
        print(f"[e2e] run_id={tracer.run_id} max_turns={config.max_turns} "
              f"budget={invoke_budget(config)}", flush=True)

        result = app.invoke(
            {
                "messages": [{"role": "user", "content": args.hypothesis}],
                "current_hypothesis": args.hypothesis,
            },
            config={
                "configurable": {"thread_id": tracer.run_id},
                "recursion_limit": invoke_budget(config),
            },
        )

    print("\n===== 状态摘要 =====")
    print("stop_reason :", result.get("stop_reason"))
    print("steps       :", len(result.get("completed_steps") or []))
    for s in result.get("completed_steps") or []:
        print(f"  - [{s['status']:8}] {s['worker']}: {s['summary'][:80]}")
    print("visualizations :", len(result.get("visualizations") or []))
    print("report        :", Path(config.output_dir) / "report.md")
    final = result.get("messages")[-1]
    print("\n===== Leader 最终总结（前 800 字符）=====")
    print(str(getattr(final, "content", final))[:800])


if __name__ == "__main__":
    main()
