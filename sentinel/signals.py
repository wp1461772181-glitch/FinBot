"""Probes and actions the sentinel loops use (stdlib only; never imports ``app``)."""

from __future__ import annotations

import json
import logging
import math
import os
import resource
import statistics
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

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


# --- intraday move signals (Task 11) -----------------------------------------------------------------
# Pure functions: every rule compares a move with the stock's own history (sigma), not a flat percentage.
# Where sigma is unknown (a new listing, too little history) fixed fallbacks apply: 5% over a short
# window, 8% over a day.  Sigma 0.02 stands in as the unit for "one more sigma" in the cooldown.

ET = ZoneInfo("America/New_York")
Bucket = Literal["pre", "open30", "mid", "close30", "post"]
SHORT_FLOOR = 0.01            # a short-window move under 1% never counts, however quiet the stock
SHORT_SIGMAS = 4.0
SHORT_FALLBACK = 0.05
DAILY_FALLBACK = 0.08
STALE_AFTER = timedelta(minutes=10)
COOLDOWN_SECONDS = 30 * 60
SPLIT_LOOKBACK_DAYS = 2
VOLUME_SURGE_X = 5.0
FALLBACK_UNIT = 0.02


def _et(ts: datetime) -> datetime:
    """A timestamp in New York time; a naive one is taken to be New York time already."""
    return ts.replace(tzinfo=ET) if ts.tzinfo is None else ts.astimezone(ET)


def bucket_of(ts_et: datetime) -> Bucket:
    t = _et(ts_et).time()
    if t < dtime(9, 30):
        return "pre"
    if t < dtime(10, 0):
        return "open30"
    if t < dtime(15, 30):
        return "mid"
    if t < dtime(16, 0):
        return "close30"
    return "post"


def short_move_signal(r: float, bucket_sigma: float | None) -> bool:
    """|r| >= 4 sigma and |r| >= 1%; without sigma a 5-minute window needs |r| >= 5%."""
    if bucket_sigma is None:
        return abs(r) >= SHORT_FALLBACK
    return abs(r) >= SHORT_SIGMAS * bucket_sigma and abs(r) >= SHORT_FLOOR


def daily_move_level(r_from_prev_close: float, sigma: float | None) -> int:
    """0 none, 1 beyond 2 sigma, 2 beyond 3 sigma; without sigma |r| >= 8% is level 1."""
    r = abs(r_from_prev_close)
    if sigma is None:
        return 1 if r >= DAILY_FALLBACK else 0
    if r > 3 * sigma:
        return 2
    if r > 2 * sigma:
        return 1
    return 0


def gap_signal(price: float, prev_close: float, sigma: float | None) -> bool:
    """The open or pre-market price is more than 2 sigma away from yesterday's close."""
    if not prev_close:
        return False
    return daily_move_level(price / prev_close - 1, sigma) >= 1


def is_stale(last_bar_ts: datetime | None, now: datetime) -> bool:
    return last_bar_ts is None or now - last_bar_ts > STALE_AFTER


def in_trading_session(now: datetime) -> bool:
    """New York Monday-Friday 04:00-20:00 (holidays show up as stale or empty bars instead)."""
    local = _et(now)
    return local.weekday() < 5 and dtime(4, 0) <= local.time() < dtime(20, 0)


@dataclass(frozen=True)
class Signal:
    symbol: str
    kind: str                 # short | daily | gap | split | plan_add | plan_stop | plan_target
    direction: str            # up | down | "" 
    r: float = 0.0            # the move that fired it
    price: float = 0.0
    ref_price: float = 0.0    # the price the move is measured from
    level: int = 0            # daily: 1 or 2
    sigma_mult: float = 0.0   # |r| in units of the relevant sigma (cooldown deepening)
    window: str = ""          # short: "5m" or "15m"
    volume_surge: bool = False
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.direction}"


def _bar_ok(bar: dict) -> bool:
    return bool(bar.get("ts")) and isinstance(bar.get("close"), (int, float)) and bar["close"] > 0


def prev_close_from_daily(bars: list[dict], now: datetime) -> float | None:
    """Close of the last daily bar dated strictly before ``now``'s New York date, or None.

    Yahoo's ``chartPreviousClose`` is relative to the last completed session, which in premarket is a
    day too early; the daily bars give the real previous trading day's close.
    """
    today = _et(now).date()
    found = None
    for bar in sorted((b for b in bars if _bar_ok(b)), key=lambda b: b["ts"]):
        if _et(bar["ts"]).date() < today:
            found = float(bar["close"])
    return found


def _recent_split(splits, now: datetime) -> dict | None:
    today = now.date()
    for item in splits or []:
        try:
            when = datetime.fromisoformat(str(item["date"])).date()
        except (KeyError, ValueError):
            continue
        if 0 <= (today - when).days <= SPLIT_LOOKBACK_DAYS:
            return item
    return None


def _bar_before(bars: list[dict], ts: datetime) -> dict | None:
    found = None
    for bar in bars:
        if bar["ts"] <= ts:
            found = bar
        else:
            break
    return found


def detect(symbol: str, bars: list[dict], now: datetime, baseline: dict | None, prev_close: float | None, *,
           held: bool, splits=None) -> list[Signal]:
    """Signals for one symbol from its 1-minute bars (oldest first, ``ts`` aware, ``close``/``volume``).

    A holding gets every rule; a research-queue symbol only a level-2 day move.  A split in the last two
    days replaces everything with one ``split`` signal (prices around it are not comparable).  Empty,
    gappy or stale bars give nothing."""
    split = _recent_split(splits, now)
    if split is not None:
        return [Signal(symbol, "split", "", detail=str(split.get("ratio") or ""))]
    bars = [b for b in bars if _bar_ok(b)]
    if not bars or is_stale(bars[-1]["ts"], now):
        return []
    baseline = baseline or {}
    last = bars[-1]
    price = float(last["close"])
    bucket = bucket_of(last["ts"])
    sigma5 = (baseline.get("bucket_sigma") or {}).get(bucket)
    out: list[Signal] = []

    daily_sigma = baseline.get("daily_sigma")
    if prev_close:
        r = price / prev_close - 1
        level = daily_move_level(r, daily_sigma)
        direction = "up" if r > 0 else "down"
        unit = daily_sigma or FALLBACK_UNIT
        if bucket in ("pre", "open30") and gap_signal(price, prev_close, daily_sigma) and held:
            out.append(Signal(symbol, "gap", direction, r, price, prev_close, level, abs(r) / unit))
        elif level >= (1 if held else 2):
            out.append(Signal(symbol, "daily", direction, r, price, prev_close, level, abs(r) / unit))

    if held:
        best = None
        for minutes, label, scale in ((5, "5m", 1.0), (15, "15m", math.sqrt(3))):
            ref = _bar_before(bars, last["ts"] - timedelta(minutes=minutes))
            if ref is None or last["ts"] - ref["ts"] > timedelta(minutes=minutes + 3):
                continue
            r = price / float(ref["close"]) - 1
            sigma = None if sigma5 is None else sigma5 * scale
            if short_move_signal(r, sigma):
                mult = abs(r) / (sigma or FALLBACK_UNIT)
                candidate = Signal(symbol, "short", "up" if r > 0 else "down", r, price, float(ref["close"]),
                                   sigma_mult=mult, window=label)
                if best is None or mult > best.sigma_mult:
                    best = candidate
        if best is not None:
            out.append(best)

    avg_vol = (baseline.get("avg_vol5") or {}).get(bucket)
    recent_volume = sum(float(b.get("volume") or 0) for b in bars[-5:])
    surge = bool(avg_vol) and recent_volume > VOLUME_SURGE_X * avg_vol
    return [replace(s, volume_surge=True) for s in out] if surge else out


def plan_crossings(symbol: str, prev_price: float | None, price: float | None, plan: dict) -> list[Signal]:
    """The preset add / stop / target price crossed between two consecutive looks at the price."""
    if prev_price is None or price is None:
        return []
    found = []
    for field, kind, downward in (("add_price", "plan_add", True), ("stop_price", "plan_stop", True),
                                  ("target_price", "plan_target", False)):
        level = plan.get(field)
        if level is None:
            continue
        crossed = prev_price > level >= price if downward else prev_price < level <= price
        if crossed:
            found.append(Signal(symbol, kind, "down" if downward else "up", price / prev_price - 1, price, level,
                                detail=str(level)))
    return found


# --- the push policy (.local/design-alert-policy.md) -----------------------------------------------------------
# One event per symbol per New York date; the sentinel remembers one price for it, the anchor (the price in the
# last message the owner got).  Entry signals above open the event; after that only the price travelling away
# from the anchor can push.  Time passing never does, and neither does crossing a sigma line.

STEP_MIN, STEP_MAX = 0.01, 0.03
MIN_GAP = 10 * 60                 # seconds between price pushes on one symbol, no exceptions
T1_HELD_STEPS = 1.0               # further from yesterday's close than the anchor, a holding
T1_QUEUE_STEPS = 2.0              # same, a research-queue symbol
T2_STEPS = 2.0                    # back toward yesterday's close
T3_STEPS = 1.0                    # the 09:35 open check, either direction
OPEN_CHECK_AT = dtime(9, 35)
CONTINUATION_MAX_DAYS = 4


def step_for(sigma: float | None) -> float:
    """1 step = the stock's daily sigma clamped to 1%-3%; 2% when sigma is unknown."""
    if not sigma:
        return FALLBACK_UNIT
    return min(STEP_MAX, max(STEP_MIN, float(sigma)))


@dataclass(frozen=True)
class Decision:
    action: str                    # push | hold (a trigger fired but MIN_GAP holds it) | none
    trigger: str = ""              # T0 | T1 | T2 | T3
    reason: str = ""               # why it did not push: min_gap | inside_limits
    dist: float = 0.0              # price / anchor - 1
    steps: float = 0.0             # |dist| in steps
    worse: bool = False            # further from yesterday's close than the anchor
    open_checked: bool = False     # the T3 look was done at this poll; the caller records it
    continuation: bool = False     # a first alert that repeats yesterday's last one


def realert_limits(anchor: float, anchor_r: float, step: float, held: bool) -> tuple[float, float]:
    """(low, high): the prices at which the next push happens, as measured from ``anchor``."""
    worse_steps = T1_HELD_STEPS if held else T1_QUEUE_STEPS
    if anchor_r > 0:
        low_steps, high_steps = T2_STEPS, worse_steps
    else:
        low_steps, high_steps = worse_steps, T2_STEPS
    return anchor * (1 - low_steps * step), anchor * (1 + high_steps * step)


def decide_push(event: dict | None, price: float, prev_close: float, now: datetime, *, held: bool, entry: bool,
                prev_event: dict | None = None, step: float | None = None) -> Decision:
    """Whether this poll pushes.  ``event`` is today's event row (None before the first push of the day),
    ``entry`` whether detect() produced a gap/daily/short signal at this poll.  Pure: no state is changed."""
    r_now = price / prev_close - 1
    if event is None:
        if not entry:
            return Decision("none", reason="no_signal")
        use_step = step or FALLBACK_UNIT
        continuation = False
        if prev_event and prev_event.get("anchor_price"):
            same_side = (prev_event["anchor_r"] > 0) == (r_now > 0)
            near = abs(price / prev_event["anchor_price"] - 1) <= use_step
            continuation = same_side and near
        return Decision("push", "T0", continuation=continuation)

    use_step = event["step"]
    anchor = event["anchor_price"]
    dist = price / anchor - 1
    steps = abs(dist) / use_step
    worse = abs(r_now) > abs(event["anchor_r"])
    local = _et(now)
    t3_due = (not event.get("open_checked")) and event.get("first_bucket") == "pre" and local.time() >= OPEN_CHECK_AT
    gap_open = now.timestamp() - float(event.get("last_push_ts") or 0) >= MIN_GAP

    trigger = ""
    if t3_due and steps >= T3_STEPS:
        trigger = "T3"
    elif worse and steps >= (T1_HELD_STEPS if held else T1_QUEUE_STEPS):
        trigger = "T1"
    elif not worse and steps >= T2_STEPS:
        trigger = "T2"
    if not trigger:
        return Decision("none", reason="inside_limits", dist=dist, steps=steps, worse=worse, open_checked=t3_due)
    if not gap_open:
        return Decision("hold", trigger, "min_gap", dist, steps, worse)   # T3 stays due: it is not marked done
    return Decision("push", trigger, dist=dist, steps=steps, worse=worse, open_checked=t3_due)


class Cooldown:
    """One alert per (symbol, signal) in 30 minutes, unless the move went a further sigma the same way.
    No longer used for price moves (the anchor policy above replaced it); kept as a plain helper."""

    def __init__(self, store=None, window: float = COOLDOWN_SECONDS) -> None:
        self.window, self.store = window, store
        self._last: dict[tuple[str, str], tuple[float, float]] = {}

    def _get(self, symbol: str, key: str):
        if (symbol, key) in self._last:
            return self._last[(symbol, key)]
        return self.store.get_cooldown(symbol, key) if self.store else None

    def allow(self, symbol: str, key: str, mult: float, now_ts: float) -> bool:
        last = self._get(symbol, key)
        if last is not None and now_ts - last[0] < self.window and mult < last[1] + 1.0:
            return False
        self._last[(symbol, key)] = (now_ts, mult)
        if self.store:
            self.store.set_cooldown(symbol, key, now_ts, mult)
        return True


# --- baseline: 20 trading days of 5-minute bars --------------------------------------------------------

def compute_baseline(bars5: list[dict], now: datetime, days: int = 20) -> dict:
    """Per-bucket 5-minute sigma and mean 5-minute volume, and the daily-return sigma, over the last ``days``
    trading days.  Returns beyond 50% are dropped (a split, not a move).  Too few samples give ``None``."""
    bars = sorted((b for b in bars5 if _bar_ok(b)), key=lambda b: b["ts"])
    dates = sorted({_et(b["ts"]).date() for b in bars})[-(days + 1):]
    keep = set(dates)
    returns: dict[str, list[float]] = {}
    volumes: dict[str, list[float]] = {}
    closes: dict = {}
    prev = None
    for bar in bars:
        local = _et(bar["ts"])
        if local.date() not in keep:
            continue
        bucket = bucket_of(local)
        if bar.get("volume") is not None:
            volumes.setdefault(bucket, []).append(float(bar["volume"]))
        if prev is not None and _et(prev["ts"]).date() == local.date():
            r = float(bar["close"]) / float(prev["close"]) - 1
            if abs(r) <= 0.5:
                returns.setdefault(bucket, []).append(r)
        if local.time() <= dtime(16, 0):
            closes[local.date()] = float(bar["close"])
        prev = bar
    ordered = [closes[d] for d in sorted(closes)]
    daily = [b / a - 1 for a, b in zip(ordered, ordered[1:]) if a and abs(b / a - 1) <= 0.5]

    def sigma(values, minimum):
        return statistics.stdev(values) if len(values) >= minimum else None

    return {"daily_sigma": sigma(daily, 10),
            "bucket_sigma": {b: sigma(returns.get(b, []), 30) for b in ("pre", "open30", "mid", "close30", "post")},
            "avg_vol5": {b: (statistics.fmean(volumes[b]) if len(volumes.get(b, [])) >= 10 else None)
                         for b in ("pre", "open30", "mid", "close30", "post")},
            "computed_at": now.astimezone(UTC).isoformat()}


# --- Yahoo chart (the same endpoint as app/market_data.py; this package never imports app) -------------

YAHOO_CHART = "https://query2.finance.yahoo.com/v8/finance/chart"
YAHOO_UA = "market-evidence-agent/0.1 (+sentinel intraday)"


def yahoo_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def parse_chart(payload: dict) -> dict:
    """``{"bars": [...], "prev_close": float|None, "splits": [...]}`` from one Yahoo chart response."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
    stamps = result.get("timestamp") or []
    quote = (((result.get("indicators") or {}).get("quote")) or [{}])[0]
    bars = []
    for i, stamp in enumerate(stamps):
        close = (quote.get("close") or [])[i] if i < len(quote.get("close") or []) else None
        volume = (quote.get("volume") or [])[i] if i < len(quote.get("volume") or []) else None
        bars.append({"ts": datetime.fromtimestamp(stamp, UTC), "close": close, "volume": volume})
    splits = []
    for item in ((result.get("events") or {}).get("splits") or {}).values():
        when = datetime.fromtimestamp(item.get("date", 0), UTC).date().isoformat()
        splits.append({"date": when, "ratio": item.get("splitRatio") or f"{item.get('numerator')}:{item.get('denominator')}"})
    meta = result.get("meta") or {}
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return {"bars": bars, "prev_close": float(prev) if prev else None, "splits": splits}


def fetch_chart(symbol: str, interval: str, range_: str, *, prepost: bool = True, events: bool = False,
                timeout: float = 20) -> dict:
    query = f"interval={interval}&range={range_}&includePrePost={'true' if prepost else 'false'}"
    if events:
        query += "&events=splits"
    req = urllib.request.Request(f"{YAHOO_CHART}/{yahoo_symbol(symbol)}?{query}", headers={"User-Agent": YAHOO_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # honours the proxy env, like the other outbound calls
        return parse_chart(json.loads(resp.read()))


# --- alert text ------------------------------------------------------------------------------------------

def _money(value: float) -> str:
    return f"${abs(value):,.0f}"


BEIJING = timezone(timedelta(hours=8))
SESSION_LABEL = {"pre": "盘前异动", "open30": "盘中异动", "mid": "盘中异动", "close30": "盘中异动", "post": "盘后异动"}


def _clock(ts: float) -> str:
    """Beijing time, the owner's clock, as HH:MM."""
    return datetime.fromtimestamp(ts, BEIJING).strftime("%H:%M")


def _limits_text(price: float, r: float, step: float, held: bool) -> str:
    low, high = realert_limits(price, r, step, held)
    return f"再次提醒线：≤{low:.2f} 或 ≥{high:.2f}"


def format_alert(signal: Signal, position: dict | None, total_assets: float | None, *, now: datetime | None = None,
                 step: float | None = None, day_r: float = 0.0, held: bool = False,
                 earnings_at: float | None = None, continuation: bool = False) -> str:
    """The alert in Chinese; for a holding it says how much the move cost (or made) and what share of
    total assets that is.  With ``step`` it is the first alert of the day and prints its own re-alert limits."""
    name = signal.symbol
    if signal.kind == "split":
        return (f"【拆股提醒】{name} 最近 {SPLIT_LOOKBACK_DAYS} 天有拆股/合股事件（{signal.detail}），"
                f"价格不可比，已暂停该股的异动信号。请核对持仓股数和成本。")
    if signal.kind.startswith("plan_"):
        label = {"plan_add": "补仓价", "plan_stop": "止损价", "plan_target": "目标价"}[signal.kind]
        verb = "跌破" if signal.kind != "plan_target" else "涨到"
        text = f"【价位提醒】{name} {verb}预设{label} {signal.detail}，现价 {signal.price:.2f}。"
        return text + _position_line(signal, position, total_assets, with_move=False)
    where = {"short": f"{signal.window.replace('15m', '15 分钟').replace('5m', '5 分钟')}内" if signal.window else "短时", "daily": "较昨收", "gap": "开盘/盘前跳空，较昨收"}[signal.kind]
    arrow = "跌" if signal.direction == "down" else "涨"
    bucket = bucket_of(now) if now is not None else "mid"
    head = f"【{SESSION_LABEL[bucket]}】{name} {where}{arrow} {abs(signal.r) * 100:.1f}%（约 {signal.sigma_mult:.1f}σ），现价 {signal.price:.2f}。"
    if signal.kind == "daily" and signal.level == 2:
        head += "超过 3σ。"
    if signal.volume_surge:
        head += "同时放量（5 分钟成交量超过同时段均值 5 倍）。"
    if earnings_at is not None:
        head += f"\n财报 8-K 已于 {_clock(earnings_at)} 发布。"
    text = head + _position_line(signal, position, total_assets, with_move=True)
    if step is not None:
        tail = ("今日首条（延续昨日提醒）。" if continuation else "今日首条。") + _limits_text(signal.price, day_r, step, held)
        if bucket == "pre":
            tail += "；开盘后 5 分钟再看一次"
        text += "\n" + tail + "。"
    return text


def format_update(*, symbol: str, price: float, prev_close: float, event: dict, decision: Decision, now: datetime,
                  sigma: float | None, position: dict | None, total_assets: float | None, held: bool) -> str:
    """A re-alert, measured from the last push: how far since then, where that leaves the day, the new limits."""
    anchor, dist = event["anchor_price"], decision.dist
    r = price / prev_close - 1
    unit = sigma or FALLBACK_UNIT
    if decision.trigger == "T3":
        head = f"【开盘更新】{symbol} 开盘后较盘前提醒（{anchor:.2f}）"
    else:
        head = f"【异动更新】{symbol} 较上次提醒（{anchor:.2f}，{_clock(event['anchor_ts'])}）"
    if decision.worse:
        move = "又跌" if dist < 0 else "又涨"
    else:
        move = "回升" if dist > 0 else "回落"
    still = "仍" if (r < 0) == (event["anchor_r"] < 0) and not decision.worse else ""
    side = "跌" if r < 0 else "涨"
    text = (f"{head}{move} {abs(dist) * 100:.1f}%，现价 {price:.2f}。\n"
            f"较昨收{still}{side} {abs(r) * 100:.1f}%（约 {abs(r) / unit:.1f}σ）。今日第 {int(event.get('pushes') or 1) + 1} 条。\n"
            f"{_limits_text(price, r, event['step'], held)}。")
    if position and position.get("shares"):
        shares = float(position["shares"])
        since, total_move = shares * (price - anchor), shares * (price - prev_close)
        line = f"\n持仓 {shares:g} 股，较上次提醒又{'亏' if since < 0 else '赚'} {_money(since)}"
        if total_assets:
            line += f"，占总资产 {abs(since) / total_assets * 100:.2f}%"
        line += f"；较昨收共{'亏' if total_move < 0 else '赚'} {_money(total_move)}"
        if total_assets and position.get("market_value") is not None:
            line += f"；现仓位占总资产 {position_weight(position, price, total_assets) * 100:.1f}%"
        text += line + "。"
    return text


def format_digest_line(*, symbol: str, price: float, prev_close: float, event: dict, sigma: float | None,
                       extreme: float | None) -> str:
    """The one night-digest line of an event, written from where the price stands now."""
    anchor = event["anchor_price"]
    dist, r = price / anchor - 1, price / prev_close - 1
    word = "又跌" if dist < 0 else "回升" if (r < 0) else "又涨"
    text = (f"{symbol} 较上次提醒（{anchor:.2f}）{word} {abs(dist) * 100:.1f}%，现价 {price:.2f}，"
            f"较昨收{'跌' if r < 0 else '涨'} {abs(r) * 100:.1f}%（约 {abs(r) / (sigma or FALLBACK_UNIT):.1f}σ）")
    if extreme is not None:
        text += f"；夜间一度到 {extreme:.2f}"
    return text + "。"


def format_merged(items: list[dict]) -> str:
    """One message for a burst: what moved, no claim about why."""
    downs = sum(1 for i in items if i.get("direction") == "down")
    lines = [f"【多股异动】5 分钟内 {len(items)} 只股票触发提醒（跌 {downs} / 涨 {len(items) - downs}）："]
    for item in items:
        body = item["text"].splitlines()[0]
        lines.append(f"· {body.split('】', 1)[-1]}")
    return "\n".join(lines)


def _position_line(signal: Signal, position: dict | None, total_assets: float | None, *, with_move: bool) -> str:
    if not position or not position.get("shares"):
        return ""
    shares = float(position["shares"])
    change = shares * (signal.price - signal.ref_price)
    text = f"\n持仓 {shares:g} 股"
    if with_move and signal.ref_price:
        word = "亏" if change < 0 else "赚"
        text += f"，这一波{word} {_money(change)}"
        if total_assets:
            text += f"，占总资产 {abs(change) / total_assets * 100:.2f}%"
    if total_assets and position.get("market_value") is not None:
        text += f"；现仓位占总资产 {position_weight(position, signal.price, total_assets) * 100:.1f}%"
    return text + "。"


def position_weight(position: dict, price: float, total_assets: float) -> float:
    """The position's share of total assets at ``price`` (total assets move with the position)."""
    shares = float(position.get("shares") or 0)
    old_value = float(position.get("market_value") or shares * price)
    value = shares * price
    assets = total_assets - old_value + value
    return value / assets if assets > 0 else 0.0
