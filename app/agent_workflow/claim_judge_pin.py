"""Global default judge model and frozen versions (U10).

The pin file holds the model label and the version strings that sampling and acceptance must share.
It never holds a key.  Environment variables still override the label for an operator, but the
shadow path is disabled when any code version differs from the pin, so unfrozen code cannot run.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

PIN_PATH = Path(__file__).resolve().parents[2] / "config" / "claim_judge_pin.json"


@lru_cache(maxsize=1)
def load_pin(path: str | None = None) -> dict:
    return json.loads(Path(path or PIN_PATH).read_text(encoding="utf-8"))


def _judge_role_entry() -> str | None:
    """The catalog entry the settings page bound to the judge role, or None (no row, the entry has left the
    catalog, or the lookup failed).  None hands the decision back to env / pin, so the judge never silently becomes
    the catalog default.  Read on every call, never cached: a change in settings applies to the next turn.
    Imported here because claim_shadow lazily imports this module and agent_model_roles pulls in the database."""
    try:
        from .. import agent_model_catalog as catalog
        from .. import agent_model_roles as roles
        owner = roles.judge_owner()
        name = roles.get(owner, "judge") if owner else None
        return name if name and catalog.exists(name) else None
    except Exception as exc:  # the role is an override; if it cannot be read the env / pin judge still stands
        logger.warning("Judge role lookup failed: %s", type(exc).__name__)
        return None


def shadow_model_name() -> str:
    """Catalog entry name of the judge: settings role, else CLAIM_JUDGE_SHADOW_MODEL, else the pin."""
    return (_judge_role_entry()
            or (os.environ.get("CLAIM_JUDGE_SHADOW_MODEL") or "").strip()
            or load_pin()["judge"]["name"])


def expected_model() -> str:
    """Provider model string the resolved judge must have (claim_shadow compares it with ``resolved["model"]``).
    With the role in force it is that entry's own model; otherwise env, else the pin."""
    entry = _judge_role_entry()
    if entry:
        try:
            from .. import agent_model_catalog as catalog
            return str(catalog.resolve(entry)["model"])
        except Exception as exc:  # e.g. key missing: claim_shadow's own resolve then reports model_unavailable
            logger.warning("Judge role model unresolved: %s", type(exc).__name__)
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
