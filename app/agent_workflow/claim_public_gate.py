"""Public gate for shadow contradiction marks (U9).

Pure code: no model call, no network.  A mark is built only from structured shadow fields (verified quote,
subtype, passed short review, source completeness).  The judge's free text (reason) never reaches the public
payload, and the wording is a fixed code template.  The gate state is a small JSON file:

- pre_review: the first PRE_REVIEW_COUNT candidates are reviewed by a person before display;
  a rejected candidate counts as a candidate false positive, not a public mislabel.
- auto: approved displays continue; a displayed mark later reviewed as a confirmed mislabel is added to
  the versioned regression list.  The second confirmed mislabel among the most recent ROLLING_WINDOW
  reviewed public marks pauses display (back to shadow).  The first one does not pause.
- paused: nothing is displayed until a person resumes with a replay reference.

Unreviewed displays do not count as clean samples and do not dilute the rolling count.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

PUBLIC_GATE_VERSION = "public-gate-v1"
PRE_REVIEW_COUNT = 10
ROLLING_WINDOW = 20
PAUSE_CONFIRMED_MISLABELS = 2

# Neutral templates, built from code only.  No wording of verdict or fact-check status is used.
TEMPLATES = {
    "number": "来源 [{ordinal}] 中同一指标的数值与此句不同",
    "direction": "来源 [{ordinal}] 中该变动的方向与此句不同",
    "state": "来源 [{ordinal}] 中该事项的状态与此句不同",
    # A pointer only: code must not assert who holds the figure (U3 revision); the reader checks the source text.
    "subject": "请对照来源 [{ordinal}] 中关于「{name}」的原文",
    "other": "来源 [{ordinal}] 中有与此句不一致的表述",
}
FORBIDDEN_PUBLIC_WORDS = ("矛盾", "编造", "已核验", "核实", "证据不足", "数字未核实")


def _sha(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def _completeness(record: Mapping[str, Any], ordinal: int) -> str:
    meta = (record.get("sources") or {}).get(str(ordinal)) or {}
    complete = bool(meta.get("complete_sent")) and not bool(meta.get("truncated"))
    return "complete" if complete else "excerpt"


def public_annotation(record: Mapping[str, Any], sentence: Mapping[str, Any]) -> dict | None:
    """One public-eligible mark from one judged sentence of a shadow record, or None (no mark)."""
    if sentence.get("status") != "ok" or sentence.get("verdict") != "contradiction":
        return None
    if sentence.get("quote_verified") is not True or sentence.get("quote_ordinal") is None:
        return None
    review = sentence.get("short_review")
    if not (isinstance(review, Mapping) and review.get("status") == "ok" and review.get("passed") is True):
        return None
    subtype = sentence.get("subtype") if sentence.get("subtype") in TEMPLATES else "other"
    ordinal = int(sentence["quote_ordinal"])
    name = str(sentence.get("name_span") or "")
    if subtype == "subject" and not name:
        subtype = "other"
    template = TEMPLATES[subtype].format(ordinal=ordinal, name=name)
    turn_id = str(record.get("turn_id") or "")
    idx = int(sentence.get("idx", -1))
    quote = str(sentence.get("quote") or "")[:300]
    return {
        "version": PUBLIC_GATE_VERSION,
        "id": _sha(turn_id, str(idx), str(sentence.get("text") or "")),
        "turn_id": turn_id,
        "sentence_idx": idx,
        "marker": "neutral",
        "hit_kind": subtype,
        "template": template,
        "hover": {
            "answer_sentence": str(sentence.get("text") or ""),
            "evidence": {"ordinal": ordinal, "quote": quote, "completeness": _completeness(record, ordinal)},
            "name_span": name if subtype == "subject" else "",
        },
    }


def annotations_from_record(record: Mapping[str, Any]) -> list[dict]:
    out = []
    for sentence in record.get("sentences") or []:
        if isinstance(sentence, Mapping):
            mark = public_annotation(record, sentence)
            if mark is not None:
                out.append(mark)
    return out


def new_state() -> dict:
    return {"version": PUBLIC_GATE_VERSION, "phase": "pre_review", "pre_review": [], "displayed": [],
            "regression": [], "candidate_false_positives": 0, "paused": False, "pause_reason": None,
            "resumes": []}


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return new_state()
    return json.loads(p.read_text(encoding="utf-8"))


def save_state(path: str | Path, state: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def _known_ids(state: Mapping[str, Any]) -> set[str]:
    return {e["id"] for e in state["pre_review"]} | {e["id"] for e in state["displayed"]}


def submit(state: dict, mark: Mapping[str, Any]) -> str:
    """Route one candidate mark.  Returns 'awaiting_human', 'display', 'shadow_only', or 'known'."""
    if mark["id"] in _known_ids(state):
        return "known"
    if state["paused"]:
        return "shadow_only"
    if state["phase"] == "pre_review":
        state["pre_review"].append({"id": mark["id"], "decision": None, "mark": dict(mark)})
        return "awaiting_human"
    state["displayed"].append({"id": mark["id"], "review": None, "mark": dict(mark), "pre_reviewed": False})
    return "display"


def decide_pre_review(state: dict, mark_id: str, decision: str) -> None:
    """A person decides a pre-review candidate: 'approve' (may display) or 'reject' (candidate false positive)."""
    if decision not in {"approve", "reject"}:
        raise ValueError("decision must be approve or reject")
    entry = next((e for e in state["pre_review"] if e["id"] == mark_id and e["decision"] is None), None)
    if entry is None:
        raise KeyError("no pending pre-review candidate with this id")
    entry["decision"] = decision
    if decision == "reject":
        state["candidate_false_positives"] += 1
    else:
        # An approved first-batch mark is public; a later confirmed mislabel is still recorded for regression.
        state["displayed"].append({"id": mark_id, "review": None, "mark": dict(entry["mark"]), "pre_reviewed": True})
    if len(state["pre_review"]) >= PRE_REVIEW_COUNT and all(e["decision"] for e in state["pre_review"]):
        state["phase"] = "auto"


def is_public(state: Mapping[str, Any], mark_id: str) -> bool:
    if state["paused"]:
        return False
    return any(e["id"] == mark_id for e in state["displayed"])


def review_displayed(state: dict, mark_id: str, outcome: str) -> None:
    """Record a person's review of a displayed mark: 'ok' or 'confirmed_mislabel'."""
    if outcome not in {"ok", "confirmed_mislabel"}:
        raise ValueError("outcome must be ok or confirmed_mislabel")
    entry = next((e for e in state["displayed"] if e["id"] == mark_id), None)
    if entry is None:
        raise KeyError("mark was not displayed")
    if entry["review"] is not None:
        raise ValueError("already reviewed")
    entry["review"] = outcome
    if outcome == "confirmed_mislabel":
        state["regression"].append({"id": mark_id, "turn_id": entry["mark"]["turn_id"],
                                    "sentence_idx": entry["mark"]["sentence_idx"],
                                    "gate_version": PUBLIC_GATE_VERSION})
    # Rolling count: post-review marks only (the first batch is excluded by design: 'after the first 10').
    reviewed = [e for e in state["displayed"] if e["review"] is not None and not e.get("pre_reviewed")]
    reviewed = reviewed[-ROLLING_WINDOW:]
    confirmed = sum(1 for e in reviewed if e["review"] == "confirmed_mislabel")
    if confirmed >= PAUSE_CONFIRMED_MISLABELS and not state["paused"]:
        state["paused"] = True
        state["pause_reason"] = (f"{confirmed} confirmed mislabels in the latest {len(reviewed)} reviewed "
                                 f"public marks; back to shadow, replay the frozen set")


def displayable_marks(record: Mapping[str, Any], state: Mapping[str, Any]) -> list[dict]:
    """The marks the public surface may show for one shadow record: only those the gate has displayed,
    and none at all while the gate is paused."""
    if state.get("paused"):
        return []
    shown = {e["id"] for e in state.get("displayed", [])}
    return [m for m in annotations_from_record(record) if m["id"] in shown]


def resume(state: dict, *, replay_ref: str, note: str) -> None:
    """Only a person resumes, and only with a replay reference; history is kept."""
    if not state["paused"]:
        return
    if not replay_ref or not note:
        raise ValueError("resume needs a replay reference and a note")
    state["resumes"].append({"replay_ref": replay_ref, "note": note, "was": state["pause_reason"]})
    state["paused"] = False
    state["pause_reason"] = None
