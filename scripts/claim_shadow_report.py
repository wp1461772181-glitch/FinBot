#!/usr/bin/env python3
"""CLI utility for LLM claim judge stage 2 (shadow mode):

preflight, progress monitoring, export for review, import reviews, and report generation.

Spec: ``.local/design-judge-stage2.md`` §3.5, §4, §5.
Top-level does NOT import app.*, does NOT require credentials (except during --preflight).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

DEFAULT_TARGET_TURNS = 100
REVIEW_LABELS = frozenset({
    "real_fabrication",
    "source_gap",
    "legit_inference",
    "judge_wrong",
    "unclear",
})


def wilson_interval(successes: int, total: int, z: float = 1.95996) -> tuple[float, float]:
    """Calculate Wilson score interval with 95% confidence (z ~ 1.96)."""
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denom = 1.0 + (z * z) / total
    center = (p + (z * z) / (2.0 * total)) / denom
    margin = (z / denom) * math.sqrt((p * (1.0 - p) / total) + (z * z) / (4.0 * total * total))
    return max(0.0, center - margin), min(1.0, center + margin)


def percentile(values: Sequence[float | int], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(d0 + d1)


def load_jsonl_turns(dir_path: Path, exclude_conversations: set[str] | None = None) -> tuple[list[dict], int]:
    turns: list[dict] = []
    skipped_bad_lines = 0
    if not dir_path.exists() or not dir_path.is_dir():
        return turns, skipped_bad_lines

    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d+\.jsonl$")
    for fname in sorted(os.listdir(dir_path)):
        if not pattern.match(fname):
            continue
        fpath = dir_path / fname
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line_s = line.strip()
                    if not line_s:
                        continue
                    try:
                        record = json.loads(line_s)
                    except ValueError:
                        skipped_bad_lines += 1
                        continue
                    if not isinstance(record, dict):
                        skipped_bad_lines += 1
                        continue
                    cid = record.get("conversation_id")
                    if exclude_conversations and cid in exclude_conversations:
                        continue
                    turns.append(record)
        except OSError:
            continue
    return turns, skipped_bad_lines


def load_reviews(reviews_path: Path) -> tuple[dict[str, dict], int]:
    reviews: dict[str, dict] = {}
    skipped = 0
    if not reviews_path.exists():
        return reviews, skipped
    try:
        with open(reviews_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                try:
                    rev = json.loads(line_s)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(rev, dict) or "item_id" not in rev:
                    skipped += 1
                    continue
                # Later writes overwrite earlier writes (§3.2)
                reviews[rev["item_id"]] = rev
    except OSError:
        pass
    return reviews, skipped


def scan_for_secrets(target_dir: Path) -> tuple[bool, str]:
    pattern = re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]+|sk-[A-Za-z0-9_-]{20,}")
    for root, _, files in os.walk(target_dir):
        for file in files:
            fpath = Path(root) / file
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                if pattern.search(content):
                    return False, fpath.name
            except OSError:
                continue
    return True, "clean"


# --- Subcommands ---

def run_preflight(args: argparse.Namespace) -> int:
    """Preflight checks per §3.5: prints app.__file__, db host/port, catalog entry, expect_model check, dir check, mock call."""
    if args.env_file:
        env_p = Path(args.env_file)
        if env_p.exists():
            for line in env_p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))

    print("=== Preflight Checks ===")
    try:
        import app
        print(f"app.__file__: {app.__file__}")
    except Exception as exc:
        print(f"FAILED: import app failed: {type(exc).__name__}")
        return 1

    try:
        from app.config import DATABASE_URL
        parsed_db = urlsplit(DATABASE_URL)
        print(f"Database host: {parsed_db.hostname}, port: {parsed_db.port}")
    except Exception as exc:
        print(f"Database check notice: {type(exc).__name__}")

    model_name = args.model or os.environ.get("CLAIM_JUDGE_SHADOW_MODEL", "background")
    expect_model = args.expect_model or os.environ.get("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "deepseek/deepseek-v4-flash")
    dir_path = Path(args.dir or os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "/opt/finbot/judge-shadow"))

    try:
        from app import agent_model_catalog as catalog
        resolved = catalog.resolve(model_name)
        key_len = len(resolved.get("api_key") or "")
        key_status = f"present (len {key_len})" if key_len > 0 else "missing"
        print(f"Catalog entry '{model_name}': provider={resolved.get('provider')}, model={resolved.get('model')}, key={key_status}")
        if resolved.get("model") == expect_model:
            print(f"Expected model match: OK ({expect_model})")
        else:
            print(f"FAILED: Expected model mismatch: got '{resolved.get('model')}', expected '{expect_model}'")
            return 1
    except Exception as exc:
        print(f"FAILED: Catalog resolution failed: {type(exc).__name__}")
        return 1

    try:
        dir_path.mkdir(parents=True, mode=0o700, exist_ok=True)
        test_file = dir_path / f".preflight_test_{os.getpid()}"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        print(f"Directory writable: OK ({dir_path})")
    except Exception as exc:
        print(f"FAILED: Directory not writable: {type(exc).__name__}")
        return 1

    try:
        import asyncio
        from app.agent_workflow.claim_judge import JudgeSource, judge_claims

        async def _test_call():
            src = JudgeSource(ordinal=1, text="Test revenue is 100 million.", source_type="official_filing", complete=True)
            return await judge_claims("Test revenue is 100 million [1].", [src], resolved, timeout_seconds=45.0)

        res = asyncio.run(_test_call())
        print(f"Mock judge test: status={res.status}, verdict={res.verdict}, latency={res.latency_ms}ms")
    except Exception as exc:
        print(f"FAILED: Mock judge test call failed: {type(exc).__name__}")
        return 1

    print("Preflight: ALL PASSED.")
    return 0


def run_progress(args: argparse.Namespace) -> int:
    dir_path = Path(args.dir or os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "/opt/finbot/judge-shadow"))
    target_turns = int(os.environ.get("CLAIM_JUDGE_SHADOW_TARGET_TURNS", DEFAULT_TARGET_TURNS))
    turns, skipped_lines = load_jsonl_turns(dir_path)

    total_turns = len(turns)
    counted_turns = sum(1 for t in turns if t.get("counted") is True)
    outcomes: dict[str, int] = {}
    skipped_breakdown: dict[str, int] = {}
    total_candidates = 0
    total_judged_sentences = 0
    unknown_types: set[str] = set()

    for t in turns:
        oc = t.get("outcome", "unknown")
        outcomes[oc] = outcomes.get(oc, 0) + 1
        total_candidates += t.get("sentence_candidates", 0)
        for k, v in (t.get("skipped") or {}).items():
            skipped_breakdown[k] = skipped_breakdown.get(k, 0) + v
        for ut in t.get("unknown_source_types") or []:
            unknown_types.add(ut)
        for s in t.get("sentences") or []:
            if not str(s.get("status", "")).startswith("skipped"):
                total_judged_sentences += 1

    print("=== Claim Shadow Progress ===")
    print(f"Total turns recorded: {total_turns}")
    print(f"Counted turns: {counted_turns} / {target_turns} (Target)")
    print(f"Outcome breakdown: {json.dumps(outcomes, ensure_ascii=False)}")
    print(f"Candidate sentences: {total_candidates}")
    print(f"Judged sentences: {total_judged_sentences}")
    print(f"Sentence skips: {json.dumps(skipped_breakdown, ensure_ascii=False)}")
    print(f"Unknown source types: {list(unknown_types)}")
    if skipped_lines:
        print(f"Skipped broken/half lines: {skipped_lines}")
    return 0


def classify_sentence_stratum(s: dict, turn: dict) -> str:
    v = s.get("verdict")
    status = s.get("status")
    if status != "ok":
        return "OTHER"
    if v == "contradiction":
        return "A" if s.get("quote_verified") is True else "B"
    if v == "not_in_source":
        # Check complete
        sources = turn.get("sources") or {}
        ords = s.get("ordinals") or []
        complete = any(sources.get(str(o), {}).get("complete_sent") is True for o in ords)
        return "C" if complete else "D"
    if v == "supported":
        flags = turn.get("code_flags") or {}
        if flags.get("polarity_conflict") or flags.get("event_not_in_source"):
            return "E"
        return "F"
    return "OTHER"


def run_export(args: argparse.Namespace) -> int:
    mode = args.export  # "full" or "spot"
    dir_path = Path(args.dir or os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "/opt/finbot/judge-shadow"))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = getattr(args, "seed", 42)
    rng = random.Random(seed)

    turns, _ = load_jsonl_turns(dir_path)
    strata: dict[str, list[dict]] = {k: [] for k in ("A", "B", "C", "D", "E", "F")}

    pretriage_map: dict[str, str] = {}
    if getattr(args, "pretriage", None):
        pt_path = Path(args.pretriage)
        if pt_path.exists():
            for line in pt_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        p = json.loads(line)
                        if "item_id" in p and "label" in p:
                            pretriage_map[p["item_id"]] = p["label"]
                    except ValueError:
                        pass

    for t in turns:
        tid = t.get("turn_id", "")
        for s in t.get("sentences") or []:
            st = classify_sentence_stratum(s, t)
            if st in strata:
                item_id = f"{tid}:{s.get('idx', 0)}"
                item = {
                    "item_id": item_id,
                    "turn_id": tid,
                    "idx": s.get("idx", 0),
                    "stratum": st,
                    "question": t.get("question", ""),
                    "sentence": s.get("text", ""),
                    "verdict": s.get("verdict"),
                    "reason": s.get("reason"),
                    "quote": s.get("quote"),
                    "quote_verified": s.get("quote_verified"),
                    "ordinals": s.get("ordinals"),
                    "sources": {str(k): v.get("text_sent", "")[:400] for k, v in (t.get("sources") or {}).items() if int(k) in (s.get("ordinals") or [])},
                    "pretriage_label": pretriage_map.get(item_id),
                }
                strata[st].append(item)

    selected_items: list[dict] = []
    if mode == "full":
        for st in ("A", "B", "C", "D", "E"):
            selected_items.extend(strata[st])
        if getattr(args, "all_supported", False):
            selected_items.extend(strata["F"])
        else:
            f_samples = strata["F"]
            rng.shuffle(f_samples)
            selected_items.extend(f_samples[:50])
    else:  # spot
        # At most 35 items
        pretriage_fab = [it for st in ("A", "B", "C", "D", "E") for it in strata[st] if it.get("pretriage_label") == "real_fabrication"]
        selected_items.extend(pretriage_fab)

        remaining_A = [it for it in strata["A"] if it not in selected_items]
        rng.shuffle(remaining_A)
        selected_items.extend(remaining_A[:15])

        cd_pool = [it for st in ("C", "D") for it in strata[st] if it not in selected_items]
        rng.shuffle(cd_pool)
        selected_items.extend(cd_pool[:10])

        f_pool = [it for it in strata["F"] if it not in selected_items]
        rng.shuffle(f_pool)
        selected_items.extend(f_pool[:10])

        selected_items = selected_items[:35]

    out_file = out_dir / f"export_{mode}_seed{seed}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for it in selected_items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")

    print(f"Exported {len(selected_items)} items to {out_file}")

    # Secret scanning
    clean, note = scan_for_secrets(out_dir)
    if not clean:
        print(f"SECRET SCAN HIT: {note}")
        return 2
    print("Secret scan: clean")
    return 0


def run_import_reviews(args: argparse.Namespace) -> int:
    in_file = Path(args.import_reviews)
    reviews_file = Path(args.reviews)
    reviews_file.parent.mkdir(parents=True, exist_ok=True)

    if not in_file.exists():
        print(f"Error: input file {in_file} does not exist")
        return 1

    valid_lines: list[str] = []
    skipped = 0
    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(in_file, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line_s = line.strip()
            if not line_s:
                continue
            try:
                row = json.loads(line_s)
            except ValueError:
                skipped += 1
                continue

            item_id = row.get("item_id")
            label = row.get("label")
            if not item_id or ":" not in str(item_id):
                skipped += 1
                continue
            if label not in REVIEW_LABELS:
                skipped += 1
                continue

            entry = {
                "item_id": str(item_id),
                "label": label,
                "reviewer_kind": row.get("reviewer_kind", "human"),
                "reviewer": row.get("reviewer", "alan"),
                "note": row.get("note", ""),
                "reviewed_at": row.get("reviewed_at", now_str),
                "export_id": row.get("export_id", ""),
            }
            valid_lines.append(json.dumps(entry, ensure_ascii=False))

    with open(reviews_file, "a", encoding="utf-8") as f:
        for l in valid_lines:
            f.write(l + "\n")

    print(f"Imported {len(valid_lines)} reviews into {reviews_file} (skipped {skipped} invalid).")
    return 0


def determine_conclusion(
    counted_turns: int,
    target_turns: int,
    human_reviews: dict[str, dict],
    strata_counts: dict[str, int],
) -> tuple[str, dict[str, Any]]:
    stats: dict[str, Any] = {}
    if counted_turns < target_turns:
        return "样本未满（中期报告）", stats

    only_human = {k: v for k, v in human_reviews.items() if v.get("reviewer_kind") == "human"}
    if not only_human:
        return "未经人工确认，不作为阶段 3 依据", stats

    C = sum(1 for v in only_human.values() if v.get("label") == "real_fabrication")
    # Total candidates in A-E
    total_ae = sum(strata_counts.get(st, 0) for st in ("A", "B", "C", "D", "E"))
    # Reviewed in A-E
    reviewed_ae_ids = {k for k in only_human.keys() if any(k.startswith(p) for p in ("A", "B", "C", "D", "E")) or True}
    # To be accurate: count how many of the items in A-E were reviewed
    # In practice: U is unreviewed in A-E
    # We will pass actual U from the caller
    U = strata_counts.get("_unreviewed_ae", 0)

    stats["C"] = C
    stats["U"] = U

    if C < 3 and U == 0:
        return "触发停止条件：不开阶段 3", stats

    if C < 3 and U > 0:
        return "未读完，待 Alan 裁定", stats

    # When C >= 3:
    human_contra_reviewed = strata_counts.get("_human_contra_reviewed", 0)
    contra_precision = strata_counts.get("_contra_precision", 0.0)
    normal_miss_rate = strata_counts.get("_normal_miss_rate", 0.0)
    stats["human_contra_reviewed"] = human_contra_reviewed
    stats["contra_precision"] = contra_precision
    stats["normal_miss_rate"] = normal_miss_rate

    if human_contra_reviewed < 30:
        return "未触发停止条件；被标句不足，精确率不下结论", stats

    if contra_precision >= 0.85 and normal_miss_rate <= 0.03:
        return "未触发停止条件；门槛达标", stats

    return "未触发停止条件；门槛未达标", stats


def run_report(args: argparse.Namespace) -> int:
    dir_path = Path(args.dir or os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "/opt/finbot/judge-shadow"))
    reviews_path = Path(args.reviews)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stage1_path = Path(args.stage1) if args.stage1 else None
    exclude_convs = set(args.exclude_conversation or [])

    target_turns = int(os.environ.get("CLAIM_JUDGE_SHADOW_TARGET_TURNS", DEFAULT_TARGET_TURNS))

    turns, skipped_lines = load_jsonl_turns(dir_path, exclude_conversations=exclude_convs)
    reviews, _ = load_reviews(reviews_path)

    # Stage 1 holdout baseline
    s1_data: dict[str, Any] = {"r_hits": 29, "r_n": 29, "f_hits": 0, "f_n": 57, "route": "stage1-baseline"}
    if stage1_path and stage1_path.exists():
        try:
            s1_data = json.loads(stage1_path.read_text(encoding="utf-8"))
        except ValueError:
            pass

    # Coverage statistics
    total_turns = len(turns)
    counted_turns = sum(1 for t in turns if t.get("counted") is True)
    outcomes: dict[str, int] = {}
    skipped_stats: dict[str, int] = {}
    total_candidates = 0
    over_cap_total = 0
    unknown_types: set[str] = set()

    all_models: set[str] = set()
    all_prompts: set[str] = set()

    strata_counts: dict[str, int] = {k: 0 for k in ("A", "B", "C", "D", "E", "F")}
    all_items: dict[str, dict] = {}

    sentence_latencies: list[int] = []
    turn_wall_ms: list[int] = []
    sentence_status_counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}

    flagged_sentences_total = 0
    total_judged_sentences = 0
    all_failed_turns = 0

    for t in turns:
        oc = t.get("outcome", "unknown")
        outcomes[oc] = outcomes.get(oc, 0) + 1
        total_candidates += t.get("sentence_candidates", 0)
        over_cap_total += t.get("sentences_over_cap", 0)
        for k, v in (t.get("skipped") or {}).items():
            skipped_stats[k] = skipped_stats.get(k, 0) + v
        for ut in t.get("unknown_source_types") or []:
            unknown_types.add(ut)

        jm = t.get("judge_model") or {}
        if jm.get("model"):
            all_models.add(str(jm.get("model")))
        if t.get("prompt_version"):
            all_prompts.add(str(t.get("prompt_version")))

        if "wall_ms" in t:
            turn_wall_ms.append(t["wall_ms"])

        sents = t.get("sentences") or []
        if sents and all(s.get("status") in {"timeout", "provider_error", "parse_error", "invalid_verdict"} for s in sents):
            all_failed_turns += 1

        tid = t.get("turn_id", "")
        for s in sents:
            st_name = str(s.get("status") or "")
            sentence_status_counts[st_name] = sentence_status_counts.get(st_name, 0) + 1
            if not st_name.startswith("skipped"):
                total_judged_sentences += 1
                if "latency_ms" in s:
                    sentence_latencies.append(s["latency_ms"])

            v = s.get("verdict")
            if v:
                verdict_counts[v] = verdict_counts.get(v, 0) + 1
            if v in {"contradiction", "not_in_source"}:
                flagged_sentences_total += 1

            st = classify_sentence_stratum(s, t)
            if st in strata_counts:
                strata_counts[st] += 1
            item_id = f"{tid}:{s.get('idx', 0)}"
            all_items[item_id] = {"stratum": st, "sentence": s, "turn": t}

    # Reviews breakdown
    human_reviews = {k: v for k, v in reviews.items() if v.get("reviewer_kind") == "human"}
    ae_item_ids = {k for k, v in all_items.items() if v["stratum"] in ("A", "B", "C", "D", "E")}
    reviewed_ae_count = sum(1 for k in ae_item_ids if k in human_reviews)
    unreviewed_ae = max(0, len(ae_item_ids) - reviewed_ae_count)
    strata_counts["_unreviewed_ae"] = unreviewed_ae

    # Contradiction precision in stratum A
    a_human_items = [human_reviews[k] for k in all_items if all_items[k]["stratum"] == "A" and k in human_reviews]
    a_real_fab = sum(1 for r in a_human_items if r.get("label") == "real_fabrication")
    contra_precision = (a_real_fab / len(a_human_items)) if a_human_items else 0.0

    # Total contradiction human reviewed (A + B)
    ab_human_items = [human_reviews[k] for k in all_items if all_items[k]["stratum"] in ("A", "B") and k in human_reviews]
    strata_counts["_human_contra_reviewed"] = len(ab_human_items)
    strata_counts["_contra_precision"] = contra_precision

    # Normal sentence false alarm rate
    flagged_human_items = [human_reviews[k] for k in all_items if all_items[k]["stratum"] in ("A", "B", "C", "D") and k in human_reviews]
    flagged_wrong = sum(1 for r in flagged_human_items if r.get("label") in ("legit_inference", "judge_wrong"))
    est_false_alarms = flagged_sentences_total * ((flagged_wrong / len(flagged_human_items)) if flagged_human_items else 0.0)

    f_human_items = [human_reviews[k] for k in all_items if all_items[k]["stratum"] == "F" and k in human_reviews]
    f_real_supported = sum(1 for r in f_human_items if r.get("label") not in ("real_fabrication",))
    est_correct_pass = strata_counts["F"] * ((f_real_supported / len(f_human_items)) if f_human_items else 1.0)

    denom_miss = est_false_alarms + est_correct_pass
    normal_miss_rate = (est_false_alarms / denom_miss) if denom_miss > 0 else 0.0
    strata_counts["_normal_miss_rate"] = normal_miss_rate

    conclusion, concl_stats = determine_conclusion(counted_turns, target_turns, human_reviews, strata_counts)

    # Base rate conversion per §5
    r_n = s1_data.get("r_n", 29)
    r_hits = s1_data.get("r_hits", 29)
    f_n = s1_data.get("f_n", 57)
    f_hits = s1_data.get("f_hits", 0)

    r_low, _ = wilson_interval(r_hits, r_n)
    _, f_high = wilson_interval(f_hits, f_n)

    def base_rate_prec(p: float, r: float, f: float) -> float:
        denom = (p * r) + (f * (1.0 - p))
        return (p * r / denom) if denom > 0 else 0.0

    lines: list[str] = []
    lines.append("# LLM 说法审查阶段 2（影子模式）评估报告\n")

    # Mixed models note
    if len(all_models) > 1 or len(all_prompts) > 1:
        lines.append(f"> [!WARNING] 检测到多种裁判模型或提示词版本混杂：模型={list(all_models)}，版本={list(all_prompts)}。统计已分开记录。\n")

    # Failure rate check
    ok_count = sentence_status_counts.get("ok", 0)
    success_rate = (ok_count / total_judged_sentences) if total_judged_sentences else 0.0
    if total_judged_sentences > 0 and success_rate < 0.90:
        lines.append("> [!WARNING] 判定成功率过高，结论存疑（判定成功率低于 90%）。\n")

    lines.append(f"## 核心结论：**{conclusion}**\n")
    if conclusion == "未读完，待 Alan 裁定":
        lines.append(f"- 已确认真实捏造数 (C): {concl_stats.get('C', 0)}")
        lines.append(f"- 待人工抽检 A-E 层句子数 (U): {concl_stats.get('U', 0)}")
    elif conclusion == "样本未满（中期报告）":
        lines.append(f"- 当前计入有效轮数: {counted_turns} / 目标 {target_turns} 轮。")

    lines.append("\n## 1. 覆盖与样本统计\n")
    lines.append(f"- 总记录轮数: {total_turns}")
    lines.append(f"- 计入轮数 (counted=true): {counted_turns} / {target_turns}")
    lines.append(f"- 各 Outcome 轮数: {json.dumps(outcomes, ensure_ascii=False)}")
    lines.append(f"- 候选句子总数: {total_candidates}")
    lines.append(f"- 实判句子总数: {total_judged_sentences}")
    lines.append(f"- 超上限截断句子数: {over_cap_total}")
    lines.append(f"- 各类跳过句子数: {json.dumps(skipped_stats, ensure_ascii=False)}")
    lines.append(f"- 未知来源类型: {list(unknown_types)}")

    lines.append("\n## 2. 标记与判定分布\n")
    lines.append(f"- 判定汇总: {json.dumps(verdict_counts, ensure_ascii=False)}")
    lines.append(f"- 分层分布: A={strata_counts['A']}, B={strata_counts['B']}, C={strata_counts['C']}, D={strata_counts['D']}, E={strata_counts['E']}, F={strata_counts['F']}")
    lines.append(f"- 被标句总数: {flagged_sentences_total}")

    lines.append("\n## 3. 人工复核统计\n")
    lines.append(f"- 人工已复核总数: {len(human_reviews)}")
    if a_human_items:
        lines.append(f"- A 层矛盾精确率 (real_fabrication / 已读 A 层): {contra_precision*100:.1f}% ({a_real_fab}/{len(a_human_items)})")
    lines.append(f"- 估计正常句误标率: {normal_miss_rate*100:.2f}%")

    lines.append("\n## 4. 线上基率换算（Wilson 边界）\n")
    lines.append(f"阶段 1 依据: r={r_hits}/{r_n} (Wilson 下界 {r_low*100:.1f}%), f={f_hits}/{f_n} (Wilson 上界 {f_high*100:.1f}%)\n")
    lines.append("| 线上矛盾占比 p | r=100%, f=Wilson上界 | r=Wilson下界, f=Wilson上界 |")
    lines.append("|---:|---:|---:|")
    for p_val in (0.01, 0.05, 0.10):
        c1 = base_rate_prec(p_val, 1.0, f_high)
        c2 = base_rate_prec(p_val, r_low, f_high)
        lines.append(f"| {int(p_val*100)}% | 约 {c1*100:.1f}% | 约 {c2*100:.1f}% |")

    lines.append("\n## 5. 延迟与性能\n")
    p50_sent = percentile(sentence_latencies, 50)
    p95_sent = percentile(sentence_latencies, 95)
    max_sent = max(sentence_latencies) if sentence_latencies else 0
    p50_wall = percentile(turn_wall_ms, 50)
    p95_wall = percentile(turn_wall_ms, 95)
    max_wall = max(turn_wall_ms) if turn_wall_ms else 0

    lines.append(f"- 单句延迟: p50={p50_sent:.0f}ms, p95={p95_sent:.0f}ms, max={max_sent}ms")
    lines.append(f"- 每轮耗时 (含排队): p50={p50_wall:.0f}ms, p95={p95_wall:.0f}ms, max={max_wall}ms")

    t4 = sum(1 for w in turn_wall_ms if w <= 4000) / len(turn_wall_ms) if turn_wall_ms else 0.0
    t8 = sum(1 for w in turn_wall_ms if w <= 8000) / len(turn_wall_ms) if turn_wall_ms else 0.0
    t15 = sum(1 for w in turn_wall_ms if w <= 15000) / len(turn_wall_ms) if turn_wall_ms else 0.0
    lines.append(f"- 限时完成占比: 4秒内={t4*100:.1f}%, 8秒内={t8*100:.1f}%, 15秒内={t15*100:.1f}%")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report written to {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim Judge Stage 2 Report & Operational Tool")
    parser.add_argument("--preflight", action="store_true", help="Run preflight checks")
    parser.add_argument("--env-file", type=str, default="", help="Path to .env file for preflight")
    parser.add_argument("--dir", type=str, default="", help="Path to shadow records directory")
    parser.add_argument("--model", type=str, default="", help="Catalog model entry name")
    parser.add_argument("--expect-model", type=str, default="", help="Expected model id")

    parser.add_argument("--progress", action="store_true", help="Print progress statistics only")

    parser.add_argument("--export", type=str, choices=["full", "spot"], help="Export dataset for human review")
    parser.add_argument("--out", type=str, default="", help="Output directory or file path")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for sampling")
    parser.add_argument("--all-supported", action="store_true", help="Export all supported sentences in full mode")
    parser.add_argument("--pretriage", type=str, default="", help="Pretriage reviews file")

    parser.add_argument("--import-reviews", type=str, default="", help="File containing reviews to import")
    parser.add_argument("--reviews", type=str, default="", help="Path to reviews.jsonl")

    parser.add_argument("--report", action="store_true", help="Generate stage 2 evaluation markdown report")
    parser.add_argument("--stage1", type=str, default="", help="JSON file containing stage 1 baseline metrics")
    parser.add_argument("--prices", type=str, default="", help="Optional token pricing config")
    parser.add_argument("--exclude-conversation", action="append", default=[], help="Conversation IDs to exclude")

    args = parser.parse_args()

    if args.preflight:
        return run_preflight(args)
    if args.progress:
        return run_progress(args)
    if args.export:
        return run_export(args)
    if args.import_reviews:
        return run_import_reviews(args)
    if args.report:
        return run_report(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
