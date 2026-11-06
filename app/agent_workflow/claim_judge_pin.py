"""Global default judge model and frozen versions (U10).

The pin file holds the model label and the version strings that sampling and acceptance must share.
It never holds a key.  Environment variables still override the label for an operator, but the
shadow path is disabled when any code version differs from the pin, so unfrozen code cannot run.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

PIN_PATH = Path(__file__).resolve().parents[2] / "config" / "claim_judge_pin.json"


@lru_cache(maxsize=1)
def load_pin(path: str | None = None) -> dict:
    return json.loads(Path(path or PIN_PATH).read_text(encoding="utf-8"))


def shadow_model_name() -> str:
    return (os.environ.get("CLAIM_JUDGE_SHADOW_MODEL") or "").strip() or load_pin()["judge"]["name"]


def expected_model() -> str:
    return (os.environ.get("CLAIM_JUDGE_SHADOW_EXPECT_MODEL") or "").strip() or load_pin()["judge"]["model"]


def code_versions() -> dict[str, str]:
    from . import claim_judge, claim_pool_review, claim_public_gate, claim_shadow, claim_short_review, claim_windows
    return {
        "prompt": claim_judge.PROMPT_VERSION,
        "window": claim_windows.WINDOW_VERSION,
        "review": claim_short_review.REVIEW_VERSION,
        "pool": claim_pool_review.POOL_REVIEW_VERSION,
        "public_gate": claim_public_gate.PUBLIC_GATE_VERSION,
        "shadow_prompt": claim_shadow.PROMPT_VERSION,
    }


def version_mismatches(pin: dict | None = None) -> list[str]:
    """Keys whose code version differs from the pin (shadow_prompt must equal prompt)."""
    pin = pin or load_pin()
    pinned = dict(pin["versions"], shadow_prompt=pin["versions"]["prompt"])
    actual = code_versions()
    return sorted(k for k in pinned if pinned[k] != actual.get(k))
