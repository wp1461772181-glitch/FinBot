"""Probes and actions the sentinel loops use (stdlib only; never imports ``app``)."""

from __future__ import annotations

import json
import logging
import os
import resource
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

logger = logging.getLogger("sentinel.signals")

MIN_AVAILABLE_MB = 200
DEFAULT_WORKER_MEM_MB = 1536
DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "data" / "sentinel-config.json"

# Local API calls must not go through the egress proxy that outbound HTTPS needs.
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class SnapshotConfig:
    """data/sentinel-config.json, reloaded when its mtime changes; keeps the last good copy."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path or os.environ.get("SENTINEL_CONFIG_PATH") or DEFAULT_CONFIG)
        self._mtime: float | None = None
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self) -> dict:
        with self._lock:
            try:
                mtime = self.path.stat().st_mtime_ns
                if mtime != self._mtime:
                    self._data = json.loads(self.path.read_text(encoding="utf-8"))
                    self._mtime = mtime
            except (OSError, ValueError):
                pass  # missing or half-written: keep the last good snapshot
            return self._data


def api_base(snapshot: dict) -> str:
    return (os.environ.get("SENTINEL_API_BASE") or snapshot.get("api_base") or "http://127.0.0.1:8000").rstrip("/")


def _token_headers() -> dict:
    return {"X-Sentinel-Token": os.environ.get("SENTINEL_TOKEN", "")}


def probe_health(base: str, timeout: float = 10) -> bool:
    try:
        with _local.open(f"{base}/health", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def api_request(base: str, method: str, path: str, body: dict | None = None, timeout: float = 15) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", **_token_headers()}
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with _local.open(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b"{}")


def post_event(base: str, event_type: str, payload: dict) -> None:
    api_request(base, "POST", "/agent-chat/internal/sentinel/events", {"type": event_type, "payload": payload})


def pending_forecast_jobs(base: str) -> int:
    return int(api_request(base, "GET", "/agent-chat/internal/sentinel/pending-forecast-jobs").get("pending", 0))


def mem_available_mb(meminfo: str = "/proc/meminfo") -> float:
    with open(meminfo, encoding="ascii") as handle:
        for line in handle:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    return 0.0


def worker_running(proc_dir: str = "/proc") -> bool:
    """Any process (ours or started by hand) running app.forecast_worker."""
    me = os.getpid()
    for entry in os.listdir(proc_dir):
        if not entry.isdigit() or int(entry) == me:
            continue
        try:
            cmd = Path(proc_dir, entry, "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if b"app.forecast_worker" in cmd:
            return True
    return False


_CAPPED_EXEC = (
    "import os, resource, sys; limit = int(sys.argv[1]); "
    "resource.setrlimit(resource.RLIMIT_AS, (limit, limit)); "
    "os.execv(sys.executable, [sys.executable, *sys.argv[2:]])"
)


def spawn_worker(cwd: Path | str | None = None) -> subprocess.Popen:
    """`python -m app.forecast_worker --once`, capped by RLIMIT_AS (SENTINEL_WORKER_MEM_MB, default 1536).

    RLIMIT_AS is plain stdlib and needs no cgroup rights; an over-limit worker gets MemoryError and
    exits instead of taking the VM (and the API) down.  The limit is applied by a tiny bootstrap that
    execs the worker, not by preexec_fn, which is unsafe in a multithreaded process like this one.
    """
    limit = int(os.environ.get("SENTINEL_WORKER_MEM_MB", DEFAULT_WORKER_MEM_MB)) * 1024 * 1024
    env = {**os.environ, "MALLOC_ARENA_MAX": "2", "DB_POOL_SIZE": "1", "DB_MAX_OVERFLOW": "0"}
    return subprocess.Popen(
        [sys.executable, "-c", _CAPPED_EXEC, str(limit), "-m", "app.forecast_worker", "--once"],
        cwd=str(cwd) if cwd else str(Path(__file__).resolve().parent.parent),
        env=env,
    )


def heartbeat(url: str, timeout: float = 10) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False
