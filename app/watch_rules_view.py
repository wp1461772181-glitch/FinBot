"""What the system watches for the owner, in one list (``list_watch_rules``): his own rules and the defaults that apply today.

Read-only.  The defaults are static text written here from the sentinel's constants (5b-2 makes them editable); a symbol with an owner day-move
rule is marked as not getting the default move tiers.  ``last_fired`` is read from the sentinel's store when it has the table (best effort)."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from . import watch_rules

log = logging.getLogger(__name__)
OWN = "你自己定的规则"
DEFAULT = "系统默认"
NOT_APPLIED = "默认的涨跌分级对它不生效"
SENSITIVITY_WORDS = {"quiet": "安静", "standard": "标准", "sensitive": "敏感"}


def _sentinel_db() -> Path:
    env = os.environ.get("SENTINEL_DB_PATH")
    return Path(env) if env else Path(__file__).resolve().parent.parent / "data" / "sentinel.db"


def last_fired(rule_ids: list[str]) -> dict[str, str]:
    """{rule_id: when} from the sentinel's ``rule_state`` table; empty when the table or the file is not there."""
    path = _sentinel_db()
    if not rule_ids or not path.is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = conn.execute("SELECT rule_id, MAX(fired_at) FROM rule_state GROUP BY rule_id").fetchall()
        finally:
            conn.close()
    except Exception:
        return {}
    from datetime import UTC, datetime
    wanted = set(rule_ids)
    return {rid: datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M") for rid, at in rows if rid in wanted and at}


def _tiers_text(sensitivity: str) -> str:
    try:
        from sentinel.tiers import thresholds
        low, high = thresholds(sensitivity)
        numbers = f"约 {low:g}σ 值得提醒，{high:g}σ 算重大"
    except Exception:
        numbers = "分值得提醒和重大两档"
    word = SENSITIVITY_WORDS.get(sensitivity, "标准")
    return f"涨跌分级：按每只股票自己的日波动幅度（σ）分档，现在的灵敏度是「{word}」：{numbers}。"


def _plan_prices(owner: str) -> list[str]:
    from . import portfolio
    from .database import SessionLocal
    with SessionLocal() as db:
        plans = portfolio.load_plans(db, owner)
    found = []
    for symbol, plan in sorted(plans.items()):
        parts = [f"{label} {float(plan[key]):g}" for key, label in (("add_price", "补仓"), ("stop_price", "止损"), ("target_price", "目标")) if plan.get(key)]
        if parts:
            found.append(f"{symbol} {'、'.join(parts)}")
    return found


def rows(owner: str) -> list[dict]:
    mine = watch_rules.list_rules(owner)
    fired = last_fired([r["id"] for r in mine])
    moved = sorted({r["symbol"] for r in mine if r["metric"] == "day_change"})
    out = []
    for rule in mine:
        row = {"kind": OWN, "id": rule["id"], "symbol": rule["symbol"], "text": rule["text"], "created_on": rule["created_on"],
               "expires_on": rule["expires_on"], "last_fired": fired.get(rule["id"])}
        if rule["metric"] == "day_change":
            row["note"] = NOT_APPLIED
        out.append(row)
    sensitivity = (os.environ.get("SENTINEL_SENSITIVITY") or "standard").strip().lower()
    tiers = _tiers_text(sensitivity) + (f"{'、'.join(moved)} {NOT_APPLIED}（你为它定了自己的涨跌规则）。" if moved else "")
    prices = _plan_prices(owner)
    short = (os.environ.get("SENTINEL_SHORT_MOVES") or "").strip().lower() in {"on", "1", "true", "yes"}
    out += [{"kind": DEFAULT, "text": tiers},
            {"kind": DEFAULT, "text": "持仓计划里的价位线（补仓价、止损价、目标价）：" + ("；".join(prices) if prices else "你还没写。") + " 止损价永远会盯，不受你的规则影响。"},
            {"kind": DEFAULT, "text": f"5 分钟急动提醒：{'开' if short else '关'}。"},
            {"kind": DEFAULT, "text": "新公告（SEC 申报）：盯你的持仓和研究队列。"}]
    return out
