"""Unit tests for scripts/claim_shadow_report.py (§4.3, §4.5, §5, §6.3)."""
import argparse
import json
from pathlib import Path

import pytest

from scripts.claim_shadow_report import (
    determine_conclusion,
    load_jsonl_turns,
    load_reviews,
    run_export,
    run_progress,
    run_report,
    scan_for_secrets,
    wilson_interval,
)


def test_wilson_interval_bounds_and_stage1_baseline():
    """Wilson interval never outputs 100% when f=0, matching §5 numbers."""
    # 0/57: upper bound approx 6.3%
    f_low, f_high = wilson_interval(0, 57)
    assert f_low == 0.0
    assert 0.05 < f_high < 0.07  # approx 6.27%

    # 29/29: lower bound approx 88.3%
    r_low, r_high = wilson_interval(29, 29)
    assert 0.85 < r_low < 0.90  # approx 88.3%
    assert r_high == 1.0


def test_conclusions_rule_tree():
    """Test every branch of §4.5 decision table."""
    target = 100

    # 1. Sample not full (< TARGET)
    c1, _ = determine_conclusion(counted_turns=50, target_turns=target, human_reviews={}, strata_counts={})
    assert c1 == "样本未满（中期报告）"

    # 2. No human reviews
    c2, _ = determine_conclusion(counted_turns=100, target_turns=target, human_reviews={}, strata_counts={})
    assert c2 == "未经人工确认，不作为阶段 3 依据"

    # Pretriage model reviews must not count as human
    model_review = {"t1:0": {"reviewer_kind": "model", "label": "real_fabrication"}}
    c2_model, _ = determine_conclusion(counted_turns=100, target_turns=target, human_reviews=model_review, strata_counts={})
    assert c2_model == "未经人工确认，不作为阶段 3 依据"

    # 3. C < 3 and U == 0: Trigger stop condition
    human_reviews_c2 = {
        "t1:0": {"reviewer_kind": "human", "label": "real_fabrication"},
        "t2:0": {"reviewer_kind": "human", "label": "real_fabrication"},
        "t3:0": {"reviewer_kind": "human", "label": "legit_inference"},
    }
    c3, _ = determine_conclusion(
        counted_turns=100,
        target_turns=target,
        human_reviews=human_reviews_c2,
        strata_counts={"_unreviewed_ae": 0},
    )
    assert c3 == "触发停止条件：不开阶段 3"

    # 4. C < 3 and U > 0: Pending Alan decision
    c4, _ = determine_conclusion(
        counted_turns=100,
        target_turns=target,
        human_reviews=human_reviews_c2,
        strata_counts={"_unreviewed_ae": 5},
    )
    assert c4 == "未读完，待 Alan 裁定"

    # 5. C >= 3, human contradiction < 30
    human_reviews_c3 = {
        "t1:0": {"reviewer_kind": "human", "label": "real_fabrication"},
        "t2:0": {"reviewer_kind": "human", "label": "real_fabrication"},
        "t3:0": {"reviewer_kind": "human", "label": "real_fabrication"},
    }
    c5, _ = determine_conclusion(
        counted_turns=100,
        target_turns=target,
        human_reviews=human_reviews_c3,
        strata_counts={"_unreviewed_ae": 0, "_human_contra_reviewed": 15},
    )
    assert c5 == "未触发停止条件；被标句不足，精确率不下结论"

    # 6. C >= 3, human contradiction >= 30, precision >= 85%, normal miss <= 3%
    c6, _ = determine_conclusion(
        counted_turns=100,
        target_turns=target,
        human_reviews=human_reviews_c3,
        strata_counts={
            "_unreviewed_ae": 0,
            "_human_contra_reviewed": 35,
            "_contra_precision": 0.90,
            "_normal_miss_rate": 0.02,
        },
    )
    assert c6 == "未触发停止条件；门槛达标"

    # 7. C >= 3, human contradiction >= 30, threshold NOT met (e.g. miss > 3%)
    c7, _ = determine_conclusion(
        counted_turns=100,
        target_turns=target,
        human_reviews=human_reviews_c3,
        strata_counts={
            "_unreviewed_ae": 0,
            "_human_contra_reviewed": 35,
            "_contra_precision": 0.80,
            "_normal_miss_rate": 0.05,
        },
    )
    assert c7 == "未触发停止条件；门槛未达标"


def test_f_stratum_human_real_fabrication_counts_in_c():
    """Human real_fabrication found in stratum F must count into C."""
    reviews = {
        "t1:0": {"reviewer_kind": "human", "label": "real_fabrication"},  # from F layer
        "t2:0": {"reviewer_kind": "human", "label": "real_fabrication"},
        "t3:0": {"reviewer_kind": "human", "label": "real_fabrication"},
    }
    conclusion, stats = determine_conclusion(
        counted_turns=100,
        target_turns=100,
        human_reviews=reviews,
        strata_counts={"_unreviewed_ae": 0, "_human_contra_reviewed": 10},
    )
    assert stats["C"] == 3


def test_load_jsonl_skips_bad_lines(tmp_path: Path):
    fpath = tmp_path / "2026-11-06.1234.jsonl"
    valid = json.dumps({"turn_id": "t1", "outcome": "judged"})
    bad = "{\"turn_id\": \"broken"
    fpath.write_text(f"{valid}\n{bad}\n", encoding="utf-8")

    turns, skipped = load_jsonl_turns(tmp_path)
    assert len(turns) == 1
    assert skipped == 1


def test_load_reviews_later_overwrites_earlier(tmp_path: Path):
    rpath = tmp_path / "reviews.jsonl"
    r1 = json.dumps({"item_id": "t1:0", "reviewer_kind": "human", "label": "judge_wrong"})
    r2 = json.dumps({"item_id": "t1:0", "reviewer_kind": "human", "label": "real_fabrication"})
    rpath.write_text(f"{r1}\n{r2}\n", encoding="utf-8")

    reviews, _ = load_reviews(rpath)
    assert len(reviews) == 1
    assert reviews["t1:0"]["label"] == "real_fabrication"


def test_secret_scan_detects_bearer_and_sk(tmp_path: Path):
    clean_file = tmp_path / "data.jsonl"
    clean_file.write_text("{\"content\": \"ordinary text\"}\n", encoding="utf-8")
    clean, note = scan_for_secrets(tmp_path)
    assert clean is True
    assert note == "clean"

    bad_file = tmp_path / "leaked.jsonl"
    bad_file.write_text("{\"auth\": \"Bearer secret-token-abc\"}\n", encoding="utf-8")
    clean2, note2 = scan_for_secrets(tmp_path)
    assert clean2 is False
    assert note2 == "leaked.jsonl"


def _write_shadow_turns(directory: Path, rows: list[dict]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "2026-11-05.1.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
    )


def test_progress_reads_env_dir_when_dir_arg_is_empty(tmp_path: Path, monkeypatch, capsys):
    """Regression: --dir defaults to "", and Path("") read the current directory, so --progress printed 0 turns."""
    shadow = tmp_path / "shadow"
    _write_shadow_turns(shadow, [
        {"turn_id": "t1", "outcome": "judged", "counted": True, "sentence_candidates": 2},
        {"turn_id": "t2", "outcome": "skipped", "counted": False, "sentence_candidates": 0},
        {"turn_id": "t3", "outcome": "judged", "counted": True, "sentence_candidates": 1},
    ])
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(shadow))
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_TARGET_TURNS", raising=False)

    assert run_progress(argparse.Namespace(dir="")) == 0

    out = capsys.readouterr().out
    assert "Total turns recorded: 3" in out
    assert "Counted turns: 2 / 100" in out


def test_export_reads_env_dir_when_dir_arg_is_empty(tmp_path: Path, monkeypatch, capsys):
    """Same fallback for --export: an empty --dir must not read the current directory."""
    shadow = tmp_path / "shadow"
    _write_shadow_turns(shadow, [{
        "turn_id": "t1", "question": "q", "counted": True, "sources": {},
        "sentences": [{"idx": 0, "text": "AMD closed at 100.", "status": "ok", "verdict": "contradiction",
                       "quote_verified": True, "ordinals": [1]}],
    }])
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(shadow))
    args = argparse.Namespace(export="full", dir="", out=str(tmp_path / "out"), seed=42,
                              all_supported=False, pretriage="")

    assert run_export(args) == 0

    assert "Exported 1 items" in capsys.readouterr().out


def test_report_reads_env_dir_when_dir_arg_is_empty(tmp_path: Path, monkeypatch):
    """Same fallback for --report: the counted-turn line must come from the env directory."""
    shadow = tmp_path / "shadow"
    _write_shadow_turns(shadow, [
        {"turn_id": "t1", "outcome": "judged", "counted": True},
        {"turn_id": "t2", "outcome": "skipped", "counted": False},
    ])
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(shadow))
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_TARGET_TURNS", raising=False)
    out_path = tmp_path / "report.md"
    args = argparse.Namespace(dir="", reviews=str(tmp_path / "reviews.jsonl"), out=str(out_path),
                              stage1="", exclude_conversation=[])

    assert run_report(args) == 0

    text = out_path.read_text(encoding="utf-8")
    assert "总记录轮数: 2" in text
    assert "计入轮数 (counted=true): 1 / 100" in text
