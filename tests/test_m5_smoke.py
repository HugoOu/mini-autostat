"""M5 冒烟测试（离线，不调用 LLM）：RAG 预留接口、六要素报告校验与兜底、
中断编译与暂停行为（不实际执行 team，避免 LLM 调用）。"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import load_config
from core.datastore import clear as clear_store
from core.tracer import RunTracer


def _tracer():
    return RunTracer(log_dir=tempfile.mkdtemp(), run_id="m5_test")


def _sample_state() -> dict:
    return {
        "current_hypothesis": "可再生能源发展与 GDP 的关系",
        "stop_reason": "所有计划步骤完成且合格",
        "data_profile": {"data_overview": "中国 2000-2023, 24 行 4 列",
                         "quality_issues": ["2023 年 GDP 缺测"]},
        "completed_steps": [
            {"step": "描述统计", "worker": "descriptive_analyst", "status": "ok",
             "summary": "两列均上升趋势"},
        ],
        "statistical_results": {"modeling": [
            {"analyses": [{"method": "spearman", "results": "r=0.85, p<0.001",
                           "ci": "95% CI [0.7, 0.93]"}]}]},
        "visualizations": [{"title": "趋势图", "image_path": "outputs/figures/a.png",
                            "status": "ok", "text_table": "[图表类型: line] ..."}],
    }


# ---- T5.3 RAG 预留接口 ----

def test_retriever_null_and_factory():
    from knowledge.retriever import NullRetriever, build_context_block, create_retriever

    r = create_retriever("null")
    assert isinstance(r, NullRetriever)
    assert r.retrieve("任何查询") == []
    assert build_context_block(r, "任何查询") == ""  # 空结果 → 不注入
    try:
        create_retriever("不存在的")
        raise AssertionError("应报 KeyError")
    except KeyError:
        pass


def test_static_catalog_retrieval():
    from knowledge.retriever import StaticMethodCatalog, build_context_block

    r = StaticMethodCatalog()
    docs = r.retrieve("请对可再生能源与 GDP 做格兰杰因果检验")
    assert docs and all("格兰杰" not in d or "因果" in d for d in docs)
    assert any("平稳" in d for d in docs)
    assert r.retrieve("完全无关的查询xyzzy") == []
    block = build_context_block(r, "相关性与格兰杰检验", k=2)
    assert block.startswith("[方法知识库 · static 检索结果") and block.count("\n- ") >= 2


# ---- T5.2 六要素报告 ----

def test_collect_materials_and_validate():
    from agents.reporter import collect_materials, validate_report

    state = _sample_state()
    materials = collect_materials(state)
    assert "可再生能源发展与 GDP 的关系" in materials
    assert "r=0.85" in materials and "a.png" in materials

    good = "## 数据说明\n..\n## 方法及选择原因\n..\n## 结果\n..\n## 不确定性\n..\n## 限制\n..\n## 不应得出的结论\n.."
    assert validate_report(good) == []
    missing = validate_report("## 数据说明\n..\n## 结果\n..")
    assert set(missing) == {"方法及选择原因", "不确定性", "限制", "不应得出的结论"}


def test_fallback_report_has_six_sections():
    from agents.reporter import REQUIRED_SECTIONS, _fallback_report, validate_report

    report = _fallback_report(_sample_state())
    assert validate_report(report) == []  # 兜底版六要素齐全
    assert all(s in report for s in REQUIRED_SECTIONS)
    assert "r=0.85" in report  # 内容来自实际 state，非编造
    assert "确定性兜底" in report


def test_generate_report_llm_failure_falls_back():
    """LLM 抛异常时 generate_report 应退回兜底报告（不抛出）。"""
    import agents.reporter as rep
    from agents.reporter import validate_report

    state = _sample_state()
    config = load_config([])

    class _Boom:
        def invoke(self, *_a, **_k):
            raise RuntimeError("网络故障")

    original = rep.get_llm
    rep.get_llm = lambda *a, **k: _Boom()
    try:
        tracer = _tracer()
        report = rep.generate_report(state, config, tracer)
        tracer.close()
    finally:
        rep.get_llm = original
    assert validate_report(report) == [] and "确定性兜底" in report


# ---- T5.1 中断机制 ----

def test_interrupt_pause_before_team():
    """interrupt_before=True 编译后，invoke 应停在 team 之前且可注入状态。"""
    from langgraph.checkpoint.memory import MemorySaver

    from workflows.graph import build_app

    config = load_config([])
    config.data_path = Path("owid-energy-data.csv")
    tracer = _tracer()
    app = build_app(config, tracer, checkpointer=MemorySaver(), interrupt_before=True)
    cfg = {"configurable": {"thread_id": "m5_interrupt_test"}}

    result = app.invoke(
        {"messages": [{"role": "user", "content": "测试假设"}],
         "current_hypothesis": "测试假设"},
        config=cfg,
    )
    assert Path(result["data_path"]) == Path("owid-energy-data.csv")  # init 已执行
    snap = app.get_state(cfg)
    assert snap.next == ("team",)  # 静态暂停在 team 之前（T5.1 验收核心）

    # 注入用户新指令（模拟中断点输入）→ 状态可恢复
    from langchain_core.messages import HumanMessage
    app.update_state(cfg, {"messages": [HumanMessage(content="补充：也看美国")]})
    snap2 = app.get_state(cfg)
    assert any(getattr(m, "content", "") == "补充：也看美国"
               for m in snap2.values.get("messages") or [])
    assert snap2.next == ("team",)  # 注入不改变执行位置
    tracer.close()
    clear_store()


def test_stop_reason_terminates():
    """stop_reason 写入后 check_termination 立即终止（CLI stop 路径的依据）。"""
    from core.state import check_termination

    stop, reason = check_termination({"stop_reason": "用户主动中断"}, 12)
    assert stop and reason == "用户主动中断"


if __name__ == "__main__":
    tests = [
        test_retriever_null_and_factory,
        test_static_catalog_retrieval,
        test_collect_materials_and_validate,
        test_fallback_report_has_six_sections,
        test_generate_report_llm_failure_falls_back,
        test_interrupt_pause_before_team,
        test_stop_reason_terminates,
    ]
    for fn in tests:
        fn()
        print(f"PASS  {fn.__name__}")
    print("M5 smoke tests: all passed")
