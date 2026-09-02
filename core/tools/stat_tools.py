"""统计工具（T3.2，题目 B 第 2、4 条：方法及适用条件；模型假设检查）。

每个工具返回：统计量、p 值、效应量、假设条件是否满足、适用性警告。
方法选择规则（自动判定，属于技术细节，D-015 登记）：
- 相关分析：对两序列做正态性检验（Shapiro-Wilk，n≤5000），双方均正态
  用 Pearson，否则 Spearman；
- 格兰杰因果：前置 ADF 平稳性检验，任一序列非平稳则**结构化拒绝执行**
  并返回差分建议——这条天然构成考核要求的"失败→检测→恢复"链；
- 回归：OLS + 残差诊断（DW 自相关 / JB 正态 / BP 异方差 / VIF 多重共线）。
"""
from __future__ import annotations

import contextlib
import io
import json
import warnings

import numpy as np
import pandas as pd
from langchain_core.tools import tool
from scipy import stats as sps

from core import datastore


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _r(x, nd: int = 4):
    """数值取整；不可序列化对象原样返回。"""
    if isinstance(x, (int, float, np.floating, np.integer)) and not pd.isna(x):
        return round(float(x), nd)
    return x


def _get(key: str) -> pd.DataFrame:
    if not datastore.has_df(key) and key != "current" and datastore.has_df("current"):
        return datastore.get_df("current")
    return datastore.get_df(key)


def _pair(df: pd.DataFrame, x: str, y: str) -> tuple[pd.Series, pd.Series, str | None]:
    for c in (x, y):
        if c not in df.columns:
            raise ValueError(f"列不存在: {c}")
        if not pd.api.types.is_numeric_dtype(df[c]):
            raise ValueError(f"列 {c} 不是数值型（dtype={df[c].dtype}），请先预处理")
    sub = df[[x, y]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < 8:
        raise ValueError(f"有效样本过少（n={len(sub)}，需≥8），无法做统计推断")
    return sub[x], sub[y], None


@tool
def run_descriptive_stats(columns: str = "", df_key: str = "current") -> str:
    """描述性统计：数值列的计数/均值/标准差/最小四分位最大值，类别列的取值分布。
    columns 为逗号分隔列名（空=全部数值列+类别列前 10 个）。"""
    try:
        df = _get(df_key)
        if columns.strip():
            cols = [c.strip() for c in columns.split(",") if c.strip()]
            missing = [c for c in cols if c not in df.columns]
            if missing:
                raise ValueError(f"列不存在: {missing}")
        else:
            cols = list(df.select_dtypes("number").columns[:12]) + list(
                df.select_dtypes(include=["object", "string"]).columns[:5]
            )
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    out = {}
    for c in cols:
        s = df[c].dropna()
        if s.empty:
            out[c] = {"n": 0}
        elif pd.api.types.is_numeric_dtype(s):
            out[c] = {
                "n": int(len(s)), "mean": _r(s.mean(), 3), "std": _r(s.std(), 3),
                "min": _r(s.min(), 3), "q25": _r(s.quantile(.25), 3),
                "median": _r(s.median(), 3), "q75": _r(s.quantile(.75), 3),
                "max": _r(s.max(), 3),
            }
        else:
            top = s.value_counts().head(3)
            out[c] = {"n": int(len(s)), "n_unique": int(s.nunique()),
                      "top_values": {str(k): int(v) for k, v in top.items()}}
    return _dumps({"n_columns": len(cols), "stats": out})


@tool
def run_correlation_test(x: str, y: str, df_key: str = "current") -> str:
    """相关性检验（自动选法）：两列均通过正态性检验用 Pearson，否则 Spearman。
    返回相关系数、p 值、样本量、效应量解读与假设条件状态。"""
    try:
        df = _get(df_key)
        xs, ys, _ = _pair(df, x, y)
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    warnings_list = []
    n = len(xs)

    def normality(s: pd.Series) -> dict:
        if len(s) > 5000:
            # Shapiro 限制 5000 样本：改用偏度峰度近似判断
            skew, kurt = float(sps.skew(s)), float(sps.kurtosis(s))
            approx_ok = abs(skew) < 2 and abs(kurt) < 7
            return {"test": "skew_kurtosis", "passed": bool(approx_ok),
                    "skew": _r(skew, 3), "kurtosis": _r(kurt, 3)}
        stat, p = sps.shapiro(s)
        return {"test": "shapiro_wilk", "passed": bool(p > 0.05),
                "statistic": _r(stat), "p_value": _r(p)}

    nx, ny = normality(xs), normality(ys)
    both_normal = nx["passed"] and ny["passed"]
    if both_normal:
        method = "pearson"
        r, p = sps.pearsonr(xs, ys)
    else:
        method = "spearman"
        r, p = sps.spearmanr(xs, ys)
        warnings_list.append("至少一列不满足正态性，已自动改用 Spearman 秩相关")
    if p < 0.05 and abs(r) < 0.1:
        warnings_list.append("统计显著但效应量极小，实际意义存疑，不应过度解读")

    abs_r = abs(float(r))
    effect = ("极弱" if abs_r < 0.2 else "弱" if abs_r < 0.4 else
              "中等" if abs_r < 0.6 else "强" if abs_r < 0.8 else "极强")
    return _dumps({
        "method": method, "method_why": (
            "两列均近似正态 → Pearson（度量线性关系）"
            if both_normal else "存在非正态序列 → Spearman（基于秩，稳健）"),
        "correlation": _r(r), "p_value": _r(p), "n": n,
        "effect_size": effect,
        "interpretation": f"{method} {'r' if both_normal else 'rho'}={_r(r)}，{effect}相关，"
                          f"p={'<0.001' if p < 0.001 else _r(p)}",
        "assumptions": {"normality_x": nx, "normality_y": ny},
        "limitations": [
            "相关不等于因果；混杂变量（如时间趋势、国家规模）未控制",
            f"n={n} 的样本量下，p 值对微弱效应也可能显著",
        ],
        "warnings": warnings_list,
    })


@tool
def run_granger_causality(x: str, y: str, df_key: str = "current", maxlag: int = 2) -> str:
    """格兰杰因果检验（前置 ADF 平稳性检查）。检验 x 是否 Granger-导致 y。
    若任一序列非平稳（ADF p>0.05），拒绝执行并返回差分建议。"""
    try:
        df = _get(df_key)
        xs, ys, _ = _pair(df, x, y)
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    from statsmodels.tsa.stattools import adfuller

    def adf(s: pd.Series) -> dict:
        stat, p, *_ = adfuller(s.values, autolag="AIC", result_object=False)
        return {"adf_statistic": _r(stat), "p_value": _r(p),
                "stationary": bool(p <= 0.05)}

    adf_x, adf_y = adf(xs), adf(ys)
    if not (adf_x["stationary"] and adf_y["stationary"]):
        return _dumps({
            "ok": False,
            "reason": "格兰杰因果检验要求数据平稳，ADF 检验未通过",
            "adf_x": adf_x, "adf_y": adf_y,
            "assumptions_met": False,
            "suggestion": "对非平稳序列做一阶差分（np.diff）后重新检验；"
                          "或改用协整检验/误差修正模型",
            "note": "这是统计方法的适用条件限制，不是程序错误",
        })

    from statsmodels.tsa.stattools import grangercausalitytests

    data = np.column_stack([ys.values, xs.values])  # 检验第2列是否导致第1列
    results = {}
    with contextlib.redirect_stdout(io.StringIO()):  # 抑制 statsmodels 的表格打印
        res = grangercausalitytests(data, maxlag=maxlag)
    for lag in range(1, maxlag + 1):
        ftest = res[lag][0]["ssr_ftest"]
        results[f"lag{lag}"] = {"f_statistic": _r(ftest[0]), "p_value": _r(ftest[1])}
    p_min = min(v["p_value"] for v in results.values())
    return _dumps({
        "ok": True, "direction": f"{x} → {y}",
        "results_by_lag": results,
        "min_p_value": p_min,
        "conclusion": ("拒绝原假设：x 对 y 有格兰杰因果意义的预测力（需警惕伪回归）"
                       if p_min < 0.05 else "不能拒绝原假设：无显著格兰杰因果"),
        "assumptions_met": True,
        "limitations": [
            "格兰杰因果是预测意义上的因果，不等于真实因果机制",
            "结果对滞后阶数选择敏感；需先确认平稳（ADF 已通过）",
        ],
    })


@tool
def run_regression_analysis(y: str, x_vars: str, df_key: str = "current") -> str:
    """多元线性回归（OLS）+ 残差诊断。y 为因变量，x_vars 为逗号分隔自变量。
    返回系数表、R²、系数 95% 置信区间与 DW/JB/BP/VIF 四项诊断。"""
    try:
        df = _get(df_key)
        xlist = [c.strip() for c in x_vars.split(",") if c.strip()]
        if not xlist:
            raise ValueError("x_vars 不能为空")
        sub = df[[y] + xlist].copy()
    except KeyError as e:
        return _dumps({"error": f"数据集不存在: {e}"})
    except Exception as e:  # noqa: BLE001
        return _dumps({"error": str(e)})

    for c in [y] + xlist:
        if c not in df.columns:
            return _dumps({"error": f"列不存在: {c}"})
        if not pd.api.types.is_numeric_dtype(df[c]):
            return _dumps({"error": f"列 {c} 不是数值型，请先预处理"})
    sub = sub.replace([np.inf, -np.inf], np.nan).dropna()
    if len(sub) < len(xlist) + 10:
        return _dumps({"error": f"有效样本过少（n={len(sub)}），自由度不足"})

    import statsmodels.api as sm
    from statsmodels.stats.diagnostic import het_breuschpagan
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    from statsmodels.stats.stattools import durbin_watson, jarque_bera

    Y = sub[y].astype(float)
    X = sm.add_constant(sub[xlist].astype(float))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = sm.OLS(Y, X).fit()

    coefs = []
    for name in model.params.index:
        ci = model.conf_int().loc[name]
        coefs.append({
            "term": name, "coef": _r(model.params[name], 4),
            "std_err": _r(model.bse[name], 4), "t_value": _r(model.tvalues[name], 3),
            "p_value": _r(model.pvalues[name], 4),
            "ci95_low": _r(ci[0], 4), "ci95_high": _r(ci[1], 4),
        })

    dw = durbin_watson(model.resid)
    jb_stat, jb_p, _, _ = jarque_bera(model.resid)
    bp_lm, bp_p, _, _ = het_breuschpagan(model.resid, X)

    diagnostics = {
        "durbin_watson": {"value": _r(dw, 3),
                          "passed": bool(1.5 <= dw <= 2.5),
                          "note": "接近 2 为无自相关"},
        "residual_normality_jb": {"statistic": _r(jb_stat), "p_value": _r(jb_p, 4),
                                  "passed": bool(jb_p > 0.05)},
        "homoscedasticity_bp": {"lm_p_value": _r(bp_p, 4),
                                "passed": bool(bp_p > 0.05)},
    }
    if len(xlist) >= 2:
        vifs = [variance_inflation_factor(X.values, i + 1) for i in range(len(xlist))]
        diagnostics["multicollinearity_vif"] = {
            "per_variable": {c: _r(v, 2) for c, v in zip(xlist, vifs)},
            "passed": bool(max(vifs) < 10),
        }

    warnings_list = []
    if not diagnostics["durbin_watson"]["passed"]:
        warnings_list.append("残差存在自相关（时间序列数据常见），"
                             "标准误可能被低估，建议考虑 Newey-West 或面板方法")
    if not diagnostics["residual_normality_jb"]["passed"]:
        warnings_list.append("残差非正态，系数置信区间与 p 值解释需谨慎")
    if not diagnostics["homoscedasticity_bp"]["passed"]:
        warnings_list.append("存在异方差，建议稳健标准误（robust）")

    return _dumps({
        "formula": f"{y} ~ {' + '.join(xlist)}", "n": int(len(sub)),
        "r_squared": _r(model.rsquared, 4), "adj_r_squared": _r(model.rsquared_adj, 4),
        "f_statistic": _r(model.fvalue, 3), "f_p_value": _r(model.f_pvalue, 4),
        "coefficients": coefs,
        "diagnostics": diagnostics,
        "assumptions_met": all(
            v.get("passed", True) for v in diagnostics.values()
            if isinstance(v, dict) and "passed" in v
        ) and not warnings_list,
        "warnings": warnings_list,
        "limitations": [
            "OLS 结果解释为控制其他变量后的条件关联，非因果效应",
            "遗漏变量偏误无法通过诊断发现，解释需结合领域知识",
        ],
    })


TOOLS = [run_descriptive_stats, run_correlation_test, run_granger_causality, run_regression_analysis]
