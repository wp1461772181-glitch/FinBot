"""Smoke test of provider ``anthropic`` over the native Messages API, through FinBot's own provider functions.

This is the only script that spends real money, and it is meant for the owner to run with their own key.  The key is read
from ANTHROPIC_API_KEY, kept in memory, and never printed (only its length).  Nothing is written to disk.

    ANTHROPIC_API_KEY=sk-ant-... .venv-rag/bin/python scripts/anthropic_native_smoke.py --model claude-haiku-5-5
    ANTHROPIC_API_KEY=sk-ant-... .venv-rag/bin/python scripts/anthropic_native_smoke.py --model claude-sonnet-5-5
    ANTHROPIC_API_KEY=sk-ant-... .venv-rag/bin/python scripts/anthropic_native_smoke.py --model claude-opus-5-5

Run it once per model: the three 5.5 models differ in default effort, caching minimum and what they refuse, so one passing run
does not stand for the others.  If the key is not scoped to one workspace the API answers 400 "...must include the
anthropic-workspace-id header": then also set ANTHROPIC_WORKSPACE_ID=wrkspc_... (passed on as FINBOT_ANTHROPIC_WORKSPACE_ID).

What it checks, in order, and prints (text, tokens, cache counters, seconds):
  1. the capabilities the Models API reports for the model (effort tiers, adaptive thinking);
  2. a plain streamed answer;
  3. prompt caching the way FinBot uses it: the same tools and system, a different question each time.  The breakpoint is on
     the last tool, so the second call should report cache_read_input_tokens > 0 (a model's minimum cacheable prefix is
     512-4096 tokens; the tool list here is sized above the largest);
  4. a tool call, then the follow-up that sends the reply back with its thinking block (binding mode drop_block): prints the
     blocks the API reports as dropped or let through (input_transformations);
  5. the same follow-up after FinBot-style prompt churn (system prompt changed between steps) in each binding mode:
       5a drop_block  - must succeed; input_transformations should say the stale block was dropped;
       5b off         - thinking sent with no control; the result (400 "bound to a different conversation", or accepted with
                        thinking_mismatch_allowed) is recorded, not judged;
       5c strip       - the default: no thinking sent, must succeed;
  6. two effort tiers (low vs max) on one question: output tokens and time should differ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOOL = {"type": "function", "function": {"name": "get_number", "description": "Return the secret number for a name.",
                                         "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}}
# Twelve tools with long descriptions: well above the largest minimum cacheable prefix, so the tool-list breakpoint can be read back.
BIG_TOOLS = [{"type": "function", "function": {
    "name": f"query_segment_{i}", "description": f"Read the figures of segment {i}. " + " ".join(f"Rule {j}: the reported value for segment {i} in period {j} is stated in units of {j * 7 % 13 + 1}." for j in range(140)),
    "parameters": {"type": "object", "properties": {"period": {"type": "string"}}, "required": ["period"]}}} for i in range(12)]
LONG_SYSTEM = "You answer briefly. Do not call tools unless asked."


def line(label, value=""):
    print(f"  {label:<28}{value}")


def usage_line(usage):
    return (f"in={usage.get('prompt_tokens')} (cache read {usage.get('cache_read_input_tokens')}, "
            f"written {usage.get('cache_creation_input_tokens')})  out={usage.get('completion_tokens')}")


def transformations_line(data):
    items = (data or {}).get("input_transformations") or []
    if not items:
        return "none reported"
    return ", ".join(f"{kind} x{count}" for kind, count in Counter(t["type"] for t in items).items())


async def main(model: str) -> int:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("Set ANTHROPIC_API_KEY first.")
        return 2
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        os.environ["FINBOT_ANTHROPIC_WORKSPACE_ID"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    os.environ.setdefault("FINBOT_ANTHROPIC_NATIVE", "on")
    from fastapi import HTTPException
    from app import agent_chat_provider as provider
    from app import anthropic_native as native

    print(f"model {model}   key: set ({len(key)} chars)   workspace header: {'yes' if native.workspace_id() else 'no'}")
    failures = []

    def binding(mode):
        os.environ["FINBOT_ANTHROPIC_THINKING_BINDING"] = mode

    async def call(label, messages, schemas, effort=None, *, judged=True):
        started = time.monotonic()
        try:
            data, message = await provider.decision_request("anthropic", model, key, messages, schemas, None, effort)
        except HTTPException as exc:
            if judged:
                failures.append(label)
            line(label, f"{'FAILED' if judged else 'rejected'}: {exc.detail}" + (f" (refusal category {exc.category})" if hasattr(exc, "category") else ""))
            return None, None
        line(label, f"{time.monotonic() - started:5.1f}s  {usage_line(data['usage'])}")
        return data, message

    print("\n1. capabilities (Models API)")
    async with native.client_for(key) as client:
        caps = await native.read_caps(client, model)
    line("adaptive thinking / tiers", f"{caps['adaptive']} / {list(caps['efforts'])}" if caps else "not readable: static table in use")

    print("\n2. plain answer")
    binding("strip")
    data, message = await call("answer", [{"role": "user", "content": "In one sentence: what is a price-to-earnings ratio?"}], [], "low")
    if message:
        line("text", message["content"][:160])
        line("thinking summary", f"{len(message.get('reasoning_content', ''))} chars")
    pieces = []
    started = time.monotonic()
    try:
        async for piece in provider.stream_answer("anthropic", model, key, [{"role": "user", "content": "Say hello in five words."}], None):
            pieces.append(piece)
        line("stream_answer", f"{time.monotonic() - started:5.1f}s  {''.join(pieces)[:100]!r}")
    except HTTPException as exc:
        failures.append("stream_answer")
        line("stream_answer", f"FAILED: {exc.detail}")

    print("\n3. prompt caching (same tools and system, a different question each time)")
    system = {"role": "system", "content": LONG_SYSTEM}
    await call("question A", [system, {"role": "user", "content": "What is 2+2? Answer with the number only."}], BIG_TOOLS, "low")
    await asyncio.sleep(2)
    data, _ = await call("question B", [system, {"role": "user", "content": "What is 3+3? Answer with the number only."}], BIG_TOOLS, "low")
    if data:
        read = data["usage"]["cache_read_input_tokens"]
        line("cache hit", "yes" if read > 0 else "NO: no cache read (tool list below this model's minimum cacheable prefix, or the tools changed)")

    print("\n4. tool call, then the reply sent back with its thinking block (binding mode drop_block)")
    binding("drop_block")
    base = [{"role": "system", "content": "Use the tool when you need a secret number. Be brief."},
            {"role": "user", "content": "What is the secret number for 'orchid'? Use the tool, then answer."}]
    data, first = await call("step 1 (tool request)", base, [TOOL], "medium")
    if first and first.get("tool_calls"):
        line("blocks returned", str([b["type"] for b in first.get("_anthropic_content", [])]))
        assistant = {"role": "assistant", **{k: v for k, v in first.items() if k in {"content", "tool_calls", "reasoning_content", "_anthropic_content"}}}
        result = [{"role": "tool", "tool_call_id": first["tool_calls"][0]["id"], "content": json.dumps({"ok": True, "number": 4271})}]
        data, step2 = await call("step 2 (thinking echoed)", [*base, assistant, *result], [TOOL], "medium")
        if step2:
            line("text", step2["content"][:160])
            line("input_transformations", transformations_line(data))
        print("\n5. the same follow-up after the system prompt changed (what FinBot does every step)")
        churned = [{"role": "system", "content": base[0]["content"] + " Status: 1 tool call so far."}, *base[1:], assistant, *result]
        binding("drop_block")
        data, reply = await call("5a drop_block", churned, [TOOL], "medium")
        if reply:
            line("  text", reply["content"][:120])
            line("  input_transformations", transformations_line(data))
        binding("off")
        data, reply = await call("5b off (not judged)", churned, [TOOL], "medium", judged=False)
        if reply:
            line("  accepted; report", transformations_line(data))
        binding("strip")
        plain = [m for m in churned]
        plain[2] = {k: v for k, v in assistant.items() if k != "_anthropic_content"}
        data, reply = await call("5c strip (default)", plain, [TOOL], "medium")
        if reply:
            line("  text", reply["content"][:120])
    else:
        failures.append("tool call")
        line("step 1", "the model did not call the tool" if first else "no reply")

    print("\n6. effort tiers")
    binding("strip")
    question = [{"role": "user", "content": "A bond pays 4% annually, 7 years to maturity, priced at 96. Roughly what is its yield to maturity? Show the main steps."}]
    for tier in ("low", "max"):
        _, reply = await call(f"effort {tier}", question, [], tier)
        if reply:
            line("  thinking / answer", f"{len(reply.get('reasoning_content', ''))} / {len(reply['content'])} chars")

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "all checks completed"))
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="claude-haiku-5-5", help="claude-haiku-5-5 | claude-sonnet-5-5 | claude-opus-5-5 (run all three)")
    sys.exit(asyncio.run(main(parser.parse_args().model)))
