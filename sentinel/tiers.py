"""Tiered price alerts (design section 7.3): pure functions, no I/O, stdlib only, never imports ``app``.

A move is measured against the stock's own daily sigma, grouped into three tiers (0 record, 1 worth knowing,
2 major), and said once per direction per New York date.  Price levels lock after a crossing.  The state the
decisions read (``states``, ``level`` rows) lives in sentinel/store.py; this module only computes."""

from __future__ import annotations

from dataclasses import dataclass

UNIT_FALLBACK = 0.02              # one "sigma" when the stock has no baseline
SENSITIVITY = {"quiet": (2.5, 5.0), "standard": (2.0, 4.0), "sensitive": (1.5, 3.0)}   # (worth knowing, major) in sigmas
IMPACT_PCT = 2.0                  # a holding's move that costs or makes this share of total assets matters to the owner:
                                  # on its own it is "worth knowing"; on top of a sigma-worthy move it is major
MIN_GAP = 10 * 60                 # seconds between minor pushes on one symbol
REARM_SIGMAS = 0.5                # a locked level re-arms after the price is this many daily sigmas away
REARM_FALLBACK = 0.01
SHORT_SIGMAS = 0.5                # a 5/15-minute move must be at least this many daily sigmas
SHORT_FALLBACK = 0.01
SHORT_EXT_VOLUME_X = 3.0
GROUP_MIN = 3
GROUP_FALLBACK = 0.01             # SPY's move that counts as "the market moved" when its sigma is unknown
RECORD_MIN_SIGMAS = 1.0           # tier-0 moves above this are written as digest lines


def thresholds(sensitivity: str | None) -> tuple[float, float]:
    return SENSITIVITY.get((sensitivity or "").strip().lower(), SENSITIVITY["standard"])


def measure(price: float, prev_close: float, daily_sigma: float | None = None, market_r: float | None = None,
            shares: float | None = None, total_assets: float | None = None) -> dict:
    """The three numbers that describe a move: against itself, against the market, against the owner's assets."""
    r = price / prev_close - 1
    impact = None
    if shares and total_assets and total_assets > 0:
        impact = float(shares) * (price - prev_close) / float(total_assets) * 100
    return {"r": r, "direction": "up" if r > 0 else "down" if r < 0 else "", "market_r": market_r,
            "sigma_mult": round(abs(r) / (daily_sigma or UNIT_FALLBACK), 9), "impact_pct": impact}


def tier_rule(m: dict, sensitivity: str | None = "standard", held: bool = False) -> tuple[int, str]:
    """(tier, why): why is ``sigma_major`` | ``impact`` | ``sigma`` | ``record`` (tier 0 above 1 sigma) | ``""``."""
    low, high = thresholds(sensitivity)
    sigma_tier = 2 if m["sigma_mult"] >= high else 1 if m["sigma_mult"] >= low else 0
    impact = bool(held and m.get("impact_pct") is not None and abs(m["impact_pct"]) >= IMPACT_PCT)
    if sigma_tier == 2:
        return 2, "sigma_major"
    if sigma_tier == 1 and impact:
        return 2, "impact"
    if sigma_tier == 1:
        return 1, "sigma"
    if impact:
        return 1, "impact_only"
    return 0, "record" if m["sigma_mult"] >= RECORD_MIN_SIGMAS else ""


def tier_of(m: dict, sensitivity: str | None = "standard", held: bool = False) -> int:
    return tier_rule(m, sensitivity, held)[0]


@dataclass(frozen=True)
class Decision:
    action: str                  # push | hold (MIN_GAP) | none
    why: str = ""                # first | rise | reversal
    tier: int = 0
    direction: str = ""          # the direction the message is about (for a reversal: the move that is being given back)
    reason: str = ""             # why a hold was held: min_gap


def _gave_back_half(extreme_r: float, r: float) -> bool:
    return bool(extreme_r) and (r <= extreme_r / 2 if extreme_r > 0 else r >= extreme_r / 2)


def decide(states: dict | None, tier: int, direction: str, r: float, now: float,
           last_push_ts: float | None = None) -> Decision:
    """Whether this look pushes.  ``states`` maps ``up``/``down`` to today's rows ({max_tier, extreme_r,
    reversal_said}); only a state the caller has committed counts as said.  A major push is never held."""
    states = states or {}
    said = int((states.get(direction) or {}).get("max_tier") or 0)
    why, side, out_tier = "", direction, tier
    if tier >= 1 and direction:
        if said == 0:
            why = "first"
        elif tier > said:
            why = "rise"
    if not why and not any(s.get("reversal_said") for s in states.values()):
        for name, state in states.items():
            if int(state.get("max_tier") or 0) >= 1 and _gave_back_half(float(state.get("extreme_r") or 0), r):
                why, side, out_tier = "reversal", name, max(1, min(tier, 1))
                break
    if not why:
        return Decision("none")
    if out_tier < 2 and last_push_ts is not None and now - last_push_ts < MIN_GAP:
        return Decision("hold", why, out_tier, side, "min_gap")
    return Decision("push", why, out_tier, side)


def level_state(state: dict | None, kind: str, level: float, price: float, daily_sigma: float | None,
                ny_date: str, ref: float | None = None) -> tuple[bool, int, dict]:
    """The lock of one price level.  ``state`` is the stored row or None (never seen).  Returns (fire, count today,
    new state).  A level fires when armed and the price reaches it; then it locks until the price has moved away
    from it by half a daily sigma on the side it came from.  A level never seen before is seeded from ``ref``
    (the last price the owner saw, or yesterday's close): if ``ref`` was on the side the price comes from and the price is
    now at or through the level, it fires; if ``ref`` was already through it, it starts locked.  Without ``ref`` it is
    seeded from the current side and cannot fire at its first look."""
    falling = kind in ("plan_add", "plan_stop")                  # these fire when the price falls to the level
    from_side = price > level if falling else price < level
    reached = price <= level if falling else price >= level
    if state is None:
        if ref is None:
            return False, 0, {"armed": 1 if from_side else 0, "last_date": None, "count_today": 0}
        state = {"armed": 1 if (ref > level if falling else ref < level) else 0, "last_date": None, "count_today": 0}
    new = dict(state)
    if new.get("armed"):
        if not reached:
            return False, int(new.get("count_today") or 0), new
        count = int(new.get("count_today") or 0) + 1 if new.get("last_date") == ny_date else 1
        new.update(armed=0, last_date=ny_date, count_today=count)
        return True, count, new
    away = (daily_sigma * REARM_SIGMAS) if daily_sigma else REARM_FALLBACK
    if (price >= level * (1 + away)) if falling else (price <= level * (1 - away)):
        new["armed"] = 1
    return False, int(new.get("count_today") or 0), new


def short_move(r_window: float, daily_sigma: float | None, bucket: str, volume: float | None = None,
               avg_volume: float | None = None) -> bool:
    """A 5- or 15-minute move counts (tier 1 at most) at half a daily sigma; outside the regular session the last
    five minutes' volume must also be 3x the bucket's average."""
    floor = daily_sigma * SHORT_SIGMAS if daily_sigma else SHORT_FALLBACK
    if abs(r_window) < floor:
        return False
    if bucket in ("pre", "post"):
        return bool(avg_volume) and volume is not None and volume >= SHORT_EXT_VOLUME_X * avg_volume
    return True


def group(items: list[dict], market_r: float | None, market_sigma: float | None = None):
    """(members, rest) when at least 3 pushes go the way the market went (SPY at least 1 sigma of its own, or 1%
    when unknown); members ordered major holdings first.  None otherwise.  A reversal is not "moving together"."""
    if market_r is None or abs(market_r) < (market_sigma or GROUP_FALLBACK):
        return None
    way = "up" if market_r > 0 else "down"
    members = [c for c in items if c.get("direction") == way and c.get("why") != "reversal"]
    if len(members) < GROUP_MIN:
        return None
    members.sort(key=lambda c: (not (c.get("held") and c.get("tier") == 2), not c.get("held"), -(c.get("tier") or 0),
                                -(c.get("sigma_mult") or 0)))
    return members, [c for c in items if c not in members]
