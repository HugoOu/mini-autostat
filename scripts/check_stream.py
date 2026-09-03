"""D-028 前置实测：stream 流式模式与两类 interrupt 的兼容性与事件粒度。

验证三件事（结果决定 app.py 改动方案）：
1. stream_mode="updates" 下静态 interrupt_before 是否照常生效、如何呈现；
2. 动态 interrupt() 在流中的呈现方式与 Command(resume=...) 续流是否正常；
3. 真实主图 + subgraphs=True 时，supervisor 子图内部（Leader/Worker/工具）
   的更新事件以什么 (namespace, node, 消息类型) 形态出现——决定进度打印机
   能否按 Worker 归组展示。
"""
import json
import sys
from typing import Annotated, TypedDict

sys.path.insert(0, ".")

from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt


class ToyState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    log: list


def node_work(state):
    return {"log": ["work-done"]}


def node_confirm(state):
    answer = interrupt({"question": "确认出报告？"})
    return {"log": [f"confirm={answer}"]}


print("=" * 30, "PART 1: 玩具图（机制验证）", "=" * 30)
g = StateGraph(ToyState)
g.add_node("work", node_work)
g.add_node("confirm", node_confirm)
g.add_edge(START, "work")
g.add_edge("work", "confirm")
g.add_edge("confirm", END)

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

app = g.compile(checkpointer=MemorySaver(), interrupt_before=["confirm"])
cfg = {"configurable": {"thread_id": "toy-1"}}

print("\n-- 第一段 stream（应先吐 work 更新，然后停在 confirm 前）--")
for chunk in app.stream({"log": ["start"]}, cfg, stream_mode="updates"):
    print("  chunk:", chunk)
snap = app.get_state(cfg)
print("  next =", snap.next)

print("\n-- 第二段 stream（input=None 续过静态断点，应触发动态 interrupt）--")
for chunk in app.stream(None, cfg, stream_mode="updates"):
    print("  chunk:", chunk)
snap = app.get_state(cfg)
print("  next =", snap.next, "| tasks:", [t.name for t in (snap.tasks or [])])

print("\n-- 第三段 stream（resume=go，应走完）--")
final = None
for chunk in app.stream(Command(resume="go"), cfg, stream_mode="updates"):
    print("  chunk:", chunk)
    final = chunk
print("  state.log =", app.get_state(cfg).values.get("log"))

print("\n" + "=" * 30, "PART 2: 真实主图（事件粒度观测）", "=" * 30)
from core.config import ensure_dirs, load_config  # noqa: E402
from core.tracer import RunTracer  # noqa: E402
from workflows.graph import build_app, invoke_budget  # noqa: E402

config = load_config(["--data", "examples/renewable_energy_gdp.csv",
                      "--max-turns", "2"])
ensure_dirs(config)

with RunTracer(log_dir="logs") as tracer:
    real = build_app(config, tracer, checkpointer=MemorySaver(),
                     interrupt_before=True, user_checkpoint=True)
    rcfg = {"configurable": {"thread_id": tracer.run_id},
            "recursion_limit": invoke_budget(config)}
    state_in = {"messages": [{"role": "user", "content":
                "对比中美两国 2000-2023 年可再生能源占比的描述统计"}],
                "current_hypothesis": "中美可再生能源占比描述统计"}

    seen = []
    print("\n-- 真实图第一段 stream（updates + subgraphs=True）--")
    stream = real.stream(state_in, rcfg, stream_mode="updates",
                         subgraphs=True, durability="async")
    # 手动喂入恢复指令：遇暂停即 resume（模拟回车）
    pending_input = None
    while True:
        if pending_input is not None:  # 先恢复续流，再取事件（旧流已耗尽）
            resume_val = pending_input[0]
            print("  >>> resume:", resume_val)
            stream = real.stream(
                None if resume_val is None else Command(resume=resume_val),
                rcfg, stream_mode="updates", subgraphs=True)
            pending_input = None
        try:
            chunk = next(stream)
        except StopIteration:
            break
        ns, payload = chunk
        if isinstance(payload, dict) and "__interrupt__" in payload:
            print("  INTERRUPT payload keys:", list(payload))
            print("  ns =", ns)
            intr = payload["__interrupt__"]
            seen.append(("__interrupt__", ns))
            if intr:  # 动态 interrupt（确认点）：元组含 Interrupt 对象
                val = getattr(intr[0], "value", None)
                print("  interrupt value =",
                      json.dumps(val, ensure_ascii=False)[:120])
                pending_input = ("go",)
            else:  # 静态中断点（interrupt_before）：呈现为空元组（实测）
                print("  静态中断点（空元组）→ 回车继续（input=None）")
                pending_input = (None,)  # 哨兵：静态断点必须以 None 续流
            continue
        for node, upd in (payload or {}).items():
            kinds = []
            if isinstance(upd, dict):
                for m in upd.get("messages") or []:
                    kinds.append(type(m).__name__)
            seen.append((ns, node, kinds))
            print(f"  ns={ns!s:<30} node={node:<22} msgs={kinds}")

    print(f"\n共 {len(seen)} 个事件")
    from collections import Counter
    print("node 频次:", Counter(s[1] for s in seen if s[0] != "__interrupt__"))
print("DONE")
