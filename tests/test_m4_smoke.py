"""M4 冒烟测试（离线，不调用 LLM）：主图编译、消息解析、QC 校验逻辑。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import load_config
from core.datastore import clear as clear_store
from core.tracer import RunTracer
from workflows.graph import (
    chart_request, classify_worker, invoke_budget, pending_rejections,
    process_new_messages,
)

_PREPROCESSOR_JSON = '```json\n{"data_overview": "23377 行 130 列", "working_set": "China 2000-2023, 5 列", "quality_issues": [], "cleaning_actions": [], "warnings": []}\n```'
_BAD_PREPROCESSOR = '```json\n{"data_overview": "缺 working_set 字段"}\n```'
_DESCRIPTIVE_JSON = '```json\n{"findings": ["gdp 逐年上升"], "key_numbers": {}, "chart_requests": [{"chart_type": "line", "x": "year", "y": "gdp", "hue": "", "title": "GDP 趋势", "intent": "看趋势"}], "suggestions_for_modeling": []}\n```'
_MODELING_JSON = '```json\n{"analyses": [{"method": "spearman", "why_this_method": "非正态", "results": "r=0.85, p<0.001", "limitations": []}], "chart_requests": [], "overall_conclusion": "强正相关"}\n```'
_VIZ_JSON = '```json\n{"charts": [{"title": "GDP 趋势", "image_path": "outputs/figures/x.png", "text_table": "[图表类型: line]...", "status": "ok"}]}\n```'


def _fresh_state(messages: list) -> dict:
    return {"messages": messages, "synced_msg_count": 0}


def _tracer():
    return RunTracer(log_dir=tempfile.mkdtemp(), run_id="m4_test")


class _Msg:
    def __init__(self, content, tool_calls=None, name=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.name = name


class _ToolMsg:
    """模拟 ToolMessage（工具真实执行结果，D-024 工具证据）。"""

    def __init__(self, name, content="ok", status="success"):
        self.content = content
        self.name = name
        self.tool_call_id = f"call_{name}"
        self.status = status


def test_classify_worker():
    assert classify_worker(_PREPROCESSOR_JSON) == "data_preprocessor"
    assert classify_worker(_DESCRIPTIVE_JSON) == "descriptive_analyst"
    assert classify_worker(_MODELING_JSON) == "modeling_analyst"
    assert classify_worker(_VIZ_JSON) == "visualizer"
    assert classify_worker("没有 JSON 的普通文本") is None
    # 分类键命中即归属（即使校验字段不全）——归属后由校验层打回（T4.3）
    assert classify_worker('{"data_overview": "缺必需字段"}') == "data_preprocessor"


def test_process_new_messages_ok():
    tracer = _tracer()
    state = _fresh_state([
        _Msg("用户假设：可再生能源与GDP的关系"),
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_data_preprocessor", "args": {}}]),
        _Msg("", name="data_preprocessor",
             tool_calls=[{"name": "load_csv", "args": {"path": "owid-energy-data.csv"}}]),
        _ToolMsg("load_csv", "23377 行已加载"),
        _Msg(_PREPROCESSOR_JSON, name="data_preprocessor"),
        _Msg("", name="data_preprocessor",
             tool_calls=[{"name": "transfer_back_to_leader", "args": {}}]),
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_descriptive_analyst", "args": {}}]),
        _Msg(_DESCRIPTIVE_JSON, name="descriptive_analyst",
             tool_calls=[{"name": "run_descriptive_stats", "args": {}}]),
    ])
    updates = process_new_messages(state, tracer)

    assert updates["synced_msg_count"] == 8
    statuses = [s["status"] for s in updates["completed_steps"]]
    assert statuses == ["ok", "ok"]
    assert updates["data_cleaned"] is True
    assert updates["data_profile"]["data_overview"].startswith("23377")
    assert updates["statistical_results"]["descriptive"][0]["findings"]
    assert updates["chart_requests"][0]["requester"] == "descriptive_analyst"
    assert updates["chart_requests"][0]["chart_type"] == "line"
    assert updates["tool_usage"]["data_preprocessor"] == 1
    assert updates["tool_usage"]["descriptive_analyst"] == 1
    assert "messages" not in updates  # 全部合格，无需反馈
    tracer.close()


def test_tool_usage_enforced_without_tools():
    """D-024：Worker JSON 完整但零工具调用 → 必须打回（防编造）。"""
    tracer = _tracer()
    state = _fresh_state([_Msg("任务"), _Msg(_PREPROCESSOR_JSON)])
    updates = process_new_messages(state, tracer)

    assert updates["completed_steps"][0]["status"] == "rejected"
    feedback = updates["messages"][0].content
    assert "没有任何真实工具调用" in feedback and "打回" in feedback
    assert updates["rejection_counts"] == {"data_preprocessor": 1}
    tracer.close()


def test_viz_render_failure_rejected():
    """D-024：visualizer 图表条目缺 image_path（渲染失败）→ 必须打回。"""
    bad_viz = ('```json\n{"charts": [{"title": "t", "image_path": null,'
               ' "text_table": "", "status": "render failed"}]}\n```')
    tracer = _tracer()
    state = _fresh_state([
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_visualizer", "args": {}}]),
        _Msg("", name="visualizer",
             tool_calls=[{"name": "create_chart", "args": {}}]),
        _ToolMsg("create_chart", "列不存在", status="error"),
        _Msg(bad_viz, name="visualizer"),
    ])
    updates = process_new_messages(state, tracer)

    assert updates["completed_steps"][0]["status"] == "rejected"
    assert "image_path" in updates["messages"][0].content
    # 渲染失败也是真实工具调用（有尝试证据），usage 应计数
    assert updates["tool_usage"]["visualizer"] == 1
    tracer.close()


def test_viz_charts_recovered_from_tool_results():
    """D-025：visualizer 最终消息缺 charts JSON 块时，成功的 create_chart
    工具结果仍应确定性回写 visualizations（M6 演示实测缺口）。"""
    ok_chart = ('{"image_path": "outputs/figures/a.png", "chart_type": "line",'
                ' "text_table": "[图表类型: line]\\n[标题: GDP 趋势]"}')
    tracer = _tracer()
    state = _fresh_state([
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_visualizer", "args": {}}]),
        _Msg("", name="visualizer",
             tool_calls=[{"name": "create_chart", "args": {}}]),
        _ToolMsg("create_chart", ok_chart),
        _Msg("4 张图表已全部渲染完成。", name="visualizer"),  # 最终消息无 JSON
    ])
    updates = process_new_messages(state, tracer)

    assert len(updates["visualizations"]) == 1
    v = updates["visualizations"][0]
    assert v["image_path"] == "outputs/figures/a.png"
    assert v["title"] == "GDP 趋势" and v["status"] == "ok"
    # 无 JSON 分类键 → 不产生校验条目，也不打回（真实工作已完成）
    assert updates["completed_steps"] == []
    assert "messages" not in updates
    tracer.close()


def test_viz_tool_evidence_dedup():
    """D-025：JSON 已归档的图表与工具结果重复时按 image_path 去重。"""
    ok_chart = ('{"image_path": "outputs/figures/x.png", "chart_type": "line",'
                ' "text_table": "[标题: 重复图]"}')
    dup_json = ('```json\n{"charts": [{"title": "重复图",'
                ' "image_path": "outputs/figures/x.png",'
                ' "text_table": "[标题: 重复图]", "status": "ok"}]}\n```')
    tracer = _tracer()
    state = _fresh_state([
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_visualizer", "args": {}}]),
        _Msg("", name="visualizer",
             tool_calls=[{"name": "create_chart", "args": {}}]),
        _ToolMsg("create_chart", ok_chart),
        _Msg(dup_json, name="visualizer"),
    ])
    updates = process_new_messages(state, tracer)

    assert len(updates["visualizations"]) == 1
    assert updates["visualizations"][0]["title"] == "重复图"
    tracer.close()


def test_tool_calls_logged_to_tracer():
    """D-024：Worker 工具调用/结果逐条入 tracer，actor 归属正确。"""
    tracer = _tracer()
    state = _fresh_state([
        _Msg("", name="leader",
             tool_calls=[{"name": "transfer_to_data_preprocessor", "args": {}}]),
        _Msg("", name="data_preprocessor",
             tool_calls=[{"name": "load_csv", "args": {"path": "a.csv"}}]),
        _ToolMsg("load_csv", "ok"),
        _Msg(_PREPROCESSOR_JSON, name="data_preprocessor"),
    ])
    process_new_messages(state, tracer)
    tracer.close()

    import json
    log_path = tracer.log_path
    events = [json.loads(line) for line in
              log_path.read_text(encoding="utf-8").splitlines()]
    calls = [(e["actor"], e["action"], e["tool"]["name"]) for e in events
             if e["action"] in ("tool_call", "tool_result")]
    assert ("leader", "tool_call", "transfer_to_data_preprocessor") in calls
    assert ("data_preprocessor", "tool_call", "load_csv") in calls
    assert ("data_preprocessor", "tool_result", "load_csv") in calls


def test_process_new_messages_rejection_flow():
    tracer = _tracer()
    state = _fresh_state([_Msg("任务"), _Msg(_BAD_PREPROCESSOR)])
    updates = process_new_messages(state, tracer)

    assert updates["completed_steps"][0]["status"] == "rejected"
    assert updates["rejection_counts"] == {"data_preprocessor": 1}
    feedback = updates["messages"]
    assert len(feedback) == 1 and "第 1/2 次打回" in feedback[0].content
    assert pending_rejections({**state, **updates}) == ["data_preprocessor"]

    # 第二次不合格 → 达上限，反馈要求换方法，不再回环
    state2 = {**state, "synced_msg_count": updates["synced_msg_count"],
              "rejection_counts": updates["rejection_counts"]}
    state2["messages"] = list(state2["messages"]) + [_Msg(_BAD_PREPROCESSOR)]
    updates2 = process_new_messages(state2, tracer)
    assert updates2["rejection_counts"]["data_preprocessor"] == 2
    assert "换用其他方法或跳过" in updates2["messages"][0].content
    assert pending_rejections({**state2, **updates2}) == []
    tracer.close()


def test_chart_request_normalization():
    cr = chart_request({"chart_type": "scatter", "x": "a", "y": "b", "extra": 1}, "modeling_analyst")
    assert cr == {"requester": "modeling_analyst", "chart_type": "scatter",
                  "x": "a", "y": "b", "hue": None, "title": None, "intent": None}


def test_graph_compiles():
    from workflows.graph import build_app

    config = load_config([])
    tracer = _tracer()
    app = build_app(config, tracer)
    nodes = set(app.get_graph().nodes)
    assert {"init", "team", "sync", "gate", "report"} <= nodes
    tracer.close()
    clear_store()


def test_invoke_budget():
    config = load_config(["--max-turns", "5"])
    assert invoke_budget(config) == 5 * 8 + 30
    config2 = load_config([])
    assert invoke_budget(config2) == 12 * 8 + 30


if __name__ == "__main__":
    tests = [
        test_classify_worker,
        test_process_new_messages_ok,
        test_tool_usage_enforced_without_tools,
        test_viz_render_failure_rejected,
        test_tool_calls_logged_to_tracer,
        test_process_new_messages_rejection_flow,
        test_chart_request_normalization,
        test_graph_compiles,
        test_invoke_budget,
    ]
    for fn in tests:
        fn()
        print(f"PASS  {fn.__name__}")
    print("M4 smoke tests: all passed")
