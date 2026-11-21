"""SiliconFlow's thinking control is per model (FINBOT_SF_EFFORT): what the strength list offers is what a request sends."""
import asyncio

import pytest

from app import agent_chat_provider as provider
from app.agent_chat_provider import REASONING_EFFORTS, reasoning_options, siliconflow_efforts
from app.agent_model_catalog import _reasoning_fields

V4 = "deepseek-ai/DeepSeek-V4-Flash"
QWEN = "Qwen/Qwen3-32B"


def _switch(monkeypatch, on):
    monkeypatch.setenv("FINBOT_SF_EFFORT", "on" if on else "off")


def test_the_effort_family_sends_high_or_max(monkeypatch):
    _switch(monkeypatch, True)
    for model in (V4, "deepseek-ai/DeepSeek-V4-Pro", "zai-org/GLM-5.2"):
        assert siliconflow_efforts(model) == ("high", "max")
        assert reasoning_options("siliconflow", "high", model) == {"reasoning_effort": "high"}
        # Lower tiers (the environment default "low" of a bot that chose nothing) keep the model's own default.
        for tier in ("none", "minimal", "low", "medium"):
            assert reasoning_options("siliconflow", tier, model) == {}, (model, tier)
        for tier in ("xhigh", "max"):
            assert reasoning_options("siliconflow", tier, model) == {"reasoning_effort": "max"}, (model, tier)


def test_the_budget_family_switches_thinking_and_sets_a_budget(monkeypatch):
    _switch(monkeypatch, True)
    for model in (QWEN, "Qwen/Qwen3-235B-A22B", "deepseek-ai/DeepSeek-V3.2", "tencent/Hunyuan-A13B-Instruct", "zai-org/GLM-4.6V"):
        assert siliconflow_efforts(model) == ("none", "low", "medium", "high", "max")
        assert reasoning_options("siliconflow", "none", model) == {"enable_thinking": False}
        assert reasoning_options("siliconflow", "low", model) == {"enable_thinking": True, "thinking_budget": 1024}
        assert reasoning_options("siliconflow", "minimal", model) == {"enable_thinking": True, "thinking_budget": 1024}
        assert reasoning_options("siliconflow", "medium", model) == {"enable_thinking": True, "thinking_budget": 4096}
        assert reasoning_options("siliconflow", "high", model) == {"enable_thinking": True, "thinking_budget": 16384}
        assert reasoning_options("siliconflow", "xhigh", model) == {"enable_thinking": True, "thinking_budget": 32768}
        assert reasoning_options("siliconflow", "max", model) == {"enable_thinking": True, "thinking_budget": 32768}


@pytest.mark.parametrize("model", ["Qwen/Qwen3-Coder-480B-A35B-Instruct", "deepseek-ai/DeepSeek-V3.1", "deepseek-ai/DeepSeek-R1",
                                   "moonshotai/Kimi-K2-Instruct", "", None])
def test_other_models_get_nothing_and_say_so(monkeypatch, model):
    _switch(monkeypatch, True)
    assert all(reasoning_options("siliconflow", tier, model) == {} for tier in REASONING_EFFORTS)
    assert _reasoning_fields({"provider": "siliconflow", "model": model}) == {"reasoning_supported": False}


def test_every_listed_tier_is_really_sent(monkeypatch):
    _switch(monkeypatch, True)
    for model in (V4, QWEN):
        fields = _reasoning_fields({"provider": "siliconflow", "model": model})
        assert fields["reasoning_supported"] is True
        assert all(reasoning_options("siliconflow", tier, model) for tier in fields["supported_efforts"])


def test_switch_off_is_the_old_behaviour(monkeypatch):
    _switch(monkeypatch, False)
    for model in (V4, QWEN):
        assert all(reasoning_options("siliconflow", tier, model) == {} for tier in REASONING_EFFORTS)
        assert _reasoning_fields({"provider": "siliconflow", "model": model}) == {"reasoning_supported": False}


def test_other_providers_do_not_read_the_model(monkeypatch):
    _switch(monkeypatch, True)
    for name in ("deepseek", "zhipu", "openrouter", "kimi", "custom"):
        for tier in REASONING_EFFORTS:
            assert reasoning_options(name, tier, V4) == reasoning_options(name, tier) == reasoning_options(name, tier, QWEN), (name, tier)


def test_a_decision_request_carries_the_model_s_fields(monkeypatch):
    _switch(monkeypatch, True)
    seen = {}

    async def fake_post(name, key, body, base_url=None):
        seen.update(body)
        return {}, {}

    monkeypatch.setattr(provider, "_post", fake_post)
    asyncio.run(provider.decision_request("siliconflow", QWEN, "k", [{"role": "user", "content": "q"}], [], reasoning_effort="medium"))
    assert seen["enable_thinking"] is True and seen["thinking_budget"] == 4096
    seen.clear()
    asyncio.run(provider.decision_request("siliconflow", V4, "k", [{"role": "user", "content": "q"}], [], reasoning_effort="max"))
    assert seen["reasoning_effort"] == "max" and "enable_thinking" not in seen
