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
        assert provider not in NATIVE_EFFORTS
        assert reasoning_options(provider, "high") == {}
        assert thinking_disabled_options(provider) == {}
