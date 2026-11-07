#!/usr/bin/env python3
"""Channel probe: compare GLM-5.3-Flash serving channels fairly.

Compares, with identical prompts and streaming on (the production shape):
  siliconflow       zai-org/GLM-5.3-Flash via api.siliconflow.cn, no reasoning
                    parameter (the current production configuration)
  zhipu-default     glm-5.3-flash via open.bigmodel.cn, no reasoning parameter
                    (the platform default, documented as max thinking)
  zhipu-low         glm-5.3-flash + thinking enabled, reasoning_effort=low
  zhipu-flashx-low  glm-5.3-flashx + thinking enabled, reasoning_effort=low

Probes per channel, repeated --repeats times, channels rotated each round so
a slow minute does not punish one channel systematically:
  short   one short question, no tools
  tool    a prompt that must call the given function; records whether a
          complete tool call was assembled and whether any streamed fragment
          carried an explicit "type": null (the SiliconFlow dialect quirk
          that broke production on 2026-11-07)
  judge   a judge-style verification prompt over a padded source text;
          the expected verdict is deterministic, so correctness is checked

Keys come from the environment only (SILICONFLOW_API_KEY / ZHIPU_API_KEY)
and are never printed.  Stdlib only, so it runs on the box as-is.
Usage: channel_probe.py [--repeats 2] [--timeout 150] [--channels a,b]
                        [--out results.json]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

CHANNELS = {
    "siliconflow": {
        "url": "https://api.siliconflow.cn/v1/chat/completions",
        "model": "zai-org/GLM-5.3-Flash",
        "key_env": "SILICONFLOW_API_KEY",
        "extra": {},
    },
    "zhipu-default": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-5.3-flash",
        "key_env": "ZHIPU_API_KEY",
        "extra": {},
    },
    "zhipu-low": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-5.3-flash",
        "key_env": "ZHIPU_API_KEY",
        "extra": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
    },
    "zhipu-flashx-low": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-5.3-flashx",
        "key_env": "ZHIPU_API_KEY",
        "extra": {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
    },
}

TOOL = {
    "type": "function",
    "function": {
        "name": "get_stock_price",
        "description": "Get the latest closing price for a stock ticker.",
        "parameters": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
    },
}

# A source paragraph repeated to give the judge probe a realistic prompt size.
_FILLER = (
    "公司在本季度继续推进其数据中心业务，管理层在电话会议中表示，供应链状况较上一季度有所改善，"
    "部分关键零部件的交付周期缩短。分析师关注的焦点包括毛利率走势、资本开支计划以及主要客户的订单能见度。"
    "公司重申了全年指引区间，并表示将根据市场需求动态调整产能安排。\n"
)

JUDGE_SYSTEM = "你是一名严格的财务事实核查员。只依据给定的来源文本判断，不得使用外部知识。只输出 JSON。"
JUDGE_USER = (
    "来源文本：\n" + _FILLER * 30 + "\n"
    "另一份来源写道：该公司本季度营收为1080亿美元，同比增长22%。\n\n"
    "待核查的说法：该公司本季度营收为1080亿美元。\n"
    '请只输出一个 JSON 对象：{"verdict": "supported"} 或 {"verdict": "not_supported"}。'
)


def run_probe(channel: dict, key: str, kind: str, timeout: float) -> dict:
    body: dict = {
        "model": channel["model"],
        "stream": True,
        "max_tokens": 32768,
        **channel["extra"],
    }
    if kind == "short":
        body["messages"] = [
            {"role": "user", "content": "用一句话解释什么是市盈率。"},
        ]
    elif kind == "tool":
        body["messages"] = [
            {"role": "user", "content": "帮我查一下英伟达（NVDA）最新的收盘价，你必须调用工具来获取。"},
        ]
        body["tools"] = [TOOL]
        body["tool_choice"] = "auto"
    elif kind == "judge":
        body["messages"] = [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": JUDGE_USER},
        ]
    else:  # pragma: no cover
        raise ValueError(kind)

    req = urllib.request.Request(
        channel["url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    result = {
        "kind": kind, "ok": False, "error": None, "http": None,
        "ttft_s": None, "total_s": None, "content_chars": 0,
        "reasoning_chars": 0, "tool_call_ok": None, "null_type_fragment": False,
        "verdict_ok": None,
    }
    started = time.monotonic()
    tool_name, tool_args = "", ""
    content_parts: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result["http"] = resp.status
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except ValueError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                semantic = delta.get("content") or delta.get("reasoning_content")
                if semantic and result["ttft_s"] is None:
                    result["ttft_s"] = round(time.monotonic() - started, 3)
                if isinstance(delta.get("content"), str):
                    content_parts.append(delta["content"])
                if isinstance(delta.get("reasoning_content"), str):
                    result["reasoning_chars"] += len(delta["reasoning_content"])
                for part in delta.get("tool_calls") or []:
                    if isinstance(part, dict) and "type" in part and part["type"] is None:
                        result["null_type_fragment"] = True
                    fn = (part or {}).get("function") or {}
                    if isinstance(fn.get("name"), str):
                        tool_name += fn["name"]
                    if isinstance(fn.get("arguments"), str):
                        tool_args += fn["arguments"]
    except urllib.error.HTTPError as exc:
        result["http"] = exc.code
        result["error"] = f"http_{exc.code}"
    except Exception as exc:  # timeouts and network errors are data, not crashes
        result["error"] = type(exc).__name__
    result["total_s"] = round(time.monotonic() - started, 3)
    result["content_chars"] = sum(len(p) for p in content_parts)
    result["ok"] = result["error"] is None and result["http"] == 200
    if kind == "tool" and result["ok"]:
        try:
            parsed = json.loads(tool_args) if tool_args else {}
        except ValueError:
            parsed = {}
        result["tool_call_ok"] = tool_name == "get_stock_price" and parsed.get("ticker") == "NVDA"
    if kind == "judge" and result["ok"]:
        text = "".join(content_parts)
        result["verdict_ok"] = '"supported"' in text.replace(" ", "") and "not_supported" not in text
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=150.0)
    parser.add_argument("--channels", default=",".join(CHANNELS))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    names = [n.strip() for n in args.channels.split(",") if n.strip()]
    keys = {}
    for name in names:
        env = CHANNELS[name]["key_env"]
        if not os.environ.get(env):
            print(f"skip {name}: {env} not set", flush=True)
        else:
            keys[name] = os.environ[env]
    active = [n for n in names if n in keys]
    if not active:
        print("no channel has a key; nothing to do", flush=True)
        return 1

    rows: list[dict] = []
    kinds = ["short", "tool", "judge"]
    for rep in range(args.repeats):
        rotated = active[rep % len(active):] + active[:rep % len(active)]
        for name in rotated:
            for kind in kinds:
                row = run_probe(CHANNELS[name], keys[name], kind, args.timeout)
                row.update({"channel": name, "rep": rep})
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)

    print("\n=== summary (medians) ===")
    for name in active:
        for kind in kinds:
            subset = [r for r in rows if r["channel"] == name and r["kind"] == kind]
            good = [r for r in subset if r["ok"]]
            totals = [r["total_s"] for r in good]
            ttfts = [r["ttft_s"] for r in good if r["ttft_s"] is not None]
            extra = ""
            if kind == "tool" and good:
                extra = f" tool_ok={[r['tool_call_ok'] for r in good]} null_type={any(r['null_type_fragment'] for r in good)}"
            if kind == "judge" and good:
                extra = f" verdict_ok={[r['verdict_ok'] for r in good]} reasoning_chars={[r['reasoning_chars'] for r in good]}"
            print(
                f"{name:18s} {kind:6s} ok={len(good)}/{len(subset)} "
                f"total_med={statistics.median(totals) if totals else '-'}s "
                f"ttft_med={statistics.median(ttfts) if ttfts else '-'}s{extra}",
                flush=True,
            )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
