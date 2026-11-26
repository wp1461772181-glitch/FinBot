"""Replay of the sentinel's price-alert policy over stored 5-minute bars (stdlib only; never imports ``app``).

It steps every five minutes through each New York session (04:00-20:00), builds the bars the live loop would have seen,
and runs the real ``Sentinel.alerts_from`` + ``flush`` with the escalator replaced by a collector.  Nothing is sent and
nothing touches the network here: ``fetch_data`` is the only function that does, and the CLI calls it by hand.

Limits, written down because they change the numbers a little: the live loop reads 1-minute bars and the replay reads
5-minute bars (each stamped at the last minute of its period), so a 5-minute "short" window is one bar and the volume
check sums five bars, not five minutes; the sentinel's baseline is rebuilt once per replayed date from the bars before it;
the night rule (Beijing 00:00-08:00) is not applied, so alerts the live system would have held for the digest are listed too."""

from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
from datetime import UTC, date, datetime, time as dtime, timedelta
from pathlib import Path

from . import signals
from .main import Sentinel
from .store import Store

STEP = timedelta(minutes=5)
PRICE_KINDS = ("short", "daily", "gap", "update", "merged", "plan_add", "plan_stop", "plan_target")


def fetch_data(symbols: list[str]) -> dict:
    """Yahoo 5-minute bars (60 days, pre/post) and daily bars for each symbol, with the sentinel's own fetcher."""
    data: dict = {"bars5": {}, "daily": {}, "errors": {}}
    for symbol in symbols:
        try:
            data["bars5"][symbol] = signals.fetch_chart(symbol, "5m", "60d", events=True)["bars"]
            data["daily"][symbol] = signals.fetch_chart(symbol, "1d", "3mo", prepost=False, events=True)["bars"]
        except Exception as exc:                                  # a refused or rate-limited symbol: say so, go on
            data["errors"][symbol] = f"{type(exc).__name__}: {exc}"
    return data


def dump_data(data: dict, path: Path | str) -> None:
    def enc(bar):
        return {"ts": bar["ts"].isoformat(), "close": bar["close"], "volume": bar.get("volume")}
    out = {"errors": data.get("errors", {}), **{k: {s: [enc(b) for b in bars] for s, bars in data[k].items()}
                                                 for k in ("bars5", "daily")}}
    Path(path).write_text(json.dumps(out), encoding="utf-8")


def load_data(path: Path | str) -> dict:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    def dec(bar):
        return {"ts": datetime.fromisoformat(bar["ts"]), "close": bar["close"], "volume": bar.get("volume")}
    return {"errors": raw.get("errors", {}), **{k: {s: [dec(b) for b in bars] for s, bars in raw[k].items()}
                                                 for k in ("bars5", "daily")}}


class Collector:
    """Stands in for the escalator: records what would have been sent, and keeps the alerts table the merge rules read."""

    def __init__(self, store: Store) -> None:
        self.store, self.now, self.sent = store, 0.0, []

    def raise_alert(self, snap: dict, alert: dict) -> int:
        self.sent.append({"ts": self.now, "alert": alert})
        return self.store.add_alert(alert["symbol"], alert.get("kind", ""), alert["text"], bool(alert.get("escalate")),
                                    self.now)

    def deferred(self, alert_id) -> bool:
        return False


def _sessions(start: date, end: date, bars5: dict) -> list[date]:
    days, cursor = [], start
    have = {signals._et(b["ts"]).date() for bars in bars5.values() for b in bars if signals._bar_ok(b)}
    while cursor <= end:
        if cursor.weekday() < 5 and cursor in have:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def run_replay(data: dict, snapshot: dict, start: date, end: date, *, policy: str = "tiers",
               sensitivity: str = "standard", short_moves: bool = False, workdir: Path | str | None = None) -> dict:
    """``{"alerts": [...], "records": [...], "trace": {symbol: [(ts, r, sigma_mult), ...]}, "symbols": [...]}``."""
    workdir = Path(workdir or tempfile.mkdtemp(prefix="sentinel-replay-"))
    store = Store(workdir / "replay.db")
    sentinel = Sentinel(config=signals.SnapshotConfig(workdir / "none.json"), store=store)
    collector = Collector(store)
    sentinel.escalator, sentinel._announce = collector, lambda *a, **k: None
    sentinel.policy, sentinel.sensitivity, sentinel.short_moves = policy, sensitivity, short_moves
    held = [p["symbol"] for p in snapshot.get("positions") or [] if p.get("symbol") and p.get("shares")]
    queue = [s for s in snapshot.get("research_queue") or [] if s not in held]
    symbols = [s for s in held + queue if s in data["bars5"]]
    bars5 = {s: sorted((b for b in data["bars5"][s] if signals._bar_ok(b)), key=lambda b: b["ts"])
             for s in set(symbols) | {"SPY"} if s in data["bars5"]}
    alerts, trace = [], {s: [] for s in symbols}
    baselines: dict = {}

    def baseline_of(symbol: str, day: date) -> dict:
        key = (symbol, day)
        if key not in baselines:
            cut = datetime.combine(day, dtime(0, 0), tzinfo=signals.ET)
            prior = [b for b in bars5.get(symbol, []) if b["ts"] < cut]
            baselines[key] = signals.compute_baseline(prior, cut.astimezone(UTC)) if prior else {}
        return baselines[key]

    def visible(symbol: str, now: datetime) -> list[dict]:
        out = [{**b, "ts": b["ts"] + timedelta(minutes=4)} for b in bars5.get(symbol, [])
               if b["ts"] + STEP <= now and now - b["ts"] <= timedelta(days=1)]
        return out

    for day in _sessions(start, end, bars5):
        moment = datetime.combine(day, dtime(4, 5), tzinfo=signals.ET)
        stop = datetime.combine(day, dtime(20, 0), tzinfo=signals.ET)
        while moment < stop:
            now = moment.astimezone(UTC)
            moment += STEP
            sentinel._market = None
            if policy == "tiers" and "SPY" in bars5:
                spy = [b for b in visible("SPY", now) if signals._bar_ok(b)]
                spy_prev = signals.prev_close_from_daily(data["daily"].get("SPY", []), now)
                if spy and spy_prev and not signals.is_stale(spy[-1]["ts"], now):
                    sentinel._market = {"r": float(spy[-1]["close"]) / spy_prev - 1,
                                        "sigma": baseline_of("SPY", day).get("daily_sigma")}
            collected: list[dict] = []
            for symbol in symbols:
                series = visible(symbol, now)
                prev_close = signals.prev_close_from_daily(data["daily"].get(symbol, []), now)
                if not series or prev_close is None:
                    continue
                base = baseline_of(symbol, day)
                last = series[-1]
                if signals._bar_ok(last) and not signals.is_stale(last["ts"], now):
                    r = float(last["close"]) / prev_close - 1
                    trace[symbol].append((now.timestamp(), r, abs(r) / (base.get("daily_sigma") or 0.02)))
                try:
                    collected += sentinel.alerts_from(symbol, symbol in held, now, snapshot, series, prev_close, base, [])
                except Exception as exc:                          # one symbol's bad data must not end the replay
                    alerts.append({"ts": now.timestamp(), "symbol": symbol, "kind": "error", "tier": "", "text": repr(exc),
                                   "escalate": False, "symbols": [symbol]})
            collector.now, collector.sent = now.timestamp(), []
            sentinel.flush(collected, snapshot, now)
            for item in collector.sent:
                a = item["alert"]
                alerts.append({"ts": item["ts"], "symbol": a["symbol"], "kind": a.get("kind", ""),
                               "tier": a.get("tier", ""), "text": a["text"], "escalate": bool(a.get("escalate")),
                               "symbols": a.get("symbols") or [a["symbol"]], "sigma_mult": a.get("sigma_mult", "")})
    records = [{"ts": r["created_at"], "symbol": r["symbol"], "text": r["digest_text"] or r["text"]}
               for r in store.alerts_where("kind = 'record'")]
    return {"alerts": alerts, "records": records, "trace": trace, "symbols": symbols, "policy": policy}


def _nearest(series: list[tuple], ts: float) -> tuple | None:
    best = min(series, key=lambda row: abs(row[0] - ts), default=None)
    return best if best is not None and abs(best[0] - ts) <= 15 * 60 else None


def sigma_at(result: dict, symbol: str, ts: float) -> float | None:
    row = _nearest(result["trace"].get(symbol, []), ts)
    return None if row is None else row[2]


def counts(result: dict) -> dict:
    """Alerts per symbol and per tier (merged messages count under their own name)."""
    per_symbol: dict[str, int] = {}
    per_tier: dict[str, int] = {}
    for a in result["alerts"]:
        per_symbol[a["symbol"]] = per_symbol.get(a["symbol"], 0) + 1
        key = str(a["tier"]) if a["tier"] != "" else "-"
        per_tier[key] = per_tier.get(key, 0) + 1
    return {"total": len(result["alerts"]), "per_symbol": dict(sorted(per_symbol.items())),
            "per_tier": dict(sorted(per_tier.items())), "digest_lines": len(result["records"])}


def _clock(ts: float, zone) -> str:
    return datetime.fromtimestamp(ts, zone).strftime("%m-%d %H:%M")


def write_alerts_csv(result: dict, path: Path | str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time_et", "time_bj", "symbol", "tier", "kind", "escalate", "sigma_mult", "text"])
        for a in result["alerts"]:
            mult = a.get("sigma_mult")
            if mult in ("", None) and a["symbol"] in result["trace"]:
                mult = sigma_at(result, a["symbol"], a["ts"])
            writer.writerow([_clock(a["ts"], signals.ET), _clock(a["ts"], signals.BEIJING), a["symbol"], a["tier"], a["kind"],
                             int(a["escalate"]), "" if mult in ("", None) else f"{float(mult):.1f}", a["text"].replace("\n", " / ")])


def compare_actual(db_path: Path | str, result: dict, start: date, end: date, window: float = 30 * 60) -> list[dict]:
    """Each alert the live sentinel really sent (the ``alerts`` table of a copy of its sentinel.db) against the
    replayed alerts within +-30 minutes on the same symbol.  An unmatched one says how big the move was then."""
    lo = datetime.combine(start, dtime(0, 0), tzinfo=signals.ET).timestamp()
    hi = datetime.combine(end + timedelta(days=1), dtime(0, 0), tzinfo=signals.ET).timestamp()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, symbol, kind, text, escalate, created_at FROM alerts WHERE created_at >= ?"
                            " AND created_at < ? ORDER BY created_at", (lo, hi)).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        if row["kind"] not in PRICE_KINDS:
            continue
        symbols = row["symbol"].split("+")
        near = [a for a in result["alerts"] if abs(a["ts"] - row["created_at"]) <= window
                and any(s in a["symbols"] for s in symbols)]
        entry = {"id": row["id"], "time_et": _clock(row["created_at"], signals.ET), "symbol": row["symbol"],
                 "kind": row["kind"], "text": row["text"].splitlines()[0] if row["text"] else ""}
        if near:
            best = near[0]
            entry |= {"would_send": True, "new_time_et": _clock(best["ts"], signals.ET), "new_tier": best["tier"],
                      "new_kind": best["kind"], "why_not": ""}
        else:
            mults = [m for m in (sigma_at(result, s, row["created_at"]) for s in symbols) if m is not None]
            if not mults:
                why = "回放没有当时的价格"
            elif max(mults) < 2:
                why = f"当时只有约 {max(mults):.1f} 倍日常波动，不到标准档的 2 倍，也没有穿过价位"
            else:
                why = f"当时约 {max(mults):.1f} 倍日常波动，但同一方向已经提醒过（每档每个方向一天一次），或价位还在锁内"
            entry |= {"would_send": False, "new_time_et": "", "new_tier": "", "new_kind": "", "why_not": why}
        out.append(entry)
    return out


def write_summary(result: dict, path: Path | str, *, title: str, args_line: str, notes: list[str],
                  comparison: list[dict] | None = None) -> None:
    c = counts(result)
    lines = [f"# {title}", "", f"命令：`{args_line}`", ""]
    lines += [f"- 发出 {c['total']} 条；夜间简报行（不到档、过 1 倍日常波动）{c['digest_lines']} 条", ""]
    lines += ["| 股票 | 条数 |", "|---|---|"] + [f"| {s} | {n} |" for s, n in c["per_symbol"].items()]
    lines += ["", "| 档位 | 条数 |", "|---|---|"] + [f"| {t} | {n} |" for t, n in c["per_tier"].items()]
    if notes:
        lines += ["", "说明："] + [f"- {n}" for n in notes]
    if comparison is not None:
        sent = sum(1 for e in comparison if e["would_send"])
        lines += ["", f"## 与实际提醒对照（实际 {len(comparison)} 条价格类提醒，新规则也会发 {sent} 条）", "",
                  "| 实际时间(ET) | 股票 | 类型 | 新规则 | 说明 |", "|---|---|---|---|---|"]
        for e in comparison:
            verdict = f"会发（{e['new_time_et']}，档 {e['new_tier']}）" if e["would_send"] else "不会发"
            lines.append(f"| {e['time_et']} | {e['symbol']} | {e['kind']} | {verdict} | {e['why_not']} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
