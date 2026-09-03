"""RAG 预留接口（T5.3，D-004 / D-021）。

demo 阶段不引入真实 RAG，但在此预留**可替换的检索接口**：
- Leader/Worker 提示词组装处（workflows/graph.py 的 init 节点）只依赖
  BaseRetriever 接口，检索结果的注入格式由 build_context_block 统一；
- 未来接入向量检索时，仅需新增一个 BaseRetriever 子类并在
  create_retriever 工厂注册，工作流代码零改动（T5.3 验收标准）。

当前提供两个占位实现：
- NullRetriever：恒返回空列表（默认，等价于不注入任何上下文）；
- StaticMethodCatalog：内置统计方法适用条件知识条目，按关键词匹配——
  兼作方法目录的静态知识与真实 RAG 之间的过渡实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseRetriever(ABC):
    """检索接口：给定查询返回若干条知识文本（T5.3 约定签名）。"""

    name: str = "base"

    @abstractmethod
    def retrieve(self, query: str, k: int = 3) -> list[str]:
        """返回与 query 相关的至多 k 条知识文本；无结果返回空列表。"""


class NullRetriever(BaseRetriever):
    """空实现：恒返回空列表（demo 默认，注入点静默关闭）。"""

    name = "null"

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        return []


class StaticMethodCatalog(BaseRetriever):
    """静态方法目录：按关键词命中返回内置知识条目（D-004 占位实现）。

    条目内容与 core/tools/stat_tools.py 的方法选择逻辑对齐
    （正态性→Pearson/Spearman、平稳性→格兰杰前置等），作为
    Leader/Worker 决策的参考知识来源。
    """

    name = "static"

    _CATALOG: list[tuple[tuple[str, ...], str]] = [
        (("相关", "关联", "correlation", "pearson", "spearman"),
         "相关分析选择：两变量近似正态且线性关系用 Pearson；偏态、序数或"
         "含异常值时用 Spearman。相关系数仅度量线性/单调关联强度，不能"
         "推断因果，且易受共同趋势（混杂）影响，可先差分去除趋势再比较。"),
        (("格兰杰", "因果", "granger", "causality"),
         "格兰杰因果检验前置条件：序列须平稳（ADF 检验），非平稳时先差分；"
         "它检验的是「预测力增强」而非真实因果，样本量小（如年度数据 "
         "n<40）时功效很低，未拒绝原假设不等于不存在因果。"),
        (("回归", "regression", "ols"),
         "OLS 回归假设：线性、误差独立同分布、正态性（小样本推断需要）。"
         "应报告 R²、系数置信区间并做残差诊断（异方差/自相关）；时间序列"
         "回归须警惕伪回归——两边不平稳时 R² 高但无意义。"),
        (("平稳", "adf", "差分", "stationary"),
         "平稳性检验：ADF 原假设为存在单位根（不平稳）。不平稳序列先做"
         "一阶差分再检验，仍不平稳可二阶差分；差分后结论的解释对象是"
         "增量而非水平值。"),
        (("异常值", "缺失", "outlier", "missing"),
         "数据体检：缺失优先区分机制（随机/系统性），异常值用 IQR 法标记"
         "后须结合业务判断，不应静默删除；小样本下删除观测会显著改变结论。"),
    ]

    def retrieve(self, query: str, k: int = 3) -> list[str]:
        text = (query or "").lower()
        hits = [entry for keywords, entry in self._CATALOG
                if any(kw in text for kw in keywords)]
        return hits[:k]


_PROVIDERS: dict[str, type[BaseRetriever]] = {
    NullRetriever.name: NullRetriever,
    StaticMethodCatalog.name: StaticMethodCatalog,
}


def create_retriever(provider: str) -> BaseRetriever:
    """按 provider 名创建检索器（未知名报错并列出可用项）。"""
    if provider not in _PROVIDERS:
        raise KeyError(f"未知检索器 provider: {provider}；可用: "
                       f"{', '.join(sorted(_PROVIDERS))}")
    return _PROVIDERS[provider]()


def build_context_block(retriever: BaseRetriever, query: str, k: int = 3) -> str:
    """检索结果 → 提示词注入块；无命中返回空串（调用方跳过注入）。

    这是 Leader/Worker 提示词组装处的**唯一注入点**：无论底层是
    NullRetriever、静态目录还是未来的真实 RAG，注入格式都由本函数
    统一，工作流代码不感知实现（D-004 终态）。
    """
    docs = retriever.retrieve(query, k=k)
    if not docs:
        return ""
    lines = [f"[方法知识库 · {retriever.name} 检索结果，供决策参考]"]
    lines += [f"- {doc}" for doc in docs]
    return "\n".join(lines)
