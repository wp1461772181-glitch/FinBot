"""4e Task 5: the pages ``open_page`` can name.  The memory page (「它眼中的你」, ``/assistant/memory``) is one of them for the kernel; the old
engine is offered the list it always had (its tool list stays byte-identical, pinned by ``tests/test_x_search.py``)."""
import pytest

from app.agent_tool_catalog import definitions, legacy_definitions, schemas, validate

OLD_PAGES = ["overview", "predictions", "materials", "sec", "revisions", "evaluation", "agent", "knowledge"]


def _pages(policy):
    return policy.args_schema.model_json_schema()["properties"]["page"]["enum"]


def test_the_kernel_can_open_the_memory_page_and_the_list_is_pinned():
    assert _pages(definitions()["open_page"]) == OLD_PAGES + ["memory"]
    assert validate("open_page", {"page": "memory"}) == {"page": "memory"}
    for page in OLD_PAGES:
        assert validate("open_page", {"page": page}) == {"page": page}
    for bad in ("profile", "Memory", "/assistant/memory", "", "memory "):
        with pytest.raises(Exception):
            validate("open_page", {"page": bad})
    with pytest.raises(Exception):
        validate("open_page", {"page": "memory", "path": "/assistant/memory"})


def test_the_old_engine_is_still_offered_the_old_list():
    assert _pages(legacy_definitions()["open_page"]) == OLD_PAGES
    assert legacy_definitions()["open_page"].description == definitions()["open_page"].description
    old = next(s for s in schemas(owner=True, granted=set(definitions())) if s["function"]["name"] == "open_page")
    assert old["function"]["parameters"]["properties"]["page"]["enum"] == OLD_PAGES
    new = next(s for s in schemas(owner=True, kernel=True, granted=set(definitions())) if s["function"]["name"] == "open_page")
    assert new["function"]["parameters"]["properties"]["page"]["enum"] == OLD_PAGES + ["memory"]
