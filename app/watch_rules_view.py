"""What the system watches for the owner, in one list: his own rules and the system defaults (the presets), with his settings.

Read-only.  ``watch_view`` is the one builder: ``GET /agent-chat/watch``, the ``list_watch_rules`` tool and the memory overview all read it.
``last_fired`` is read from the sentinel's store when it has the table (best effort)."""
from __future__ import annotations

import logging

from . import watch_presets, watch_rules

log = logging.getLogger(__name__)
OWN = "你自己定的规则"
DEFAULT = "系统默认"
SENSITIVITY_WORDS = watch_presets.SENSITIVITY_WORDS
FINISHED = "finished"      # the page's code for a ``once`` rule that has said everything (``watch_rules.DONE``)
DONE_CODE = {FINISHED: watch_rules.DONE}
YIELDS = {"position_weight": "concentration", "volume_ratio": "volume_surge", "down_days": "down_streak", "high_52w": "new_high_52w", "low_52w": "new_low_52w"}


def last_fired(rule_ids: list[str]) -> dict[str, str]:
    """{rule_id: "11-26 22:40（北京时间）"} for the rules the sentinel has a row for; empty when its store cannot be read."""
    found = watch_rules.fired_rows(rule_ids) or {}
    return {rid: watch_rules.when_beijing(max(at for _, _, at in rows)) for rid, rows in found.items() if rows}


def _tiers_text(sensitivity: str) -> str:
    word = SENSITIVITY_WORDS.get(sensitivity, "标准")
    return f"涨跌分级：按每只股票自己的日波动幅度（σ）分档，现在的灵敏度是「{word}」：{watch_presets.tiers_words(sensitivity)}。"


def _plan_prices(owner: str) -> dict[str, list[str]]:
    """The position plans' prices, by kind: ``{"add_target": [...], "stop": [...]}`` as ``INTC 补仓 40、目标 60`` lines."""
    from . import portfolio
    from .database import SessionLocal
    with SessionLocal() as db:
        plans = portfolio.load_plans(db, owner)
    found = {"add_target": [], "stop": []}
    for symbol, plan in sorted(plans.items()):
        for kind, keys in (("add_target", (("add_price", "补仓"), ("target_price", "目标"))), ("stop", (("stop_price", "止损"),))):
            parts = [f"{label} {float(plan[key]):g}" for key, label in keys if plan.get(key)]
            if parts:
                found[kind].append(f"{symbol} {'、'.join(parts)}")
    return found


COVERS = {"up": "上涨", "down": "下跌"}
NEVER_FIRED = "近 7 天没有触发"


def _override_word(direction: str) -> str:
    return COVERS.get(direction, "涨跌")


def _own_rules(owner: str) -> tuple[list[dict], dict]:
    """His rules as the page lists them, and the day-move directions each symbol's active rules cover."""
    mine = watch_rules.list_rules(owner)
    states = watch_rules.fired_rows([r["id"] for r in mine])
    out, covered = [], {}
    for rule in mine:
        fired = (states or {}).get(rule["id"]) or []
        status = watch_rules.status_of(rule, fired)
        note = None
        if status == watch_rules.ACTIVE and rule["metric"] == "day_change":      # only a rule that is still checked takes the default's place
            note = f"默认的{_override_word(rule['direction'])}分级对它不生效"
            covered.setdefault(rule["symbol"], set()).update({"up", "down"} if rule["direction"] == "either" else {rule["direction"]})
        elif status != watch_rules.EXPIRED and rule["metric"] in YIELDS:
            note = f"系统默认的「{watch_presets.CATALOG[YIELDS[rule['metric']]]['title']}」在 {rule['symbol']} 上让位给这条"
        out.append({"id": rule["id"], "symbol": rule["symbol"], "metric": rule["metric"], "direction": rule["direction"], "levels": rule["levels"],
                    "text": rule["text"], "status": FINISHED if status == watch_rules.DONE else status, "last_fired": watch_rules.when_beijing(max(at for _, _, at in fired)) if fired else None,
                    "overrides_default": note, "created_on": rule["created_on"], "expires_on": rule["expires_on"]})
    return out, covered


def _fixed_text(owner: str, key: str, settings: dict, covered: dict) -> str:
    if key == "day_tiers":
        moved = [f"{symbol}（{_override_word('either' if len(sides) == 2 else next(iter(sides)))}）" for symbol, sides in sorted(covered.items())]
        return _tiers_text(settings["sensitivity"]) + (f"你为{'、'.join(moved)}定了自己的涨跌规则，默认的分级在这些方向上对它们不生效。" if moved else "")
    plans = _plan_prices(owner)
    if key == "plan_prices":
        return "持仓计划里的补仓价和目标价：" + ("；".join(plans["add_target"]) + "。" if plans["add_target"] else "你还没写。") + "价位在持仓计划里改。"
    if key == "stop_price":
        return "持仓计划里的止损价：" + ("；".join(plans["stop"]) + "。" if plans["stop"] else "你还没写。") + "跌破就会提醒你，不受你的规则和设置影响。这条是硬保证，不能关。"
    if key == "short_moves":
        return f"5 分钟急动提醒：{'开' if settings['short_moves'] else '关'}。"
    return "新公告（SEC 申报）：盯你的持仓和研究队列。这条是硬保证，不能关。"


def watch_view(owner: str) -> dict:
    """``{"rules": [...], "presets": [...], "settings": {...}}``: the contract of ``GET /agent-chat/watch`` (``docs/superpowers/plans/2026-11-26-stage5b2-preset-rules.md``)."""
    rules, covered = _own_rules(owner)
    live = [r for r in rules if r["status"] != watch_rules.EXPIRED]      # what the sentinel is handed: an expired rule is not
    settings = watch_presets.settings_view(owner)
    presets = []
    for preset in watch_presets.resolved(owner):
        key = preset["preset_key"]
        metric = preset["metric"]
        presets.append({"key": key, "title": watch_presets.CATALOG[key]["title"], "text": preset["text"], "enabled": preset["enabled"],
                        "levels": preset["levels"], "editable": True, "hard_guarantee": False, "applies_to": watch_presets.APPLIES[preset["scope"]],
                        "yields_on": sorted({r["symbol"] for r in live if r["metric"] == metric}),
                        "changed": preset["changed"], "threshold_editable": watch_presets.CATALOG[key]["thresholds"],
                        "unit": watch_presets.UNITS.get(metric) if watch_presets.CATALOG[key]["thresholds"] else None})
    for key, spec in watch_presets.FIXED.items():
        yields = sorted({r["symbol"] for r in live if r["metric"] == "day_change"}) if key == "day_tiers" else []
        presets.append({"key": key, "title": spec["title"], "text": _fixed_text(owner, key, settings, covered),
                        "enabled": settings["short_moves"] if key == "short_moves" else True, "levels": None, "editable": False,
                        "hard_guarantee": spec["hard"], "applies_to": "持仓和研究队列" if key not in ("plan_prices", "stop_price") else "写了计划价位的持仓",
                        "yields_on": yields, "changed": False, "threshold_editable": False, "unit": None})
    return {"rules": rules, "presets": presets, "settings": settings}


def rows(owner: str) -> list[dict]:
    """The same view as a flat list for ``list_watch_rules``: his own rules, then every system default (marked 系统默认, with its on/off)."""
    view = watch_view(owner)
    known = bool(watch_rules.fired_rows([r["id"] for r in view["rules"]]) is not None) if view["rules"] else False
    out = []
    for rule in view["rules"]:
        row = {"kind": OWN, "id": rule["id"], "symbol": rule["symbol"], "text": rule["text"], "created_on": rule["created_on"], "expires_on": rule["expires_on"],
               "status": watch_rules.STATUS_WORDS.get(DONE_CODE.get(rule["status"], rule["status"]), "生效中"),
               "last_fired": rule["last_fired"] or (NEVER_FIRED if known else None)}
        if rule["overrides_default"]:
            row["note"] = rule["overrides_default"]
        out.append(row)
    for preset in view["presets"]:
        off = "" if preset["enabled"] or preset["key"] == "short_moves" else "（现在关着）"
        out.append({"kind": DEFAULT, "key": preset["key"], "title": preset["title"], "enabled": preset["enabled"],
                    "hard_guarantee": preset["hard_guarantee"], "text": preset["text"] + off,
                    **({"yields_on": preset["yields_on"]} if preset["yields_on"] else {})})
    return out
