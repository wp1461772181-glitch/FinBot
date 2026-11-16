"""U9 wiring: shadow record -> public gate -> public marks file -> chat history and owner review.

Plumbing only.  The judgement (what counts as a mark) lives in claim_judge / claim_short_review and the gate's
conditions (claim_public_gate.public_annotation); the state machine lives in claim_public_gate.  This module decides
where the gate's state and the displayable marks are kept, and what the public read path may return.

Files, all in the shadow directory (CLAIM_JUDGE_SHADOW_DIR, 0700 dir / 0600 files):
- claim-public-gate-state.json  gate state (claim_public_gate.save_state format)
- public-marks.jsonl            one line per shadow turn that produced displayable marks: {turn_id, recorded_at, marks}
- claim-public-gate.lock        advisory lock for read-modify-write of the two files above
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from . import claim_public_gate as gate

STATE_NAME = "claim-public-gate-state.json"
MARKS_NAME = "public-marks.jsonl"
LOCK_NAME = "claim-public-gate.lock"

_LOCK = threading.RLock()
_READ_CACHE: dict[str, tuple[tuple[int, int], list[dict]]] = {}


def shadow_dir() -> Path | None:
    value = os.environ.get("CLAIM_JUDGE_SHADOW_DIR", "")
    return Path(value) if value and os.path.isabs(value) else None


def production_state() -> dict:
    """Initial gate state in production.

    Alan's decision, 2026-11-07 07:22 (overrides the original plan): the first ten candidates are NOT held for a
    person's review.  Qualifying marks display directly, so the phase starts at 'auto' and the pre-review count is
    treated as already met.  claim_public_gate.new_state() still starts at 'pre_review' and the pre-review code path
    is kept untouched; only this production initialiser sets the phase.  The pause / resume rules are unchanged.
    """
    state = gate.new_state()
    state["phase"] = "auto"
    return state


@contextmanager
def _locked(dir_path: Path) -> Iterator[None]:
    dir_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with _LOCK:
        fd = os.open(str(dir_path / LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _load_state(dir_path: Path) -> dict:
    path = dir_path / STATE_NAME
    if not path.exists():
        return production_state()
    state = gate.load_state(path)
    # A state file still waiting for pre-review decisions that nobody will make is moved to 'auto' (see above).
    if state.get("phase") == "pre_review" and not any(e.get("decision") for e in state.get("pre_review", [])):
        state["phase"] = "auto"
    return state


def _save_state(dir_path: Path, state: Mapping[str, Any]) -> None:
    gate.save_state(dir_path / STATE_NAME, state)


def _read_entries(path: Path) -> list[dict]:
    """All well-formed entries of the marks file.  Cached on (mtime, size); a torn last line is skipped."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    cached = _READ_CACHE.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    entries: list[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("turn_id"), str) and isinstance(row.get("marks"), list):
                entries.append(row)
    _READ_CACHE[str(path)] = (key, entries)
    return entries


def _append_marks(dir_path: Path, turn_id: str, marks: list[dict]) -> None:
    """Append one entry unless every mark of this turn is already recorded (idempotent re-processing)."""
    path = dir_path / MARKS_NAME
    known = {m.get("id") for e in _read_entries(path) if e["turn_id"] == turn_id for m in e["marks"]}
    if all(m["id"] in known for m in marks):
        return
    row = {"turn_id": turn_id, "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "marks": marks}
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)


def process_record(dir_path: str | Path, record: Mapping[str, Any]) -> list[str]:
    """Run the public gate on one shadow record that has just been written.  Returns the ids shown for it."""
    dir_path = Path(dir_path)
    turn_id = str(record.get("turn_id") or "")
    marks = gate.annotations_from_record(record)
    if not turn_id or not marks:
        return []
    with _locked(dir_path):
        state = _load_state(dir_path)
        for mark in marks:
            gate.submit(state, mark)  # 'display', 'known' (already routed) or 'shadow_only' (paused)
        shown = gate.displayable_marks(record, state)
        _save_state(dir_path, state)
        if shown:
            _append_marks(dir_path, turn_id, shown)
    return [m["id"] for m in shown]


def public_view(mark: Mapping[str, Any]) -> dict:
    """The only fields a reader may see.  Built from the gate's public mark; the judge's reason never appears here."""
    hover = mark.get("hover") if isinstance(mark.get("hover"), Mapping) else {}
    evidence = hover.get("evidence") if isinstance(hover.get("evidence"), Mapping) else {}
    return {
        "id": str(mark.get("id", "")),
        "sentence_idx": mark.get("sentence_idx"),
        "marker": "neutral",
        "hit_kind": mark.get("hit_kind"),
        "template": mark.get("template"),
        "hover": {
            "answer_sentence": str(hover.get("answer_sentence") or ""),
            "evidence": {
                "ordinal": evidence.get("ordinal"),
                "quote": str(evidence.get("quote") or ""),
                "completeness": evidence.get("completeness"),
            },
        },
    }


def public_marks_for_turns(turn_ids) -> dict[str, list[dict]]:
    """Displayable public marks for the given turns.  Nothing is returned while the gate is paused, and only marks the
    gate has actually displayed are returned, so a pause takes effect on reads at once."""
    dir_path = shadow_dir()
    wanted = {str(t) for t in turn_ids if t}
    if dir_path is None or not wanted or not (dir_path / STATE_NAME).exists():
        return {}
    try:
        state = gate.load_state(dir_path / STATE_NAME)
    except (OSError, ValueError):
        return {}
    if state.get("paused"):
        return {}
    shown = {e.get("id") for e in state.get("displayed", [])}
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    for entry in _read_entries(dir_path / MARKS_NAME):
        if entry["turn_id"] not in wanted:
            continue
        for mark in entry["marks"]:
            if not isinstance(mark, Mapping):
                continue
            mark_id = mark.get("id")
            if mark_id in shown and mark_id not in seen:
                seen.add(mark_id)
                out.setdefault(entry["turn_id"], []).append(public_view(mark))
    return out


def status_view(state: Mapping[str, Any]) -> dict:
    return {
        "phase": state.get("phase"),
        "paused": bool(state.get("paused")),
        "pause_reason": state.get("pause_reason"),
        "displayed": len(state.get("displayed", [])),
        "regression": len(state.get("regression", [])),
        "resumes": len(state.get("resumes", [])),
    }


def status(dir_path: str | Path) -> dict:
    with _locked(Path(dir_path)):
        return status_view(_load_state(Path(dir_path)))


def review_mark(dir_path: str | Path, mark_id: str, outcome: str) -> dict:
    """Owner review of a displayed mark: 'ok' or 'confirmed_mislabel'.  Raises KeyError / ValueError from the gate."""
    dir_path = Path(dir_path)
    with _locked(dir_path):
        state = _load_state(dir_path)
        gate.review_displayed(state, mark_id, outcome)
        _save_state(dir_path, state)
        return status_view(state)


def manual_pause(dir_path: str | Path, reason: str) -> dict:
    dir_path = Path(dir_path)
    with _locked(dir_path):
        state = _load_state(dir_path)
        if not state["paused"]:
            state["paused"] = True
            state["pause_reason"] = f"manual (owner): {reason}"
        _save_state(dir_path, state)
        return status_view(state)


def manual_resume(dir_path: str | Path, *, replay_ref: str, note: str) -> dict:
    """Resume display; the gate requires a replay reference and a note, and keeps the history."""
    dir_path = Path(dir_path)
    with _locked(dir_path):
        state = _load_state(dir_path)
        if not state.get("paused"):
            raise KeyError("not_paused")
        gate.resume(state, replay_ref=replay_ref, note=note)
        _save_state(dir_path, state)
        return status_view(state)


# ---- SW2 S2 (spec-sw2 §3.1; K6–K10): the settled ledger and the previous answer's system source check -------------
# One line per shadow turn that reaches a terminal outcome: {turn_id, outcome, at}.  No answer, question or credential
# is written, and the file is 0600 in the 0700 shadow directory.  Readers look only at the last SETTLED_TAIL_LINES.
SETTLED_NAME = "turn-settled.jsonl"
SETTLED_TAIL_LINES = 2000
_SETTLED_CACHE: dict[str, tuple[tuple[int, int], dict[str, dict]]] = {}
# Ledger outcome -> why the answer was not checked (None: judged, decided by the marks).
LEDGER_REASON = {"no_judgeable": "no_judgeable", "daily_cap": "daily_cap", "circuit_open": "unavailable",
                 "model_unavailable": "unavailable", "model_changed": "unavailable", "stopped": "shadow_off",
                 "error": "unavailable"}


def append_settled(dir_path: str | Path, turn_id: str, outcome: str) -> None:
    """Record that a shadow turn has settled.  Callers ignore a failure: the shadow record and the answer stand."""
    dir_path = Path(dir_path)
    row = {"turn_id": str(turn_id), "outcome": outcome, "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with _locked(dir_path):
        fd = os.open(str(dir_path / SETTLED_NAME), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)


def _tail_lines(path: Path, count: int) -> list[bytes]:
    """The last `count` non-empty lines, read from the end: older bytes are never read."""
    with open(path, "rb") as handle:
        handle.seek(0, os.SEEK_END)
        pos = handle.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= count:
            step = min(8192, pos)
            pos -= step
            handle.seek(pos)
            data = handle.read(step) + data
    lines = data.split(b"\n")
    if pos > 0:
        lines = lines[1:]  # the first piece may start in the middle of a line
    return [line for line in lines if line.strip()][-count:]


def _settled_index(dir_path: Path) -> dict[str, dict]:
    """turn_id -> ledger row, from the tail only.  Missing file or unreadable bytes: nothing indexed (the caller says unknown)."""
    path = dir_path / SETTLED_NAME
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (stat.st_mtime_ns, stat.st_size)
    cached = _SETTLED_CACHE.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    index: dict[str, dict] = {}
    try:
        lines = _tail_lines(path, SETTLED_TAIL_LINES)
    except OSError:
        return {}
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("turn_id"), str) and isinstance(row.get("outcome"), str):
            index[row["turn_id"]] = row
    _SETTLED_CACHE[str(path)] = (key, index)
    return index


def read_settled(turn_id: str) -> dict | None:
    dir_path = shadow_dir()
    if dir_path is None or not turn_id:
        return None
    return _settled_index(dir_path).get(str(turn_id))


def prior_turn_marks(turn_id: str) -> tuple[bool, list[dict]]:
    """(paused, displayed marks) for one turn, read the way public_marks_for_turns reads them (SW2 K6).

    The paused flag is its own answer: a pause returns (True, []); a missing state file returns (False, []).
    public_marks_for_turns keeps its signature and its return value."""
    dir_path = shadow_dir()
    wanted = str(turn_id or "")
    if dir_path is None or not wanted or not (dir_path / STATE_NAME).exists():
        return False, []
    try:
        state = gate.load_state(dir_path / STATE_NAME)
    except (OSError, ValueError):
        return False, []
    if state.get("paused"):
        return True, []
    shown = {e.get("id") for e in state.get("displayed", [])}
    marks: list[dict] = []
    seen: set[str] = set()
    for entry in _read_entries(dir_path / MARKS_NAME):
        if entry["turn_id"] != wanted:
            continue
        for mark in entry["marks"]:
            if not isinstance(mark, Mapping):
                continue
            mark_id = mark.get("id")
            if mark_id in shown and mark_id not in seen:
                seen.add(mark_id)
                marks.append(public_view(mark))
    return False, marks


# Reasons a shadow turn can carry in judge_schedule (graph.py) that mean "not checked", spelled as the self-state block says them.
NOT_CHECKED_CODES = frozenset({"shadow_off", "unattended", "pending_request", "not_succeeded", "no_numbered_sources", "busy"})


def prior_answer_state(turn_id: str, *, owner: bool, audit: Mapping | None, elapsed_s: float) -> dict:
    """The previous answer's system source check, decided once per turn (SW2 §3.1 item 3; K8, K9).

    Returns {state, ...}: shown (with sentences), none, pending, paused, not_checked (with reason), unknown.
    A requester who is not the owner is not checked at all; that is decided here, not written to the ledger (K8)."""
    if not owner:
        return {"state": "not_checked", "reason": "not_owner"}
    paused, marks = prior_turn_marks(turn_id)
    sentences = [str(((m.get("hover") or {}).get("answer_sentence")) or "") for m in marks]
    if not isinstance(audit, Mapping) or "judge_schedule" not in audit:
        # A turn from before judge_schedule existed (or with the switch off): the marks it has are all there is.
        return {"state": "shown", "sentences": sentences} if marks else {"state": "unknown"}
    schedule = audit.get("judge_schedule")
    if schedule != "scheduled":
        return {"state": "not_checked", "reason": schedule if schedule in NOT_CHECKED_CODES else "unavailable"}
    if paused:
        return {"state": "paused"}
    settled = read_settled(turn_id)
    if settled is None:
        from .claim_shadow import TURN_BUDGET_SECONDS
        if elapsed_s < TURN_BUDGET_SECONDS + 60:
            return {"state": "pending", "elapsed_s": elapsed_s}
        return {"state": "unknown"}
    outcome = settled.get("outcome")
    if outcome == "judged":
        return {"state": "shown", "sentences": sentences} if marks else {"state": "none"}
    if outcome in LEDGER_REASON:
        return {"state": "not_checked", "reason": LEDGER_REASON[outcome]}
    return {"state": "unknown"}
