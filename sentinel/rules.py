"""The owner's own watch rules (stage 5b-1) and the system's preset rules (5b-2): pure functions, no I/O, stdlib only,
never imports ``app``.

A rule is the JSON the API writes into the snapshot (``rules``): one symbol, one metric, one or two levels.  This module
only measures and compares; the state ("fired today"), the sending and the text live in sentinel/main.py and signals.py.
A metric whose data is missing measures ``None`` and never fires: a rule must not guess.  A preset is rule-shaped (plus
``source: "preset"``, ``preset_key`` and ``scope``); ``concrete`` turns it into one rule per symbol the scope covers."""

from __future__ import annotations

import hashlib
import statistics
from datetime import date, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PCT_METRICS = ("day_change", "open_change", "cost_change", "n_day_change")
DIRECTIONS = {
    **{m: ("up", "down", "either") for m in PCT_METRICS},
    "position_pnl": ("up", "down", "either"),
    "price": ("above", "below"),
    "position_weight": ("above", "below"),
    "volume_ratio": ("above",),
    "portfolio_day_change": ("up", "down", "either"),
    "down_days": ("down",),
    "high_52w": ("above",),
    "low_52w": ("below",),
}
METRICS = tuple(DIRECTIONS)
# State-like metrics describe a condition that can stay true for days: they fire on the edge (see main._rule_alerts).
# The others measure a move or a pace that resets by itself and keep plain once-per-level-per-day.
STATE_METRICS = ("price", "position_weight", "cost_change", "n_day_change", "down_days", "high_52w", "low_52w")
EXTREME_METRICS = ("high_52w", "low_52w")   # the threshold is ignored: the condition is "price is past the extreme close"
YEAR_METRICS = ("down_days", "high_52w", "low_52w")   # need the daily history of a year (52-week window / long streaks)
PRESET_SCOPES = ("holdings", "watched", "portfolio")
EXTREME_COOLDOWN_DAYS = 20        # after a 52-week level fired for a symbol: not again within this many completed trading days
YEAR_CLOSES = 252                 # the 52-week window: completed trading days
YEAR_MIN_CLOSES = 240             # fewer than this is not a year of history (a 1y chart holds about 250): measure None
LEVEL_NAMES = ("remind", "urgent")
REPEATS = ("daily", "once")
SESSION_MINUTES = 390             # 09:30-16:00
VOLUME_MIN_MINUTES = 30           # volume_ratio is not measured before 10:00 ET: the first half hour is too noisy
VOLUME_LINEAR_MIN_MINUTES = 90    # without the intraday profile, linear pacing over-reads early (volume is U-shaped): not before 11:00
VOLUME_MIN_FRACTION = 0.1
AVG_VOLUME_DAYS = 20
AVG_VOLUME_MIN_DAYS = 10


def valid(rule) -> bool:
    """Shape check the sentinel can rely on; an invalid rule is ignored rather than guessed at."""
    try:
        if not isinstance(rule, dict) or not rule.get("id") or not str(rule.get("symbol") or "").strip():
            return False
        metric = rule.get("metric")
        if metric not in DIRECTIONS or rule.get("direction") not in DIRECTIONS[metric]:
            return False
        is_preset = rule.get("source") == "preset"
        if str(rule["symbol"]).strip() == "*" and not is_preset:
            return False                                    # "every symbol" is a preset's way of saying its scope
        if (metric == "portfolio_day_change") != (is_preset and rule.get("scope") == "portfolio"):
            return False                                    # a portfolio measure belongs to the portfolio preset alone
        if (rule.get("repeat") or "daily") not in REPEATS:
            return False
        levels = rule.get("levels")
        if not isinstance(levels, list) or not 1 <= len(levels) <= 2:
            return False
        for item in levels:
            threshold = item.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                return False
            if metric in EXTREME_METRICS:
                if threshold < 0:                           # ignored, but a malformed number is still refused
                    return False
            elif threshold <= 0:
                return False
            if metric == "down_days" and (float(threshold) != int(threshold) or threshold < 2):
                return False
            if item.get("level") not in LEVEL_NAMES:
                return False
        if metric == "n_day_change":
            days = rule.get("window_days")
            if isinstance(days, bool) or not isinstance(days, int) or not 2 <= days <= 60:
                return False
        return True
    except (AttributeError, TypeError):
        return False


def preset_valid(preset) -> bool:
    """A well-formed preset: a valid rule (symbol ``*`` allowed) that says where it applies.  A bad one is ignored."""
    try:
        return (valid(preset) and preset.get("source") == "preset" and bool(str(preset.get("preset_key") or "").strip())
                and preset.get("scope") in PRESET_SCOPES
                and (preset["metric"] == "portfolio_day_change") == (preset["scope"] == "portfolio"))
    except (AttributeError, TypeError, KeyError):
        return False


def concrete(preset: dict, symbol: str) -> dict:
    """The preset as one rule for one symbol (``*`` for the portfolio).  Its id carries the symbol, so every symbol has its
    own fired / armed state; ``preset_id`` is the id the API knows."""
    return {**preset, "id": f"{preset['id']}:{symbol}", "preset_id": preset["id"], "symbol": symbol}


def symbol_of(rule: dict) -> str:
    return str(rule["symbol"]).strip().upper()


def expired(rule: dict, today: str) -> bool:
    """``expires_on`` is the last day the rule is checked; ``today`` is the New York date as ISO text."""
    until = rule.get("expires_on")
    return bool(until) and str(until)[:10] < today


def needs_daily(rule: dict) -> bool:
    return rule.get("metric") in ("n_day_change", "volume_ratio") + YEAR_METRICS


def needs_year(rule: dict) -> bool:
    return rule.get("metric") in YEAR_METRICS


def severity_order(rule: dict) -> list[int]:
    """Level indexes from the mildest to the strongest: an ``urgent`` level outranks any ``remind`` whatever its number
    (for a "below" rule the urgent threshold is the lower one, so thresholds alone do not order the levels)."""
    levels = rule["levels"]
    return sorted(range(len(levels)), key=lambda i: (levels[i]["level"] == "urgent", i))


def fingerprint(rule: dict) -> str:
    """Eight hex digits of what the rule checks (symbol, metric, direction, window).  An edit that changes what is measured
    gives a new fingerprint, so the old fired / armed / done state cannot leak into the edited rule."""
    basis = "|".join(str(x) for x in (symbol_of(rule), rule.get("metric"), rule.get("direction"),
                                       rule.get("window_days") or ""))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]


def level_key(rule: dict, index: int) -> str:
    """The state key of one level: ``<level>@<threshold>#<fingerprint>``, e.g. ``urgent@20#3fa9c1d2``.  Editing the
    threshold or anything the fingerprint covers starts the level afresh."""
    item = rule["levels"][index]
    return f"{item['level']}@{item['threshold']:g}#{fingerprint(rule)}"


def covered_directions(rule: dict) -> set[str]:
    """The move directions (``up`` / ``down``) a day_change rule speaks for; ``either`` covers both."""
    return {"up": {"up"}, "down": {"down"}}.get(rule.get("direction"), {"up", "down"})


def reference(rule: dict, ctx: dict) -> float | None:
    """The price a percentage metric is measured from (also what the message names), or None."""
    metric = rule["metric"]
    if metric == "day_change":
        ref = ctx.get("prev_close")
    elif metric == "open_change":
        ref = ctx.get("open")
    elif metric == "cost_change":
        ref = ctx.get("avg_cost")
    elif metric == "n_day_change":
        closes = ctx.get("closes") or []
        days = int(rule.get("window_days") or 0)
        ref = closes[-days] if days >= 1 and len(closes) >= days else None
    else:
        return None
    return float(ref) if isinstance(ref, (int, float)) and ref > 0 else None


def expected_volume(avg_vol5: dict | None, minutes: float) -> float | None:
    """Volume a stock normally trades in the first ``minutes`` of the regular session: its average 5-minute volume of each
    bucket summed over the elapsed slots (a partial slot counts in proportion).  None when a needed bucket is unknown."""
    if not avg_vol5 or minutes is None or minutes <= 0:
        return None
    total, slot = 0.0, 0
    while slot * 5 < min(minutes, SESSION_MINUTES):
        covered = min(5.0, min(minutes, SESSION_MINUTES) - slot * 5) / 5
        at = 9 * 60 + 30 + slot * 5
        bucket = "open30" if at < 10 * 60 else "mid" if at < 15 * 60 + 30 else "close30"
        avg = avg_vol5.get(bucket)
        if not isinstance(avg, (int, float)) or avg <= 0:
            return None
        total += avg * covered
        slot += 1
    return total


def volume_fraction(minutes: float) -> float:
    return max(VOLUME_MIN_FRACTION, min(1.0, minutes / SESSION_MINUTES))


def measure(rule: dict, ctx: dict) -> float | None:
    """The rule's number now, in the unit its thresholds use, or None when any input it needs is missing.

    ctx keys: price, prev_close, open (regular session only), avg_cost, closes (completed daily closes, oldest first,
    the last one is yesterday's), volume_today (regular session so far), avg_volume (20-day average daily volume),
    expected_volume (volume normally traded by now, from the 5-minute profile; None when unknown),
    session_minutes (minutes since 09:30 ET, None outside the regular session), shares, market_value, total_assets."""
    metric = rule["metric"]
    if metric == "portfolio_day_change":
        move = portfolio_move(ctx)
        return None if move is None else move["pct"]
    price = ctx.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    if metric == "down_days":
        return down_days(ctx)
    if metric in EXTREME_METRICS:
        closes = ctx.get("closes")
        if not closes or len(closes) < YEAR_MIN_CLOSES:
            return None
        window = closes[-YEAR_CLOSES:]
        return round(float(price) - (max(window) if metric == "high_52w" else min(window)), 6)
    if metric in PCT_METRICS:
        ref = reference(rule, ctx)
        return None if ref is None else round((price / ref - 1) * 100, 6)
    if metric == "price":
        return float(price)
    shares = ctx.get("shares")
    if metric == "volume_ratio":
        minutes, volume = ctx.get("session_minutes"), ctx.get("volume_today")
        if minutes is None or minutes < VOLUME_MIN_MINUTES or volume is None:
            return None
        expected = ctx.get("expected_volume")             # the stock's own intraday profile (sum of average 5-minute volumes)
        if isinstance(expected, (int, float)) and expected > 0:
            return round(float(volume) / float(expected), 6)
        avg = ctx.get("avg_volume")                        # no profile: linear pacing, only once the session is well under way
        if minutes < VOLUME_LINEAR_MIN_MINUTES or not avg or avg <= 0:
            return None
        return round(float(volume) / (float(avg) * volume_fraction(minutes)), 6)
    if not shares or shares <= 0:
        return None
    if metric == "position_pnl":
        prev = ctx.get("prev_close")
        return None if not prev or prev <= 0 else round(float(shares) * (price - float(prev)), 6)
    if metric == "position_weight":
        total = ctx.get("total_assets")
        if not total or total <= 0:
            return None
        value = float(shares) * price
        old = ctx.get("market_value")
        assets = float(total) - float(old if old is not None else value) + value   # total assets move with the position
        return None if assets <= 0 else round(value / assets * 100, 6)
    return None


def cooldown_active(fired_on: str | None, today: str, dates: list | None) -> bool:
    """True while fewer than ``EXTREME_COOLDOWN_DAYS`` completed trading days have passed since ``fired_on`` (ISO dates).
    Trading days are counted from the daily history's dates; without them, weekdays stand in."""
    if not fired_on:
        return False
    if dates:
        passed = sum(1 for d in dates if fired_on < str(d)[:10] < today)
    else:
        day, end, passed = date.fromisoformat(fired_on) + timedelta(days=1), date.fromisoformat(today), 0
        while day < end:
            passed += day.weekday() < 5
            day += timedelta(days=1)
    return passed < EXTREME_COOLDOWN_DAYS


def extreme_close(rule: dict, ctx: dict) -> float | None:
    """The close a 52-week rule is measured against (what its message names), or None."""
    closes = ctx.get("closes")
    if not closes or len(closes) < YEAR_MIN_CLOSES:
        return None
    window = closes[-YEAR_CLOSES:]
    return float(max(window) if rule["metric"] == "high_52w" else min(window))


def completed_run(ctx: dict) -> int | None:
    """Consecutive completed trading days that closed below the close before, counted back from yesterday; None when the
    closes are unknown."""
    closes = ctx.get("closes")
    if not closes:
        return None
    run, i = 0, len(closes) - 1
    while i >= 1 and closes[i] < closes[i - 1]:
        run, i = run + 1, i - 1
    return run


def down_days(ctx: dict) -> int | None:
    """The completed run plus today when the price is below yesterday's close now.  None when the closes or the previous
    close are unknown."""
    run, prev = completed_run(ctx), ctx.get("prev_close")
    if run is None or not isinstance(prev, (int, float)) or prev <= 0:
        return None
    return run + (1 if float(ctx["price"]) < float(prev) else 0)


def rearm_levels(rule: dict, ctx: dict, hit: list[int]) -> list[int]:
    """The levels of a state-like rule whose condition counts as seen false now, so the next time it holds it may say so
    again.  For most metrics that is "does not hold now".  A down streak ends when a completed day closed up, not when
    today's price flickers back over yesterday's close: otherwise one streak would be said twice (once on the day it
    reached the threshold, once the morning after)."""
    if rule["metric"] == "down_days":
        return list(range(len(rule["levels"]))) if completed_run(ctx) == 0 else []
    return [i for i in range(len(rule["levels"])) if i not in hit]


def portfolio_move(ctx: dict) -> dict | None:
    """The day's move of all holdings against yesterday's total assets: ``{"pct", "amount", "rows": [(symbol, amount)]}``.

    ctx: ``holdings`` ([{symbol, shares, price, prev_close, market_value?}]) and ``total_assets``.  Total assets move with
    the holdings (as in position_weight: the snapshot's market values come out, today's go in), so yesterday's assets are
    the total now minus the day's move.  None when any holding lacks a price or a previous close."""
    holdings, total = ctx.get("holdings"), ctx.get("total_assets")
    if not holdings or not isinstance(total, (int, float)) or total <= 0:
        return None
    rows, delta, old, now_value = [], 0.0, 0.0, 0.0
    for h in holdings:
        shares, price, prev = h.get("shares"), h.get("price"), h.get("prev_close")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 for x in (shares, price, prev)):
            return None
        amount = float(shares) * (float(price) - float(prev))
        rows.append((str(h.get("symbol") or ""), amount))
        delta += amount
        now_value += float(shares) * float(price)
        old += float(h["market_value"]) if isinstance(h.get("market_value"), (int, float)) else float(shares) * float(price)
    base = float(total) - old + now_value - delta
    if base <= 0:
        return None
    return {"pct": round(delta / base * 100, 6), "amount": delta, "rows": rows}


def _hit(direction: str, value: float, threshold: float) -> bool:
    if direction in ("up", "above"):
        return value >= threshold
    if direction in ("down", "below"):
        return value <= -threshold if direction == "down" else value <= threshold
    return abs(value) >= threshold


def reached(rule: dict, value: float | None) -> list[int]:
    """Indexes of every level whose condition holds at ``value``, mildest first.  Equal to a threshold counts."""
    if value is None:
        return []
    metric = rule.get("metric")
    out = []
    for i in severity_order(rule):
        threshold = float(rule["levels"][i]["threshold"])
        if metric == "down_days":
            hit = value >= threshold                         # a count of days, not a signed move
        elif metric in EXTREME_METRICS:
            hit = value >= 0 if metric == "high_52w" else value <= 0     # the value is the price minus the extreme close
        else:
            hit = _hit(rule["direction"], value, threshold)
        if hit:
            out.append(i)
    return out


def crossed(rule: dict, value: float | None) -> int | None:
    """The index of the strongest level ``value`` has reached, or None."""
    hit = reached(rule, value)
    return hit[-1] if hit else None


def daily_summary(bars: list[dict], today: date) -> dict:
    """``{"closes": [...], "avg_volume": float|None}`` from daily bars, completed days only (dated before ``today``, a
    New York date).  The average is over the last 20 of them that traded; under 10 such days it is None."""
    done = []
    for bar in sorted((b for b in bars if b.get("ts") and isinstance(b.get("close"), (int, float)) and b["close"] > 0),
                      key=lambda b: b["ts"]):
        ts = bar["ts"]
        day = (ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)).date()
        if day < today:
            done.append((day, float(bar["close"]), bar.get("volume")))
    volumes = [float(v) for _, _, v in done[-AVG_VOLUME_DAYS:] if isinstance(v, (int, float)) and v > 0]
    return {"closes": [c for _, c, _ in done], "dates": [d.isoformat() for d, _, _ in done],
            "avg_volume": statistics.fmean(volumes) if len(volumes) >= AVG_VOLUME_MIN_DAYS else None}
