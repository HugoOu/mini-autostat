"""M3 人工验收脚本：用真实 LLM（GLM-5.3-Flash）逐个 invoke 4 个 Worker。

T3.5 验收标准：每个 Worker 单独调用时能正确选择工具并返回结构化结果。
脚本按调度顺序执行，前一个 Worker 的产出（工作数据集）供后续使用。
每步打印 Worker 的工具调用轨迹与最终 JSON 输出摘要。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.workers import build_workers  # noqa: E402
from core.config import load_config, ensure_dirs  # noqa: E402
from core.tools import register_all_tools  # noqa: E402

TASKS = [
    ("data_preprocessor",
     "加载 owid-energy-data.csv 做数据体检，然后筛选 China、2000:2023 年、"
     "列 gdp,renewables_share_energy,energy_per_gdp 为工作数据集"),
    ("descriptive_analyst",
     "对当前工作数据集的 gdp 与 renewables_share_energy 做描述性统计，"
     "总结分布特征，并给出你认为必要的图表需求单"),
    ("modeling_analyst",
     "检验 gdp 与 renewables_share_energy 的统计关系：先做相关性检验；"
     "再做格兰杰因果检验（若被拒绝请按建议处理后再试）；最后给出你的方法说明与结论"),
    ("visualizer",
     "绘制一张图表：chart_type=scatter, x=year, y=renewables_share_energy, "
     "title=中国可再生能源占比趋势"),
]


def main() -> None:
    config = load_config()
    ensure_dirs(config)
    overview = register_all_tools()
    print(f"[registry] {len(overview)} tools registered: {sorted(overview)}\n")

    workers = {agent.name: agent for agent in build_workers(config)}
    print(f"[workers] built: {sorted(workers)}\n")

    for name, task in TASKS:
        print(f"{'=' * 70}\n>>> 调度 {name}: {task}\n{'=' * 70}")
        result = workers[name].invoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": 40},
        )
        # 打印工具调用轨迹
        for msg in result["messages"]:
            if tool_calls := getattr(msg, "tool_calls", None):
                for tc in tool_calls:
                    args = json.dumps(tc["args"], ensure_ascii=False)[:120]
                    print(f"  [tool_call] {tc['name']}({args})")
        final = result["messages"][-1].content
        print(f"--- 最终输出（前 600 字符）---\n{final[:600]}\n")

    print("all 4 workers checked")


if __name__ == "__main__":
    main()
