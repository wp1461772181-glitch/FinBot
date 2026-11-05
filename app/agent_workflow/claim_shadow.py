"""LLM claim judge, stage 2 (shadow mode): asynchronous background scheduling and execution.

Spec: ``.local/design-judge-stage2.md`` §1, §3.
Top-level MUST ONLY import the standard library. Everything else is lazily imported inside tasks.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import re
import stat
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

# Constants and limits from spec §1, §3.4, §7.3
DEFAULT_TARGET_TURNS = 100  # Overridden default per user request (spec default was 200)
DEFAULT_DAILY_CALLS = 600
MAX_SENTENCES = 12
MAX_PENDING_TURNS = 8
CALL_CONCURRENCY = 3
BACKOFF_SECONDS = 600
TURN_BUDGET_SECONDS = 300
RETENTION_DAYS = 180
PROMPT_VERSION = "judge-v1"

# Module-level state
_TASKS: set[asyncio.Task] = set()
_DROPPED_BUSY: int = 0
_CALLS_TODAY: int = 0
_COUNTED_TURNS: int = 0
_SEEN_ANSWER_HASHES: set[str] = set()
_CIRCUIT_OPEN_UNTIL: float = 0.0
_INITIALIZED: bool = False
_TARGET_REACHED_WRITTEN: bool = False
_SEMAPHORE: asyncio.Semaphore | None = None

# Test hooks
_TEST_JUDGE_FN: Callable | None = None
_TEST_RESOLVE_FN: Callable | None = None


def set_test_judge_fn(fn: Callable | None) -> None:
    global _TEST_JUDGE_FN
    _TEST_JUDGE_FN = fn


def set_test_resolve_fn(fn: Callable | None) -> None:
    global _TEST_RESOLVE_FN
    _TEST_RESOLVE_FN = fn


def reset_state() -> None:
    """Reset module-level in-memory counters and state (for test isolation)."""
    global _TASKS, _DROPPED_BUSY, _CALLS_TODAY, _COUNTED_TURNS
    global _SEEN_ANSWER_HASHES, _CIRCUIT_OPEN_UNTIL, _INITIALIZED
    global _TARGET_REACHED_WRITTEN, _SEMAPHORE, _TEST_JUDGE_FN, _TEST_RESOLVE_FN
    _TASKS.clear()
    _DROPPED_BUSY = 0
    _CALLS_TODAY = 0
    _COUNTED_TURNS = 0
    _SEEN_ANSWER_HASHES.clear()
    _CIRCUIT_OPEN_UNTIL = 0.0
    _INITIALIZED = False
    _TARGET_REACHED_WRITTEN = False
    _SEMAPHORE = None
    _TEST_JUDGE_FN = None
    _TEST_RESOLVE_FN = None


def enabled() -> bool:
    """Check if shadow mode is enabled according to §1.3 and §3.4."""
    if os.environ.get("CLAIM_JUDGE_SHADOW") != "on":
        return False

    dir_val = os.environ.get("CLAIM_JUDGE_SHADOW_DIR")
    if not dir_val or not os.path.isabs(dir_val):
        return False

    model_val = os.environ.get("CLAIM_JUDGE_SHADOW_MODEL")
    if not model_val or not model_val.strip():
        return False

    stop_path = os.path.join(dir_val, "STOP")
    try:
        if os.path.exists(stop_path):
            return False
    except OSError:
        return False

    return True


@dataclass(frozen=True)
class ShadowTurn:
    turn_id: str
    conversation_id: str
    bot_id: str | None
    question: str
    answer: str
    status: str
    reason: str | None
    route: str | None
    citations: tuple[dict, ...]
    code_flags: dict
    answer_model: str
    identity_credential: str | None = field(repr=False)


def _extract_code_flags(result: dict) -> dict:
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}

    def _truncate_list(items: Any, limit: int = 200) -> list[str]:
        if not isinstance(items, (list, tuple)):
            return []
        res = []
        for item in items:
            if isinstance(item, Mapping):
                text = str(item.get("sentence") or item.get("line") or item)
            else:
                text = str(item)
            res.append(text[:limit])
        return res

    unverified_count = 0
    if isinstance(result.get("unverified_lines"), (list, tuple)):
        unverified_count = len(result["unverified_lines"])
    elif isinstance(audit.get("unverified_lines"), (list, tuple)):
        unverified_count = len(audit["unverified_lines"])

    return {
        "polarity_conflict": _truncate_list(audit.get("polarity_conflict")),
        "event_not_in_source": _truncate_list(audit.get("event_not_in_source")),
        "answer_issues": list(audit.get("answer_issues") or []) if isinstance(audit.get("answer_issues"), (list, tuple)) else [],
        "unverified_lines": unverified_count,
    }


def maybe_schedule(result: dict, context: Any, state: Mapping[str, Any]) -> None:
    """Sync, no I/O beyond one stat(); never raises past the caller's guard."""
    global _DROPPED_BUSY
    if not enabled():
        return

    # Synchronous filtering: drop if hit, no record left
    if getattr(context, "unattended", False) is True:
        return

    if result.get("pending_request"):
        return

    status = result.get("status")
    if status not in {"succeeded", "partially_succeeded"}:
        return

    citations = result.get("citations")
    if not citations or not isinstance(citations, (list, tuple)):
        return

    answer = result.get("answer") or ""
    if not re.search(r"\[\d+\]", answer):
        return

    # In-flight capacity check
    if len(_TASKS) >= MAX_PENDING_TURNS:
        _DROPPED_BUSY += 1
        return

    provider = getattr(context, "provider", None) or ""
    model = getattr(context, "model", None) or ""
    answer_model = f"{provider}/{model}".strip("/")

    raw_bot_id = getattr(context, "bot_id", None)
    bot_id = raw_bot_id if isinstance(raw_bot_id, str) else None

    raw_reason = result.get("reason")
    reason = raw_reason if (raw_reason is None or isinstance(raw_reason, str)) else str(raw_reason)

    raw_route = result.get("route")
    route = raw_route if (raw_route is None or isinstance(raw_route, str)) else str(raw_route)

    snapshot = ShadowTurn(
        turn_id=str(result.get("turn_id") or getattr(context, "turn_id", None) or state.get("turn_id") or ""),
        conversation_id=str(getattr(context, "conversation_id", None) or state.get("conversation_id") or ""),
        bot_id=bot_id,
        question=str(state.get("question") or ""),
        answer=answer,
        status=str(status),
        reason=reason,
        route=route,
        citations=tuple(dict(c) for c in citations if isinstance(c, Mapping)),
        code_flags=_extract_code_flags(result),
        answer_model=answer_model,
        identity_credential=getattr(context, "identity_credential", None),
    )

    task = asyncio.create_task(_run(snapshot), context=contextvars.Context())
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


async def _ensure_initialized(dir_path: str) -> None:
    global _INITIALIZED, _CALLS_TODAY, _COUNTED_TURNS, _SEEN_ANSWER_HASHES
    if _INITIALIZED:
        return
    try:
        from .claim_shadow_store import prune, scan_counters
        scanned = await asyncio.to_thread(scan_counters, dir_path)
        _CALLS_TODAY = scanned.calls_today
        _COUNTED_TURNS = scanned.counted_turns
        _SEEN_ANSWER_HASHES = set(scanned.seen_answer_hashes)
        await asyncio.to_thread(prune, dir_path, RETENTION_DAYS)
        _INITIALIZED = True
    except Exception as exc:
        logger.warning("Claim shadow initialization error: %s", type(exc).__name__)
        _INITIALIZED = True


async def _write_outcome_record(
    dir_path: str,
    snapshot: ShadowTurn,
    outcome: str,
    started_monotonic: float,
    selection: Any = None,
    judge_model_info: dict | None = None,
) -> None:
    from .claim_shadow_store import append_turn

    wall_ms = int((time.monotonic() - started_monotonic) * 1000)
    recorded_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    record = {
        "schema": "claim-shadow-v1",
        "turn_id": snapshot.turn_id,
        "conversation_id": snapshot.conversation_id,
        "bot_id": snapshot.bot_id,
        "recorded_at": recorded_at,
        "wall_ms": wall_ms,
        "outcome": outcome,
        "counted": False,
        "route": snapshot.route,
        "status": snapshot.status,
        "reason": snapshot.reason,
        "answer_model": snapshot.answer_model,
        "judge_model": judge_model_info or {},
        "prompt_version": PROMPT_VERSION,
        "reasoning_effort": os.environ.get("AGENT_REASONING_EFFORT", "low"),
        "sentence_candidates": getattr(selection, "sentence_candidates", 0) if selection else 0,
        "sentences_over_cap": getattr(selection, "sentences_over_cap", 0) if selection else 0,
        "skipped": getattr(selection, "skipped", {}) if selection else {},
        "unknown_source_types": getattr(selection, "unknown_types", []) if selection else [],
        "code_flags": snapshot.code_flags,
        "sentences": [],
    }

    try:
        await asyncio.to_thread(append_turn, dir_path, record)
    except Exception as exc:
        logger.warning("Claim shadow append_turn failed: %s", type(exc).__name__)


async def _run(snapshot: ShadowTurn) -> None:
    global _CALLS_TODAY, _COUNTED_TURNS, _CIRCUIT_OPEN_UNTIL, _TARGET_REACHED_WRITTEN, _SEMAPHORE

    started_monotonic = time.monotonic()
    dir_path = os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "")
    model_name = os.environ.get("CLAIM_JUDGE_SHADOW_MODEL", "")
    expect_model = os.environ.get("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "")

    try:
        daily_calls = int(os.environ.get("CLAIM_JUDGE_SHADOW_DAILY_CALLS", DEFAULT_DAILY_CALLS))
    except ValueError:
        daily_calls = DEFAULT_DAILY_CALLS

    try:
        target_turns = int(os.environ.get("CLAIM_JUDGE_SHADOW_TARGET_TURNS", DEFAULT_TARGET_TURNS))
    except ValueError:
        target_turns = DEFAULT_TARGET_TURNS

    # Outer exception handler: never leak str(exc), never catch CancelledError
    try:
        # Step 1: Owner verification
        from app.agent_chat_identity import owner_credential_matches
        is_owner = await asyncio.to_thread(owner_credential_matches, snapshot.identity_credential)
        if not is_owner:
            return

        await _ensure_initialized(dir_path)

        # Step 2: Sentence extraction and source adaptation
        from .claim_shadow_extract import select_sentences, to_judge_sources
        selection = await asyncio.to_thread(select_sentences, snapshot.answer, snapshot.citations)

        # Step 3: No judgeable sentences
        if not selection.candidates:
            await _write_outcome_record(
                dir_path, snapshot, "no_judgeable", started_monotonic, selection=selection
            )
            return

        # Step 4: Check target, daily cap, circuit breaker, STOP file
        stop_path = os.path.join(dir_path, "STOP")
        if os.path.exists(stop_path):
            return

        if _COUNTED_TURNS >= target_turns:
            if not _TARGET_REACHED_WRITTEN:
                _TARGET_REACHED_WRITTEN = True
                await _write_outcome_record(
                    dir_path, snapshot, "target_reached", started_monotonic, selection=selection
                )
            return

        if _CALLS_TODAY >= daily_calls:
            await _write_outcome_record(
                dir_path, snapshot, "daily_cap", started_monotonic, selection=selection
            )
            return

        if time.monotonic() < _CIRCUIT_OPEN_UNTIL:
            await _write_outcome_record(
                dir_path, snapshot, "circuit_open", started_monotonic, selection=selection
            )
            return

        # Step 5 & 6: Catalog resolve and model verification
        resolved = None
        if _TEST_RESOLVE_FN is not None:
            try:
                resolved = await _TEST_RESOLVE_FN(model_name)
            except Exception as exc:
                logger.warning("Test resolve failed: %s", type(exc).__name__)
                resolved = None
        else:
            try:
                from app.agent_model_catalog import catalog, CatalogError
                resolved = await asyncio.to_thread(catalog.resolve, model_name)
            except (CatalogError, Exception) as exc:
                logger.warning("Catalog resolve failed: %s", type(exc).__name__)
                resolved = None

        if not resolved or not isinstance(resolved, Mapping) or not resolved.get("api_key"):
            await _write_outcome_record(
                dir_path, snapshot, "model_unavailable", started_monotonic, selection=selection
            )
            return

        judge_model_info = {
            "name": model_name,
            "provider": resolved.get("provider"),
            "model": resolved.get("model"),
        }

        if resolved.get("model") != expect_model:
            await _write_outcome_record(
                dir_path,
                snapshot,
                "model_changed",
                started_monotonic,
                selection=selection,
                judge_model_info=judge_model_info,
            )
            return

        # Step 7 & 8: Judge sentences with semaphore and turn budget
        if _SEMAPHORE is None:
            _SEMAPHORE = asyncio.Semaphore(CALL_CONCURRENCY)

        judged_sentences: list[dict] = []
        sources_map: dict[str, dict] = {}
        circuit_tripped = False

        try:
            # Python 3.11+ asyncio.timeout
            async with asyncio.timeout(TURN_BUDGET_SECONDS):
                for candidate in selection.candidates:
                    # Check STOP file before sentence
                    if os.path.exists(stop_path):
                        for c_rem in selection.candidates[len(judged_sentences):]:
                            judged_sentences.append({
                                "idx": c_rem.idx,
                                "text": c_rem.text,
                                "ordinals": list(c_rem.ordinals),
                                "tier": c_rem.tier,
                                "status": "skipped_stopped",
                                "verdict": None,
                                "reason": "",
                                "quote": "",
                                "quote_verified": False,
                                "quote_ordinal": None,
                                "truncated": False,
                                "latency_ms": 0,
                                "usage": {},
                                "error_code": None,
                            })
                        break

                    # Check circuit breaker before sentence
                    if time.monotonic() < _CIRCUIT_OPEN_UNTIL or circuit_tripped:
                        for c_rem in selection.candidates[len(judged_sentences):]:
                            judged_sentences.append({
                                "idx": c_rem.idx,
                                "text": c_rem.text,
                                "ordinals": list(c_rem.ordinals),
                                "tier": c_rem.tier,
                                "status": "skipped_rate_limited",
                                "verdict": None,
                                "reason": "",
                                "quote": "",
                                "quote_verified": False,
                                "quote_ordinal": None,
                                "truncated": False,
                                "latency_ms": 0,
                                "usage": {},
                                "error_code": None,
                            })
                        break

                    # Check daily call limit before sentence
                    if _CALLS_TODAY >= daily_calls:
                        for c_rem in selection.candidates[len(judged_sentences):]:
                            judged_sentences.append({
                                "idx": c_rem.idx,
                                "text": c_rem.text,
                                "ordinals": list(c_rem.ordinals),
                                "tier": c_rem.tier,
                                "status": "skipped_stopped",
                                "verdict": None,
                                "reason": "",
                                "quote": "",
                                "quote_verified": False,
                                "quote_ordinal": None,
                                "truncated": False,
                                "latency_ms": 0,
                                "usage": {},
                                "error_code": None,
                            })
                        break

                    c_sources, c_meta = to_judge_sources(candidate.ordinals, snapshot.citations)
                    sources_map.update(c_meta)

                    async with _SEMAPHORE:
                        _CALLS_TODAY += 1
                        if _TEST_JUDGE_FN is not None:
                            judge_res = await _TEST_JUDGE_FN(
                                candidate.text, c_sources, resolved, timeout_seconds=45.0
                            )
                        else:
                            from .claim_judge import judge_claims
                            judge_res = await judge_claims(
                                candidate.text, c_sources, resolved, timeout_seconds=45.0
                            )

                    sent_dict = {
                        "idx": candidate.idx,
                        "text": candidate.text,
                        "ordinals": list(candidate.ordinals),
                        "tier": candidate.tier,
                        "status": judge_res.status,
                        "verdict": judge_res.verdict,
                        "reason": judge_res.reason,
                        "quote": judge_res.quote,
                        "quote_verified": judge_res.quote_verified,
                        "quote_ordinal": judge_res.quote_ordinal,
                        "truncated": judge_res.truncated,
                        "latency_ms": judge_res.latency_ms,
                        "usage": judge_res.usage,
                        "error_code": judge_res.error_code,
                    }
                    judged_sentences.append(sent_dict)

                    err = str(judge_res.error_code or "")
                    if (
                        err == "provider_rate_or_quota_error"
                        or "429" in err
                        or "rate_limit" in err.lower()
                    ):
                        _CIRCUIT_OPEN_UNTIL = time.monotonic() + BACKOFF_SECONDS
                        circuit_tripped = True

        except (TimeoutError, asyncio.TimeoutError):
            for c_rem in selection.candidates[len(judged_sentences):]:
                judged_sentences.append({
                    "idx": c_rem.idx,
                    "text": c_rem.text,
                    "ordinals": list(c_rem.ordinals),
                    "tier": c_rem.tier,
                    "status": "skipped_budget",
                    "verdict": None,
                    "reason": "",
                    "quote": "",
                    "quote_verified": False,
                    "quote_ordinal": None,
                    "truncated": False,
                    "latency_ms": 0,
                    "usage": {},
                    "error_code": "budget_timeout",
                })

        # Calculate counted per §4.1
        answer_sha256 = hashlib.sha256(snapshot.answer.encode("utf-8")).hexdigest()
        has_ok_verdict = any(s.get("status") == "ok" for s in judged_sentences)
        first_time_seen = answer_sha256 not in _SEEN_ANSWER_HASHES

        counted = bool(
            snapshot.status in {"succeeded", "partially_succeeded"}
            and has_ok_verdict
            and first_time_seen
        )

        if counted:
            _COUNTED_TURNS += 1
            _SEEN_ANSWER_HASHES.add(answer_sha256)

        wall_ms = int((time.monotonic() - started_monotonic) * 1000)
        recorded_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        record = {
            "schema": "claim-shadow-v1",
            "turn_id": snapshot.turn_id,
            "conversation_id": snapshot.conversation_id,
            "bot_id": snapshot.bot_id,
            "recorded_at": recorded_at,
            "wall_ms": wall_ms,
            "outcome": "judged",
            "counted": counted,
            "route": snapshot.route,
            "status": snapshot.status,
            "reason": snapshot.reason,
            "question": snapshot.question,
            "answer": snapshot.answer,
            "answer_sha256": answer_sha256,
            "answer_model": snapshot.answer_model,
            "judge_model": judge_model_info,
            "prompt_version": PROMPT_VERSION,
            "reasoning_effort": os.environ.get("AGENT_REASONING_EFFORT", "low"),
            "sentence_candidates": selection.sentence_candidates,
            "sentences_over_cap": selection.sentences_over_cap,
            "skipped": selection.skipped,
            "unknown_source_types": selection.unknown_types,
            "code_flags": snapshot.code_flags,
            "sources": sources_map,
            "sentences": judged_sentences,
        }

        from .claim_shadow_store import append_turn
        await asyncio.to_thread(append_turn, dir_path, record)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Claim shadow background task error: %s", type(exc).__name__)
