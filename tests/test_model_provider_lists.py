"""The provider lists the model dialog depends on must agree: the browser's CATALOG (frontend/src/model-profiles.mjs)
and the server's PROVIDER_NAMES / BASE_URLS / PROVIDERS (app/agent_chat_api.py), plus the material-analysis catalog.
A provider added on one side only would offer a choice the server refuses, or hide one it accepts."""
import re
from pathlib import Path

from app.agent_chat_api import BASE_URLS, PROVIDER_NAMES, PROVIDER_PATTERN, PROVIDERS
from app.model_providers import PROVIDER_CATALOG, thinking_disabled_options

NEW = {"anthropic", "openai", "gemini", "xai", "mistral", "groq"}
SOURCE = (Path(__file__).resolve().parent.parent / "frontend/src/model-profiles.mjs").read_text(encoding="utf-8")


def _browser_catalog() -> dict[str, str]:
    block = SOURCE.split("export const CATALOG = [", 1)[1].split("];", 1)[0]
    rows = re.findall(r'\{provider:"([^"]+)",label:"[^"]*",baseUrl:"([^"]*)"', block)
    assert rows, "the CATALOG block of model-profiles.mjs could not be read"
    return dict(rows)


def test_browser_and_server_list_the_same_providers_with_the_same_addresses():
    browser = _browser_catalog()
    assert set(browser) == set(PROVIDER_NAMES)
    for provider, base in browser.items():
        if provider == "custom":
            assert base == "" and provider not in BASE_URLS
            continue
        assert BASE_URLS[provider] == base, provider
        assert PROVIDERS[provider] == base + "/chat/completions", provider


def test_material_analysis_catalog_knows_every_provider_with_the_same_address():
    assert set(PROVIDER_CATALOG) == set(PROVIDER_NAMES)
    for provider, base in BASE_URLS.items():
        assert PROVIDER_CATALOG[provider]["base_url"] == base, provider


def test_the_provider_pattern_accepts_exactly_the_listed_names():
    for provider in PROVIDER_NAMES:
        assert re.fullmatch(PROVIDER_PATTERN, provider)
    assert not re.fullmatch(PROVIDER_PATTERN, "anthropic2") and not re.fullmatch(PROVIDER_PATTERN, "")


def test_new_providers_are_listed_and_get_no_reasoning_parameter():
    assert NEW <= set(PROVIDER_NAMES)
    from app.agent_chat_provider import NATIVE_EFFORTS, reasoning_options
    for provider in NEW:
        if provider == "anthropic":
            # The native Messages API sends the tier itself (anthropic_native.build_request); reasoning_options is the compatible
            # endpoint's path (FINBOT_ANTHROPIC_NATIVE=off), which still sends nothing.
            from app.anthropic_native import STATIC_EFFORTS
            assert NATIVE_EFFORTS[provider] == STATIC_EFFORTS
        else:
            assert NATIVE_EFFORTS[provider] == ()
        assert reasoning_options(provider, "high") == {}
        assert thinking_disabled_options(provider) == {}


def _sends(provider, tier):
    """Whether a request for this provider carries the tier.  Provider anthropic sends it as output_config.effort through the
    native Messages API while FINBOT_ANTHROPIC_NATIVE is on, and nothing through the compatible endpoint when it is off."""
    from app.agent_chat_provider import reasoning_options
    if provider == "anthropic":
        from app.anthropic_native import build_request, use_native
        return use_native(provider) and "output_config" in build_request("claude-haiku-5-5", [{"role": "user", "content": "q"}], [], effort=tier)[0]
    return bool(reasoning_options(provider, tier))


def test_a_provider_that_sends_no_effort_says_it_takes_none(monkeypatch):
    """What the strength list offers must be what the request sends.  Every provider but OpenRouter (answered per model
    by OpenRouter's own list): one that sends nothing for any tier is declared as taking no effort, so the browser does
    not offer seven tiers that do nothing; one that sends something declares tiers.  A provider added to PROVIDER_NAMES
    and left out of NATIVE_EFFORTS fails here.  Provider anthropic is held to it with the native switch on AND off."""
    from app.agent_chat_provider import REASONING_EFFORTS
    from app.agent_model_catalog import _reasoning_fields
    for switch in ("on", "off"):
        monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", switch)
        for provider in set(PROVIDER_NAMES) - {"openrouter"}:
            fields = _reasoning_fields({"provider": provider})
            assert fields, f"{provider} has no entry in NATIVE_EFFORTS: the browser would offer every tier"
            sends = any(_sends(provider, tier) for tier in REASONING_EFFORTS)
            assert fields["reasoning_supported"] is sends, (provider, switch)
            if not sends:
                assert "supported_efforts" not in fields, (provider, switch)
            elif provider == "anthropic":
                assert all(_sends(provider, tier) for tier in fields["supported_efforts"]), "a listed tier must really be sent"
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", "off")
    assert _reasoning_fields({"provider": "anthropic", "model": "claude-haiku-5-5"}) == {"reasoning_supported": False}
    monkeypatch.setenv("FINBOT_ANTHROPIC_NATIVE", "on")
    assert _reasoning_fields({"provider": "anthropic", "model": "claude-haiku-5-5"})["supported_efforts"] == ["low", "medium", "high", "xhigh", "max"]
