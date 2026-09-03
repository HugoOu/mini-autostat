"""从 checkpoints.sqlite 续跑指定 thread 的确认点，生成报告（确认点恢复）。

用法：python scripts/resume_report.py <thread_id>
适用场景：CLI 在确认点等待回车时被关闭/后台运行 stdin 无法提供回车，
分析结果完好保存在 checkpoints.sqlite，本脚本以 Command(resume="go")
恢复该线程，report 节点会用最新 reporter 代码生成并保存 outputs/report.md。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from core.config import load_config
from core.tracer import RunTracer
from workflows.graph import build_app, invoke_budget


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/resume_report.py <thread_id>")
        return 2
    thread_id = sys.argv[1]
    config = load_config([])
    with RunTracer(log_dir=config.log_dir) as tracer, \
            SqliteSaver.from_conn_string("checkpoints.sqlite") as saver:
        app = build_app(config, tracer, checkpointer=saver,
                        interrupt_before=True, user_checkpoint=True)
        cfg = {"configurable": {"thread_id": thread_id},
               "recursion_limit": invoke_budget(config)}
        result = app.invoke(Command(resume="go"), cfg)

    rep = str(result.get("final_report") or "")
    print("stop_reason    :", result.get("stop_reason"))
    print("visualizations :", len(result.get("visualizations") or []))
    print("report chars   :", len(rep))
    print("report head    :", rep[:200].replace("\n", " | "))
    first_line = rep.splitlines()[0] if rep else "(empty)"
    print("is_fallback    :", "兜底" in first_line)
    return 0 if rep else 1


if __name__ == "__main__":
    sys.exit(main())
