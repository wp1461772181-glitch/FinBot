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
from datetime import UTC, date, datetime, timedelta

from . import notify, signals, tiers
from . import rules as owner_rules
from .filings import FilingWatcher
from .escalation import Escalator
from .store import Store

logger = logging.getLogger("sentinel")

INTERVAL = 60.0
FAST_JOBS = {"escalation": 15.0, "filings": 30.0, "events": 30.0}  # the one-minute rule needs a finer tick than the other jobs
FAILURES_BEFORE_ALERT = 3
BASELINE_MAX_AGE = 20 * 3600      # rebuilt about once a day
MERGE_WINDOW = 5 * 60            # 3 symbols pushing within this window make a burst
MERGE_MIN = 3
ALERT_EVENT_MAX_AGE = 24 * 3600   # a wake-up for an alert older than this is useless
DAILY_RETRY = 10 * 60             # a failed daily-history fetch (owner rules) is tried again after this long
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
        self._market: dict | None = None   # SPY's move at this poll ({"r", "sigma"}); the tiers policy reads it
        self.policy: str | None = None     # overrides SENTINEL_ALERT_POLICY (the replay harness sets it)
        self.sensitivity: str | None = None
        self.short_moves: bool | None = None
        self.escalator = Escalator(self.store, notify.Channels())
        self._daily_failed: dict[str, float] = {}
        self._poll: dict[str, dict] = {}   # this poll's fresh price of each symbol ({"price", "prev_close"}); the portfolio preset reads it
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

    # --- the push policy: ``tiers`` (design section 7.3, stage 5a; the default) or ``anchor`` (design-alert-policy.md) ----
    # Unchanged on purpose: the night rule still defers a small-weight holding's alerts to the 08:00 Beijing digest
    # (only a fall on a holding of at least 10% of total assets rings at night).
    def _policy(self) -> str:
        return (self.policy or os.environ.get("SENTINEL_ALERT_POLICY") or "tiers").strip().lower()

    # Settings the owner can change (5b-2): the snapshot's ``alert_settings`` first, then its old flat keys, then the env of
    # this process.  ``self.sensitivity`` / ``self.short_moves`` are the replay harness's explicit override.
    def _sensitivity(self, snap: dict) -> str:
        settings = snap.get("alert_settings")
        return (self.sensitivity or (settings.get("sensitivity") if isinstance(settings, dict) else None)
                or snap.get("alert_sensitivity") or os.environ.get("SENTINEL_SENSITIVITY") or "standard")

    def _short_moves_on(self, snap: dict) -> bool:
        if self.short_moves is not None:
            return self.short_moves
        settings = snap.get("alert_settings")
        if isinstance(settings, dict) and isinstance(settings.get("short_moves"), bool):
            return settings["short_moves"]
        if "short_moves" in snap:
            return bool(snap["short_moves"])
        env = (os.environ.get("SENTINEL_SHORT_MOVES") or "").strip().lower()
        return env in ("on", "1", "true", "yes")

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

    def evaluate_symbol(self, symbol: str, held: bool, now: datetime, snap: dict, rules_only: bool = False) -> list[dict]:
        """The alerts (text plus how to escalate them) for one symbol at this minute.  ``rules_only``: the symbol is
        only here because an owner rule names it, so the default alerts do not apply to it."""
        base = self.baseline_for(symbol, now)
        chart = signals.fetch_chart(symbol, "1m", "1d")
        prev_close = base.get("prev_close")
        if prev_close is None:
            prev_close = chart["prev_close"]  # e.g. under two days of daily history: the meta value
        today = signals._et(now).date().isoformat()
        daily = None
        mine = [r for r in self._owner_rules(snap, today) if owner_rules.symbol_of(r) == symbol]
        wanted = mine + self._presets_for(symbol, held, rules_only, snap, today, mine)
        if any(owner_rules.needs_daily(r) for r in wanted):
            daily = self.rules_daily(symbol, now, year=any(owner_rules.needs_year(r) for r in wanted))
        return self.alerts_from(symbol, held, now, snap, chart["bars"], prev_close,
                                base.get("baseline"), base.get("splits"), daily=daily, rules_only=rules_only)

    def rules_daily(self, symbol: str, now: datetime, year: bool = False) -> dict | None:
        """``{"closes", "avg_volume"}`` from the symbol's daily bars (3 months; a year for the 52-week and down-days rules),
        fetched once per New York date and only for a symbol that has a rule or preset needing it.  None when it cannot be
        had; the rule then measures None.  A cached year serves a three-month need too."""
        today = signals._et(now).date()
        cached = self.store.get_kv(f"rules_daily:{symbol}")
        if cached and cached[0].get("asof") == today.isoformat() and (cached[0].get("year") or not year):
            return cached[0]
        if time.time() - self._daily_failed.get(symbol, 0.0) < DAILY_RETRY:
            return None
        try:
            bars = signals.fetch_chart(symbol, "1d", "1y" if year else "3mo", prepost=False)["bars"]
        except Exception as exc:
            self._daily_failed[symbol] = time.time()
            logger.warning("daily history for %s unavailable: %s", symbol, type(exc).__name__)
            return None
        data = owner_rules.daily_summary(bars, today) | {"asof": today.isoformat(), "year": year}
        self.store.set_kv(f"rules_daily:{symbol}", data)
        return data

    def alerts_from(self, symbol: str, held: bool, now: datetime, snap: dict, bars: list[dict], prev_close,
                    baseline: dict | None, splits, *, daily: dict | None = None, rules_only: bool = False) -> list[dict]:
        """The default alerts of the push policy plus the owner's own rules for this symbol.  The rules are independent of
        the default policy (they run under ``tiers`` and ``anchor`` alike); the only thing they change in the defaults is
        that an owner ``day_change`` rule replaces the sigma-tier day-move pushes of its symbol (tiers policy)."""
        today = signals._et(now).date().isoformat()
        mine = [r for r in self._owner_rules(snap, today) if owner_rules.symbol_of(r) == symbol]
        day_rule = set().union(*(owner_rules.covered_directions(r) for r in mine if r["metric"] == "day_change"))
        self._note_poll(symbol, now, bars, prev_close, splits)
        out = [] if rules_only else self._default_alerts(symbol, held, now, snap, bars, prev_close, baseline, splits,
                                                         day_rule=day_rule)
        checked = mine + self._presets_for(symbol, held, rules_only, snap, today, mine)
        if checked:
            out += self._rule_alerts(symbol, held, now, today, snap, bars, prev_close, splits, daily, checked, baseline)
        return out

    # --- the system's preset rules (5b-2) -------------------------------------------------------------------------------
    def _presets_for(self, symbol: str, held: bool, rules_only: bool, snap: dict, today: str, mine: list[dict]) -> list[dict]:
        """The snapshot's presets as concrete rules for this symbol: enabled, well-formed, not expired, within their scope
        (``holdings``: held; ``watched``: held or in the research queue, not a symbol only an owner rule names) and not
        yielding: where the owner has an enabled rule of the same metric on the symbol, the preset of that metric stays out.
        The portfolio preset is not here (``portfolio_alerts``).  Presets never touch the stop price or the filings."""
        out = []
        for preset in snap.get("presets") or []:
            if not owner_rules.preset_valid(preset) or preset.get("enabled") is False or owner_rules.expired(preset, today):
                continue
            scope = preset["scope"]
            if scope == "portfolio" or (scope == "holdings" and not held) or (scope == "watched" and rules_only):
                continue
            if any(r["metric"] == preset["metric"] for r in mine):
                continue
            out.append(owner_rules.concrete(preset, symbol))
        return out

    def new_poll(self) -> None:
        """Forget the previous poll's prices (the portfolio preset must only see prices of this one)."""
        self._poll = {}

    def _note_poll(self, symbol: str, now: datetime, bars: list[dict], prev_close, splits) -> None:
        """Remember this poll's fresh price of ``symbol``; a stale price, a recent split or no previous close leaves none."""
        self._poll.pop(symbol, None)
        valid = [b for b in bars if signals._bar_ok(b)]
        if (valid and not signals.is_stale(valid[-1]["ts"], now) and signals._recent_split(splits, now) is None
                and isinstance(prev_close, (int, float)) and prev_close > 0):
            self._poll[symbol] = {"price": float(valid[-1]["close"]), "prev_close": float(prev_close)}

    def portfolio_alerts(self, now: datetime, snap: dict) -> list[dict]:
        """The portfolio-scope presets, once per poll after every symbol was looked at.  They measure None (and say nothing)
        unless every holding has a fresh price from this poll."""
        today = signals._et(now).date().isoformat()
        presets = [p for p in snap.get("presets") or [] if owner_rules.preset_valid(p) and p["scope"] == "portfolio"
                   and p.get("enabled") is not False and not owner_rules.expired(p, today)]
        if not presets:
            return []
        holdings = []
        for position in snap.get("positions") or []:
            if not position.get("symbol") or not position.get("shares"):
                continue
            seen = self._poll.get(position["symbol"])
            if seen is None:
                return []
            holdings.append({"symbol": position["symbol"], "shares": position["shares"], "price": seen["price"],
                             "prev_close": seen["prev_close"], "market_value": position.get("market_value")})
        ctx = {"holdings": holdings, "total_assets": snap.get("total_assets")}
        out = []
        for preset in presets:
            try:
                hit = self._fire(owner_rules.concrete(preset, "*"), ctx, now, today,
                                 lambda r, i, v: signals.format_preset(r, i, v, ctx))
                if hit is not None:
                    out.append(self._preset_alert(hit, True, None, None, None, ctx))
            except Exception as exc:
                logger.warning("preset %s failed: %s", preset.get("preset_key"), type(exc).__name__)
        return out

    def _default_alerts(self, symbol: str, held: bool, now: datetime, snap: dict, bars: list[dict], prev_close,
                        baseline: dict | None, splits, *, day_rule: set | frozenset = frozenset()) -> list[dict]:
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
        tiers_on = self._policy() == "tiers"
        plan_found = []
        if held and price is not None and not tiers_on:
            plan = next((p for p in snap.get("plans") or [] if p.get("symbol") == symbol), None)
            if plan:
                plan_found = signals.plan_crossings(symbol, self.store.get_price(symbol), price, plan)
        last_seen = self.store.get_price(symbol)      # before set_price below: the level locks are seeded from it
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
                    "event_date": None, "price": price, "prev_close": prev_close,
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

        if tiers_on:
            if price is not None and prev_close and not any(s.kind == "split" for s in found):
                out += self._tiers_alerts(symbol, held, now, today, snap, price, prev_close, baseline or {}, valid,
                                          position, total, candidate, last_seen, day_rule=day_rule)
            return out

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

    # --- the owner's own rules (5b-1) -------------------------------------------------------------------------------
    def _rule_done_on(self, rule: dict) -> str | None:
        """For a ``once`` rule whose strongest level has fired: the New York date it did, else None."""
        if (rule.get("repeat") or "daily") != "once":
            return None
        top = owner_rules.severity_order(rule)[-1]
        ts = self.store.rule_fired_at(str(rule["id"]), "*", owner_rules.level_key(rule, top))
        return None if ts is None else signals._et(datetime.fromtimestamp(ts, UTC)).date().isoformat()

    def _owner_rules(self, snap: dict, today: str) -> list[dict]:
        """The snapshot's rules that count today: well-formed, enabled, not expired, and not a ``once`` rule that finished
        on an earlier day (on the day it finishes it still counts, so its symbol's default alerts do not pile on top)."""
        out = []
        for rule in snap.get("rules") or []:
            if not owner_rules.valid(rule) or rule.get("enabled") is False or owner_rules.expired(rule, today):
                continue
            done = self._rule_done_on(rule)
            if done is not None and done < today:
                continue
            out.append(rule)
        return out

    def _rule_ctx(self, symbol: str, now: datetime, snap: dict, bars: list[dict], price: float, prev_close,
                  daily: dict | None, baseline: dict | None = None) -> dict:
        """Every input a rule metric can use; what is not known stays None and its metrics measure None."""
        position = next((p for p in snap.get("positions") or [] if p.get("symbol") == symbol and p.get("shares")), None)
        local = signals._et(now)
        start = local.replace(hour=9, minute=30, second=0, microsecond=0)
        regular = [b for b in bars if signals._bar_ok(b) and start <= signals._et(b["ts"]) < start.replace(hour=16, minute=0)]
        in_regular = start <= local < start.replace(hour=16, minute=0)
        opened = None
        if in_regular and regular:
            first = min(regular, key=lambda b: b["ts"])
            opened = first.get("open") if isinstance(first.get("open"), (int, float)) and first["open"] > 0 else first["close"]
        position = position or {}
        minutes = (local - start).total_seconds() / 60 if in_regular else None
        return {"price": price, "prev_close": prev_close, "open": opened, "avg_cost": position.get("avg_cost"),
                "closes": (daily or {}).get("closes"), "avg_volume": (daily or {}).get("avg_volume"),
                "volume_today": sum(float(b.get("volume") or 0) for b in regular) if in_regular and regular else None,
                "session_minutes": minutes,
                "expected_volume": owner_rules.expected_volume((baseline or {}).get("avg_vol5"), minutes) if in_regular else None,
                "shares": position.get("shares"), "market_value": position.get("market_value"),
                "total_assets": snap.get("total_assets")}

    def _rule_alerts(self, symbol, held, now, today, snap, bars, prev_close, splits, daily, mine, baseline=None) -> list[dict]:
        """Check each owner rule of this symbol.  A level is said once per New York date (``daily``) or once ever
        (``once``); reaching a stronger level is said even if a milder one was said before, and saying a level also
        settles the milder ones.  Rule pushes are never merged into a group message and never held by MIN_GAP."""
        valid = [b for b in bars if signals._bar_ok(b)]
        if not valid or signals.is_stale(valid[-1]["ts"], now) or signals._recent_split(splits, now) is not None:
            return []                                    # no fresh price, or a split: prices before and after do not compare
        price = float(valid[-1]["close"])
        ctx = self._rule_ctx(symbol, now, snap, bars, price, prev_close, daily, baseline)
        weight = None
        if ctx["shares"] and snap.get("total_assets"):
            weight = signals.position_weight({"shares": ctx["shares"], "market_value": ctx["market_value"]}, price,
                                             snap["total_assets"]) * 100
        out = []
        for rule in mine:
            try:
                is_preset = rule.get("source") == "preset"
                hit = self._fire(rule, ctx, now, today, lambda r, i, v: (signals.format_preset if is_preset else signals.format_rule)(r, i, v, ctx))
                if hit is None:
                    continue
                out.append(self._preset_alert(hit, held, weight, price, prev_close, ctx) if is_preset
                           else self._owner_alert(hit, symbol, held, weight, price, prev_close))
            except Exception as exc:                     # one bad rule must not stop the others, nor the default alerts
                logger.warning("owner rule %s for %s failed: %s", rule.get("id"), symbol, type(exc).__name__)
        return out

    def _fire(self, rule: dict, ctx: dict, now: datetime, today: str, render) -> dict | None:
        """Measure one rule (an owner's or a concrete preset) and, if a level is to be said now, commit its state and return
        ``{"rule", "index", "value", "text"}``; else None.  A state-like metric fires on the edge: once while its condition
        stays true, again only after it was seen false."""
        if self._rule_done_on(rule) is not None:
            return None
        value = owner_rules.measure(rule, ctx)
        rule_id = str(rule["id"])
        hit = owner_rules.reached(rule, value)
        edge = rule["metric"] in owner_rules.STATE_METRICS
        if edge and value is not None:
            # re-arm every level whose condition is seen false at this poll (no measurement: no change)
            for i in owner_rules.rearm_levels(rule, ctx, hit):
                self.store.set_rule_armed(rule_id, owner_rules.level_key(rule, i), True)
        index = hit[-1] if hit else None
        if index is None:
            return None
        scope = "*" if (rule.get("repeat") or "daily") == "once" else today
        if self.store.rule_fired_at(rule_id, scope, owner_rules.level_key(rule, index)) is not None:
            return None
        if edge and not self.store.rule_armed(rule_id, owner_rules.level_key(rule, index)):
            return None                                   # still the same stretch of the condition being true
        text = render(rule, index, value)
        order = owner_rules.severity_order(rule)
        for i in order[:order.index(index) + 1]:
            self.store.rule_mark(rule_id, scope, owner_rules.level_key(rule, i), now.timestamp())
            if edge:
                self.store.set_rule_armed(rule_id, owner_rules.level_key(rule, i), False)
        return {"rule": rule, "index": index, "value": value, "text": text}

    @staticmethod
    def _candidate(hit: dict, symbol: str, held: bool, weight, price, prev_close, *, kind: str, rule_id: str) -> dict:
        rule, value = hit["rule"], hit["value"]
        level = rule["levels"][hit["index"]]["level"]
        way = {"up": "up", "above": "up", "down": "down", "below": "down"}.get(rule["direction"]) or (
            "up" if (value or 0) > 0 else "down")
        return {"symbol": symbol, "kind": kind, "direction": way, "held": held, "text": hit["text"],
                "escalate": level == "urgent", "weight_pct": weight, "price_move": False, "trigger": "",
                "event_date": None, "price": price, "prev_close": prev_close, "earnings_unacked": False,
                "after_send": lambda deferred, alert_id: None, "rollback": lambda: None,
                "tier": 2 if level == "urgent" else 1, "rule_id": rule_id, "digest_text": hit["text"].splitlines()[0]}

    def _owner_alert(self, hit: dict, symbol, held, weight, price, prev_close) -> dict:
        return self._candidate(hit, symbol, held, weight, price, prev_close, kind="rule",
                               rule_id=str(hit["rule"]["id"])) | {"owner_rule": True}

    def _preset_alert(self, hit: dict, held, weight, price, prev_close, ctx) -> dict:
        rule = hit["rule"]
        return self._candidate(hit, rule["symbol"], held, weight, price, prev_close, kind="preset",
                               rule_id=str(rule.get("preset_id") or rule["id"])) | {"preset_key": rule["preset_key"]}

    # --- the tiers policy ---------------------------------------------------------------------------------------------
    _ROW = {"max_tier": 0, "extreme_r": 0.0, "reversal_said": 0, "short_said": 0, "last_push_ts": None,
            "record_alert_id": None, "record_mult": 0.0}

    def _tiers_alerts(self, symbol, held, now, today, snap, price, prev_close, baseline, valid, position, total,
                      candidate, last_seen=None, day_rule=frozenset()) -> list[dict]:
        """Section 7.3: measure the move against the stock's own daily sigma, tier it, say each tier once per direction
        per New York date, lock price levels.  State is committed here; a candidate carries ``rollback`` for the
        merge interval."""
        stamp = now.timestamp()
        sigma = baseline.get("daily_sigma")
        sens = self._sensitivity(snap)
        low, high = tiers.thresholds(sens)
        market = self._market if symbol != "SPY" else None
        market_r = market.get("r") if market else None
        shares = position.get("shares") if position else None
        m = tiers.measure(price, prev_close, sigma, market_r, shares, total)
        r, direction = m["r"], m["direction"]
        tier, rule = tiers.tier_rule(m, sens, held)
        store = self.store
        states = store.get_tier_states(symbol, today)
        row_of = lambda d: states.get(d) or dict(self._ROW)       # noqa: E731
        if direction and abs(r) > abs(row_of(direction)["extreme_r"] or 0):
            store.set_tier_state(symbol, today, direction, extreme_r=r)
            states[direction] = dict(row_of(direction), extreme_r=r)
        out: list[dict] = []
        common = {"sigma_mult": m["sigma_mult"], "r": r, "impact_pct": m["impact_pct"], "market_r": market_r,
                  "market_sigma": market.get("sigma") if market else None}

        def text_of(**kw) -> str:
            return signals.format_tiered(symbol=symbol, now=now, price=price, prev_close=prev_close,
                                         sigma_mult=m["sigma_mult"], low=low, high=high, position=position,
                                         total_assets=total, impact_pct=m["impact_pct"], market_r=market_r, **kw)

        # price levels: held symbols only; a stop is major, add/target worth knowing.  Not evaluated for 2 days after a
        # split (alerts_from skips every price signal then: prices before and after are not comparable).
        plan = next((p for p in snap.get("plans") or [] if p.get("symbol") == symbol), None) if held else None
        for field, kind in (("add_price", "plan_add"), ("stop_price", "plan_stop"), ("target_price", "plan_target")):
            level = (plan or {}).get(field)
            if level is None:
                continue
            old = store.get_level(symbol, kind, float(level))
            fire, count, new = tiers.level_state(old, kind, float(level), price, sigma, today,
                                                    ref=last_seen if last_seen else prev_close)
            if new != old:
                store.set_level(symbol, kind, float(level), new)
            if not fire:
                continue
            lt = 2 if kind == "plan_stop" else 1
            sig = signals.Signal(symbol, kind, "up" if kind == "plan_target" else "down", r, price, float(level),
                                 detail=str(level))
            out.append(candidate(sig, text_of(tier=lt, why="level", kind=kind, level=float(level), count=count),
                                 escalate=bool(held and kind == "plan_stop"), tier=lt, why="level", **common))

        last_push = max((st["last_push_ts"] for st in states.values() if st.get("last_push_ts") is not None),
                        default=None)
        dec = tiers.decide(states, tier, direction, r, stamp, last_push)
        if day_rule:
            # The owner's own day_change rule replaces the sigma-tier day-move pushes of the direction(s) it covers (levels and
            # the 5-minute rule are untouched; the other direction keeps its defaults).  A covered move is still written as a
            # digest line, so nothing is silently lost.
            if direction in day_rule and tier >= 1:
                self._record_move(symbol, today, stamp, direction, r, m["sigma_mult"], row_of(direction))
            if dec.action != "none" and dec.direction in day_rule:
                dec = tiers.Decision("none")
        if dec.action == "hold":
            logger.info("%s %s: tier %s push held (%s)", symbol, today, dec.tier, dec.reason)
            return out
        if dec.action == "push":
            out.append(self._tier_push(symbol, held, today, stamp, dec, states, tier, rule, r, text_of, common, candidate,
                                       price, prev_close))
            return out
        if self._short_moves_on(snap) and held:
            short = self._short_push(symbol, today, stamp, now, states, valid, price, sigma, baseline, text_of, common,
                                     last_push, candidate, prev_close)
            if short is not None:
                out.append(short)
                return out
        if tier == 0 and rule == "record" and direction and not row_of(direction)["max_tier"]:
            self._record_move(symbol, today, stamp, direction, r, m["sigma_mult"], row_of(direction))
        return out

    def _tier_push(self, symbol, held, today, stamp, dec, states, tier, rule, r, text_of, common, candidate, price,
                   prev_close) -> dict:
        store = self.store
        target = dec.direction
        row = states.get(target) or dict(self._ROW)
        old = {k: row[k] for k in ("max_tier", "last_push_ts", "reversal_said")}
        if dec.why == "reversal":
            fields = {"reversal_said": 1, "last_push_ts": stamp}
            move_dir = "up" if target == "down" else "down"
            text = text_of(tier=1, why="reversal", kind="reversal", extreme_r=row["extreme_r"])
            kind, escalate, pushed_tier = "reversal", False, 1      # its own kind: it must not supersede a ringing alert
        else:
            fields = {"max_tier": max(int(row["max_tier"] or 0), dec.tier), "last_push_ts": stamp}
            move_dir = target
            text = text_of(tier=dec.tier, why=dec.why, kind="move", rule=rule)
            # today's convention: only a fall on a holding rings (a stop crossing too); a major rise is pushed, not escalated
            kind, escalate, pushed_tier = ("daily" if dec.why == "first" else "update"), bool(
                held and dec.tier == 2 and move_dir == "down"), dec.tier
        store.set_tier_state(symbol, today, target, **fields)
        if row.get("record_alert_id"):                              # it is now said on its own: the digest line goes
            store.update_alert(row["record_alert_id"], digested_at=stamp)
            store.set_tier_state(symbol, today, target, record_alert_id=None)
        sig = signals.Signal(symbol, kind, move_dir, r, price, prev_close, sigma_mult=common["sigma_mult"])
        return candidate(sig, text, escalate=escalate, kind=kind, direction=move_dir, price_move=True, tier=pushed_tier,
                         why=dec.why, rollback=lambda: store.set_tier_state(symbol, today, target, **old), **common) | (
            {"price_move": False} if dec.why == "reversal" else {})   # not a merge/supersede candidate: the first alert keeps ringing

    def _short_push(self, symbol, today, stamp, now, states, valid, price, sigma, baseline, text_of, common, last_push,
                    candidate, prev_close) -> dict | None:
        """A 5- or 15-minute move (off unless the owner turned short moves on): tier 1 at most, once per direction a day."""
        last = valid[-1]
        bucket = signals.bucket_of(last["ts"])
        volume = sum(float(b.get("volume") or 0) for b in valid[-5:])
        avg = (baseline.get("avg_vol5") or {}).get(bucket)
        best = None
        for minutes, label in ((5, "5m"), (15, "15m")):
            ref = signals._bar_before(valid, last["ts"] - timedelta(minutes=minutes))
            if ref is None or last["ts"] - ref["ts"] > timedelta(minutes=minutes + 3):
                continue
            window_r = price / float(ref["close"]) - 1
            if tiers.short_move(window_r, sigma, bucket, volume, avg) and (best is None or abs(window_r) > abs(best[1])):
                best = (label, window_r)
        if best is None:
            return None
        label, window_r = best
        way = "up" if window_r > 0 else "down"
        row = states.get(way) or dict(self._ROW)
        if row["short_said"] or (last_push is not None and stamp - last_push < tiers.MIN_GAP):
            return None
        store = self.store
        old = {"short_said": 0, "last_push_ts": row["last_push_ts"]}
        store.set_tier_state(symbol, today, way, short_said=1, last_push_ts=stamp)
        sig = signals.Signal(symbol, "short", way, window_r, price, prev_close, sigma_mult=common["sigma_mult"], window=label)
        return candidate(sig, text_of(tier=1, why="short", kind="short", window=label, window_r=window_r), escalate=False,
                         price_move=True, tier=1, why="short",
                         rollback=lambda: store.set_tier_state(symbol, today, way, **old), **common)

    def _record_move(self, symbol, today, stamp, direction, r, mult, row) -> None:
        """A move over 1 sigma that stayed under the tier line: one night-digest line per symbol and direction a day,
        rewritten when it grows by a quarter sigma."""
        text = signals.format_record_line(symbol, r, mult)
        if not row.get("record_alert_id"):
            alert_id = self.store.add_alert(symbol, "record", text, False, stamp, deferred=True, digest_text=text)
            self.store.set_tier_state(symbol, today, direction, record_alert_id=alert_id, record_mult=mult)
        elif mult - float(row.get("record_mult") or 0) >= 0.25:
            self.store.update_alert(row["record_alert_id"], text=text, digest_text=text)
            self.store.set_tier_state(symbol, today, direction, record_mult=mult)

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
        tiered = [c for c in moves if "tier" in c]
        if tiered:
            known = next((c for c in tiered if c.get("market_r") is not None), tiered[0])
            grouped = tiers.group(tiered, known.get("market_r"), known.get("market_sigma"))
            if grouped:                                            # the whole market moved with them: one message
                members, _ = grouped
                self._raise_merged(snap, members, text=signals.format_grouped(members, known["market_r"]))
                moves = [c for c in moves if c not in members]
                if not moves:
                    return
        mode = self.store.get_kv("merge_mode")
        state = mode[0] if mode else {}
        active = bool(state.get("active"))
        if active and stamp - float(state.get("last_flush") or 0) < signals.MIN_GAP:
            urgent = [c for c in moves if c.get("tier") == 2]      # a major move is never held back, only the rest
            for c in moves:
                if c not in urgent and c.get("rollback"):
                    c["rollback"]()                                # anchors stay put; re-measured at the next flush
            for c in urgent:
                self._raise(snap, c)
            logger.info("merge interval: %d price pushes held back, %d major sent", len(moves) - len(urgent), len(urgent))
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
        self._announce(alert_id, alert)

    def _raise_merged(self, snap: dict, members: list[dict], text: str | None = None) -> None:
        if any("tier" in m for m in members):                      # a major holding is listed first
            members = sorted(members, key=lambda m: not (m["held"] and m.get("tier") == 2))
        symbols = [m["symbol"] for m in members]
        merged = {"symbol": "+".join(symbols)[:80], "symbols": symbols, "kind": "merged", "direction": "",
                  "held": any(m["held"] for m in members), "text": text or signals.format_merged(members),
                  "escalate": any(m["escalate"] for m in members), "price_move": True, "members": members,
                  "weight_pct": max(m.get("weight_pct") or 0 for m in members), "trigger": "T0",
                  "event_date": None, "earnings_unacked": False}
        if any("tier" in m for m in members):
            merged["tier"] = max(m.get("tier") or 0 for m in members)
            merged["sigma_mult"] = max(m.get("sigma_mult") or 0 for m in members)
        alert_id = self.escalator.raise_alert(snap, merged)
        deferred = self.escalator.deferred(alert_id)
        for m in members:
            m["after_send"](deferred, None)
        self._announce(alert_id, merged)

    def _announce(self, alert_id: int, alert: dict) -> None:
        """Tell the API about an alert that is already stored and sent (`alert_posted`) so the agent can judge it.

        Only queues the event: no HTTP in the alert path, so a down or slow API can never delay an alert.  The events
        job (every 30 s, its own thread) delivers it and keeps it until the API accepts.  An update of a pending
        night line queues again under the same alert id; the API judges an id once (a later stage may re-judge)."""
        try:
            self.store.enqueue("alert_posted", self.alert_payload(alert_id, alert))
        except Exception as exc:
            logger.warning("alert_posted for alert %s not queued: %s", alert_id, type(exc).__name__)

    def alert_payload(self, alert_id: int, alert: dict) -> dict:
        """What the sentinel knows about an alert; fields it does not have are left out, never invented."""
        row = self.store.alert(alert_id) or {}
        members = [m["symbol"] for m in alert.get("members") or [] if isinstance(m, dict) and m.get("symbol")]
        payload = {"alert_id": alert_id, "symbol": alert["symbol"], "kind": alert.get("kind", ""), "text": alert["text"],
                   "created_at": row.get("created_at"), "deferred": bool(row.get("deferred")),
                   "escalate": bool(row.get("escalate", alert.get("escalate"))), "held": bool(alert.get("held")),
                   "weight_pct": alert.get("weight_pct") or None, "price": alert.get("price"),
                   "prev_close": alert.get("prev_close"), "trigger": alert.get("trigger") or None,
                   "event_date": alert.get("event_date"), "members": members or None, "tier": alert.get("tier"),
                   "sigma_mult": alert.get("sigma_mult"), "rule_id": alert.get("rule_id"),
                   "owner_rule": True if alert.get("kind") == "rule" else None, "preset_key": alert.get("preset_key")}
        price, prev_close = alert.get("price"), alert.get("prev_close")
        if price is not None and prev_close:
            payload["move_pct"] = (price / prev_close - 1) * 100
        return {k: v for k, v in payload.items() if v is not None}

    def check_signals(self) -> None:
        now = datetime.now(UTC)
        if not signals.in_trading_session(now):
            return
        snap = self.config.get()
        held = [p["symbol"] for p in snap.get("positions") or [] if p.get("symbol") and p.get("shares")]
        queued = [s for s in snap.get("research_queue") or [] if s not in held]
        today = signals._et(now).date().isoformat()
        # a symbol only an owner rule names is polled for that rule alone: the owner did not ask for default alerts on it
        named = sorted({owner_rules.symbol_of(r) for r in self._owner_rules(snap, today)} - set(held) - set(queued))
        collected: list[dict] = []
        self.new_poll()
        self._market = self.fetch_market(now) if self._policy() == "tiers" else None
        for symbol, is_held, only in ([(s, True, False) for s in held] + [(s, False, False) for s in queued]
                                      + [(s, False, True) for s in named]):
            try:
                collected += self.evaluate_symbol(symbol, is_held, now, snap, rules_only=only)
            except Exception as exc:  # one symbol failing must not stop the others
                logger.warning("signal check for %s failed: %s", symbol, type(exc).__name__)
        try:
            collected += self.portfolio_alerts(now, snap)         # after every symbol: it needs this poll's prices
        except Exception as exc:
            logger.warning("portfolio presets failed: %s", type(exc).__name__)
        self.flush(collected, snap, now)

    def fetch_market(self, now: datetime) -> dict | None:
        """SPY's move from its previous close at this minute and its daily sigma, once per poll; None when unavailable."""
        try:
            base = self.baseline_for("SPY", now)
            chart = signals.fetch_chart("SPY", "1m", "1d")
            valid = [b for b in chart["bars"] if signals._bar_ok(b)]
            prev = base.get("prev_close") or chart["prev_close"]
            if not valid or not prev or signals.is_stale(valid[-1]["ts"], now):
                return None
            return {"r": float(valid[-1]["close"]) / prev - 1, "sigma": (base.get("baseline") or {}).get("daily_sigma")}
        except Exception as exc:
            logger.warning("SPY for the market line unavailable: %s", type(exc).__name__)
            return None

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
        """Drain the queue: `earnings_detected` first, always, then `alert_posted`, so one bad alert row never holds up
        a filing.  An API answer of 4xx for an alert is final (dropped, logged); 5xx or no answer keeps the row and
        moves on to the next one, but after 3 no-answers in a row the API is plainly down and the drain stops."""
        base = signals.api_base(self.config.get())
        for event in self.store.pending(event_type="earnings_detected"):
            try:
                signals.post_event(base, event["type"], event["payload"])
            except Exception as exc:
                self.store.bump(event["id"])
                if getattr(exc, "code", None) is None:
                    return  # API unreachable: keep order, try next tick
                break       # the API answered but refused: its alerts may still go through
            self.store.delete(event["id"])
            self.filings.mark_delivered(event["payload"]["accession"], time.time())
        silent = 0
        for event in self.store.pending(event_type="alert_posted"):
            alert_id = event["payload"].get("alert_id")
            if time.time() - float(event.get("created_at") or 0) > ALERT_EVENT_MAX_AGE:
                self.store.delete(event["id"])
                logger.warning("alert_posted for alert %s dropped: older than 24 hours", alert_id)
                continue
            try:
                signals.post_event(base, event["type"], event["payload"])
            except Exception as exc:
                code = getattr(exc, "code", None)
                if isinstance(code, int) and 400 <= code < 500:
                    self.store.delete(event["id"])
                    logger.warning("alert_posted for alert %s dropped: the API refused it (HTTP %s)", alert_id, code)
                    continue
                self.store.bump(event["id"])
                silent = silent + 1 if code is None else 0
                if silent >= 3:
                    return
                continue
            silent = 0
            self.store.delete(event["id"])

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
