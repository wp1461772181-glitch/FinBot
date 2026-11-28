"""Nothing slips: every route that changes data is either an ``act`` operation or a recorded decision (app/kernel/operation_registry.py)."""
from __future__ import annotations

from app.kernel import act
from app.kernel.operation_registry import KERNEL_ONLY_OPERATIONS, OPERATION_REGISTRY, operations_of
from app.main import app

CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


def _walk(routes, prefix=""):
    """Every (method, path) under the app, through included routers whichever way this FastAPI keeps them."""
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from _walk(route.original_router.routes, prefix + (route.include_context.prefix or ""))
            continue
        methods = getattr(route, "methods", None)
        if methods is None:
            if hasattr(route, "routes"):
                yield from _walk(route.routes, prefix + getattr(route, "path", ""))
            continue
        for method in sorted(set(methods) & CHANGING):
            yield method, prefix + route.path


def app_routes() -> set[tuple[str, str]]:
    return set(_walk(app.routes))


def test_the_walk_finds_the_routers():
    routes = app_routes()
    assert ("POST", "/agent-chat/bots") in routes and ("POST", "/finbot/routines/{routine_id}/confirm") in routes
    assert len(routes) > 80


def test_every_changing_route_has_a_decision():
    missing = sorted(app_routes() - set(OPERATION_REGISTRY))
    assert not missing, "".join(
        f"\nRoute {m} {p} changes data but is not in app/kernel/operation_registry.py.  Choose one: "
        f"map it to the act operation that covers it ({{\"operation\": name}}), or record why it is left out "
        f"({{\"exempt\": reason}}; use {{\"gap\": reason}} only if it is simply not built yet)." for m, p in missing)


def test_the_registry_names_no_route_that_is_gone():
    stale = sorted(set(OPERATION_REGISTRY) - app_routes())
    assert not stale, f"registry rows with no route (remove or fix the path): {stale}"


def test_every_entry_is_one_of_the_three_shapes_with_a_chinese_reason():
    for key, entry in OPERATION_REGISTRY.items():
        assert set(entry) in ({"operation"}, {"exempt"}, {"gap"}), key
        if "operation" in entry:
            assert operations_of(entry), key
        else:
            reason = next(iter(entry.values()))
            assert isinstance(reason, str) and any("一" <= c <= "鿿" for c in reason), key
            assert "\n" not in reason, key


def test_every_named_operation_exists_in_act():
    for key, entry in OPERATION_REGISTRY.items():
        for name in operations_of(entry):
            assert name in act.OPERATIONS, f"{key} names {name!r}, which act does not have"


def test_every_act_operation_is_on_a_route_or_marked_kernel_only():
    covered = {name for entry in OPERATION_REGISTRY.values() for name in operations_of(entry)}
    missing = [name for name in act.OPERATIONS if name not in covered and name not in KERNEL_ONLY_OPERATIONS]
    assert not missing, f"act operations that no route row names (add the row, or list them in KERNEL_ONLY_OPERATIONS): {missing}"
    assert not (KERNEL_ONLY_OPERATIONS & covered)


def test_gaps_stay_visible():
    gaps = sorted(k for k, v in OPERATION_REGISTRY.items() if "gap" in v)
    assert gaps == [("DELETE", "/agent-chat/news-sources/{source_id}"), ("POST", "/agent-chat/news-sources/{source_id}/enabled"),
                    ("PUT", "/agent-chat/news-sources/push-settings")]


def test_the_feedback_route_is_rate_alert():
    """5c-3c: the 「有用／没用」 the page posts is the same verdict as one said in a conversation."""
    assert OPERATION_REGISTRY[("POST", "/backstage/feedback")] == {"operation": "rate_alert"}
    assert "rate_alert" in act.TIER1 and "rate_alert" not in KERNEL_ONLY_OPERATIONS


def test_the_answer_feedback_routes_are_rate_answer():
    """5d-3a: the thumbs under an answer (PUT a verdict, DELETE it) are the same verdict as one said in a conversation."""
    path = "/agent-chat/conversations/{conversation_id}/turns/{turn_id}/feedback"
    assert OPERATION_REGISTRY[("PUT", path)] == OPERATION_REGISTRY[("DELETE", path)] == {"operation": "rate_answer"}
    assert ("PUT", path) in app_routes() and ("DELETE", path) in app_routes()
    assert "rate_answer" in act.TIER1 and "rate_answer" not in KERNEL_ONLY_OPERATIONS


def test_a_new_route_without_a_row_is_reported_by_name(monkeypatch):
    from fastapi import FastAPI
    import tests.test_operation_registry as me
    extra = FastAPI()

    @extra.post("/brand-new/{x}")
    def _new(x: str):
        return {}

    monkeypatch.setattr(me, "app", extra)
    missing = sorted(me.app_routes() - set(OPERATION_REGISTRY))
    assert missing == [("POST", "/brand-new/{x}")]


def test_the_memory_page_added_two_view_writes_and_nothing_else_that_changes_data():
    """4e: the page writes a view and withdraws one (the same operations as in chat); the overview and the export are reads, and no other row appeared."""
    mine = sorted(r for r in app_routes() if r[1].startswith(("/agent-chat/views", "/agent-chat/memory")))
    assert mine == [("DELETE", "/agent-chat/views/{view_id}"), ("POST", "/agent-chat/views/{symbol}"), ("POST", "/agent-chat/views/{symbol}/drop"),
                    ("POST", "/agent-chat/views/{view_id}/restore")]
    assert OPERATION_REGISTRY[("POST", "/agent-chat/views/{symbol}")] == {"operation": "record_view"}
    assert OPERATION_REGISTRY[("POST", "/agent-chat/views/{symbol}/drop")] == {"operation": "drop_view"}
    assert KERNEL_ONLY_OPERATIONS == {"report_missed"}       # 11-28: said in a conversation only, no page
