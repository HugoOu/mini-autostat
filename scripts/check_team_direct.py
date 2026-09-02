"""诊断 4：直接 invoke supervisor 子图（真实 4 Worker，无外层 wrapper / checkpointer）。

区分停滞根因：若本脚本也停滞 → 问题在 Leader 提示词/Worker 构成；
若本脚本通过 → 问题在外层包装（wrapper/checkpointer/subgraph 嵌套）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph_supervisor import create_supervisor

from agents.leader import build_leader_prompt
from agents.workers import build_workers
from core.config import load_config
from core.llm import get_llm
from core.state import AnalysisState
from core.tools import register_all_tools


def main() -> None:
    cfg = load_config([])
    register_all_tools()
    workers = build_workers(cfg)
    print("workers built", flush=True)

    team = create_supervisor(
        agents=workers, model=get_llm(cfg),
        prompt=build_leader_prompt(cfg) + "\n\n本次只做一件事：把任务交给 "
        "data_preprocessor 并在其返回后立即 FINISH，不要调度其他 Worker。",
        supervisor_name="leader",
        state_schema=AnalysisState,
    ).compile()
    print("team compiled", flush=True)

    t0 = time.time()
    result = team.invoke(
        {"messages": [{"role": "user",
                       "content": "请加载 owid-energy-data.csv 并筛选 China 2000:2023 "
                                  "年的 gdp,renewables_share_energy 两列。"}]},
        config={"recursion_limit": 40},
    )
    print(f"direct team invoke ok in {time.time() - t0:.1f}s, "
          f"n_msgs={len(result['messages'])}")


if __name__ == "__main__":
    main()
