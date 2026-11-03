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
from datetime import UTC, date, datetime

from . import notify, signals
from .filings import FilingWatcher
from .escalation import Escalator
from .store import Store

logger = logging.getLogger("sentinel")

INTERVAL = 60.0
FAST_JOBS = {"escalation": 15.0, "filings": 30.0}  # the one-minute rule needs a finer tick than the other jobs
FAILURES_BEFORE_ALERT = 3
BASELINE_MAX_AGE = 20 * 3600      # rebuilt about once a day
MERGE_WINDOW = 5 * 60            # 3 symbols pushing within this window make a burst
MERGE_MIN = 3
SPLITS_MAX_AGE = 3600            # a split announced today must not wait for tomorrow's baseline


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
        """Signals -> push policy -> candidate alerts.  Separate from the fetching so it can be run on built data.

        The event row (anchor etc.) is committed here.  A candidate carries ``rollback`` (undo it, when a merge
        interval holds the message back) and ``after_send`` (undo it when the night rule deferred the message,
        because the owner has not seen that price)."""
        position = next((p for p in snap.get("positions") or [] if p.get("symbol") == symbol), None) if held else None
        total = snap.get("total_assets")
        stamp = now.timestamp()
        today = signals._et(now).date().isoformat()
        found = signals.detect(symbol, bars, now, baseline, prev_close, held=held, splits=splits)
        valid = [b for b in bars if signals._bar_ok(b)]
        price = float(valid[-1]["close"]) if valid and not signals.is_stale(valid[-1]["ts"], now) else None
        plan_found = []
        if held and price is not None:
            plan = next((p for p in snap.get("plans") or [] if p.get("symbol") == symbol), None)
            if plan:
                plan_found = signals.plan_crossings(symbol, self.store.get_price(symbol), price, plan)
        if price is not None:
            self.store.set_price(symbol, price)
        weight = None
        if position and total and price:
            weight = signals.position_weight(position, price, total) * 100
        out: list[dict] = []
        event_before = self.store.get_event(symbol, today)     # what the plan crossings may move

        def candidate(sig, text, *, escalate, **extra) -> dict:
            down = sig.direction == "down" and held and sig.kind not in ("split", "plan_target")
            base = {"symbol": symbol, "kind": sig.kind, "direction": sig.direction, "held": held, "text": text,
                    "escalate": escalate, "weight_pct": weight, "price_move": False, "trigger": "",
                    "event_date": None, "price": price,
                    "earnings_unacked": down and self.store.earnings_alert_unacked(symbol),
                    "after_send": lambda deferred, alert_id: None, "rollback": lambda: None}
            return base | extra

        for sig in found:
            if sig.kind != "split" or not held:
                continue
            key = f"split:{(splits or [{}])[0].get('date', '')}:{sig.detail}"
            if self.store.get_cooldown(symbol, key) is None:       # once per split date and ratio
                self.store.set_cooldown(symbol, key, stamp, 0.0)
                out.append(candidate(sig, signals.format_alert(sig, position, total), escalate=False))
        for sig in plan_found:
            key = f"plan:{sig.kind}:{sig.detail}"
            last = self.store.get_cooldown(symbol, key)
            if last is not None and signals._et(datetime.fromtimestamp(last[0], UTC)).date().isoformat() == today:
                continue                                        # once per level per New York date
            self.store.set_cooldown(symbol, key, stamp, 0.0)
            c = candidate(sig, signals.format_alert(sig, position, total),
                          escalate=sig.direction == "down" and sig.kind != "plan_target")
            if event_before and prev_close:
                fields = {"anchor_price": price, "anchor_r": price / prev_close - 1, "anchor_ts": stamp,
                          "low": price, "high": price}
                old = {k: event_before[k] for k in fields}
                self.store.update_event(symbol, today, **fields)
                c["rollback"] = lambda old=old: self.store.update_event(symbol, today, **old)
                c["after_send"] = lambda deferred, alert_id, old=old: (
                    self.store.update_event(symbol, today, **old) if deferred else None)
            out.append(c)

        primary = next((s for k in ("gap", "daily", "short") for s in found if s.kind == k), None)
        if price is not None and prev_close and not any(s.kind == "split" for s in found):   # a split pauses price signals
            push = self._price_push(symbol, held, now, today, price, prev_close, baseline or {}, primary, position,
                                    total, candidate)
            if push is not None:
                out.append(push)
        return out

    def _price_push(self, symbol, held, now, today, price, prev_close, baseline, primary, position, total,
                    candidate) -> dict | None:
        stamp = now.timestamp()
        sigma = baseline.get("daily_sigma")
        r = price / prev_close - 1
        event = self.store.get_event(symbol, today)
        prev_event = None
        if event is None:
            prev_event = self.store.latest_event_before(symbol, today)
            if prev_event:
                gap_days = (date.fromisoformat(today) - date.fromisoformat(prev_event["ny_date"])).days
                if gap_days > signals.CONTINUATION_MAX_DAYS:
                    prev_event = None
        decision = signals.decide_push(event, price, prev_close, now, held=held, entry=primary is not None,
                                       prev_event=prev_event, step=signals.step_for(sigma))
        if decision.action != "push":
            if event is not None:
                self.store.track_event(symbol, today, price, r, suppressed=True)
                if decision.open_checked and decision.action == "none":
                    self.store.update_event(symbol, today, open_checked=1)
                logger.info("%s %s: no push (%s %s)", symbol, today, decision.action, decision.reason or decision.trigger)
            return None
        fields_before = None
        if event is None:
            step = signals.step_for(sigma)
            earnings = self.store.recent_earnings(symbol, stamp - 24 * 3600)
            earnings_at = min(e["detected_at"] for e in earnings) if earnings else None
            text = signals.format_alert(primary, position, total, now=now, step=step, day_r=r, held=held,
                                        earnings_at=earnings_at, continuation=decision.continuation)
            self.store.open_event(symbol, today, first_ts=stamp, first_bucket=signals.bucket_of(now), price=price,
                                  r=r, step=step)
            kind, direction = primary.kind, primary.direction
            escalate = bool(held and direction == "down" and not decision.continuation)
            digest = None
        else:
            text = signals.format_update(symbol=symbol, price=price, prev_close=prev_close, event=event,
                                         decision=decision, now=now, sigma=sigma, position=position,
                                         total_assets=total, held=held)
            kind, direction = "update", "down" if r < 0 else "up"
            escalate = bool(held and decision.worse and r < 0)
            seen = event.get("low") if decision.dist < 0 else event.get("high")
            extreme = None if seen is None else (min(seen, price) if decision.dist < 0 else max(seen, price))
            digest = signals.format_digest_line(symbol=symbol, price=price, prev_close=prev_close, event=event,
                                                sigma=sigma, extreme=extreme)
            fields_before = {k: event[k] for k in ("anchor_price", "anchor_r", "anchor_ts", "last_push_ts", "pushes",
                                                   "low", "high", "open_checked")}
            self.store.update_event(symbol, today, anchor_price=price, anchor_r=r, anchor_ts=stamp, last_push_ts=stamp,
                                    pushes=event["pushes"] + 1, low=price, high=price,
                                    open_checked=1 if (decision.open_checked or event["open_checked"]) else 0)
        store = self.store

        def rollback() -> None:
            if fields_before is None:
                store.delete_event(symbol, today)
            else:
                store.update_event(symbol, today, **fields_before)

        def after_send(deferred: bool, alert_id) -> None:
            if not deferred:
                return
            if fields_before is not None:
                store.update_event(symbol, today, **fields_before)   # the owner has not seen this price
            if alert_id:
                store.update_event(symbol, today, pending_alert_id=alert_id)

        sig = primary or signals.Signal(symbol, "update", direction, r, price, prev_close)
        return candidate(sig, text, escalate=escalate, kind=kind, direction=direction, price_move=True,
                         trigger=decision.trigger, steps=decision.steps, event_date=today, digest_text=digest,
                         rollback=rollback, after_send=after_send)

    # --- delivery: merge a burst, then raise ----------------------------------------------------------
    def flush(self, candidates: list[dict], snap: dict, now: datetime) -> None:
        """Send one tick's candidates.  Plan crossings and splits go at once; price pushes go one by one, or as a
        single merged message when 3 or more symbols push within 5 minutes (then at most every 10 minutes)."""
        stamp = now.timestamp()
        moves = [c for c in candidates if c.get("price_move")]
        for c in candidates:
            if not c.get("price_move"):
                self._raise(snap, c)
        if not moves:
            return
        mode = self.store.get_kv("merge_mode")
        state = mode[0] if mode else {}
        active = bool(state.get("active"))
        if active and stamp - float(state.get("last_flush") or 0) < signals.MIN_GAP:
            for c in moves:
                if c.get("rollback"):
                    c["rollback"]()                                # anchors stay put; re-measured at the next flush
            logger.info("merge interval: %d price pushes held back", len(moves))
            return
        recent = self.store.recent_price_push_symbols(stamp - MERGE_WINDOW) | {c["symbol"] for c in moves}
        if len(moves) >= 2 and (active or len(recent) >= MERGE_MIN):
            self.store.set_kv("merge_mode", {"active": True, "last_flush": stamp})
            self._raise_merged(snap, moves)
            return
        if active:                                               # 0 or 1 candidates: the burst is over
            self.store.set_kv("merge_mode", {"active": False, "last_flush": stamp})
        for c in moves:
            self._raise(snap, c)

    def _raise(self, snap: dict, alert: dict) -> None:
        alert_id = self.escalator.raise_alert(snap, alert)
        alert["after_send"](self.escalator.deferred(alert_id), alert_id)

    def _raise_merged(self, snap: dict, members: list[dict]) -> None:
        symbols = [m["symbol"] for m in members]
        merged = {"symbol": "+".join(symbols)[:80], "symbols": symbols, "kind": "merged", "direction": "",
                  "held": any(m["held"] for m in members), "text": signals.format_merged(members),
                  "escalate": any(m["escalate"] for m in members), "price_move": True, "members": members,
                  "weight_pct": max(m.get("weight_pct") or 0 for m in members), "trigger": "T0",
                  "event_date": None, "earnings_unacked": False}
        alert_id = self.escalator.raise_alert(snap, merged)
        deferred = self.escalator.deferred(alert_id)
        for m in members:
            m["after_send"](deferred, None)

    def check_signals(self) -> None:
        now = datetime.now(UTC)
        if not signals.in_trading_session(now):
            return
        snap = self.config.get()
        held = [p["symbol"] for p in snap.get("positions") or [] if p.get("symbol") and p.get("shares")]
        queued = [s for s in snap.get("research_queue") or [] if s not in held]
        collected: list[dict] = []
        for symbol, is_held in [(s, True) for s in held] + [(s, False) for s in queued]:
            try:
                collected += self.evaluate_symbol(symbol, is_held, now, snap)
            except Exception as exc:  # one symbol failing must not stop the others
                logger.warning("signal check for %s failed: %s", symbol, type(exc).__name__)
        self.flush(collected, snap, now)

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
