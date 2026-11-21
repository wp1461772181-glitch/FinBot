"""Smoke test of provider ``anthropic`` over the native Messages API, through FinBot's own provider functions.

This is the only script that spends real money, and it is meant for the owner to run with their own key.  The key is read
from ANTHROPIC_API_KEY, kept in memory, and never printed (only its length).  Nothing is written to disk.

    ANTHROPIC_API_KEY=sk-ant-... .venv-rag/bin/python scripts/anthropic_native_smoke.py [--model claude-haiku-5-5]

If the key is not scoped to one workspace the API answers 400 "...must include the anthropic-workspace-id header": then also set
ANTHROPIC_WORKSPACE_ID=wrkspc_... (the script passes it on as FINBOT_ANTHROPIC_WORKSPACE_ID).

What it checks, in order, and prints (text, tokens, cache counters, seconds):
  1. the capabilities the Models API reports for the model (effort tiers, adaptive thinking);
  2. a plain streamed answer;
  3. prompt caching: the same long prompt twice (the second call should report cache_read_input_tokens > 0);
  4. a tool call, then the follow-up request that sends the first reply back WITH its thinking block;
  5. the same follow-up after FinBot-style prompt churn (the system prompt changed between steps), which must not fail;
  6. two effort tiers (low vs max) on one question: output tokens and time should differ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOOL = {"type": "function", "function": {"name": "get_number", "description": "Return the secret number for a name.",
                                         "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}}
LONG = "Reference notes for the cache test. " + " ".join(f"Line {i}: the quarterly figure for segment {i} was {i * 37 % 101} units." for i in range(900))


def line(label, value=""):
    print(f"  {label:<28}{value}")


def usage_line(usage):
    return (f"in={usage.get('prompt_tokens')} (cache read {usage.get('cache_read_input_tokens')}, "
            f"written {usage.get('cache_creation_input_tokens')})  out={usage.get('completion_tokens')}")


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

    async def call(label, *args, **kwargs):
        started = time.monotonic()
        try:
            result = await provider.decision_request("anthropic", model, key, *args, **kwargs)
        except HTTPException as exc:
            failures.append(label)
            line(label, f"FAILED: {exc.detail}" + (f" (refusal category {exc.category})" if hasattr(exc, "category") else ""))
            return None
        data, message = result
        line(label, f"{time.monotonic() - started:5.1f}s  {usage_line(data['usage'])}")
        return message

    print("\n1. capabilities (Models API)")
    async with native.client_for(key) as client:
        caps = await native.read_caps(client, model)
    line("adaptive thinking / tiers", f"{caps['adaptive']} / {list(caps['efforts'])}" if caps else "not readable: static table in use")

    print("\n2. plain answer")
    message = await call("answer", [{"role": "user", "content": "In one sentence: what is a price-to-earnings ratio?"}], [], None, "low")
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

    print("\n3. prompt caching (same prompt twice)")
    cached = [{"role": "system", "content": LONG}, {"role": "user", "content": "What was the figure for segment 7? Answer with the number only."}]
    await call("first call", cached, [], None, "low")
    await asyncio.sleep(2)
    second_data = None
    started = time.monotonic()
    try:
        second_data, _ = await provider.decision_request("anthropic", model, key, cached, [], None, "low")
        line("second call", f"{time.monotonic() - started:5.1f}s  {usage_line(second_data['usage'])}")
        line("cache hit", "yes" if second_data["usage"]["cache_read_input_tokens"] > 0 else "NO (prefix below the model's minimum, or changed)")
    except HTTPException as exc:
        failures.append("cache second call")
        line("second call", f"FAILED: {exc.detail}")

    print("\n4. tool call, then the reply sent back with its thinking block")
    base = [{"role": "system", "content": "Use the tool when you need a secret number. Be brief."},
            {"role": "user", "content": "What is the secret number for 'orchid'? Use the tool, then answer."}]
    first = await call("step 1 (tool request)", base, [TOOL], None, "medium")
    if first and first.get("tool_calls"):
        blocks = [b["type"] for b in first["_anthropic_content"]]
        line("blocks returned", str(blocks))
        assistant = {"role": "assistant", **{k: v for k, v in first.items() if k in {"content", "tool_calls", "reasoning_content", "_anthropic_content"}}}
        result = [{"role": "tool", "tool_call_id": first["tool_calls"][0]["id"], "content": json.dumps({"ok": True, "number": 4271})}]
        step2 = await call("step 2 (thinking echoed)", [*base, assistant, *result], [TOOL], None, "medium")
        if step2:
            line("text", step2["content"][:160])
        print("\n5. same follow-up after the system prompt changed (what FinBot does every step)")
        churned = [{"role": "system", "content": base[0]["content"] + " Status: 1 tool call so far."}, *base[1:], assistant, *result]
        step2b = await call("step 2 (stale thinking)", churned, [TOOL], None, "medium")
        if step2b:
            line("text", step2b["content"][:160])
    else:
        failures.append("tool call")
        line("step 1", "the model did not call the tool" if first else "no reply")

    print("\n6. effort tiers")
    question = [{"role": "user", "content": "A bond pays 4% annually, 7 years to maturity, priced at 96. Roughly what is its yield to maturity? Show the main steps."}]
    for tier in ("low", "max"):
        reply = await call(f"effort {tier}", question, [], None, tier)
        if reply:
            line("  thinking / answer", f"{len(reply.get('reasoning_content', ''))} / {len(reply['content'])} chars")

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "all checks completed"))
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="claude-haiku-5-5")
    sys.exit(asyncio.run(main(parser.parse_args().model)))
