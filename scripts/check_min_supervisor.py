"""诊断 3：最小 supervisor 复现（1 个无工具 Worker），二分定位 M4 e2e 停滞。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langgraph.prebuilt import create_react_agent
from langgraph_supervisor import create_supervisor

from core.config import load_config
from core.llm import get_llm
from core.state import AnalysisState


def main() -> None:
    cfg = load_config([])
    llm = get_llm(cfg)

    worker = create_react_agent(
        llm, tools=[], name="worker_a",
        prompt="你是 worker_a。收到任何任务都直接回复：worker_a 已收到。不要调用工具。",
    )
    team = create_supervisor(
        agents=[worker], model=llm,
        prompt="你是负责人。把任务交给 worker_a，收到其结果后立即 FINISH。",
        supervisor_name="leader",
    ).compile()
    print("minimal supervisor compiled", flush=True)

    t0 = time.time()
    result = team.invoke(
        {"messages": [{"role": "user", "content": "你好"}]},
        config={"recursion_limit": 20},
    )
    print(f"minimal supervisor ok in {time.time() - t0:.1f}s, "
          f"turns={len(result['messages'])}")
    for m in result["messages"]:
        print(" -", type(m).__name__, str(getattr(m, "content", ""))[:60])


if __name__ == "__main__":
    main()
