"""M2 冒烟测试：状态定义、终止机制、全链路记录器、MemorySaver 集成。"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_state_defaults():
    from core.state import AnalysisState

    # TypedDict(total=False)：所有字段可缺省，节点可只返回变更字段
    state: AnalysisState = {"current_hypothesis": "可再生能源与GDP协同发展"}
    assert state["current_hypothesis"]
    assert "iteration" not in state or state.get("iteration") is None


def test_check_termination():
    from core.state import check_termination

    # 1) 未达任何条件 → 不终止
    stop, reason = check_termination({"iteration": 3}, max_turns=12)
    assert not stop and reason is None

    # 2) 显式 stop_reason 优先
    stop, reason = check_termination(
        {"iteration": 1, "stop_reason": "分析完成"}, max_turns=12
    )
    assert stop and reason == "分析完成"

    # 3) 用户中断
    stop, reason = check_termination(
        {"iteration": 1, "interrupted": True, "interruption_reason": "换假设"},
        max_turns=12,
    )
    assert stop and reason == "换假设"

    # 4) 中断但无原因 → 兜底文案
    stop, reason = check_termination({"interrupted": True}, max_turns=12)
    assert stop and reason == "用户主动中断"

    # 5) 达到 max_turns 硬上限
    stop, reason = check_termination({"iteration": 12}, max_turns=12)
    assert stop and "12" in reason

    # 6) 边界：差一步不终止
    stop, _ = check_termination({"iteration": 11}, max_turns=12)
    assert not stop


def test_record_step():
    from core.state import record_step

    state = {"completed_steps": [{"step": "加载", "worker": "data_preprocessor", "status": "done", "summary": "ok"}]}
    out = record_step(state, "相关性检验", "modeling_analyst", "done", "r=0.82")
    assert len(out) == 2 and out[-1]["worker"] == "modeling_analyst"
    assert len(state["completed_steps"]) == 1  # 原状态不被原地修改（纯函数）


def test_tracer_schema_and_clipping():
    from core.tracer import RunTracer

    with tempfile.TemporaryDirectory() as tmp:
        with RunTracer(log_dir=tmp, run_id="test_run") as tracer:
            tracer.log(
                "leader",
                "route",
                input_summary="用户假设：可再生能源与GDP协同发展",
                decision="先做数据预处理",
                next_action="调度 data_preprocessor",
            )
            tracer.log(
                "modeling_analyst",
                "tool_call",
                tool={"name": "run_granger_causality", "provider": "native", "args": {"x": "renewables", "y": "gdp"}},
            )
            tracer.log(
                "modeling_analyst",
                "tool_result",
                output_summary="x" * 2000,  # 触发截断
            )
            path = Path(tracer.log_path)

        lines = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
        # run_start + 3 条 + run_end
        assert len(lines) == 5
        assert lines[0]["action"] == "run_start" and lines[-1]["action"] == "run_end"
        assert [e["step"] for e in lines] == [1, 2, 3, 4, 5]

        route = lines[1]
        assert route["actor"] == "leader" and route["decision"] == "先做数据预处理"

        tool_ev = lines[2]
        assert tool_ev["tool"]["provider"] == "native"
        assert json.loads(tool_ev["tool"]["args"]) == {"x": "renewables", "y": "gdp"}

        clipped = lines[3]["output_summary"]
        assert clipped.endswith("[truncated 1400 chars]") and len(clipped) < 700

        # 所有行 schema/ts/step/actor/action 字段齐全
        for e in lines:
            assert e["schema"] == 1 and e["ts"] and e["actor"] and e["action"]


def test_tracer_validation():
    from core.tracer import RunTracer

    with tempfile.TemporaryDirectory() as tmp:
        tracer = RunTracer(log_dir=tmp, run_id="test_validate")
        try:
            try:
                tracer.log("hacker", "route")
                raise AssertionError("非法 actor 应抛 ValueError")
            except ValueError as e:
                assert "hacker" in str(e)
            try:
                tracer.log("leader", "tool_call", tool={"name": "x"})
                raise AssertionError("缺 provider 应抛 ValueError")
            except ValueError:
                pass
        finally:
            tracer.close()


def test_memory_saver_integration():
    """T2.2 验收：同一 thread_id 两次 invoke 状态延续；不同 thread_id 隔离。"""
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.graph import END, StateGraph

    from core.state import AnalysisState

    def node_ask(state: AnalysisState) -> dict:
        return {
            "messages": [HumanMessage(content="数据体检完成")],
            "current_hypothesis": state.get("current_hypothesis") or "默认假设",
        }

    def node_count(state: AnalysisState) -> dict:
        return {"iteration": (state.get("iteration") or 0) + 1}

    g = StateGraph(AnalysisState)
    g.add_node("ask", node_ask)
    g.add_node("count", node_count)
    g.set_entry_point("ask")
    g.add_edge("ask", "count")
    g.add_edge("count", END)

    app = g.compile(checkpointer=MemorySaver())

    cfg1 = {"configurable": {"thread_id": "t1"}}
    r1 = app.invoke({"current_hypothesis": "假设A"}, cfg1)
    assert r1["iteration"] == 1 and len(r1["messages"]) == 1

    r2 = app.invoke({}, cfg1)  # 同一会话第二次进入：状态从 checkpoint 恢复
    assert r2["iteration"] == 2, "iteration 应基于上次快照累加"
    assert len(r2["messages"]) == 2, "messages 应经 add_messages 累积"
    assert r2["current_hypothesis"] == "假设A", "上轮写入的假设应延续"

    cfg2 = {"configurable": {"thread_id": "t2"}}
    r3 = app.invoke({"current_hypothesis": "假设B"}, cfg2)
    assert r3["iteration"] == 1 and r3["current_hypothesis"] == "假设B", "不同 thread_id 应相互隔离"


if __name__ == "__main__":
    for fn in [
        test_state_defaults,
        test_check_termination,
        test_record_step,
        test_tracer_schema_and_clipping,
        test_tracer_validation,
        test_memory_saver_integration,
    ]:
        fn()
        print(f"PASS  {fn.__name__}")
    print("M2 smoke tests: all passed")
