"""结构化报告生成（T5.2）。

题目 B 第 5 条要求报告包含六要素：数据说明、方法及选择原因、结果、
不确定性（置信区间/效应量）、限制、不应得出的结论。

实现分三层（D-021）：
1. 素材收集 collect_materials：把 state 中的实际运行结果确定性序列化
   ——报告内容只能来自这些素材，禁止 LLM 编造（验收：报告与运行结果
   一致）；
2. LLM 生成 + 校验：调用 LLM 按六要素成文，validate_report 确定性
   检查六个必需章节是否齐全，缺项则携带反馈重试一次；
3. 确定性兜底 _fallback_report：LLM 不可用或两次校验仍缺项时，退回
   M4 式确定性汇总并显式标注缺项——报告生成永不因 LLM 失败而中断。
"""
from __future__ import annotations

import json

from core.config import AppConfig
from core.llm import get_llm
from core.state import AnalysisState
from core.tracer import RunTracer

# 六要素章节关键词（验收标准：六要素齐全）
REQUIRED_SECTIONS = (
    "数据说明",
    "方法及选择原因",
    "结果",
    "不确定性",
    "限制",
    "不应得出的结论",
)

REPORT_PROMPT = """你是统计分析报告撰写人。请严格基于下方【运行素材】撰写一份 Markdown 分析报告。

## 硬性要求
1. 报告必须包含以下六个章节（用 `##` 标题，顺序如下）：
   ## 数据说明
   ## 方法及选择原因
   ## 结果
   ## 不确定性
   ## 限制
   ## 不应得出的结论
2. **只允许使用运行素材中出现的数据、统计量、文件路径与结论**，
   禁止编造任何数值或图表；素材没有的信息写"（运行中未记录）"。
3. 「不确定性」章节须涵盖素材中的 p 值、置信区间、效应量、样本量
   局限等；素材中未提供的项也要明确指出缺失。
4. 「不应得出的结论」基于统计常识与素材中的 warnings 写（如相关性
   ≠因果、未拒绝≠不存在、伪回归风险等）。
5. 图表用素材中的图片路径与文本表格引用，不要重新解释图中没有的数据。
6. 篇幅控制在 800 字以内，直接输出 Markdown 正文，不要额外说明。

## 运行素材
{materials}
"""


def collect_materials(state: AnalysisState, clip: int = 6000) -> str:
    """把 state 的实际运行结果确定性序列化为报告素材（D-021 第 1 层）。"""
    parts: list[str] = []

    parts.append(f"### 用户假设\n{state.get('current_hypothesis') or '(未记录)'}")
    parts.append(f"### 终止原因\n{state.get('stop_reason') or '(未记录)'}")

    if state.get("data_profile"):
        parts.append("### 数据体检（data_profile）\n" + json.dumps(
            state["data_profile"], ensure_ascii=False, indent=1))

    completed = state.get("completed_steps") or []
    if completed:
        lines = [f"- **{s['step']}** [{s['worker']}] {s['status']}: {s['summary']}"
                 for s in completed]
        parts.append(f"### 完成步骤（{len(completed)}）\n" + "\n".join(lines))

    if state.get("statistical_results"):
        parts.append("### 统计结果（statistical_results）\n" + json.dumps(
            state["statistical_results"], ensure_ascii=False, indent=1))

    viz = state.get("visualizations") or []
    if viz:
        lines = []
        for v in viz:
            lines.append(f"- 图表《{v.get('title')}》：{v.get('image_path')} "
                         f"（状态 {v.get('status')}）")
            if v.get("text_table"):
                lines.append(f"  文本表格：{v['text_table']}")
        parts.append(f"### 图表（{len(viz)} 张）\n" + "\n".join(lines))

    text = "\n\n".join(parts)
    if len(text) > clip:  # 防止极端长素材撑爆上下文
        text = text[:clip] + "...[素材截断]"
    return text


def validate_report(text: str) -> list[str]:
    """确定性校验：返回缺失的六要素章节名（空列表 = 合格）。"""
    return [s for s in REQUIRED_SECTIONS if s not in (text or "")]


def _fallback_report(state: AnalysisState, missing: list[str] | None = None) -> str:
    """确定性兜底报告（M4 简版扩展六要素提示），LLM 失败时保证有产出。"""
    lines = [
        "# Mini AutoSTAT 分析报告（确定性兜底版）",
        "",
        "> 注：LLM 报告生成不可用或未通过六要素校验，以下为运行结果的"
        "确定性汇总。"
        + (f"缺项章节：{'、'.join(missing)}。" if missing else ""),
    ]
    for section, body in _six_sections_from_state(state):
        lines += [f"\n## {section}\n{body}"]
    return "\n".join(lines)


def _six_sections_from_state(state: AnalysisState) -> list[tuple[str, str]]:
    """从 state 直接拼出六要素章节（不经过 LLM）。"""
    results = state.get("statistical_results") or {}
    viz = state.get("visualizations") or []
    completed = state.get("completed_steps") or []
    return [
        ("数据说明", json.dumps(state.get("data_profile") or "(未记录)",
                                ensure_ascii=False, indent=1)),
        ("方法及选择原因",
         "\n".join(f"- {s['step']} [{s['worker']}]: {s['summary'][:200]}"
                   for s in completed) or "(未记录)"),
        ("结果", json.dumps(results, ensure_ascii=False, indent=1)[:3000]
         or "(未记录)"),
        ("不确定性",
         "(由统计结果中的 p 值/置信区间/效应量与 Worker 的 warnings 字段"
         "提供；本兜底版未做二次归纳)"),
        ("限制",
         "\n".join(f"- 图表《{v.get('title')}》状态 {v.get('status')}"
                   for v in viz) or "(见各 Worker warnings)"),
        ("不应得出的结论",
         "相关性不等于因果；未拒绝原假设不等于效应不存在；时间序列水平值"
         "回归存在伪回归风险。请结合上述统计结果的 warnings 解读。"),
    ]


def generate_report(
    state: AnalysisState,
    config: AppConfig,
    tracer: RunTracer | None = None,
) -> str:
    """生成六要素报告（T5.2 主入口）：LLM 生成 → 校验 → 重试 → 兜底。"""
    materials = collect_materials(state)
    prompt = REPORT_PROMPT.format(materials=materials)

    for attempt in (1, 2):
        try:
            llm = get_llm(config, temperature=0.2)
            text = str(llm.invoke(prompt).content).strip()
        except Exception as e:  # 网络/服务端故障 → 直接兜底
            if tracer:
                tracer.log("reporter", "error", error=str(e)[:300],
                           decision=f"第 {attempt} 次 LLM 报告生成失败")
            break
        missing = validate_report(text)
        if tracer:
            tracer.log("reporter", "check",
                       decision=(f"第 {attempt} 次生成，六要素校验"
                                 + ("通过" if not missing else f"缺 {missing}")),
                       output_summary=text[:200])
        if not missing:
            return text
        prompt = (REPORT_PROMPT.format(materials=materials)
                  + f"\n\n## 上次生成缺项\n你上次缺少以下章节，必须补齐："
                    f"{'、'.join(missing)}。\n上次输出开头：{text[:300]}")

    if tracer:
        tracer.log("reporter", "finish", decision="使用确定性兜底报告")
    return _fallback_report(state)
