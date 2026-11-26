"""The owner's own watch rules (「你自己定的盯防规则」, stage 5b-1): when he wants to be told, as one explicit, code-checkable rule.

The model only fills structured fields (symbol, metric, direction, levels ...).  Everything the owner reads about a rule is written here, by code,
from those fields: ``describe`` is the plain-language reading and ``dry_run`` the 30-day look back on the daily bars, so the card cannot drift from
what the sentinel checks.  The sentinel (``sentinel/``, stdlib only, no model) reads the enabled rules from its snapshot every minute; this module
is the only writer.  A condition that needs reading content (news, policy) is not a rule: it stays a standing instruction.

The shape sent to the sentinel is ``rule_dict`` (``docs/superpowers/plans/2026-11-26-stage5b1-owner-watch-rules.md``, "The rule").
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .agent_chat_models import WatchRule
from .database import SessionLocal
from .symbols import normalize_market_symbol

log = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
MAX_RULES = 50
DRY_RUN_DAYS = 30
MIN_BARS = 10
NO_HISTORY = "没有足够的历史行情，试跑不了"
LEVEL_WORDS = {"remind": "提醒", "urgent": "加急"}
REPEATS = ("daily", "once")
STATE_METRICS = frozenset({"price", "position_weight", "cost_change", "n_day_change"})      # edge-triggered: a level fires when its condition becomes true
MOVES = ("up", "down", "either")

# metric -> (directions allowed, default direction, needs a holding, largest threshold, label)
METRICS: dict[str, dict] = {
    "day_change": {"directions": MOVES, "default": "either", "holding": False, "max": 1000, "label": "相对昨收的涨跌幅"},
    "open_change": {"directions": MOVES, "default": "either", "holding": False, "max": 1000, "label": "相对今天开盘价的涨跌幅（常规交易时段）"},
    "cost_change": {"directions": MOVES, "default": "either", "holding": True, "max": 1000, "label": "相对你持仓成本价的涨跌幅"},
    "n_day_change": {"directions": MOVES, "default": "either", "holding": False, "max": 1000, "label": "相对 N 个交易日前收盘价的涨跌幅"},
    "price": {"directions": ("above", "below"), "default": None, "holding": False, "max": 10_000_000, "label": "股价（美元）"},
    "volume_ratio": {"directions": ("above",), "default": "above", "holding": False, "max": 1000, "label": "成交量相对 20 日均量的倍数"},
    "position_pnl": {"directions": MOVES, "default": "either", "holding": True, "max": 100_000_000, "label": "持仓当天盈亏（美元）"},
    "position_weight": {"directions": ("above", "below"), "default": "above", "holding": True, "max": 100, "label": "持仓占总资产的比例"},
}
UNITS = {"day_change": "%", "open_change": "%", "cost_change": "%", "n_day_change": "%", "price": "美元", "volume_ratio": "倍",
         "position_pnl": "美元", "position_weight": "%"}
WINDOW_MIN, WINDOW_MAX = 2, 60


class WatchRuleError(ValueError):
    """A short code and the reason in Chinese, for the card refusal and the route's 422."""

    def __init__(self, code: str, reason: str):
        super().__init__(code)
        self.code, self.reason = code, reason


def _num(value) -> int | float:
    number = round(float(value), 4)
    return int(number) if number == int(number) else number


def _g(value) -> str:
    return f"{value:g}"


def today_ny() -> date:
    return datetime.now(NY).date()


# --- validation ---------------------------------------------------------------------------------------------------------------

def _holdings(owner: str) -> dict[str, dict]:
    """The current positions as numbers: {symbol: {shares, avg_cost}} plus ``None`` key is not used; total assets come from ``_total_assets``."""
    from . import portfolio
    summary = portfolio.build_summary(owner)
    return {v["symbol"]: {"shares": float(v["shares"]), "avg_cost": float(v["avg_cost"]) if v["avg_cost"] else None,
                          "total_assets": float(summary["total_assets"]) if summary.get("total_assets") else None}
            for v in summary["positions"]}


def _parse_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise WatchRuleError("invalid_expiry", "到期日要写成 YYYY-MM-DD。")


def _levels(raw, metric: str, direction: str) -> list[dict]:
    if not isinstance(raw, (list, tuple)) or not 1 <= len(raw) <= 2:
        raise WatchRuleError("invalid_levels", "要 1 到 2 档，每档有一个数值和一个级别（提醒 remind 或加急 urgent）。")
    unit, top = UNITS[metric], METRICS[metric]["max"]
    found = []
    for item in raw:
        try:
            threshold, level = float(item["threshold"]), item["level"]
        except (KeyError, TypeError, ValueError):
            raise WatchRuleError("invalid_levels", "每一档要有数值 threshold 和级别 level（remind 或 urgent）。")
        if level not in LEVEL_WORDS:
            raise WatchRuleError("invalid_levels", "级别只有提醒（remind）和加急（urgent）两种。")
        if not 0 < threshold <= top:
            raise WatchRuleError("invalid_threshold", f"这个指标的数值要大于 0，不超过 {_g(top)} {unit}。")
        if direction == "down" and unit == "%" and threshold >= 100 and metric != "position_weight":
            raise WatchRuleError("invalid_threshold", "跌幅不可能达到 100% 或更多。")
        found.append({"threshold": _num(threshold), "level": level})
    found.sort(key=lambda entry: entry["threshold"])
    if len({entry["threshold"] for entry in found}) < len(found):
        raise WatchRuleError("invalid_levels", "两档的数值不能一样。")
    if sum(entry["level"] == "urgent" for entry in found) > 1 or (len(found) == 2 and found[0]["level"] == found[1]["level"] == "remind"):
        raise WatchRuleError("invalid_levels", "两档时要一档提醒、一档加急；加急只能有一档。")
    if len(found) == 2:      # the urgent one is the further one: the larger number, or for "below" the smaller
        urgent = next(i for i, entry in enumerate(found) if entry["level"] == "urgent")
        if urgent != (0 if direction == "below" else 1):
            raise WatchRuleError("invalid_levels", "加急要是更极端的那一档（涨跌幅或数值更大；「低于」时数值更小）。")
    return found


def validate(fields: dict, *, owner: str | None = None, today: date | None = None) -> dict:
    """The fields of one rule, checked and in their stored form; ``WatchRuleError`` with the reason otherwise.

    With ``owner`` a rule that needs a holding (cost, position P&L, position weight) is refused for a symbol he does not hold."""
    try:
        symbol = normalize_market_symbol(fields.get("symbol"))
    except ValueError:
        raise WatchRuleError("invalid_symbol", "代码不对，要美股代码，比如 INTC。")
    metric = fields.get("metric")
    spec = METRICS.get(metric)
    if spec is None:
        raise WatchRuleError("unknown_metric", "没有这个指标。可选：" + "、".join(f"{k}（{v['label']}）" for k, v in METRICS.items()) + "。")
    direction = fields.get("direction") or spec["default"]
    if direction is None:
        raise WatchRuleError("direction_required", "股价规则要说明是高于（above）还是低于（below）某个价。")
    if direction not in spec["directions"]:
        raise WatchRuleError("invalid_direction", f"这个指标的方向只能是：{'、'.join(spec['directions'])}。")
    window = fields.get("window_days")
    if metric == "n_day_change":
        if not isinstance(window, int) or isinstance(window, bool) or not WINDOW_MIN <= window <= WINDOW_MAX:
            raise WatchRuleError("invalid_window", f"N 日涨跌要给 window_days，{WINDOW_MIN} 到 {WINDOW_MAX} 个交易日。")
    elif window is not None:
        raise WatchRuleError("invalid_window", "只有 N 日涨跌（n_day_change）才用 window_days。")
    repeat = fields.get("repeat") or "daily"
    if repeat not in REPEATS:
        raise WatchRuleError("invalid_repeat", "repeat 只有 daily（每天每档一次）和 once（每档只一次，之后自动停用）。")
    expires = _parse_date(fields.get("expires_on"))
    if expires is not None and expires < (today or today_ny()):
        raise WatchRuleError("invalid_expiry", "到期日已经过了。")
    levels = _levels(fields.get("levels"), metric, direction)
    if spec["holding"] and owner is not None and symbol not in _holdings(owner):
        raise WatchRuleError("not_a_holding", f"你现在没有持有 {symbol}。成本、持仓盈亏、仓位占比这几类规则只能用在持仓上；先记下这笔持仓，或换一个指标。")
    return {"symbol": symbol, "metric": metric, "direction": direction, "levels": levels, "window_days": window,
            "repeat": repeat, "expires_on": expires.isoformat() if expires else None}


# --- the reading --------------------------------------------------------------------------------------------------------------

def _name(symbol: str) -> str:
    from .owner_views import display_name
    return display_name(symbol)


def describe(rule: dict) -> str:
    """The rule in plain Chinese, from its fields only.  What the owner reads on the card and in the list; the model never writes it."""
    metric, direction, levels, symbol = rule["metric"], rule["direction"], list(rule["levels"]), rule["symbol"]
    name = _name(symbol)
    move = {"up": "上涨", "down": "下跌", "either": "涨或跌"}.get(direction, "")
    if direction == "below":
        levels = levels[::-1]      # most severe first for a fall: 低于 100 提醒，低于 90 加急
    pct = lambda t: f"达到 {_g(t)}%"      # noqa: E731
    below = direction == "below"
    if metric == "day_change":
        prefix, reach = f"{name}相对昨收{move}", pct
    elif metric == "open_change":
        prefix, reach = f"{name}相对今天的开盘价（只看常规交易时段）{move}", pct
    elif metric == "cost_change":
        prefix, reach = f"{name}相对你的持仓成本价{move}", pct
    elif metric == "n_day_change":
        prefix, reach = f"{name}相对 {rule.get('window_days')} 个交易日前的收盘价{move}", pct
    elif metric == "price":
        prefix, reach = f"{name}的股价", lambda t: f"{'低于' if below else '高于'} {_g(t)} 美元"
    elif metric == "volume_ratio":
        prefix = f"{name}今天的成交量（只看常规交易时段，按开盘后已过去的时间折算；开盘后 30 分钟内不判断）相对近 20 个交易日的日均量"
        reach = lambda t: f"达到 {_g(t)} 倍"      # noqa: E731
    elif metric == "position_pnl":
        prefix = f"你持有的{name}今天的盈亏（现有股数 × 相对昨收的价差）"
        word = {"up": "盈利", "down": "亏损"}.get(direction, "盈利或亏损")
        reach = lambda t: f"{word}达到 {_g(t)} 美元"      # noqa: E731
    else:
        prefix, reach = f"{name}占你总资产的比例", lambda t: f"{'低于' if below else '高于'} {_g(t)}%"
    clauses = "；".join(f"{reach(entry['threshold'])}：{LEVEL_WORDS[entry['level']]}" for entry in levels)
    state = metric in STATE_METRICS
    unit = {"%": "%", "美元": " 美元"}.get(UNITS[metric], "")
    if rule.get("repeat") == "once":
        again = "每档只触发一次，最高档触发后这条规则自动停用。" if len(levels) == 2 else "只触发一次，之后这条规则自动停用。"
    elif state and len(levels) == 2:
        again = "每档各自：条件成立时提醒一次，回到该档之内后再次越过，才会再提醒；每天每档最多一次。"
    elif state:
        again = f"条件成立时提醒一次，回到 {_g(levels[0]['threshold'])}{unit}之内后再次越过，才会再提醒；每天最多一次。"
    else:
        again = "每天每档一次。" if len(levels) == 2 else "每天最多一次。"
    until = f"有效到 {rule['expires_on']}。" if rule.get("expires_on") else ""
    return f"{prefix}{clauses}。{again}{until}"


# --- the dry run --------------------------------------------------------------------------------------------------------------

def _bars(symbol: str, start: date, end: date) -> list[dict]:
    """Daily bars oldest first, one per trading date (the newest fetch wins)."""
    from .models import MarketPrice
    with SessionLocal() as db:
        found = db.scalars(select(MarketPrice).where(MarketPrice.symbol == symbol, MarketPrice.trading_date >= start, MarketPrice.trading_date <= end)
                           .order_by(MarketPrice.trading_date, MarketPrice.fetched_at.desc())).all()
        bars, seen = [], set()
        for bar in found:
            if bar.trading_date not in seen:
                seen.add(bar.trading_date)
                bars.append({"date": bar.trading_date, "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close, "volume": bar.volume})
    return bars


def _reached(direction: str, high, low, threshold: float) -> bool:
    """``high`` / ``low``: the day's best and worst value of the measure."""
    if direction in ("up", "above"):
        return high >= threshold
    if direction == "down":
        return -low >= threshold
    if direction == "below":
        return low <= threshold
    return high >= threshold or -low >= threshold


def _extremes(rule: dict, bars: list[dict], i: int, holding: dict | None) -> tuple[float, float] | None:
    """The (highest, lowest) value of the rule's measure on day ``i``, or None when the data to measure it is not there."""
    metric, day, prev = rule["metric"], bars[i], bars[i - 1]
    if metric == "day_change":
        return (day["high"] / prev["close"] - 1) * 100, (day["low"] / prev["close"] - 1) * 100
    if metric == "open_change":
        return (day["high"] / day["open"] - 1) * 100, (day["low"] / day["open"] - 1) * 100
    if metric == "price":
        return day["high"], day["low"]
    if metric == "n_day_change":
        back = i - rule["window_days"]
        if back < 0:
            return None
        move = (day["close"] / bars[back]["close"] - 1) * 100
        return move, move
    if metric == "volume_ratio":
        if i < 20:
            return None
        average = sum(b["volume"] for b in bars[i - 20:i]) / 20
        if average <= 0:
            return None
        ratio = day["volume"] / average
        return ratio, ratio
    if holding is None:
        return None
    if metric == "cost_change":
        cost = holding.get("avg_cost")
        return None if not cost else ((day["high"] / cost - 1) * 100, (day["low"] / cost - 1) * 100)
    if metric == "position_pnl":
        return holding["shares"] * (day["high"] - prev["close"]), holding["shares"] * (day["low"] - prev["close"])
    if metric == "position_weight":
        total = holding.get("total_assets")
        return None if not total else (holding["shares"] * day["high"] / total * 100, holding["shares"] * day["low"] / total * 100)
    return None


def dry_run(owner: str, rule: dict, days: int = DRY_RUN_DAYS, *, today: date | None = None) -> dict:
    """What the rule would have said over the last ``days`` days, on the daily bars: ``{"hits": [{"date", "level"}], "covered_days", "note"}``.

    Every level the day's high or low reached is one hit (a day's bars cannot say which came first); ``repeat=once`` counts each level's first hit only.
    Cost and position rules use today's holding (shares, average cost, total assets) for every day, as the plan says."""
    today = today or today_ny()
    start = today - timedelta(days=days)
    bars = _bars(rule["symbol"], start - timedelta(days=130), today)
    empty = {"hits": [], "covered_days": 0, "note": None}
    if len(bars) < MIN_BARS:
        return {**empty, "note": NO_HISTORY}
    holding = None
    if METRICS[rule["metric"]]["holding"]:
        holding = _holdings(owner).get(rule["symbol"])
        if holding is None:
            return {**empty, "note": "你现在没有持有它，试跑不了"}
        if rule["metric"] == "position_weight" and not holding.get("total_assets"):
            return {**empty, "note": "总资产暂时算不出来（有持仓缺行情），试跑不了"}
        if rule["metric"] == "cost_change" and not holding.get("avg_cost"):
            return {**empty, "note": "没有持仓成本，试跑不了"}
    state = rule["metric"] in STATE_METRICS
    hits, covered, fired = [], 0, set()
    ever = set()
    highest = (rule["levels"][0] if rule["direction"] == "below" else rule["levels"][-1])["level"]
    for i in range(1, len(bars)):
        day = bars[i]["date"]
        if day <= start or day > today:
            continue
        if rule.get("repeat") == "once" and highest in ever:
            break      # the rule switched itself off after its highest level fired
        measured = _extremes(rule, bars, i, holding)
        if measured is None:
            continue
        covered += 1
        for entry in rule["levels"]:
            now = _reached(rule["direction"], measured[0], measured[1], entry["threshold"])
            key = ("was", entry["level"])
            was = key in fired
            if state:      # edge-triggered: fires on the day the condition becomes true; the first day of the window counts as becoming true
                (fired.add if now else fired.discard)(key)
            if not now or (state and was):
                continue
            if rule.get("repeat") == "once" and entry["level"] in ever:
                continue
            ever.add(entry["level"])
            hits.append({"date": day.isoformat(), "level": entry["level"]})
    if not covered:
        return {**empty, "note": NO_HISTORY}
    hits.sort(key=lambda hit: (hit["date"], hit["level"] == "urgent"))
    return {"hits": hits, "covered_days": covered, "note": None}


def dry_run_line(result: dict, days: int = DRY_RUN_DAYS) -> str:
    """The one line the card shows under the reading."""
    if result.get("note"):
        return f"试跑：{result['note']}。"
    if not result["hits"]:
        return f"按这条规则，过去 {days} 天不会提醒你（看了 {result['covered_days']} 个交易日）。"
    by_day: dict[str, set] = {}
    for hit in result["hits"]:
        by_day.setdefault(hit["date"], set()).add(hit["level"])
    shown = []
    for day, levels in by_day.items():
        mark = "（提醒+加急）" if len(levels) == 2 else "（加急）" if "urgent" in levels else ""
        shown.append(day[5:] + mark)
    return f"按这条规则，过去 {days} 天会提醒你 {len(result['hits'])} 次：{'、'.join(shown)}。"


# --- storage ------------------------------------------------------------------------------------------------------------------

def rule_dict(row: WatchRule) -> dict:
    """The rule as the sentinel and the routes see it (the contract of the plan); ``text`` is always written fresh by ``describe``."""
    rule = {"id": str(row.id), "symbol": row.symbol, "metric": row.metric, "direction": row.direction,
            "levels": [{"threshold": _num(e["threshold"]), "level": e["level"]} for e in row.levels],
            "window_days": row.window_days, "repeat": row.repeat,
            "expires_on": row.expires_on.isoformat() if row.expires_on else None, "created_on": row.created_on.isoformat()}
    return {**rule, "text": describe(rule)}


def _refresh() -> None:
    from .sentinel_bridge import refresh_sentinel_snapshot
    refresh_sentinel_snapshot()


def _uuid(value) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise WatchRuleError("rule_not_found", "没有这条规则。")


def _live(db, owner: str, rule_id) -> WatchRule:
    row = db.get(WatchRule, _uuid(rule_id))
    if row is None or row.owner_hash != owner or not row.enabled or row.deleted_at is not None:
        raise WatchRuleError("rule_not_found", "没有这条规则（或已经删了）。")
    return row


def list_rules(owner: str) -> list[dict]:
    """His rules that are switched on, oldest first."""
    with SessionLocal() as db:
        rows = db.scalars(select(WatchRule).where(WatchRule.owner_hash == owner, WatchRule.enabled.is_(True), WatchRule.deleted_at.is_(None))
                          .order_by(WatchRule.created_at, WatchRule.id)).all()
        return [rule_dict(row) for row in rows]


def snapshot_rules(owner: str, *, today: date | None = None) -> list[dict]:
    """What the sentinel gets: the enabled rules that have not expired (by the New York date)."""
    today = today or today_ny()
    return [rule for rule in list_rules(owner) if not rule["expires_on"] or rule["expires_on"] >= today.isoformat()]


def merged_fields(owner: str, rule_id: str, fields: dict) -> tuple[dict, dict]:
    """(the rule now, the fields it would have after ``fields`` change it); only the keys given (not None) change."""
    with SessionLocal() as db:
        current = rule_dict(_live(db, owner, rule_id))
    keep = ("symbol", "metric", "direction", "levels", "window_days", "repeat", "expires_on")
    merged = {key: current[key] for key in keep}
    given = {key: value for key, value in fields.items() if key in keep and value is not None}
    if given.get("metric") not in (None, current["metric"]):      # a different measure: direction and window start over unless said
        merged.update(direction=None, window_days=None)
    merged.update(given)
    return current, validate(merged, owner=owner)


def create(owner: str, fields: dict, quote: str = "", *, today: date | None = None) -> dict:
    clean = validate(fields, owner=owner, today=today)
    with SessionLocal() as db:
        live = db.scalars(select(WatchRule.id).where(WatchRule.owner_hash == owner, WatchRule.enabled.is_(True), WatchRule.deleted_at.is_(None))).all()
        if len(live) >= MAX_RULES:
            raise WatchRuleError("too_many_rules", f"盯防规则已经有 {MAX_RULES} 条了，先删掉不用的再加。")
        row = WatchRule(owner_hash=owner, symbol=clean["symbol"], metric=clean["metric"], direction=clean["direction"], levels=clean["levels"],
                        window_days=clean["window_days"], repeat=clean["repeat"],
                        expires_on=date.fromisoformat(clean["expires_on"]) if clean["expires_on"] else None,
                        created_on=today or today_ny(), enabled=True, source="owner", quote=" ".join(str(quote or "").split())[:400])
        db.add(row)
        db.commit()
        made = rule_dict(row)
    _refresh()
    return made


def update(owner: str, rule_id: str, fields: dict, quote: str | None = None, *, today: date | None = None) -> dict:
    """Change the fields given; the rest stay.  The rule is validated as a whole."""
    _, clean = merged_fields(owner, rule_id, fields)
    with SessionLocal() as db:
        row = _live(db, owner, rule_id)
        row.symbol, row.metric, row.direction, row.levels = clean["symbol"], clean["metric"], clean["direction"], clean["levels"]
        row.window_days, row.repeat = clean["window_days"], clean["repeat"]
        row.expires_on = date.fromisoformat(clean["expires_on"]) if clean["expires_on"] else None
        row.fired_once = None
        if quote:
            row.quote = " ".join(str(quote).split())[:400]
        row.updated_at = datetime.now(UTC)
        db.commit()
        made = rule_dict(row)
    _refresh()
    return made


def delete(owner: str, rule_id: str) -> dict:
    """Soft: the row stays, switched off and stamped."""
    with SessionLocal() as db:
        row = _live(db, owner, rule_id)
        row.enabled, row.deleted_at = False, datetime.now(UTC)
        db.commit()
        gone = rule_dict(row)
    _refresh()
    return gone
