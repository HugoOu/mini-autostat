"""可视化工具（T3.3）：生成 PNG + 等价文本表格（README 多模态兼容特性）。

每个图表必附等价文本表格，确保纯文本 LLM 与无图环境可完整理解图表内容。
图表内文字（标题/轴标签/图例）一律英文（D-032/D-035）：Visualizer 按提示词
原生提供英文 title/xlabel/ylabel；非 ASCII 或空标题仍确定性回退为
"{y} vs {x}"（列名为英文）作为最后防线；中文字体配置仅作中文列名等
边缘场景兜底（D-015）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无显示环境
import matplotlib.pyplot as plt
import pandas as pd
from langchain_core.tools import tool

from core import datastore

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

_FIG_DIR: Path | None = None  # 延迟初始化，由 configure_figures_dir 注入


def configure_figures_dir(path) -> None:
    """设置图表输出目录（app 启动时按 config.output_dir 调用）。"""
    global _FIG_DIR
    _FIG_DIR = Path(path)
    _FIG_DIR.mkdir(parents=True, exist_ok=True)


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _get(key: str) -> pd.DataFrame:
    if not datastore.has_df(key) and key != "current" and datastore.has_df("current"):
        return datastore.get_df("current")
    return datastore.get_df(key)


def _slug(title: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", title.strip())[:40] or "chart"
    return f"{text}_{int(time.time() * 1000) % 10**8}"


def _render_title(title: str, x: str, y: str) -> str:
    """图表标题英文化（D-032）：非 ASCII（如中文）或空标题确定性回退为
    "{y} vs {x}"，保证 PNG 内无中文乱码；文件名与文本表格同步。"""
    text = (title or "").strip()
    return text if text and text.isascii() else f"{y} vs {x}"


def _text_table(df: pd.DataFrame, chart_type: str, x: str, y: str,
                hue: str, title: str, xlabel: str, ylabel: str,
                n_preview: int) -> str:
    """图表的等价文本表示（纯文本 LLM 可读）。标题/轴标签与 PNG 渲染一致
    （英文，D-032/D-035）。"""
    lines = [
        f"[图表类型: {chart_type}]",
        f"[标题: {title or f'{y} vs {x}'}]",
        f"[X轴: {xlabel or x}]" + (f" | [分组: {hue}]" if hue else ""),
        f"[Y轴: {ylabel or y}]",
        f"[数据点数量: {len(df)}]",
        f"[X范围: {df[x].min()} - {df[x].max()}]",
        f"[Y范围: {df[y].min()} - {df[y].max()}]",
    ]
    if chart_type in ("scatter", "line") and pd.api.types.is_numeric_dtype(df[x]):
        corr = df[x].corr(df[y])
        lines.append(f"[相关系数: {corr:.3f}]")
    if hue and hue in df.columns:
        lines.append("[分组摘要:]")
        for g in df[hue].unique():
            gd = df[df[hue] == g]
            lines.append(
                f"  {g}: n={len(gd)}, {x}均值={gd[x].mean():.2f}, {y}均值={gd[y].mean():.2f}"
            )
    lines.append(f"[数据点详情(前{n_preview}个):]")
    cols = [c for c in (x, y, hue) if c and c in df.columns]
    for _, row in df[cols].head(n_preview).iterrows():
        lines.append("  " + ", ".join(f"{c}={row[c]}" for c in cols))
    return "\n".join(lines)


@tool
def create_chart(
    chart_type: str,
    x: str,
    y: str,
    hue: str = "",
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    df_key: str = "current",
    n_preview: int = 10,
) -> str:
    """生成图表 PNG 并返回等价文本表格。chart_type 支持 scatter / line / bar；
    x、y 为列名；hue 为可选分组列；title/xlabel/ylabel 为英文图表标题与轴
    标签（中文标题会被系统降级为 "y vs x"，务必传英文）；返回 JSON 含
    image_path 与 text_table。"""
    try:
        df = _get(df_key)
    except KeyError as e:
        return _dumps({"error": str(e)})

    chart_type = chart_type.strip().lower()
    if chart_type not in ("scatter", "line", "bar"):
        return _dumps({"error": f"不支持的图表类型: {chart_type}（可选 scatter/line/bar）"})
    for c in (x, y):
        if c not in df.columns:
            return _dumps({"error": f"列不存在: {c}"})
    if hue and hue not in df.columns:
        return _dumps({"error": f"分组列不存在: {hue}"})

    sub = df[[c for c in (x, y, hue) if c]].replace(
        [float("inf"), -float("inf")], float("nan")
    ).dropna()
    if sub.empty:
        return _dumps({"error": "剔除缺失值后无数据可绘图"})

    fig, ax = plt.subplots(figsize=(9, 5))
    title = _render_title(title, x, y)  # D-032：图表内文字一律英文
    try:
        if chart_type == "scatter":
            if hue:
                for g, gd in sub.groupby(hue):
                    ax.scatter(gd[x], gd[y], label=str(g), s=28, alpha=0.8)
                ax.legend()
            else:
                ax.scatter(sub[x], sub[y], s=28, alpha=0.8)
        elif chart_type == "line":
            sub = sub.sort_values(x)
            if hue:
                for g, gd in sub.groupby(hue):
                    ax.plot(gd[x], gd[y], marker="o", markersize=3, label=str(g))
                ax.legend()
            else:
                ax.plot(sub[x], sub[y], marker="o", markersize=3)
        else:  # bar
            agg = sub.groupby(x)[y].mean()
            agg.plot(kind="bar", ax=ax)
            if not ylabel:
                ylabel = f"{y} (mean)"
        ax.set_xlabel(xlabel or x)   # D-035：轴标签用 Visualizer 提供的英文可读标签
        ax.set_ylabel(ylabel or y)
        ax.set_title(title or f"{y} vs {x}")
        ax.grid(alpha=0.3)
        fig.tight_layout()

        if _FIG_DIR is None:
            configure_figures_dir("outputs/figures")
        filename = f"{_slug(title or y)}.png"
        image_path = str(_FIG_DIR / filename)
        fig.savefig(image_path, dpi=150)
    finally:
        plt.close(fig)

    text_table = _text_table(sub, chart_type, x, y, hue, title,
                             xlabel or x, ylabel or y, n_preview)
    return _dumps({"image_path": image_path, "chart_type": chart_type,
                   "text_table": text_table})


TOOLS = [create_chart]
