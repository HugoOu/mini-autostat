"""M1 冒烟测试：配置系统、LLM 辅助函数、工具注册表。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_config_defaults_and_overrides():
    from core.config import load_config

    cfg = load_config(["--max-turns", "5", "--data", "owid-energy-data.csv"])
    assert cfg.max_turns == 5
    assert cfg.data_path == Path("owid-energy-data.csv")
    assert cfg.data_path.exists(), "示例数据应存在于项目根目录"
    assert cfg.model, "模型名应有默认值"
    assert cfg.max_repair_rounds >= 1


def test_parse_json_block():
    from core.llm import parse_json_block

    assert parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_block('前缀 {"b": [1, 2]} 后缀') == {"b": [1, 2]}
    assert parse_json_block("非 JSON 文本") is None
    assert parse_json_block(None) is None
    assert parse_json_block("plain") is None
    assert parse_json_block(json.dumps({"nested": {"x": 1}})) == {"nested": {"x": 1}}


def test_tool_registry():
    from langchain_core.tools import tool

    from core.tools.registry import get_tools, register_tool, registry_overview

    @tool
    def dummy_tool(x: str) -> str:
        """dummy tool for testing."""
        return x

    register_tool(dummy_tool)
    assert get_tools("dummy_tool")[0].name == "dummy_tool"
    assert registry_overview()["dummy_tool"] == "native"

    try:
        get_tools("not_registered")
        raise AssertionError("应抛出 KeyError")
    except KeyError as e:
        assert "not_registered" in str(e)


def test_get_llm_construction():
    """构造客户端（不发起网络请求）：需要 api_key 才能通过校验。"""
    import os

    from core.config import load_config
    from core.llm import get_llm

    os.environ.setdefault("OPENAI_API_KEY", "test-key-for-construction")
    cfg = load_config([])
    llm = get_llm(cfg)
    assert llm.model_name == cfg.model


def test_get_llm_role_models():
    """D-026：按角色取模型与 extra_body；未配置角色时回退通用模型。"""
    import os

    from core.config import AppConfig
    from core.llm import get_llm

    os.environ.pop("OPENAI_TEMPERATURE", None)
    cfg = AppConfig(api_key="test-key", model="fallback-model",
                    leader_model="leader-model", worker_model="worker-model",
                    leader_extra_body={"thinking": {"type": "enabled"}},
                    worker_extra_body={"thinking": {"type": "disabled"}})
    assert get_llm(cfg, role="leader").model_name == "leader-model"
    assert get_llm(cfg, role="worker").model_name == "worker-model"
    assert get_llm(cfg).model_name == "fallback-model"
    assert get_llm(cfg, role="leader").extra_body == {"thinking": {"type": "enabled"}}
    assert get_llm(cfg, role="worker").extra_body == {"thinking": {"type": "disabled"}}
    assert get_llm(cfg).extra_body in (None, {})

    # 未配置角色模型 → 回退通用模型，且不附加 extra_body
    plain = AppConfig(api_key="test-key", model="common")
    assert get_llm(plain, role="leader").model_name == "common"
    assert get_llm(plain, role="worker").model_name == "common"

    # 非法 JSON extra_body 环境变量应快速失败
    import pytest
    os.environ["OPENAI_LEADER_EXTRA_BODY"] = "{bad json"
    try:
        with pytest.raises(ValueError):
            from core.config import _extra_body_from_env
            _extra_body_from_env("OPENAI_LEADER_EXTRA_BODY")
    finally:
        os.environ.pop("OPENAI_LEADER_EXTRA_BODY", None)


if __name__ == "__main__":
    for fn in [
        test_config_defaults_and_overrides,
        test_parse_json_block,
        test_tool_registry,
        test_get_llm_construction,
        test_get_llm_role_models,
    ]:
        fn()
        print(f"PASS  {fn.__name__}")
    print("M1 smoke tests: all passed")
