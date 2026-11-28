"""The production turn graph: one node that runs the kernel's turn (``app.kernel.loop.run_turn``).

It keeps the LangGraph checkpoint (the conversation's pending card and result sets) and the streaming API the endpoint reads.
The old turn (``direct.py``: classify, route, the old tool loop) was removed in stage 6b; every turn is the kernel's.
"""
from __future__ import annotations

from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from .state import AgentRuntimeContext, AgentWorkflowState, checkpoint_thread_id


def _bytes(value: Any) -> int:
    import json
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


from .evidence import deterministic_confidence_gate


async def _direct_agent_turn(state: AgentWorkflowState, runtime: Runtime[AgentRuntimeContext]) -> dict:
    async def publish(event):
        event = dict(event)
        kind = event.pop("event")
        try: get_stream_writer()({"event": kind, **event})
        except RuntimeError: pass
    from ..kernel.loop import run_turn as run_kernel_turn
    result = await run_kernel_turn(state.get("question", ""), runtime.context, emit=publish,
                                   messages=state.get("messages", []), state=state)
    answer = result["answer"]
    # The LLM claim judge is retired (11-28, design 9.1: of the checking code only the figure reconciliation and the source numbers
    # stay): the kernel's answers are reconciled after they are stored (kernel/reconcile.py, shown under 「依据」), which the judge
    # duplicated with one more model call per answer.  No answer is sent to it whatever CLAIM_JUDGE_SHADOW says; marks it wrote
    # on earlier answers stay as they were.
    # The turn's own checks have run.  Stored citations and result sets keep the full checking text of a source up
    # to STORED_CHECK_TEXT_CHARS: a later answer that reads the source back checks its figures against it.  Text over
    # the cap is dropped and the citation is marked evidence_incomplete, so a later reader treats a miss as insufficient.
    # Clients never receive check_text (agent_chat_stream._client_citations).
    from .evidence import persistable_citation, persistable_result_sets
    result = {**result, "citations": [persistable_citation(c) for c in result.get("citations", [])],
              "result_sets": persistable_result_sets(result.get("result_sets", []))}
    if result.get("pending_request"):
        pending=result["pending_request"]
        await publish({"event":"clarification","request_id":pending["id"],"reason":pending["reason"],"choices":pending["choices"],"display":pending.get("display"),"question":pending.get("question"),
                       **({"options":pending["options"],"select":pending.get("select")} if pending.get("options") else {})})
    try:
        if not result.get("streamed"):  # the kernel has already streamed the answer text
            get_stream_writer()({"event": "delta", "text": answer})
        get_stream_writer()({"event": "done", "status": result.get("status", "complete"), "reason": result.get("reason"),
                            "citations": result.get("citations", []), "answer": answer,
                            "pending_request": result.get("pending_request"), "trace": result.get("trace", []),
                            "unverified_lines": result.get("unverified_lines") or [],
                            **({"citation_protocol": "v2", "citation_nodes": result.get("citation_nodes") or []} if result.get("citation_protocol") == "v2" else {}),
                            "final_protocol": {"route": result.get("route"),**result.get("final_protocol",{})}, "audit": result.get("audit", {})})
    except RuntimeError: pass
    return {"answer": answer, "citations": result.get("citations", []),
            "audit": result.get("audit", {}), "terminal_status": result.get("status"),
            "pending_request":result.get("pending_request"),"result_sets":result.get("result_sets",[]),"previous_category":result.get("previous_category"),"previous_scope":result.get("previous_scope",{}),
            "gate_reason": result.get("reason"), "node_log": [{"node": "direct_agent_turn", "route": result.get("route")}]}


def build_workflow(checkpointer=None):
    builder = StateGraph(AgentWorkflowState, context_schema=AgentRuntimeContext)
    builder.add_node("direct_agent_turn", _direct_agent_turn)      # the old name: the conversations' checkpoints are keyed by it
    builder.add_edge(START, "direct_agent_turn")
    builder.add_edge("direct_agent_turn", END)
    return builder.compile(checkpointer=checkpointer)


def layers_default_window() -> int:
    from ..agent_context import WINDOW_TOKENS
    return WINDOW_TOKENS


async def stream_workflow(*, question: str, messages: list[dict], provider: str, model: str,
                          api_key: str, base_url: str | None, owner_hash: str,
                          conversation_id: str, identity_credential: str = "", turn_id: str = "",
                          pending_request_id: str | None = None, legacy_result_sets: list[dict] | None = None,
                          legacy_source_choices: list[dict] | None = None,
                          classifier: object | None = None, watchlist: list[str] | None = None,
                          history_citation_catalogue: list[dict] | None = None,
                          profile_block: str | None = None, unattended: bool = False,
                          token_budget: int | None = None, action_sink: list | None = None,
                          bot: dict | None = None, skill_block: str | None = None,
                          active_skill: dict | None = None, context_window: int | None = None,
                          self_state: dict | None = None, catalog_name: str | None = None, inbox: object | None = None,
                          via: str | None = None):
    # These former routing hints/results stay accepted so older callers do not fail;
    # none may influence the direct route or tool scope.  ``bot`` (agent_bots.turn_settings) does narrow it.
    from .checkpoints import open_postgres_checkpointer
    from .settings import checkpoint_database_url
    bot = bot or {}
    context = AgentRuntimeContext(provider=provider, model=model, api_key=api_key, base_url=base_url,
        owner_hash=owner_hash, conversation_id=conversation_id, identity_credential=identity_credential,
        classifier=classifier, history_citation_catalogue=tuple(history_citation_catalogue or ()),
        profile_block=profile_block, unattended=unattended, token_budget=token_budget, action_sink=action_sink,
        bot_id=bot.get("bot_id"), bot_name=bot.get("bot_name"), bot_is_default=bool(bot.get("is_default")),
        bot_block=bot.get("block"), tool_scope=bot.get("tool_scope"),
        reasoning_effort=bot.get("reasoning_effort"), engine="v2",
        default_company=bot.get("default_company"), skill_block=skill_block, active_skill=active_skill,
        context_window=context_window or layers_default_window(), self_state=self_state, catalog_name=catalog_name, inbox=inbox, via=via)
    thread = checkpoint_thread_id(owner_hash, conversation_id)
    async with open_postgres_checkpointer(checkpoint_database_url()) as saver:
        graph = build_workflow(saver)
        config = {"configurable": {"thread_id": thread}, "recursion_limit": 30}
        # Legacy pending IDs are accepted for API compatibility. The direct graph
        # does not interpret them as write consent or execute a pending operation.
        state = {"question": question, "messages": messages, "turn_id": turn_id,"requested_pending_id":pending_request_id}
        async for event in graph.astream(state, config, context=context, stream_mode="custom"):
            yield event


async def mark_terminal_status(owner_hash: str, conversation_id: str, status: str, partial_answer: str) -> None:
    from .checkpoints import open_postgres_checkpointer
    from .settings import checkpoint_database_url
    async with open_postgres_checkpointer(checkpoint_database_url()) as saver:
        graph = build_workflow(saver)
        config = {"configurable": {"thread_id": checkpoint_thread_id(owner_hash, conversation_id)}}
        try: await graph.aupdate_state(config, {"terminal_status": status, "answer": partial_answer[:4000]})
        except Exception: pass


async def set_pending_request(owner_hash: str, conversation_id: str, card: dict) -> None:
    """Make ``card`` the conversation's pending request, as if its last turn had proposed it: the next
    press of its button is checked against it exactly like any other card (agent_tasks.mint_card)."""
    from .checkpoints import open_postgres_checkpointer
    from .settings import checkpoint_database_url
    async with open_postgres_checkpointer(checkpoint_database_url()) as saver:
        graph = build_workflow(saver)
        config = {"configurable": {"thread_id": checkpoint_thread_id(owner_hash, conversation_id)}}
        await graph.aupdate_state(config, {"pending_request": card})
