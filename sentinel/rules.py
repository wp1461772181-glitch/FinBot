"""The owner's own watch rules (stage 5b-1): pure functions, no I/O, stdlib only, never imports ``app``.

A rule is the JSON the API writes into the snapshot (``rules``): one symbol, one metric, one or two levels.  This module
only measures and compares; the state ("fired today"), the sending and the text live in sentinel/main.py and signals.py.
A metric whose data is missing measures ``None`` and never fires: a rule must not guess."""

from __future__ import annotations

import hashlib
import statistics
from datetime import date
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

PCT_METRICS = ("day_change", "open_change", "cost_change", "n_day_change")
DIRECTIONS = {
    **{m: ("up", "down", "either") for m in PCT_METRICS},
    "position_pnl": ("up", "down", "either"),
    "price": ("above", "below"),
    "position_weight": ("above", "below"),
    "volume_ratio": ("above",),
}
METRICS = tuple(DIRECTIONS)
# State-like metrics describe a condition that can stay true for days: they fire on the edge (see main._rule_alerts).
# The others measure a move or a pace that resets by itself and keep plain once-per-level-per-day.
STATE_METRICS = ("price", "position_weight", "cost_change", "n_day_change")
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
        if (rule.get("repeat") or "daily") not in REPEATS:
            return False
        levels = rule.get("levels")
        if not isinstance(levels, list) or not 1 <= len(levels) <= 2:
            return False
        for item in levels:
            threshold = item.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or threshold <= 0:
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


def symbol_of(rule: dict) -> str:
    return str(rule["symbol"]).strip().upper()


def expired(rule: dict, today: str) -> bool:
    """``expires_on`` is the last day the rule is checked; ``today`` is the New York date as ISO text."""
    until = rule.get("expires_on")
    return bool(until) and str(until)[:10] < today


def needs_daily(rule: dict) -> bool:
    return rule.get("metric") in ("n_day_change", "volume_ratio")


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
    price = ctx.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    metric = rule["metric"]
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
    return [i for i in severity_order(rule) if _hit(rule["direction"], value, float(rule["levels"][i]["threshold"]))]


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
    return {"closes": [c for _, c, _ in done],
            "avg_volume": statistics.fmean(volumes) if len(volumes) >= AVG_VOLUME_MIN_DAYS else None}
