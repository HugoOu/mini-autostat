"""从 checkpoints.sqlite 读取指定 thread 的最终 state，用当前 reporter
代码重新生成报告（不重跑工作流）。用于素材/提示词修复后的报告重生。

用法：python scripts/regen_report.py <thread_id>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.checkpoint.sqlite import SqliteSaver

from agents.reporter import collect_materials, generate_report
from core.config import load_config
from core.tracer import RunTracer


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python scripts/regen_report.py <thread_id>")
        return 2
    thread_id = sys.argv[1]
    config = load_config([])
    with SqliteSaver.from_conn_string("checkpoints.sqlite") as saver, \
            RunTracer(log_dir=config.log_dir) as tracer:
        tup = saver.get_tuple({"configurable": {"thread_id": thread_id}})
        if tup is None:
            print(f"thread 不存在: {thread_id}")
            return 1
        state = dict(tup.checkpoint["channel_values"])

        materials = collect_materials(state, output_dir=str(config.output_dir))
        print(f"materials chars: {len(materials)}")
        print("图表段完整:", "image_path 原文" in materials
              and materials.count("outputs") >= 1)
        report_md = generate_report(state, config, tracer)

    out = Path(config.output_dir) / "report.md"
    out.write_text(report_md, encoding="utf-8")
    first_line = report_md.splitlines()[0] if report_md else "(empty)"
    print("report chars :", len(report_md))
    print("is_fallback  :", "兜底" in first_line)
    print("saved        :", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
