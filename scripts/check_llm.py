"""LLM 真实连通性验证脚本（配置完成后一次性执行）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import load_config  # noqa: E402
from core.llm import get_llm  # noqa: E402


def main() -> None:
    cfg = load_config()
    print(f"model   = {cfg.model}")
    print(f"base_url= {cfg.base_url}")
    print(f"api_key = {(cfg.api_key or '')[:8]}...{('(len=' + str(len(cfg.api_key)) + ')') if cfg.api_key else ''}")

    llm = get_llm(cfg)
    resp = llm.invoke("请只回复两个字：正常")
    print(f"LLM response: {resp.content}")
    print("connectivity-ok")


if __name__ == "__main__":
    main()
