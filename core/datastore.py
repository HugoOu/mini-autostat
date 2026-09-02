"""进程内 DataFrame 缓存（技术细节，D-015 登记）。

工具层各函数通过 key 共享 DataFrame，避免每次调用重复读盘；
预处理 Worker 产出的筛选数据集（key="current"）供后续所有
分析/可视化工具默认使用，这是 Worker 间数据协作的通道。
"""
from __future__ import annotations

import pandas as pd

_CACHE: dict[str, pd.DataFrame] = {}


def store_df(key: str, df: pd.DataFrame) -> None:
    """保存/覆盖一个命名数据集。"""
    _CACHE[key] = df


def get_df(key: str = "current") -> pd.DataFrame:
    """按 key 取数据集；不存在时抛 KeyError 并列出可用 key。"""
    if key not in _CACHE:
        available = ", ".join(sorted(_CACHE)) or "(空)"
        raise KeyError(f"数据集 '{key}' 不存在；可用: {available}")
    return _CACHE[key]


def has_df(key: str) -> bool:
    return key in _CACHE


def clear() -> None:
    """清空缓存（会话结束或测试复位用）。"""
    _CACHE.clear()
