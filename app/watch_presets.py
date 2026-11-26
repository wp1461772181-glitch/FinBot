"""The system's own watch rules, made visible and editable (「系统默认」, stage 5b-2).

The catalog below is code: six default rules the sentinel checks next to the owner's own rules (``app/watch_rules.py``).  The owner can switch each off
or give it other levels (a row in ``watch_preset_overrides``; no row means the default; deleting the row is 「恢复默认」).  A few things that are also
"system defaults" are listed but are not edited here: the day-move tiers (the sensitivity), the 5-minute moves (their switch), the plan prices (the
position plan), and the stop price and filings, which are hard guarantees: nothing turns them off, and no rule of the owner's makes them yield.

Every text is written here by code from the fields.  The sentinel gets ``snapshot_presets`` (the enabled ones, resolved with his overrides, in the shape
of a rule plus ``source``, ``preset_key`` and ``scope``) and ``settings`` in its snapshot; it never imports this module.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

from sqlalchemy import select

from . import watch_rules
from .agent_chat_models import AlertSetting, WatchPresetOverride
from .database import SessionLocal
from .watch_rules import PORTFOLIO, WatchRuleError

HOLDINGS, WATCHED, PORTFOLIO_SCOPE = "holdings", "watched", "portfolio"
SUBJECTS = {HOLDINGS: "每只持仓", WATCHED: "持仓和研究队列里的每只股票", PORTFOLIO_SCOPE: "你的组合"}
APPLIES = {HOLDINGS: "所有持仓", WATCHED: "持仓和研究队列", PORTFOLIO_SCOPE: "整个组合"}
UNITS = {"position_weight": "%", "portfolio_day_change": "%", "down_days": "天", "volume_ratio": "倍"}
HARD_REASON = "这条是硬保证，不能关。"
MAX_SYMBOLS = 30
NIGHT_NOTE = "夜里（北京时间 0–8 点）「提醒」会攒进早上的汇总，「加急」照常马上发。"

# key -> the preset (the table of the plan).  ``thresholds``: whether the number can be changed (a 52-week high has none).
CATALOG: dict[str, dict] = {
    "concentration": {"title": "单只占比过高", "scope": HOLDINGS, "metric": "position_weight", "direction": "above", "thresholds": True,
                      "levels": [{"threshold": 25, "level": "remind"}]},
    "portfolio_drawdown": {"title": "组合当日大跌", "scope": PORTFOLIO_SCOPE, "metric": "portfolio_day_change", "direction": "down", "thresholds": True,
                           "levels": [{"threshold": 3, "level": "remind"}, {"threshold": 5, "level": "urgent"}]},
    "down_streak": {"title": "连续下跌", "scope": WATCHED, "metric": "down_days", "direction": "down", "thresholds": True,
                    "levels": [{"threshold": 5, "level": "remind"}]},
    "new_high_52w": {"title": "52 周新高", "scope": WATCHED, "metric": "high_52w", "direction": "above", "thresholds": False,
                     "levels": [{"threshold": 0, "level": "remind"}]},
    "new_low_52w": {"title": "52 周新低", "scope": WATCHED, "metric": "low_52w", "direction": "below", "thresholds": False,
                    "levels": [{"threshold": 0, "level": "remind"}]},
    "volume_surge": {"title": "成交量异常放大", "scope": HOLDINGS, "metric": "volume_ratio", "direction": "above", "thresholds": True,
                     "levels": [{"threshold": 3, "level": "remind"}]},
}
# Listed next to the presets, not editable here.  ``hard``: a guarantee nothing can switch off.
FIXED: dict[str, dict] = {
    "day_tiers": {"title": "涨跌分级", "hard": False, "why": "涨跌分级的松紧由「灵敏度」决定，请改灵敏度。"},
    "short_moves": {"title": "5 分钟急动", "hard": False, "why": "5 分钟急动由它自己的开关管，请改「5 分钟急动」的开关。"},
    "plan_prices": {"title": "计划价位（补仓价、目标价）", "hard": False, "why": "补仓价和目标价在持仓计划里改。"},
    "stop_price": {"title": "止损价", "hard": True, "why": HARD_REASON},
    "filings": {"title": "新公告（SEC 申报）", "hard": True, "why": HARD_REASON},
}
SENSITIVITIES = ("quiet", "standard", "sensitive")
SENSITIVITY_WORDS = {"quiet": "安静", "standard": "标准", "sensitive": "灵敏"}
try:
    from sentinel.tiers import SENSITIVITY as _TIERS
except Exception:      # the sentinel package is not importable: the same numbers
    _TIERS = {"quiet": (2.5, 5.0), "standard": (2.0, 4.0), "sensitive": (1.5, 3.0)}
DEFAULT_SENSITIVITY = "standard"
TRUE_WORDS = {"on", "1", "true", "yes"}


def refusal(code: str, reason: str) -> WatchRuleError:
    return WatchRuleError(code, reason)


# --- the rule of a preset -------------------------------------------------------------------------------------------------------

def _rule(key: str, levels: list[dict]) -> dict:
    """The preset as a rule of the contract (``source: preset``); ``text`` is written by ``watch_rules.describe``."""
    spec = CATALOG[key]
    rule = {"id": f"preset:{key}", "preset_key": key, "source": "preset", "scope": spec["scope"], "symbol": PORTFOLIO, "metric": spec["metric"],
            "direction": spec["direction"], "levels": [dict(level) for level in levels], "window_days": None, "repeat": "daily",
            "expires_on": None, "created_on": None}
    return {**rule, "text": watch_rules.describe(rule, subject=SUBJECTS[spec["scope"]])}


def _check_levels(key: str, raw) -> list[dict]:
    """The levels in their stored form, or the owner's reason why not: the shape and the per-metric rules are the rule validation's own."""
    spec = CATALOG[key]
    if not spec["thresholds"]:
        raise refusal("not_editable", "这条没有数值可改，只能开或关。")
    try:
        items = [{"threshold": item["threshold"], "level": item["level"]} for item in raw]
    except (KeyError, TypeError):
        raise refusal("invalid_levels", "每一档要有数值 threshold 和级别 level（remind 或 urgent）。")
    return watch_rules.validate({"symbol": PORTFOLIO, "metric": spec["metric"], "direction": spec["direction"], "levels": items}, preset=True)["levels"]


def _overrides(owner: str) -> dict[str, WatchPresetOverride]:
    with SessionLocal() as db:
        rows = db.scalars(select(WatchPresetOverride).where(WatchPresetOverride.owner_hash == owner)).all()
        db.expunge_all()
    return {row.preset_key: row for row in rows if row.preset_key in CATALOG}


def _resolve(key: str, override) -> tuple[bool, list[dict]]:
    levels = [dict(level) for level in (override.levels if override is not None and override.levels else CATALOG[key]["levels"])]
    return (override.enabled if override is not None else True), levels


def resolved(owner: str) -> list[dict]:
    """Every preset with his overrides laid over the defaults: ``[{**rule, "enabled": bool}]`` in catalog order."""
    rows = _overrides(owner)
    out = []
    for key in CATALOG:
        enabled, levels = _resolve(key, rows.get(key))
        out.append({**_rule(key, levels), "enabled": enabled, "changed": key in rows})
    return out


def snapshot_presets(owner: str) -> list[dict]:
    """What the sentinel gets: the enabled presets (the contract's ``presets`` section)."""
    return [{k: v for k, v in preset.items() if k not in ("enabled", "changed")} for preset in resolved(owner) if preset["enabled"]]


def preset_row(owner: str, key: str) -> dict:
    """One preset as the route returns it (the view's row, with yields)."""
    from . import watch_rules_view
    return next(row for row in watch_rules_view.watch_view(owner)["presets"] if row["key"] == key)


# --- changing one ---------------------------------------------------------------------------------------------------------------

def check_key(key: str, *, change: bool = True) -> None:
    """``WatchRuleError`` unless ``key`` is a preset the owner may change: an unknown key, a hard guarantee and the fixed ones each say why."""
    if key in CATALOG:
        return
    if key in FIXED:
        raise refusal("hard_guarantee" if FIXED[key]["hard"] else "not_editable", FIXED[key]["why"])
    raise refusal("unknown_preset", "没有这条系统默认规则。")


def merged(owner: str, key: str, enabled=None, levels=None, reset: bool = False) -> tuple[bool, list[dict]]:
    """(enabled, levels) the preset would have after the change (nothing is written).  Levels are checked here.  ``reset``: the default."""
    check_key(key)
    if reset:
        if enabled is not None or levels is not None:
            raise refusal("invalid_reset", "恢复默认时不要再给别的：它就是回到默认的开关和数值。")
        return True, [dict(level) for level in CATALOG[key]["levels"]]
    if enabled is None and levels is None:
        raise refusal("nothing_to_change", "没有要改的：要说开还是关，或者给新的数值。")
    now_enabled, now_levels = _resolve(key, _overrides(owner).get(key))
    return (now_enabled if enabled is None else bool(enabled)), (now_levels if levels is None else _check_levels(key, levels))


def set_override(owner: str, key: str, enabled: bool | None = None, levels=None) -> dict:
    """Change one preset (only what is given); back to the default on both counts removes the row.  Returns the preset's row."""
    new_enabled, new_levels = merged(owner, key, enabled, levels)
    return put(owner, key, new_enabled, new_levels)


def put(owner: str, key: str, new_enabled: bool, new_levels: list[dict]) -> dict:
    """Set one preset to exactly these values (what a pressed card froze); equal to the default removes the row.  Returns the preset's row."""
    check_key(key)
    new_levels = _check_levels(key, new_levels) if CATALOG[key]["thresholds"] else [dict(level) for level in CATALOG[key]["levels"]]
    default = CATALOG[key]["levels"]
    with SessionLocal() as db:
        row = db.get(WatchPresetOverride, (owner, key))
        if new_enabled and new_levels == default:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(WatchPresetOverride(owner_hash=owner, preset_key=key, enabled=new_enabled, levels=None if new_levels == default else new_levels))
        else:
            row.enabled, row.levels = new_enabled, None if new_levels == default else new_levels
        db.commit()
    _refresh()
    return preset_row(owner, key)


def reset(owner: str, key: str) -> dict:
    """Back to the default (the row is deleted)."""
    check_key(key)
    with SessionLocal() as db:
        row = db.get(WatchPresetOverride, (owner, key))
        if row is not None:
            db.delete(row)
            db.commit()
    _refresh()
    return preset_row(owner, key)


def _refresh() -> None:
    from .sentinel_bridge import refresh_sentinel_snapshot
    refresh_sentinel_snapshot()


# --- the settings ---------------------------------------------------------------------------------------------------------------

def _env_defaults() -> dict:
    """What he has not chosen yet: the box's environment (as the sentinel read it before 5b-2), then standard and off."""
    sensitivity = (os.environ.get("SENTINEL_SENSITIVITY") or "").strip().lower()
    return {"sensitivity": sensitivity if sensitivity in SENSITIVITIES else DEFAULT_SENSITIVITY,
            "short_moves": (os.environ.get("SENTINEL_SHORT_MOVES") or "").strip().lower() in TRUE_WORDS}


def get_settings(owner: str) -> dict:
    with SessionLocal() as db:
        row = db.get(AlertSetting, owner)
        if row is None:
            return _env_defaults()      # env only fills in until he has chosen: the stored row, when present, wins over env by design
        return {"sensitivity": row.sensitivity if row.sensitivity in SENSITIVITIES else DEFAULT_SENSITIVITY, "short_moves": bool(row.short_moves)}


def check_settings(sensitivity=None, short_moves=None) -> dict:
    if sensitivity is None and short_moves is None:
        raise refusal("nothing_to_change", "没有要改的：要说灵敏度（安静、标准、灵敏），或 5 分钟急动开还是关。")
    if sensitivity is not None and sensitivity not in SENSITIVITIES:
        raise refusal("invalid_sensitivity", "灵敏度只有三档：安静（quiet）、标准（standard）、灵敏（sensitive）。")
    if short_moves is not None and not isinstance(short_moves, bool):
        raise refusal("invalid_short_moves", "5 分钟急动只能是开（true）或关（false）。")
    return {k: v for k, v in (("sensitivity", sensitivity), ("short_moves", short_moves)) if v is not None}


def set_settings(owner: str, sensitivity=None, short_moves=None) -> dict:
    change = check_settings(sensitivity, short_moves)
    now = {**get_settings(owner), **change}
    with SessionLocal() as db:
        row = db.get(AlertSetting, owner)
        if row is None:
            db.add(AlertSetting(owner_hash=owner, **now))
        else:
            row.sensitivity, row.short_moves = now["sensitivity"], now["short_moves"]
        db.commit()
    _refresh()
    return settings_view(owner)


def tier_numbers(sensitivity: str) -> list[float]:
    low, high = _TIERS.get(sensitivity, _TIERS[DEFAULT_SENSITIVITY])
    return [low, high]


def tiers_words(sensitivity: str) -> str:
    low, high = tier_numbers(sensitivity)
    return f"约 {low:g}σ 提醒、{high:g}σ 重大"


def settings_view(owner: str) -> dict:
    return {**get_settings(owner), "thresholds": {name: dict(zip(("remind", "major"), tier_numbers(name))) for name in SENSITIVITIES}}


def settings_card(owner: str, change: dict) -> tuple[dict, str]:
    """(the settings after the change, the card text): what changes, in words, with the threshold table for the chosen sensitivity."""
    old = get_settings(owner)
    new = {**old, **change}
    lines = []
    if new["sensitivity"] != old["sensitivity"]:
        was, now = tier_numbers(old["sensitivity"]), tier_numbers(new["sensitivity"])
        calmer = now[0] > was[0]
        lines.append(f"灵敏度：{SENSITIVITY_WORDS[old['sensitivity']]} → {SENSITIVITY_WORDS[new['sensitivity']]}。"
                     f"涨跌按每只股票自己平时一天的波动幅度（σ）分档：原来{SENSITIVITY_WORDS[old['sensitivity']]}（{tiers_words(old['sensitivity'])}），"
                     f"改后{SENSITIVITY_WORDS[new['sensitivity']]}（{tiers_words(new['sensitivity'])}）；{'要更大的波动才会提醒，提醒会少一些' if calmer else '稍小的波动就会提醒，提醒会多一些'}。"
                     "你自己定的规则、止损价和公告不受这个影响。")
    if new["short_moves"] != old["short_moves"]:
        word = lambda on: "开" if on else "关"      # noqa: E731
        lines.append(f"5 分钟急动提醒：{word(old['short_moves'])} → {word(new['short_moves'])}。"
                     + ("开了以后，持仓的股票在几分钟内突然大幅涨跌（至少相当于它半个日波动幅度）也会提醒，会比只看日线的提醒吵一些。"
                        if new["short_moves"] else "关了以后只看每天的涨跌分级，不再为几分钟内的急动提醒。"))
    if not lines:
        raise refusal("nothing_to_change", "和现在一模一样，没有要改的。")
    return new, "\n".join([*lines, "点确认后生效；哨兵下一轮检查就按新的来。"])


# --- the card of a preset change -------------------------------------------------------------------------------------------------

def symbols_for(owner: str, scope: str) -> list[str]:
    held = list(watch_rules._holdings(owner))
    if scope == PORTFOLIO_SCOPE:
        return [PORTFOLIO]
    if scope == WATCHED:
        from .sentinel_bridge import _research_queue
        try:
            queue = _research_queue(owner)
        except Exception:
            queue = []
        held += [s for s in queue if s not in held]
    return held[:MAX_SYMBOLS]


def dry_run(owner: str, rule: dict, days: int = watch_rules.DRY_RUN_DAYS, *, today: date | None = None) -> dict:
    """The 30-day look back of a preset: the rule's dry run on each symbol it covers, the hits together (each with its symbol)."""
    symbols = symbols_for(owner, rule["scope"])
    if not symbols:
        return {"hits": [], "covered_days": 0, "note": "你现在没有持仓，试跑不了", "metric": rule["metric"], "symbols": 0}
    hits, covered, notes = [], 0, []
    for symbol in symbols:
        one = watch_rules.dry_run(owner, {**rule, "symbol": symbol}, days, today=today)
        if one.get("note"):
            notes.append(one["note"])
            continue
        covered = max(covered, one["covered_days"])
        hits += [{**hit, "symbol": symbol} for hit in one["hits"]]
    if not covered:
        return {"hits": [], "covered_days": 0, "note": notes[0] if notes else watch_rules.NO_HISTORY, "metric": rule["metric"], "symbols": len(symbols)}
    hits.sort(key=lambda hit: (hit["date"], hit["symbol"], hit["level"] == "urgent"))
    return {"hits": hits, "covered_days": covered, "note": None, "metric": rule["metric"], "symbols": len(symbols)}


def dry_run_line(result: dict, days: int = watch_rules.DRY_RUN_DAYS) -> str:
    if result.get("note"):
        return f"试跑：{result['note']}。"
    estimate = watch_rules.ESTIMATES.get(result.get("metric"), watch_rules.ESTIMATE)
    if not result["hits"]:
        return f"按这条规则，过去 {days} 天不会提醒你（看了 {result['covered_days']} 个交易日）。{estimate}"
    shown = [f"{'' if hit['symbol'] == PORTFOLIO else hit['symbol'] + ' '}{hit['date'][5:]}{'（加急）' if hit['level'] == 'urgent' else ''}" for hit in result["hits"][:8]]
    more = f"等共 {len(result['hits'])} 次" if len(result["hits"]) > 8 else ""
    return f"按这条规则，过去 {days} 天会提醒你 {len(result['hits'])} 次：{'、'.join(shown)}{more}。{estimate}"


def preset_card(owner: str, key: str, enabled=None, levels=None, reset: bool = False) -> tuple[dict, dict, list[str]]:
    """(old preset, new preset, the card's lines) for a change; ``WatchRuleError`` with the reason when it cannot be made.  Writes nothing."""
    new_enabled, new_levels = merged(owner, key, enabled, levels, reset)
    old = next(p for p in resolved(owner) if p["preset_key"] == key)
    new = {**_rule(key, new_levels), "enabled": new_enabled}
    if new_enabled == old["enabled"] and new_levels == old["levels"]:
        raise refusal("nothing_to_change", "和现在一模一样，没有要改的。")
    lines = [f"原来：{old['text']}" + ("" if old["enabled"] else "（现在是关着的）")]
    if not new_enabled:
        lines.append("改后：关掉。这条默认规则不再提醒你；之后可以再打开，或在「它在帮你盯的」页面「恢复默认」。")
    else:
        lines.append(f"改后：{new['text']}")
        if new_enabled and (not old["enabled"] or new_levels != old["levels"]):
            try:
                lines.append(dry_run_line(dry_run(owner, new)))
            except Exception:
                lines.append("试跑：这次没跑成（行情读取出错），不影响规则本身。")
    if new_enabled and any(level["level"] == "remind" for level in new_levels):
        lines.append(NIGHT_NOTE)
    lines.append("点确认后生效；哨兵每分钟检查，不用模型。")
    return old, new, lines
