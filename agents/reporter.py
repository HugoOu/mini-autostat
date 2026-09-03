"""问题驱动的分析报告生成（T5.2，D-029 重构）。

题目 B 第 5 条要求报告包含六要素：数据说明、方法及选择原因、结果、
不确定性（置信区间/效应量）、限制、不应得出的结论。六要素是**内容
清单**而非章节结构——报告按问题驱动叙事组织（问题→过程→发现→
可靠性→局限→结论），六要素内容确定性嵌入对应章节，validate_report
按叙事章节关键词校验。

实现分三层（D-021）：
1. 素材收集 collect_materials：把 state 中的实际运行结果确定性序列化
   ——报告内容只能来自这些素材，禁止 LLM 编造（验收：报告与运行结果
   一致）；
2. LLM 生成 + 校验：调用 LLM 按叙事结构成文，validate_report 确定性
   检查六章节是否齐全，缺项则携带反馈重试一次；
3. 确定性兜底 _fallback_report：LLM 不可用或两次校验仍缺项时，退回
   确定性汇总并显式标注缺项——报告生成永不因 LLM 失败而中断。
"""
from __future__ import annotations

import json
from pathlib import Path

from core.config import AppConfig
from core.llm import get_llm
from core.state import AnalysisState
from core.tracer import RunTracer

# 叙事章节关键词（D-029）：与题目 B 六要素的确定性映射
#   问题与数据→数据说明；分析过程→方法及选择原因；主要发现→结果；
#   可靠性→不确定性；局限与适用边界→限制；不应得出的结论→同名要素
REQUIRED_SECTIONS = (
    "问题与数据",
    "分析过程",
    "主要发现",
    "可靠性",
    "局限与适用边界",
    "不应得出的结论",
)

REPORT_PROMPT = """你是资深统计分析报告撰写人。请严格基于下方【运行素材】撰写一份问题驱动的专业数据分析报告（Markdown）。

## 报告结构（必须包含以下六个 `##` 章节，按序编号）
## 一、问题与数据
   重述用户假设；数据来源、时间/国家范围、质量问题（对应六要素：数据说明）
## 二、分析过程
   叙事主线：探索 → 方法选择及理由 → 遇到的问题（假设条件不满足、
   代码报错等）→ 如何调整重试。写成有起承转合的过程叙事，
   不要罗列步骤清单（对应六要素：方法及选择原因）
## 三、主要发现
   统计结果与图表解读；图表一律用 Markdown 图片语法 ![](图片路径)
   嵌入并配文字解读，路径必须**逐字使用图表段给出的 image_path**
   （已是相对本报告、可直接渲染的正斜杠路径，禁止改写）（对应六要素：结果）
## 四、可靠性
   p 值、置信区间、效应量、样本量等证据强度评估（对应六要素：不确定性）
## 五、局限与适用边界
   外部效度、数据、方法层面的限制与结论适用范围（对应六要素：限制）
## 六、结论
   回答用户假设；其中必须有一个 `### 不应得出的结论` 小节，
   列出因果误读、过度外推等禁项（对应六要素：不应得出的结论）

## 硬性要求
1. **只允许使用运行素材中出现的数据、统计量、文件路径与结论**，
   禁止编造任何数值或图表；素材没有的信息写"（运行中未记录）"。
2. 「可靠性」章节须涵盖素材中的 p 值、置信区间、效应量、样本量
   局限等；素材中未提供的项也要明确指出缺失。
3. 篇幅以专业、完整为准（建议不少于 1500 字），不设上限——
   宁可完整，不要为凑短牺牲内容。
4. 直接输出 Markdown 正文，不要额外说明。

## 运行素材
{materials}
"""


def _jclip(obj, n: int) -> str:
    """JSON 段内截断（D-037）：素材各段独立限长，避免某一段超长把后面的
    图表路径段整体挤掉（曾致 LLM 报告图片引用全为"(运行中未记录)"）。"""
    text = json.dumps(obj, ensure_ascii=False, indent=1)
    return text if len(text) <= n else text[:n] + "...[截断]"


def _md_image_path(image_path: str | None, output_dir) -> str:
    """把 state 中的 image_path 转为可直接渲染的 Markdown 路径（D-038）。

    report.md 保存在 output_dir 下，而 image_path 以进程工作目录为基准
    （如 `outputs\\figures\\x.png`）——LLM 照抄会导致渲染双重失败：
    反斜杠被 Markdown 当转义符、且相对 report.md 少了一层目录。这里
    确定性转换为相对 output_dir 的正斜杠路径（如 `figures/x.png`）。"""
    if not image_path:
        return image_path or ""
    p = Path(image_path)
    if output_dir:
        base = Path(output_dir)
        for candidate in (p, p.resolve() if p.exists() else p):
            try:
                return candidate.relative_to(base).as_posix()
            except ValueError:
                try:
                    return candidate.relative_to(base.resolve()).as_posix()
                except ValueError:
                    continue
    return p.as_posix()


def collect_materials(state: AnalysisState, clip: int = 16000,
                      output_dir=None) -> str:
    """把 state 的实际运行结果确定性序列化为报告素材（D-021 第 1 层）。

    截断策略（D-037）：数据体检/统计结果等大 JSON 段各自限长（_jclip），
    图表段（标题+image_path+状态）不受限——图片路径是报告图片引用的
    唯一来源，必须完整送达 LLM。image_path 经 _md_image_path 转为相对
    report.md 的正斜杠路径（D-038），LLM 逐字引用即可正确渲染。"""
    parts: list[str] = []

    parts.append(f"### 用户假设\n{state.get('current_hypothesis') or '(未记录)'}")
    parts.append(f"### 终止原因\n{state.get('stop_reason') or '(未记录)'}")

    if state.get("data_profile"):
        parts.append("### 数据体检（data_profile）\n" + _jclip(
            state["data_profile"], 2400))

    completed = state.get("completed_steps") or []
    if completed:
        lines = [f"- **{s['step']}** [{s['worker']}] {s['status']}: {s['summary']}"
                 for s in completed]
        parts.append(f"### 完成步骤（{len(completed)}）\n" + "\n".join(lines))

    if state.get("statistical_results"):
        parts.append("### 统计结果（statistical_results）\n" + _jclip(
            state["statistical_results"], 4000))

    viz = state.get("visualizations") or []
    if viz:
        lines = []
        for v in viz:
            lines.append(f"- 图表《{v.get('title')}》："
                         f"{_md_image_path(v.get('image_path'), output_dir)} "
                         f"（状态 {v.get('status')}）")
            if v.get("text_table"):
                # text_table 只保留图表要点（D-034 素材瘦身）；路径段不受限
                lines.append(f"  文本表格：{str(v['text_table'])[:200]}")
        parts.append(f"### 图表（{len(viz)} 张，报告引用图片一律用下述"
                     f" image_path 原文）\n" + "\n".join(lines))

    text = "\n\n".join(parts)
    if len(text) > clip:  # 极端兜底（D-037：仅整体超限的安全网）
        text = text[:clip] + "...[素材截断]"
    return text


def validate_report(text: str) -> list[str]:
    """确定性校验：返回缺失的六要素章节名（空列表 = 合格）。"""
    return [s for s in REQUIRED_SECTIONS if s not in (text or "")]


def _fallback_report(state: AnalysisState, missing: list[str] | None = None,
                     output_dir=None) -> str:
    """确定性兜底报告（M4 简版扩展六要素提示），LLM 失败时保证有产出。"""
    lines = [
        "# Mini AutoSTAT 分析报告（确定性兜底版）",
        "",
        "> 注：LLM 报告生成不可用或未通过六要素校验，以下为运行结果的"
        "确定性汇总。"
        + (f"缺项章节：{'、'.join(missing)}。" if missing else ""),
    ]
    for section, body in _six_sections_from_state(state, output_dir):
        lines += [f"\n## {section}\n{body}"]
    return "\n".join(lines)


def _six_sections_from_state(
        state: AnalysisState, output_dir=None) -> list[tuple[str, str]]:
    """从 state 直接拼出六叙事章节（不经过 LLM），章节名与
    REQUIRED_SECTIONS 一致（D-029），保证兜底版可通过 validate_report。"""
    results = state.get("statistical_results") or {}
    viz = state.get("visualizations") or []
    completed = state.get("completed_steps") or []

    # 主要发现：统计结果 + 图表 Markdown 图片引用（保留 md 图片语法）
    findings = [json.dumps(results, ensure_ascii=False, indent=1)[:3000]] \
        if results else ["(未记录)"]
    for v in viz:
        if v.get("image_path"):
            findings.append(f"![{v.get('title')}]("
                            f"{_md_image_path(v['image_path'], output_dir)})")
        if v.get("text_table"):
            findings.append(f"文本表格：{v['text_table']}")

    return [
        ("问题与数据", json.dumps(state.get("data_profile") or "(未记录)",
                                  ensure_ascii=False, indent=1)),
        ("分析过程",
         "\n".join(f"- {s['step']} [{s['worker']}]: {s['summary'][:200]}"
                   for s in completed) or "(未记录)"),
        ("主要发现", "\n\n".join(findings)),
        ("可靠性",
         "(由统计结果中的 p 值/置信区间/效应量与 Worker 的 warnings 字段"
         "提供；本兜底版未做二次归纳)"),
        ("局限与适用边界",
         "\n".join(f"- 图表《{v.get('title')}》状态 {v.get('status')}"
                   for v in viz) or "(见各 Worker warnings)"),
        ("结论",
         "以上结论仅由运行素材直接支撑，未做超出数据的推断。\n\n"
         "### 不应得出的结论\n"
         "相关性不等于因果；未拒绝原假设不等于效应不存在；时间序列水平值"
         "回归存在伪回归风险。请结合上述统计结果的 warnings 解读。"),
    ]


def _content_text(raw) -> str:
    """规范化 AIMessage.content：思考链模型可能返回分块列表（thinking/text
    混合），只拼接 text 块，避免 str(list) 把报告变成带 \\n 转义的 repr。"""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, list):
        parts = []
        for b in raw:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(str(b.get("text") or ""))
            elif isinstance(b, str):
                parts.append(b)
        return "".join(parts).strip()
    return str(raw).strip()


def generate_report(
    state: AnalysisState,
    config: AppConfig,
    tracer: RunTracer | None = None,
) -> str:
    """生成六要素报告（T5.2 主入口）：LLM 生成 → 校验 → 重试 → 兜底。

    模型分层重试（D-036/D-039）：第 1 层用报告专用模型（report_model，
    默认 qwen3.8-flash 思考链 + reasoning_effort xhigh——GLM-5.3-Flash 对
    报告级长调用间歇性 HTTP 500，实测 3 次中 2 次失败），失败或校验不过
    再降级用 Worker 模型（临时覆盖思考链为开启，不影响 Worker Agent
    本身的思考链设置）——两者都不可用才走确定性兜底。
    """
    import time

    out_dir = str(config.output_dir)
    materials = collect_materials(state, output_dir=out_dir)
    prompt = REPORT_PROMPT.format(materials=materials)

    def _fix_paths(text: str) -> str:
        """确定性路径修正（D-038 兜底）：LLM 若仍照抄了工作目录基准的
        原始路径（反斜杠/多一层 outputs），统一替换为可渲染形式。"""
        for v in state.get("visualizations") or []:
            raw, fixed = v.get("image_path"), _md_image_path(
                v.get("image_path"), out_dir)
            if raw and fixed and raw != fixed:
                text = text.replace(str(raw), fixed)
        return text

    attempts = (
        # 第 1 层：报告专用模型（思考链 + reasoning_effort xhigh，D-039）
        ("reporter", 600, None),
        # 第 2 层：Worker 模型临时开思考链（D-039：不影响 Worker Agent 设置）
        ("worker", 600, {"thinking": {"type": "enabled"}}),
    )
    for idx, (role, timeout, override) in enumerate(attempts, start=1):
        label = f"第 {idx} 层（{'报告模型' if role == 'reporter' else 'Worker 模型'}）"
        try:
            # 报告为单次调用且质量优先。timeout=600（D-034）：思考链 +
            # ≥1500 字长文的生成时间远超通用 120s 预算；transport 层重试
            # 对超时/500 无意义（max_retries=0），重试交由外层模型分层循环。
            t0 = time.time()
            llm = get_llm(config, temperature=0.2, role=role,
                          override_extra_body=override,
                          timeout=timeout, max_retries=0)
            text = _content_text(llm.invoke(prompt).content)
            elapsed = time.time() - t0
        except Exception as e:  # 网络/服务端故障 → 降级下一层
            if tracer:
                tracer.log("reporter", "error", error=str(e)[:300],
                           decision=f"{label} LLM 报告生成失败")
            continue
        text = _fix_paths(text)
        missing = validate_report(text)
        if tracer:
            tracer.log("reporter", "check",
                       decision=(f"{label}生成 {len(text)} 字"
                                 f"耗时 {elapsed:.0f}s，六要素校验"
                                 + ("通过" if not missing else f"缺 {missing}")),
                       output_summary=text[:200])
        if not missing:
            return text
        prompt = (REPORT_PROMPT.format(materials=materials)
                  + f"\n\n## 上次生成缺项\n你上次缺少以下章节，必须补齐："
                    f"{'、'.join(missing)}。\n上次输出开头：{text[:300]}")

    if tracer:
        tracer.log("reporter", "finish", decision="使用确定性兜底报告")
    return _fallback_report(state, output_dir=out_dir)
