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
