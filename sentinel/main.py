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
from datetime import UTC, datetime

from . import notify, signals
from .filings import FilingWatcher
from .escalation import Escalator
from .store import Store

logger = logging.getLogger("sentinel")

INTERVAL = 60.0
FAST_JOBS = {"escalation": 15.0, "filings": 30.0}  # the one-minute rule needs a finer tick than the other jobs
FAILURES_BEFORE_ALERT = 3
BASELINE_MAX_AGE = 20 * 3600      # rebuilt about once a day
SPLITS_MAX_AGE = 3600             # a split announced today must not wait for tomorrow's baseline


class Sentinel:
    def __init__(self, config: signals.SnapshotConfig | None = None, store: Store | None = None) -> None:
        self.config = config or signals.SnapshotConfig()
        self.store = store or Store()
        self.stop = threading.Event()
        self.health_failures = 0
        self.alerted = False
        self.worker: object | None = None  # the Popen we started, if still running
        self.cooldown = signals.Cooldown(self.store)
        self.escalator = Escalator(self.store, notify.Channels())
        self.filings = FilingWatcher(self.store, self.config.get, post_event=self.post_event_now,
                                     raise_alert=self.escalator.raise_alert)

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

    # --- intraday moves (Task 11) ----------------------------------------------------------------
    def baseline_for(self, symbol: str, now: datetime) -> dict:
        """``{"baseline": {...}, "splits": [...]}``; the 20-day sigma baseline daily, the split list hourly."""
        stamp = now.timestamp()
        row = self.store.get_baseline(symbol)
        data, baseline_at, splits_at = (row["data"], row["baseline_at"], row["splits_at"]) if row else ({}, 0.0, 0.0)
        if not row or stamp - baseline_at > BASELINE_MAX_AGE:
            chart = signals.fetch_chart(symbol, "5m", "60d", events=True)
            daily = signals.fetch_chart(symbol, "1d", "5d", prepost=False, events=True)
            data = {"baseline": signals.compute_baseline(chart["bars"], now), "splits": chart["splits"],
                    "prev_close": signals.prev_close_from_daily(daily["bars"], now)}
            baseline_at = splits_at = stamp
        elif stamp - splits_at > SPLITS_MAX_AGE:
            daily = signals.fetch_chart(symbol, "1d", "5d", prepost=False, events=True)
            data["splits"] = daily["splits"]
            data["prev_close"] = signals.prev_close_from_daily(daily["bars"], now)
            splits_at = stamp
        else:
            return data
        self.store.set_baseline(symbol, data, baseline_at, splits_at)
        return data

    def evaluate_symbol(self, symbol: str, held: bool, now: datetime, snap: dict) -> list[dict]:
        """The alerts (text plus how to escalate them) for one symbol at this minute."""
        base = self.baseline_for(symbol, now)
        chart = signals.fetch_chart(symbol, "1m", "1d")
        prev_close = base.get("prev_close")
        if prev_close is None:
            prev_close = chart["prev_close"]  # e.g. under two days of daily history: the meta value
        return self.alerts_from(symbol, held, now, snap, chart["bars"], prev_close,
                                base.get("baseline"), base.get("splits"))

    def alerts_from(self, symbol: str, held: bool, now: datetime, snap: dict, bars: list[dict], prev_close,
                    baseline: dict | None, splits) -> list[dict]:
        """Signals -> cooldown -> alert dicts.  Separate from the fetching so it can be run on built data."""
        position = next((p for p in snap.get("positions") or [] if p.get("symbol") == symbol), None) if held else None
        total = snap.get("total_assets")
        found = signals.detect(symbol, bars, now, baseline, prev_close, held=held, splits=splits)
        valid = [b for b in bars if signals._bar_ok(b)]
        price = float(valid[-1]["close"]) if valid and not signals.is_stale(valid[-1]["ts"], now) else None
        if held and price is not None:
            plan = next((p for p in snap.get("plans") or [] if p.get("symbol") == symbol), None)
            if plan:
                found += signals.plan_crossings(symbol, self.store.get_price(symbol), price, plan)
        if price is not None:
            self.store.set_price(symbol, price)
        alerts = []
        for sig in found:
            if sig.kind == "split":
                if not held:
                    continue
                key, mult = "split", 0.0
            else:
                key, mult = sig.key, sig.sigma_mult
            if not self.cooldown.allow(symbol, key, mult, now.timestamp()):
                continue
            weight = None
            if position and total and price:
                weight = signals.position_weight(position, price, total) * 100
            down = sig.direction == "down" and held and sig.kind not in ("split", "plan_target")
            alerts.append({
                "symbol": symbol, "kind": sig.kind, "direction": sig.direction, "held": held,
                "text": signals.format_alert(sig, position, total),
                "escalate": down,                              # only a fall on a holding escalates (Task 12)
                "weight_pct": weight,
                "earnings_unacked": down and self.store.earnings_alert_unacked(symbol),
            })
        return alerts

    def check_signals(self) -> None:
        now = datetime.now(UTC)
        if not signals.in_trading_session(now):
            return
        snap = self.config.get()
        held = [p["symbol"] for p in snap.get("positions") or [] if p.get("symbol") and p.get("shares")]
        queued = [s for s in snap.get("research_queue") or [] if s not in held]
        for symbol, is_held in [(s, True) for s in held] + [(s, False) for s in queued]:
            try:
                for alert in self.evaluate_symbol(symbol, is_held, now, snap):
                    self.emit_alert(snap, alert)
            except Exception as exc:  # one symbol failing must not stop the others
                logger.warning("signal check for %s failed: %s", symbol, type(exc).__name__)

    def emit_alert(self, snap: dict, alert: dict) -> None:
        self.escalator.raise_alert(snap, alert)

    def check_escalation(self) -> None:
        self.escalator.tick(self.config.get())

    # --- earnings filings (Task 9) ---------------------------------------------------------------
    def post_event_now(self, event_type: str, payload: dict) -> None:
        signals.post_event(signals.api_base(self.config.get()), event_type, payload)

    def check_filings(self) -> None:
        now = time.time()
        self.filings.poll(now)
        self.filings.fallbacks(now)

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
            if event["type"] == "earnings_detected":
                self.filings.mark_delivered(event["payload"]["accession"], time.time())

    # --- threads -----------------------------------------------------------------
    def jobs(self) -> dict[str, Callable[[], None]]:
        return {
            "health": self.check_health,
            "forecast": self.check_forecast_jobs,
            "signals": self.check_signals,
            "escalation": self.check_escalation,
            "filings": self.check_filings,
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
        threads = [threading.Thread(target=self.run_loop, args=(name, fn, min(interval, FAST_JOBS.get(name, interval))), name=f"sentinel-{name}", daemon=True)
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
