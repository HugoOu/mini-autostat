"""探针：验证 reporter 的 LLM 报告生成调用（role=leader, timeout=600）
能否真实返回。用与真实运行相近规模的素材，测量耗时与产出。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.reporter import REPORT_PROMPT, validate_report
from core.config import load_config
from core.llm import get_llm

MATERIALS = """### 用户假设
美国可再生能源的发展与经济增长（GDP）是先污染后治理还是协同发展?
### 终止原因
所有计划步骤完成且合格，Leader 已确认 FINISH
### 数据体检（data_profile）
{"data_overview": "原始数据 owid-energy-data.csv：23377 行 130 列；工作集筛选：59 行（美国 1965-2023）",
 "quality_issues": ["gdp 缺失 1.7%", "gdp 检出 58 个异常值（IQR）"],
 "working_set": {"rows": 59, "columns": ["country", "year", "gdp", "renewables_share_energy"]}}
### 完成步骤（4）
- 数据预处理 [data_preprocessor] ok: 工作集筛选美国 1965-2023 共 59 行
- 描述性统计 [descriptive_analyst] ok: renewables_share_energy 均值 12.4%，2023 年达 23.1%
- 建模分析 [modeling_analyst] ok: 对数 GDP 对可再生能源份额回归，系数 0.42（p<0.001），R²=0.78
- 可视化 [visualizer] ok: 6 张图渲染完成
### 统计结果（statistical_results）
{"descriptive": [{"renewables_share_energy": {"mean": 12.4, "max": 23.1, "min": 2.9}}],
 "modeling": [{"ols": {"coef_log_gdp": 0.42, "p_value": 0.0003, "r_squared": 0.78,
   "n": 58, "ci_95": [0.28, 0.56], "warnings": ["时间序列水平值回归存在伪回归风险"]}}]}
### 图表（6 张）
- 图表《美国GDP与可再生能源发电量散点关系 (1965-2023)》：outputs/figures/a.png（状态 ok）
- 图表《化石能源份额 vs GDP》：outputs/figures/b.png（状态 ok）"""


def main() -> int:
    prompt = REPORT_PROMPT.format(materials=MATERIALS)
    print(f"prompt chars: {len(prompt)}", flush=True)
    llm = get_llm(load_config(), temperature=0.2, role="reporter",
                  timeout=600, max_retries=0)
    for attempt in (1, 2):
        t0 = time.time()
        try:
            resp = llm.invoke(prompt)
            dt = time.time() - t0
            text = str(resp.content).strip()
            missing = validate_report(text)
            print(f"attempt {attempt}: elapsed {dt:.1f}s, output {len(text)} chars, "
                  f"missing={missing or 'NONE'}", flush=True)
            print("---- head ----\n" + text[:400], flush=True)
            if not missing:
                print("PROBE PASS", flush=True)
                return 0
        except Exception as e:
            dt = time.time() - t0
            print(f"attempt {attempt}: FAILED after {dt:.1f}s: {type(e).__name__}: {e}",
                  flush=True)
    print("PROBE FAIL", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
