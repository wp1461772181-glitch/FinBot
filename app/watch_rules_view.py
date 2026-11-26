"""What the system watches for the owner, in one list (``list_watch_rules``): his own rules and the defaults that apply today.

Read-only.  The defaults are static text written here from the sentinel's constants (5b-2 makes them editable); a symbol with an owner day-move
rule is marked as not getting the default move tiers.  ``last_fired`` is read from the sentinel's store when it has the table (best effort)."""
from __future__ import annotations

import logging
import os
from . import watch_rules

log = logging.getLogger(__name__)
OWN = "你自己定的规则"
DEFAULT = "系统默认"
SENSITIVITY_WORDS = {"quiet": "安静", "standard": "标准", "sensitive": "敏感"}


def last_fired(rule_ids: list[str]) -> dict[str, str]:
    """{rule_id: "11-26 22:40（北京时间）"} for the rules the sentinel has a row for; empty when its store cannot be read."""
    found = watch_rules.fired_rows(rule_ids) or {}
    return {rid: watch_rules.when_beijing(max(at for _, _, at in rows)) for rid, rows in found.items() if rows}


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


COVERS = {"up": "上涨", "down": "下跌"}
NEVER_FIRED = "近 7 天没有触发"


def _override_word(direction: str) -> str:
    return COVERS.get(direction, "涨跌")


def rows(owner: str) -> list[dict]:
    mine = watch_rules.list_rules(owner)
    states = watch_rules.fired_rows([r["id"] for r in mine])
    out, covered = [], {}
    for rule in mine:
        status = watch_rules.status_of(rule, (states or {}).get(rule["id"]))
        fired = (states or {}).get(rule["id"]) or []
        row = {"kind": OWN, "id": rule["id"], "symbol": rule["symbol"], "text": rule["text"], "created_on": rule["created_on"],
               "expires_on": rule["expires_on"], "status": watch_rules.STATUS_WORDS.get(status, "生效中"),
               "last_fired": watch_rules.when_beijing(max(at for _, _, at in fired)) if fired else (NEVER_FIRED if states is not None else None)}
        if status == watch_rules.ACTIVE and rule["metric"] == "day_change":      # only a rule that is still checked takes the default's place
            row["note"] = f"默认的{_override_word(rule['direction'])}分级对它不生效"
            covered.setdefault(rule["symbol"], set()).update({"up", "down"} if rule["direction"] == "either" else {rule["direction"]})
        out.append(row)
    sensitivity = (os.environ.get("SENTINEL_SENSITIVITY") or "standard").strip().lower()
    moved = [f"{symbol}（{_override_word('either' if len(sides) == 2 else next(iter(sides)))}）" for symbol, sides in sorted(covered.items())]
    tiers = _tiers_text(sensitivity) + (f"你为{'、'.join(moved)}定了自己的涨跌规则，默认的分级在这些方向上对它们不生效。" if moved else "")
    prices = _plan_prices(owner)
    short = (os.environ.get("SENTINEL_SHORT_MOVES") or "").strip().lower() in {"on", "1", "true", "yes"}
    out += [{"kind": DEFAULT, "text": tiers},
            {"kind": DEFAULT, "text": "持仓计划里的价位线（补仓价、止损价、目标价）：" + ("；".join(prices) if prices else "你还没写。") + " 止损价永远会盯，不受你的规则影响。"},
            {"kind": DEFAULT, "text": f"5 分钟急动提醒：{'开' if short else '关'}。"},
            {"kind": DEFAULT, "text": "新公告（SEC 申报）：盯你的持仓和研究队列。"}]
    return out
