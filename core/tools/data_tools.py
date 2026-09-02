"""数据工具（T3.1，题目 B 第 1 条：检查变量类型、缺失值与异常情况）。

所有工具以 JSON 字符串返回（Agent 以文本读取）；错误以
{"error": "..."} 结构返回而非抛异常，便于 Agent 读错误并调整方案。
OWID 数据说明：列 country / year / iso_code / population / gdp 与各
能源品种的消费、发电、占比等指标；缺失普遍存在（早期年份、小国）。
"""
from __future__ import annotations

import json

import pandas as pd
from langchain_core.tools import tool

from core import datastore


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _cols(df: pd.DataFrame, columns: str) -> list[str]:
    """解析逗号分隔列名；空串返回全部列。未识别列报 ValueError。"""
    if not columns or not columns.strip():
        return list(df.columns)
    wanted = [c.strip() for c in columns.split(",") if c.strip()]
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        raise ValueError(f"列不存在: {missing}；可用列示例: {list(df.columns[:15])} ...")
    return wanted


def _get(key: str) -> pd.DataFrame:
    if not datastore.has_df(key) and key != "current" and datastore.has_df("current"):
        return datastore.get_df("current")
    return datastore.get_df(key)


@tool
def load_csv(path: str) -> str:
    """加载 CSV 文件到工作区（存为 raw 与 current 两个数据集），返回数据概览：
    行列数、内存、各类型列数、类别列清单、缺失率最高的列。"""
    try:
        df = pd.read_csv(path)
    except Exception as e:  # noqa: BLE001 - 错误结构化返回给 Agent
        return _dumps({"error": f"读取失败: {e}"})

    datastore.store_df("raw", df)
    datastore.store_df("current", df)

    obj_cols = [c for c in df.columns if df[c].dtype == object]
    missing = (
        df.isna().mean().sort_values(ascending=False).head(10).round(4) * 100
    )
    summary = {
        "path": path,
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 1),
        "numeric_cols": int(df.select_dtypes("number").shape[1]),
        "categorical_cols": obj_cols[:30],
        "top_missing_columns": [
            {"column": c, "missing_pct": float(v)} for c, v in missing.items()
        ],
    }
    if "year" in df.columns:
        summary["year_range"] = [int(df["year"].min()), int(df["year"].max())]
    if "country" in df.columns:
        summary["n_countries"] = int(df["country"].nunique())
    return _dumps(summary)


@tool
def check_variable_types(columns: str = "", df_key: str = "current") -> str:
    """检查变量类型。columns 为逗号分隔列名（空=全部），返回数值/类别/时间列归类清单。"""
    try:
        df = _get(df_key)
        cols = _cols(df, columns)
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    grouped = {"numeric": [], "categorical": [], "datetime": [], "other": []}
    for c in cols:
        dtype = df[c].dtype
        if pd.api.types.is_numeric_dtype(dtype):
            grouped["numeric"].append(c)
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            grouped["datetime"].append(c)
        elif pd.api.types.is_object_dtype(dtype) or pd.api.types.is_string_dtype(dtype):
            grouped["categorical"].append(c)
        else:
            grouped["other"].append({"column": c, "dtype": str(dtype)})
    return _dumps({
        "n_checked": len(cols),
        "n_numeric": len(grouped["numeric"]),
        "numeric": grouped["numeric"][:60],
        "categorical": grouped["categorical"][:60],
        "datetime": grouped["datetime"],
        "other": grouped["other"][:20],
    })


@tool
def check_missing_values(columns: str = "", df_key: str = "current", top: int = 15) -> str:
    """检查缺失值。columns 为逗号分隔列名（空=按缺失率取前 top 列），
    返回各列缺失计数与缺失率。"""
    try:
        df = _get(df_key)
        cols = _cols(df, columns)
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    na = df[cols].isna()
    stats = [
        {"column": c, "n_missing": int(na[c].sum()),
         "missing_pct": round(float(na[c].mean()) * 100, 2)}
        for c in cols
    ]
    stats.sort(key=lambda x: x["missing_pct"], reverse=True)
    return _dumps({"rows": int(len(df)), "columns_checked": len(cols),
                   "missing_report": stats[: top]})


@tool
def detect_outliers(columns: str = "", df_key: str = "current", iqr_k: float = 1.5) -> str:
    """IQR 法异常值检测。columns 为逗号分隔的数值列名（空=取前 10 个数值列），
    返回各列上下界与异常点数量。"""
    try:
        df = _get(df_key)
        cols = _cols(df, columns)
    except (KeyError, ValueError) as e:
        return _dumps({"error": str(e)})

    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        return _dumps({"error": "指定列中没有数值列"})
    results = []
    for c in numeric[:10]:
        s = df[c].dropna()
        if s.empty:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - iqr_k * iqr, q3 + iqr_k * iqr
        n_out = int(((s < lo) | (s > hi)).sum())
        results.append({
            "column": c, "n": int(len(s)),
            "lower_bound": round(float(lo), 4), "upper_bound": round(float(hi), 4),
            "n_outliers": n_out, "outlier_pct": round(n_out / len(s) * 100, 2),
        })
    return _dumps({"method": f"IQR (k={iqr_k})", "outlier_report": results})


@tool
def select_data(
    countries: str = "",
    years: str = "",
    columns: str = "",
    df_key: str = "current",
) -> str:
    """筛选数据集并保存为新的工作数据集（覆盖 current）。
    countries: 逗号分隔国家名（空=全部）；years: 如 "2000:2023" 或 "2020"（空=全部）；
    columns: 逗号分隔列名（空=全部，自动保留 country/year）。"""
    try:
        df = _get(df_key)
    except KeyError as e:
        return _dumps({"error": str(e)})

    out = df
    if countries.strip():
        wanted = [c.strip() for c in countries.split(",") if c.strip()]
        if "country" not in out.columns:
            return _dumps({"error": "数据集中没有 country 列，无法按国家筛选"})
        found = out["country"].isin(wanted)
        not_found = sorted(set(wanted) - set(out.loc[found, "country"].unique()))
        out = out[found]
        if out.empty:
            return _dumps({"error": f"按国家筛选后为空；未找到: {not_found}"})
    if years.strip():
        if "year" not in out.columns:
            return _dumps({"error": "数据集中没有 year 列，无法按年份筛选"})
        if ":" in years:
            lo, hi = (int(x) for x in years.split(":"))
            out = out[out["year"].between(lo, hi)]
        else:
            out = out[out["year"] == int(years)]
        if out.empty:
            return _dumps({"error": f"按年份 {years} 筛选后为空"})
    if columns.strip():
        try:
            keep = _cols(out, columns)
        except ValueError as e:
            return _dumps({"error": str(e)})
        for c in ("country", "year"):
            if c in out.columns and c not in keep:
                keep = [c] + keep
        out = out[keep]

    datastore.store_df("current", out)
    return _dumps({
        "rows": int(len(out)), "cols": int(out.shape[1]), "columns": list(out.columns),
        "note": "已保存为工作数据集 current，后续工具默认使用它",
    })


TOOLS = [load_csv, check_variable_types, check_missing_values, detect_outliers, select_data]
