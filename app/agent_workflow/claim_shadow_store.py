"""Persistence, counter scanning, and retention pruning for LLM claim judge stage 2 (shadow mode).

Spec: ``.local/design-judge-stage2.md`` §3.1, §3.2, §3.3.
Directory permissions: 0700. File permissions: 0600.
Atomic line append via O_APPEND. Broken JSON lines are skipped gracefully.
"""
from __future__ import annotations

import json
import os
import re
import stat
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

FILE_NAME_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\d+\.jsonl$")


class ScanCountersResult(tuple):
    """3-tuple (calls_today, counted_turns, seen_answer_hashes) with extra attributes."""

    def __new__(
        cls,
        calls_today: int,
        counted_turns: int,
        seen_answer_hashes: set[str],
        skipped_broken_lines: int = 0,
    ):
        instance = super().__new__(cls, (calls_today, counted_turns, seen_answer_hashes))
        instance.calls_today = calls_today
        instance.counted_turns = counted_turns
        instance.seen_answer_hashes = seen_answer_hashes
        instance.skipped_broken_lines = skipped_broken_lines
        return instance


def append_turn(dir_path: str | Path, record: dict) -> Path:
    """Atomically append a single JSON turn record to today's pid-specific JSONL file."""
    dir_path = Path(dir_path)
    if not dir_path.exists():
        dir_path.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(dir_path, 0o700)
    except OSError:
        pass

    now_utc = datetime.now(UTC)
    date_str = now_utc.strftime("%Y-%m-%d")
    pid = os.getpid()
    file_path = dir_path / f"{date_str}.{pid}.jsonl"

    payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")

    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    mode = 0o600
    fd = os.open(str(file_path), flags, mode)
    try:
        try:
            os.chmod(str(file_path), 0o600)
        except OSError:
            pass
        os.write(fd, payload)
    finally:
        os.close(fd)

    return file_path


def scan_counters(
    dir_path: str | Path,
    today_utc: date | str | None = None,
) -> ScanCountersResult:
    """Scan directory to count calls today, counted turns, and seen answer sha256 hashes.

    Broken/truncated lines are skipped and counted.
    """
    dir_path = Path(dir_path)
    if not dir_path.exists() or not dir_path.is_dir():
        return ScanCountersResult(0, 0, set(), 0)

    if today_utc is None:
        today_date = datetime.now(UTC).date()
    elif isinstance(today_utc, str):
        today_date = date.fromisoformat(today_utc)
    else:
        today_date = today_utc

    today_str = today_date.strftime("%Y-%m-%d")
    today_prefix = f"{today_str}."

    calls_today = 0
    counted_turns = 0
    seen_answer_hashes: set[str] = set()
    skipped_broken = 0

    try:
        entries = sorted(os.listdir(dir_path))
    except OSError:
        return ScanCountersResult(0, 0, set(), 0)

    for entry in entries:
        if not FILE_NAME_PATTERN.match(entry):
            continue

        file_path = dir_path / entry
        is_today = entry.startswith(today_prefix)

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        row = json.loads(line_str)
                    except ValueError:
                        skipped_broken += 1
                        continue

                    if not isinstance(row, dict):
                        skipped_broken += 1
                        continue

                    if row.get("counted") is True:
                        counted_turns += 1

                    ans_sha = row.get("answer_sha256")
                    if ans_sha and isinstance(ans_sha, str):
                        seen_answer_hashes.add(ans_sha)

                    if is_today:
                        sentences = row.get("sentences") or []
                        # Each sentence actually dispatched to judge (not skipped before call)
                        calls = sum(
                            1
                            for s in sentences
                            if isinstance(s, dict)
                            and not str(s.get("status", "")).startswith("skipped")
                        )
                        review_calls = sum(
                            1 for sentence in sentences
                            if isinstance(sentence, dict)
                            and isinstance(sentence.get("short_review"), dict)
                            and sentence["short_review"].get("status") in {"ok", "timeout", "provider_error", "parse_error"}
                        )
                        attribution_calls = sum(
                            1 for sentence in sentences if isinstance(sentence, dict)
                            for item in (sentence.get("attribution_reviews") or []) if isinstance(item, dict)
                            and isinstance(item.get("review"), dict)
                            and item["review"].get("status") in {"ok", "timeout", "provider_error", "parse_error"}
                        )
                        pool_calls = sum(
                            1 for sentence in sentences if isinstance(sentence, dict)
                            and isinstance(sentence.get("pool_check"), dict)
                        )
                        calls_today += calls + review_calls + attribution_calls + pool_calls
        except OSError:
            continue

    return ScanCountersResult(
        calls_today=calls_today,
        counted_turns=counted_turns,
        seen_answer_hashes=seen_answer_hashes,
        skipped_broken_lines=skipped_broken,
    )


def prune(
    dir_path: str | Path,
    retention_days: int = 180,
    now: datetime | None = None,
) -> int:
    """Delete JSONL files older than retention_days.

    Never deletes STOP, export/ directory, or files not matching the date.pid.jsonl pattern.
    """
    dir_path = Path(dir_path)
    if not dir_path.exists() or not dir_path.is_dir():
        return 0

    now_utc = now if now is not None else datetime.now(UTC)
    cutoff_date = now_utc.date() - timedelta(days=retention_days)

    deleted_count = 0
    try:
        entries = os.listdir(dir_path)
    except OSError:
        return 0

    for entry in entries:
        match = FILE_NAME_PATTERN.match(entry)
        if not match:
            continue

        date_str = match.group(1)
        try:
            file_date = date.fromisoformat(date_str)
        except ValueError:
            continue

        if file_date < cutoff_date:
            file_path = dir_path / entry
            try:
                os.remove(file_path)
                deleted_count += 1
            except OSError:
                pass

    return deleted_count
