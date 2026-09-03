"""M3 冒烟测试（离线，不调用 LLM）：四类工具在真实 OWID 数据上的行为。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

DATA = "examples/owid-energy-data.csv"
CN_COLS = "country,year,gdp,renewables_share_energy,energy_per_gdp"


def _parse(result: str) -> dict:
    return json.loads(result)


def _load_and_select():
    from core.tools.data_tools import load_csv, select_data

    overview = _parse(load_csv.invoke({"path": DATA}))
    assert "error" not in overview and overview["rows"] > 1000
    sel = _parse(select_data.invoke({
        "countries": "China", "years": "2000:2023", "columns": CN_COLS,
    }))
    assert "error" not in sel, sel
    return overview, sel


def test_data_tools_on_owid():
    from core import datastore
    from core.tools.data_tools import (
        check_missing_values, check_variable_types, detect_outliers,
    )

    overview, sel = _load_and_select()
    assert sel["rows"] > 0 and "renewables_share_energy" in sel["columns"]

    types = _parse(check_variable_types.invoke({"columns": CN_COLS}))
    assert "country" in types["categorical"] and "gdp" in types["numeric"]

    miss = _parse(check_missing_values.invoke({"columns": CN_COLS}))
    assert miss["rows"] == sel["rows"]

    out = _parse(detect_outliers.invoke({"columns": "gdp,renewables_share_energy"}))
    assert all("n_outliers" in r for r in out["outlier_report"])

    df = datastore.get_df("current")
    assert list(df.columns) == ["country", "year", "gdp",
                                "renewables_share_energy", "energy_per_gdp"]
    assert overview["n_countries"] > 100


def test_data_tools_error_paths():
    from core.tools.data_tools import check_variable_types, select_data

    bad = _parse(check_variable_types.invoke({"columns": "not_a_column"}))
    assert "error" in bad and "not_a_column" in bad["error"]

    empty = _parse(select_data.invoke({"countries": " Atlantis不存在的国家 "}))
    assert "error" in empty


def test_correlation_auto_selection():
    from core.tools.stat_tools import run_correlation_test

    res = _parse(run_correlation_test.invoke({
        "x": "gdp", "y": "renewables_share_energy",
    }))
    assert "error" not in res, res
    assert res["method"] in ("pearson", "spearman")
    assert 0 <= res["n"] and res["assumptions"]["normality_x"]["test"]
    # 中国 2000-2023：gdp 上升，可再生能源占比也上升 → 至少方向为正
    assert res["correlation"] > 0


def test_granger_refusal_and_success():
    from core import datastore
    from core.tools.stat_tools import run_granger_causality

    # 1) 趋势序列 → ADF 不通过 → 结构化拒绝（考核"失败检测"链）
    refused = _parse(run_granger_causality.invoke({
        "x": "gdp", "y": "renewables_share_energy",
    }))
    assert refused.get("ok") is False and refused["assumptions_met"] is False
    assert "差分" in refused["suggestion"]

    # 2) 平稳白噪声 → 正常执行
    rng = np.random.default_rng(42)
    n = 300
    noise = rng.normal(0, 1, n)
    x = np.zeros(n)
    for i in range(1, n):  # x 滞后影响 y 的构造
        x[i] = 0.7 * x[i - 1] + noise[i]
    y = np.zeros(n)
    for i in range(2, n):
        y[i] = 0.5 * x[i - 1] + rng.normal(0, 1)
    datastore.store_df("test_st", pd.DataFrame({"x": x, "y": y}))
    ok = _parse(run_granger_causality.invoke({"x": "x", "y": "y", "df_key": "test_st"}))
    assert ok.get("ok") is True and ok["assumptions_met"] is True
    assert "lag1" in ok["results_by_lag"]


def test_regression_with_diagnostics():
    from core import datastore
    from core.tools.stat_tools import run_regression_analysis

    rng = np.random.default_rng(7)
    n = 200
    x1 = rng.normal(10, 2, n)
    x2 = 0.5 * x1 + rng.normal(0, 1, n)  # 与 x1 一定程度共线
    y = 3 + 2 * x1 - 1 * x2 + rng.normal(0, 1, n)
    datastore.store_df("test_reg", pd.DataFrame({"y": y, "x1": x1, "x2": x2}))

    res = _parse(run_regression_analysis.invoke({
        "y": "y", "x_vars": "x1,x2", "df_key": "test_reg",
    }))
    assert "error" not in res, res
    assert res["r_squared"] > 0.5
    coef_names = [c["term"] for c in res["coefficients"]]
    assert "const" in coef_names and "x1" in coef_names
    assert "durbin_watson" in res["diagnostics"]
    assert res["diagnostics"]["multicollinearity_vif"]["per_variable"]["x1"] > 1


def test_viz_tools():
    from pathlib import Path

    from core.tools.viz_tools import create_chart

    scatter = _parse(create_chart.invoke({
        "chart_type": "scatter", "x": "year", "y": "renewables_share_energy",
        "title": "中国可再生能源占比趋势", "n_preview": 5,
    }))
    assert "error" not in scatter, scatter
    assert Path(scatter["image_path"]).exists()
    assert "相关系数" in scatter["text_table"]
    # D-032：图表内文字一律英文——中文标题确定性回退为 "{y} vs {x}"，
    # 文本表格标题与 PNG 内标题一致（防中文渲染乱码）
    assert "renewables_share_energy vs year" in scatter["text_table"]
    assert "中国可再生能源占比趋势" not in scatter["text_table"]

    line = _parse(create_chart.invoke({
        "chart_type": "line", "x": "year", "y": "gdp",
        "title": "GDP trend 2000-2023", "n_preview": 5,  # ASCII 标题原样保留
    }))
    assert "error" not in line, line
    assert Path(line["image_path"]).exists()
    assert "GDP trend 2000-2023" in line["text_table"]

    bad = _parse(create_chart.invoke({"chart_type": "pie", "x": "year", "y": "gdp"}))
    assert "error" in bad


def test_render_title_english_fallback():
    """D-032：非 ASCII（中文）标题回退 "{y} vs {x}"，ASCII 保留。"""
    from core.tools.viz_tools import _render_title

    assert _render_title("中国趋势", "year", "gdp") == "gdp vs year"
    assert _render_title("  GDP trend  ", "year", "gdp") == "GDP trend"
    assert _render_title("", "year", "gdp") == "gdp vs year"


def test_code_tools():
    from core.tools.code_tools import execute_python

    # 1) 正确代码：用注入的 df 计算相关系数
    ok = _parse(execute_python.invoke({
        "code": "r = df['gdp'].corr(df['renewables_share_energy'])\n"
                "print(f'corr={r:.4f}')\n"
                "assert 0 < r < 1\n"
                "print('done')",
    }))
    assert ok["success"], ok
    assert "corr=" in ok["stdout"] and "done" in ok["stdout"]

    # 2) 报错代码：返回结构化错误（供修复循环）
    bad = _parse(execute_python.invoke({
        "code": "df['不存在列'].sum()",
    }))
    assert bad["success"] is False and "KeyError" in bad["stderr"]

    # 3) 黑名单：危险 import 被拒绝
    blocked = _parse(execute_python.invoke({
        "code": "import os\nos.system('echo hi')",
    }))
    assert blocked["success"] is False and "blocked_patterns" in blocked

    # 4) 绘图禁令（D-027）：生成代码不得自行绘图，须转交 visualizer
    plot = _parse(execute_python.invoke({
        "code": "import matplotlib.pyplot as plt\n"
                "plt.plot(df['year'], df['gdp'])\n"
                "plt.savefig('trend.png')\nprint('saved')",
    }))
    assert plot["success"] is False and "blocked_patterns" in plot
    assert "visualizer" in plot["error"], "应提示图表转交 visualizer"

    # 4b) savefig / seaborn / plotly 同样被禁
    for snippet in ("fig.savefig('x.png')", "import seaborn as sns",
                    "import plotly.express as px"):
        banned = _parse(execute_python.invoke({"code": snippet}))
        assert banned["success"] is False, snippet


def test_registry_full():
    from core.tools import register_all_tools

    overview = register_all_tools()
    expected = {
        "load_csv", "check_variable_types", "check_missing_values",
        "detect_outliers", "select_data",
        "run_descriptive_stats", "run_correlation_test",
        "run_granger_causality", "run_regression_analysis",
        "create_chart", "execute_python",
    }
    assert expected <= set(overview)
    assert all(p == "native" for p in overview.values())


if __name__ == "__main__":
    tests = [
        test_data_tools_on_owid,
        test_data_tools_error_paths,
        test_correlation_auto_selection,
        test_granger_refusal_and_success,
        test_regression_with_diagnostics,
        test_viz_tools,
        test_render_title_english_fallback,
        test_code_tools,
        test_registry_full,
    ]
    for fn in tests:
        fn()
        print(f"PASS  {fn.__name__}")
    print("M3 smoke tests: all passed")
