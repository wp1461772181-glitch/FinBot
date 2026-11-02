"""FinBot sentinel: the small, independent last line of defence.

Stdlib only; never imports ``app``.  One thread per job, and a job that raises is logged and
retried on its next tick without touching the others.  Restarting a dead process is systemd's job.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable

from . import notify, signals
from .store import Store

logger = logging.getLogger("sentinel")

INTERVAL = 60.0
FAILURES_BEFORE_ALERT = 3


class Sentinel:
    def __init__(self, config: signals.SnapshotConfig | None = None, store: Store | None = None) -> None:
        self.config = config or signals.SnapshotConfig()
        self.store = store or Store()
        self.stop = threading.Event()
        self.health_failures = 0
        self.alerted = False
        self.worker: object | None = None  # the Popen we started, if still running

    # --- jobs (each is one tick) -------------------------------------------------
    def check_health(self) -> None:
        snap = self.config.get()
        if signals.probe_health(signals.api_base(snap)):
            if self.alerted:
                notify.notify(snap, "FinBot API 已恢复。")
            self.health_failures, self.alerted = 0, False
            return
        self.health_failures += 1
        if self.health_failures >= FAILURES_BEFORE_ALERT and not self.alerted:
            # Only mark alerted when the message actually left; otherwise try again next tick.
            self.alerted = notify.notify(snap, f"FinBot API 连续 {self.health_failures} 次探活失败（/health）。")

    def check_forecast_jobs(self) -> None:
        snap = self.config.get()
        if self.worker is not None and self.worker.poll() is None:
            return
        self.worker = None
        if signals.pending_forecast_jobs(signals.api_base(snap)) <= 0:
            return
        if signals.worker_running():
            return
        available = signals.mem_available_mb()
        if available < signals.MIN_AVAILABLE_MB:
            logger.warning("forecast jobs pending but MemAvailable=%.0f MB < %d MB; not starting a worker",
                           available, signals.MIN_AVAILABLE_MB)
            return
        self.worker = signals.spawn_worker()

    def send_heartbeat(self) -> None:
        url = os.environ.get("SENTINEL_HEARTBEAT_URL", "").strip()
        if url:
            signals.heartbeat(url)

    def post_event(self, event_type: str, payload: dict) -> None:
        """Deliver now, or queue for resend when the API cannot be reached."""
        try:
            signals.post_event(signals.api_base(self.config.get()), event_type, payload)
        except Exception:
            self.store.enqueue(event_type, payload)

    def resend_events(self) -> None:
        base = signals.api_base(self.config.get())
        for event in self.store.pending():
            try:
                signals.post_event(base, event["type"], event["payload"])
            except Exception:
                self.store.bump(event["id"])
                return  # API still down: keep order, try next tick
            self.store.delete(event["id"])

    # --- threads -----------------------------------------------------------------
    def jobs(self) -> dict[str, Callable[[], None]]:
        return {
            "health": self.check_health,
            "forecast": self.check_forecast_jobs,
            "heartbeat": self.send_heartbeat,
            "events": self.resend_events,
        }

    def run_loop(self, name: str, fn: Callable[[], None], interval: float) -> None:
        while not self.stop.is_set():
            try:
                fn()
            except Exception:
                logger.exception("sentinel job %s failed; will retry next tick", name)
            self.stop.wait(interval)

    def start(self, interval: float = INTERVAL) -> list[threading.Thread]:
        threads = [threading.Thread(target=self.run_loop, args=(name, fn, interval), name=f"sentinel-{name}", daemon=True)
                   for name, fn in self.jobs().items()]
        for thread in threads:
            thread.start()
        return threads


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    sentinel = Sentinel()
    sentinel.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        sentinel.stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
