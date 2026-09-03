"""诊断 5：外层 wrapper（无 checkpointer）直接 invoke，隔离嵌套问题。

用法：python scripts/check_wrapper.py [--with-checkpointer]
"""
import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import ensure_dirs, load_config
from core.tracer import RunTracer
from workflows.graph import build_app, invoke_budget


def main() -> None:
    use_cp = "--with-checkpointer" in sys.argv
    cfg = load_config([])
    ensure_dirs(cfg)
    cfg.data_path = "examples/owid-energy-data.csv"

    from langgraph.checkpoint.sqlite import SqliteSaver

    if use_cp:
        saver_cm = SqliteSaver.from_conn_string("checkpoints_diag.sqlite")
    else:
        saver_cm = contextlib.nullcontext(None)
    with RunTracer(log_dir=cfg.log_dir, run_id=f"wrapdiag_{'cp' if use_cp else 'nocp'}") as tr, \
            saver_cm as saver:
        app = build_app(cfg, tr, checkpointer=saver)
        print(f"wrapper built (checkpointer={use_cp})", flush=True)
        t0 = time.time()
        result = app.invoke(
            {"messages": [{"role": "user",
                           "content": "请加载 examples/owid-energy-data.csv 并筛选 China 2000:2023 "
                                      "年的 gdp,renewables_share_energy 两列，然后 FINISH。"}],
             "current_hypothesis": "wrapper 诊断"},
            config={"configurable": {"thread_id": tr.run_id},
                    "recursion_limit": invoke_budget(cfg)},
        )
    print(f"wrapper invoke ok in {time.time() - t0:.1f}s, "
          f"steps={len(result.get('completed_steps') or [])}, "
          f"stop={result.get('stop_reason')}")


if __name__ == "__main__":
    main()
