"""诊断 2：验证 GLM 后端对 parallel_tool_calls 参数的耐受性（M4 e2e 停滞根因定位）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from core.config import load_config


@tool
def task_data_preprocessor(note: str) -> str:
    """把任务移交给 data_preprocessor。"""
    return note


def main() -> None:
    cfg = load_config([])
    llm = ChatOpenAI(model=cfg.model, base_url=cfg.base_url,
                     api_key=cfg.api_key, timeout=60, max_retries=0)

    t0 = time.time()
    r = llm.bind_tools([task_data_preprocessor],
                       parallel_tool_calls=False).invoke("把任务移交给 data_preprocessor")
    print(f"parallel_tool_calls=False : {time.time() - t0:6.1f}s ok={bool(r)}")

    t0 = time.time()
    r = llm.bind_tools([task_data_preprocessor],
                       parallel_tool_calls=True).invoke("把任务移交给 data_preprocessor")
    print(f"parallel_tool_calls=True  : {time.time() - t0:6.1f}s ok={bool(r)}")


if __name__ == "__main__":
    main()
