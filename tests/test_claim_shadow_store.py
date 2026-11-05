"""Unit tests for claim_shadow_store.py (§3.1, §3.2, §3.3, §6.3)."""
import asyncio
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.agent_workflow.claim_shadow_store import append_turn, prune, scan_counters


def test_append_turn_creates_valid_jsonl_and_sets_permissions(tmp_path: Path):
    record = {
        "schema": "claim-shadow-v1",
        "turn_id": "t1",
        "outcome": "judged",
        "counted": True,
        "answer_sha256": "hash1",
        "sentences": [{"status": "ok", "verdict": "supported"}],
    }

    fpath = append_turn(tmp_path, record)
    assert fpath.exists()

    # Permissions
    dir_mode = stat.S_IMODE(os.stat(tmp_path).st_mode)
    assert dir_mode == 0o700

    file_mode = stat.S_IMODE(os.stat(fpath).st_mode)
    assert file_mode == 0o600

    # Content
    lines = fpath.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["turn_id"] == "t1"
    assert loaded["outcome"] == "judged"


def test_concurrent_appends_do_not_interleave(tmp_path: Path):
    """Simulate multiple concurrent tasks appending to JSONL; every line must be valid JSON."""
    async def _write_records():
        async def _worker(worker_id: int):
            for i in range(25):
                rec = {
                    "worker": worker_id,
                    "seq": i,
                    "payload": "x" * 150,
                    "counted": (i % 2 == 0),
                    "answer_sha256": f"w{worker_id}_s{i}",
                    "sentences": [{"status": "ok"}],
                }
                await asyncio.to_thread(append_turn, tmp_path, rec)

        tasks = [_worker(w) for w in range(8)]
        await asyncio.gather(*tasks)

    asyncio.run(_write_records())

    # Find the created file
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text(encoding="utf-8").splitlines()
    assert len(lines) == 200

    # Every single line must parse cleanly
    for line in lines:
        parsed = json.loads(line)
        assert "worker" in parsed


def test_scan_counters_skips_broken_lines(tmp_path: Path):
    now_utc = datetime.now(UTC)
    date_str = now_utc.strftime("%Y-%m-%d")
    target_file = tmp_path / f"{date_str}.{os.getpid()}.jsonl"

    valid1 = json.dumps({"counted": True, "answer_sha256": "h1", "sentences": [{"status": "ok"}, {"status": "ok"}]})
    broken = "{\"turn_id\": \"broken_half_line"
    valid2 = json.dumps({"counted": False, "answer_sha256": "h2", "sentences": [{"status": "ok"}]})

    target_file.write_text(f"{valid1}\n{broken}\n{valid2}\n", encoding="utf-8")

    res = scan_counters(tmp_path, today_utc=now_utc.date())
    assert res.calls_today == 3  # 2 + 1
    assert res.counted_turns == 1
    assert res.seen_answer_hashes == {"h1", "h2"}
    assert res.skipped_broken_lines == 1


def test_prune_deletes_expired_files_and_preserves_stop_and_export(tmp_path: Path):
    now_utc = datetime.now(UTC)
    old_date = (now_utc - timedelta(days=200)).strftime("%Y-%m-%d")
    recent_date = (now_utc - timedelta(days=10)).strftime("%Y-%m-%d")

    old_file = tmp_path / f"{old_date}.12345.jsonl"
    old_file.write_text("{}\n", encoding="utf-8")

    recent_file = tmp_path / f"{recent_date}.12345.jsonl"
    recent_file.write_text("{}\n", encoding="utf-8")

    stop_file = tmp_path / "STOP"
    stop_file.write_text("STOP\n", encoding="utf-8")

    export_dir = tmp_path / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "exported.jsonl").write_text("{}\n", encoding="utf-8")

    deleted = prune(tmp_path, retention_days=180, now=now_utc)
    assert deleted == 1
    assert not old_file.exists()
    assert recent_file.exists()
    assert stop_file.exists()
    assert export_dir.exists()
    assert (export_dir / "exported.jsonl").exists()
