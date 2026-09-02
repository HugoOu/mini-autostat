"""tracer 演示脚本：向 logs/ 生成一条示例运行日志，供人工检验 jsonl 格式。

事件链有意包含「失败 → 检测 → 恢复」片段，展示考核要求的
异常处理记录形态。正式分析的日志由 M4/M5 的真实运行生成。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tracer import RunTracer


def main() -> None:
    with RunTracer(log_dir="logs", run_id="demo_manual_check") as t:
        t.log("user", "input",
              input_summary="我想验证假设：可再生能源发展与GDP增长存在正相关关系")
        t.log("leader", "route",
              input_summary="假设已接收",
              decision="先数据预处理，再描述统计，最后建模",
              next_action="调度 data_preprocessor")
        t.log("data_preprocessor", "tool_call",
              tool={"name": "load_csv", "provider": "native",
                    "args": {"path": "owid-energy-data.csv"}})
        t.log("data_preprocessor", "tool_result",
              output_summary="读取 221 行 × 128 列；gdp 列缺失 3.2%；"
                             "筛选 2000-2023 年主要经济体后剩 480 行",
              next_action="写回 data_profile")
        t.log("modeling_analyst", "tool_call",
              tool={"name": "run_granger_causality", "provider": "native",
                    "args": {"maxlag": 2}})
        t.log("modeling_analyst", "error",
              error="数据非平稳（ADF p=0.31），格兰杰检验前置条件不满足")
        t.log("leader", "check",
              decision="检测到非平稳错误，打回建模 Worker，要求先做一阶差分",
              next_action="重试")
        t.log("modeling_analyst", "tool_result",
              output_summary="一阶差分后 ADF p=0.02；格兰杰因果检验 p=0.04")
        t.log("leader", "finish",
              decision="所有步骤完成且结果合格",
              next_action="生成结构化报告")
    print("demo log written: logs/run_demo_manual_check.jsonl")


if __name__ == "__main__":
    main()
