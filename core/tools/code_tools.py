"""受限代码执行工具（T3.4，题目 B 第 3 条：自动生成并执行分析代码）。

安全边界（P-006 已确认：子进程 + 超时 + 静态黑名单，非沙箱级）：
1. 执行前静态扫描黑名单（os/subprocess/eval/open 等），命中即拒绝；
2. 代码在隔离子进程运行（sys.executable -I），带超时强杀；
3. 工作数据集 DataStore["current"] 先落盘为 df_input.csv，注入约定变量 df，
   代码通过 print() 输出结果，stdout 被捕获返回；
4. 运行产生的 PNG 收集回 outputs/figures/；
5. 失败返回结构化错误（stderr + 修复提示），供建模 Worker 的修复循环使用。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from langchain_core.tools import tool

from core import datastore

_STDOUT_LIMIT = 4000

# 静态黑名单：数据分析代码不需要这些能力（D-015 登记）
_BLACKLIST = [
    r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
    r"\bimport\s+shutil\b", r"\bimport\s+socket\b", r"\bimport\s+ctypes\b",
    r"\bfrom\s+(os|sys|subprocess|shutil|socket|ctypes)\b",
    r"__import__", r"\beval\s*\(", r"\bexec\s*\(", r"\bopen\s*\(",
    r"\bgetattr\s*\(", r"\bglobals\s*\(",
]

_HEADER = '''# ---- 执行环境自动注入（Mini AutoSTAT code_tools）----
import warnings
warnings.filterwarnings("ignore")
import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

df = None
try:
    df = pd.read_csv("df_input.csv")
    print(f"[data] 工作数据集已加载: {df.shape[0]} 行 x {df.shape[1]} 列")
    print(f"[data] 列: {list(df.columns)}")
except Exception as e:
    print(f"[data] 无可用工作数据集: {e}")

print("---- OUTPUT BEGIN ----")
'''


def _scan_blacklist(code: str) -> list[str]:
    hits = []
    for pattern in _BLACKLIST:
        m = re.search(pattern, code)
        if m:
            hits.append(m.group(0))
    return hits


def _clip(text: str | None, limit: int = _STDOUT_LIMIT) -> str | None:
    if text is None:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


@tool
def execute_python(code: str, timeout_seconds: int = 60) -> str:
    """在受限子进程中执行 Python 分析代码。约定：
    1) 变量 df 已注入（当前工作数据集，pandas.DataFrame，可能为 None）；
    2) 关键结果必须用 print() 输出；
    3) 禁止 import os/sys/subprocess/open()/eval() 等（黑名单会拒绝执行）；
    4) 可用库：pandas/numpy/scipy/statsmodels/matplotlib（Agg 后端）。
    失败时返回结构化错误供修复循环使用。"""
    hits = _scan_blacklist(code)
    if hits:
        return json.dumps({
            "success": False,
            "error": f"代码包含被禁止的操作: {hits}。分析代码请只使用 pandas/numpy/"
                     "scipy/statsmodels/matplotlib，数据通过变量 df 获取",
            "blocked_patterns": hits,
        }, ensure_ascii=False)

    workdir = Path(tempfile.mkdtemp(prefix="autostat_exec_"))
    try:
        if datastore.has_df("current"):
            datastore.get_df("current").to_csv(workdir / "df_input.csv", index=False)

        script = workdir / "analysis.py"
        script.write_text(_HEADER + "\n# ---- 生成代码开始 ----\n" + code + "\n", encoding="utf-8")

        started = time.perf_counter()
        try:
            proc = subprocess.run(
                # -I 隔离模式（忽略环境变量与用户站点配置）+ -B 不写 .pyc
                [sys.executable, "-I", "-B", str(script)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout_seconds, cwd=workdir,
            )
            duration = round(time.perf_counter() - started, 2)
            success = proc.returncode == 0
        except subprocess.TimeoutExpired:
            return json.dumps({
                "success": False, "error": f"执行超时（>{timeout_seconds}s），可能存在死循环",
                "stdout": None, "stderr": None,
            }, ensure_ascii=False)

        figures = []
        fig_dir = workdir.parent / "autostat_figs"  # 生成代码保存的 PNG 收集回 outputs
        png_dir = Path("outputs/figures")
        png_dir.mkdir(parents=True, exist_ok=True)
        for png in workdir.glob("*.png"):
            dest = png_dir / f"gen_{int(time.time() * 1000) % 10**8}_{png.name}"
            shutil.copy(png, dest)
            figures.append(str(dest))

        result = {
            "success": success,
            "returncode": proc.returncode,
            "duration_s": duration,
            "stdout": _clip(proc.stdout),
            "stderr": _clip(proc.stderr),
            "figures": figures,
        }
        if not success:
            result["error"] = "代码运行报错，请阅读 stderr 中的最后一个 Traceback 定位问题"
        return json.dumps(result, ensure_ascii=False)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


TOOLS = [execute_python]
