"""deployment/heibao/finbot-db-backup.sh 的本地测试（用假 docker，不碰任何真实容器）。"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deployment" / "heibao" / "finbot-db-backup.sh"
PASSWORD = "S3cr3t-P@ss/word"

FAKE_DOCKER = r"""#!/usr/bin/env bash
# 假 docker：只支持 exec [-i] <container> pg_dump|pg_restore
echo "$*" >> "$FAKE_DOCKER_LOG"
[ "$1" = "exec" ] || exit 2
shift
[ "$1" = "-i" ] && shift
container="$1"; shift
case "$1" in
  pg_dump)
    if [ "$container" = "${FAKE_DUMP_FAIL_CONTAINER:-}" ]; then exit 1; fi
    head -c "${FAKE_DUMP_BYTES:-2000000}" /dev/zero | tr '\0' 'x'
    ;;
  pg_restore)
    cat > /dev/null
    exit "${FAKE_RESTORE_RC:-0}"
    ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture()
def env(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"OTHER=1\nDATABASE_URL=postgresql+psycopg://finuser:{PASSWORD}@127.0.0.1:5432/findb\n"
    )
    backup_dir = tmp_path / "backups" / "db"
    log = tmp_path / "docker.log"
    e = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FINBOT_ENV_FILE": str(env_file),
        "BACKUP_DIR": str(backup_dir),
        "BACKUP_MIN_FREE_MB": "1",
        "FAKE_DOCKER_LOG": str(log),
    }
    return e, backup_dir, log, tmp_path


def run(e: dict[str, str], **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)], env={**e, **extra}, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
    )


def mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_success(env):
    e, backup_dir, log, _ = env
    r = run(e)
    assert r.returncode == 0, r.stdout + r.stderr
    dumps = list(backup_dir.glob("finbot-*.dump"))
    assert len(dumps) == 1
    assert mode(dumps[0]) == 0o600
    assert mode(backup_dir) == 0o700
    assert not list(backup_dir.glob("*.partial"))
    status = (backup_dir / "last-success.txt").read_text(encoding="utf-8")
    assert dumps[0].name in status and str(dumps[0].stat().st_size) in status
    assert "向量库未配置，已跳过" in r.stdout
    calls = log.read_text(encoding="utf-8")
    assert "pg_dump -U finuser -d findb -Fc" in calls
    assert "finbot-pgvector" not in calls


def test_pgvector_when_configured(env):
    e, backup_dir, log, _ = env
    r = run(e, PGVECTOR_DB_USER="vu", PGVECTOR_DB_NAME="vdb")
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(list(backup_dir.glob("finbot-*.dump"))) == 1
    assert len(list(backup_dir.glob("pgvector-*.dump"))) == 1
    assert "finbot-pgvector pg_dump -U vu -d vdb -Fc" in log.read_text(encoding="utf-8")


def test_verify_failure_keeps_old_backups(env):
    e, backup_dir, _, _ = env
    backup_dir.mkdir(parents=True)
    old = []
    for i in range(16):
        p = backup_dir / f"finbot-20260101-0000{i:02d}.dump"
        p.write_text("old")
        old.append(p)
    r = run(e, FAKE_RESTORE_RC="1")
    assert r.returncode != 0
    assert all(p.exists() for p in old)
    assert len(list(backup_dir.iterdir())) == 16  # 没有新文件、没有 .partial
    assert not (backup_dir / "last-success.txt").exists()


def test_too_small_dump_fails(env):
    e, backup_dir, _, _ = env
    r = run(e, FAKE_DUMP_BYTES="100", BACKUP_MIN_BYTES="1048576")
    assert r.returncode != 0
    assert not list(backup_dir.glob("*.dump")) and not list(backup_dir.glob("*.partial"))


def test_pg_dump_failure_alerts(env):
    e, backup_dir, _, tmp = env
    alert_out = tmp / "alert.txt"
    alert = tmp / "alert.sh"
    alert.write_text(f'#!/bin/sh\nprintf "%s" "$1" > {alert_out}\n', encoding="utf-8")
    alert.chmod(0o755)
    r = run(
        e,
        FAKE_DUMP_FAIL_CONTAINER="finbot-postgres",
        BACKUP_ALERT_CMD=str(alert),
    )
    assert r.returncode != 0
    assert "pg_dump 失败" in alert_out.read_text(encoding="utf-8")
    assert not list(backup_dir.glob("*.partial"))


def test_retention(env):
    e, backup_dir, _, _ = env
    backup_dir.mkdir(parents=True)
    for i in range(16):
        (backup_dir / f"finbot-20260101-0000{i:02d}.dump").write_text("old")
    others = {
        "market-evidence.dump": "keep1",
        "notes.txt": "keep2",
        "finbot-notes.txt": "keep3",
    }
    for name, content in others.items():
        (backup_dir / name).write_text(content)
    r = run(e)
    assert r.returncode == 0, r.stdout + r.stderr
    kept = sorted(p.name for p in backup_dir.glob("finbot-*.dump"))
    assert len(kept) == 14
    assert kept[-1] > "finbot-20260101-000015.dump"  # 新文件在里面
    assert "finbot-20260101-000000.dump" not in kept
    for name, content in others.items():
        assert (backup_dir / name).read_text(encoding="utf-8") == content


def test_low_disk_space_refuses(env):
    e, backup_dir, log, _ = env
    r = run(e, BACKUP_MIN_FREE_MB="999999999")
    assert r.returncode != 0
    assert "低于阈值" in r.stdout + r.stderr
    assert not list(backup_dir.glob("*.dump"))
    assert not log.exists()  # 没有调用 docker


def test_password_never_printed(env):
    e, backup_dir, log, _ = env
    for kw in ({}, {"FAKE_RESTORE_RC": "1"}):
        r = run(e, **kw)
        assert PASSWORD not in r.stdout + r.stderr
    assert PASSWORD not in log.read_text(encoding="utf-8")
    for p in backup_dir.glob("*.txt"):
        assert PASSWORD not in p.read_text(encoding="utf-8")
