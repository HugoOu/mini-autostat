"""全局配置管理（考核要求：可配置性）。

配置来源优先级：命令行参数 > 环境变量（.env）> 内置默认值。

可配置项包括：
- LLM 模型名称 / API 地址 / 密钥（D-002：OpenCode Go 提供的 GLM-5.3-Flash）
- 运行预算：max_turns（终止机制硬上限）、max_repair_rounds（代码修复轮数）
- 数据路径与输出目录
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv 为可选依赖（D-010），缺失时仅使用系统环境变量
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()  # 读取项目根目录 .env（若存在）


@dataclass
class AppConfig:
    """一次分析会话的全部可配置项。"""

    # ---- LLM（OpenAI-compatible 接入）----
    model: str = "glm-5.3-flash"
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.0

    # ---- 运行预算（考核要求：终止机制，避免 Agent 无限循环）----
    max_turns: int = 12          # Leader 调度步数硬上限
    max_repair_rounds: int = 3   # 建模 Worker 代码报错自修复最大轮数

    # ---- 路径 ----
    data_path: Path = Path("owid-energy-data.csv")
    output_dir: Path = Path("outputs")   # figures/ 与 reports/ 的父目录
    log_dir: Path = Path("logs")         # 全链路运行记录（jsonl）


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mini-autostat", description="Mini AutoSTAT CLI")
    p.add_argument("--model", help="LLM 模型名称（默认取 OPENAI_MODEL）")
    p.add_argument("--max-turns", type=int, help="Leader 调度步数硬上限")
    p.add_argument("--max-repair-rounds", type=int, help="代码修复最大轮数")
    p.add_argument("--data", help="数据文件路径")
    p.add_argument("--output-dir", help="输出目录（默认 outputs）")
    p.add_argument("--log-dir", help="运行日志目录（默认 logs）")
    return p


def load_config(argv: list[str] | None = None) -> AppConfig:
    """解析配置：环境变量打底，命令行参数覆盖。"""
    args = _build_parser().parse_args(argv)

    return AppConfig(
        model=args.model or os.getenv("OPENAI_MODEL", AppConfig.model),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
        api_key=os.getenv("OPENAI_API_KEY") or None,
        max_turns=args.max_turns or int(os.getenv("MAX_TURNS", AppConfig.max_turns)),
        max_repair_rounds=(
            args.max_repair_rounds
            or int(os.getenv("MAX_REPAIR_ROUNDS", AppConfig.max_repair_rounds))
        ),
        data_path=Path(args.data or os.getenv("DATA_PATH", AppConfig.data_path)),
        output_dir=Path(args.output_dir or AppConfig.output_dir),
        log_dir=Path(args.log_dir or AppConfig.log_dir),
    )


def ensure_dirs(cfg: AppConfig) -> AppConfig:
    """创建运行所需目录：outputs/figures、outputs/reports、logs。"""
    (cfg.output_dir / "figures").mkdir(parents=True, exist_ok=True)
    (cfg.output_dir / "reports").mkdir(parents=True, exist_ok=True)
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    return cfg


if __name__ == "__main__":  # 自检入口：python -m core.config
    c = load_config()
    ensure_dirs(c)
    masked = (c.api_key[:6] + "...") if c.api_key else "(未设置)"
    print(f"model           = {c.model}")
    print(f"base_url        = {c.base_url or '(未设置)'}")
    print(f"api_key         = {masked}")
    print(f"max_turns       = {c.max_turns}")
    print(f"max_repair      = {c.max_repair_rounds}")
    print(f"data_path       = {c.data_path} (exists={c.data_path.exists()})")
    print(f"output_dir      = {c.output_dir}")
    print(f"log_dir         = {c.log_dir}")
