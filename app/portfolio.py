"""Portfolio v1: manual and conversational entry only (no broker statement import).

Everything here is a pure function over a list of ``Txn`` until the "database" section at the bottom.
Money is ``Decimal`` throughout; the summary the API and the agent read carries it as plain strings
so no float ever touches a figure.

Rules (personal finance assistant plan, Task 6):
- average cost = position cost / shares; a buy's cost includes its fee; a sell removes position cost in
  proportion, so the average cost does not move;
- diluted cost (摊薄成本) = (cumulative buys incl. fees - cumulative sell net proceeds - dividends) / shares;
- realized P&L = sell net proceeds - the sold part's position cost;
- floating P&L = shares * (latest price - average cost); today's P&L = shares * (latest - previous close),
  marked reference-only when the position traded since that previous close;
- split: shares * ratio, average cost / ratio (position cost unchanged);
- available funds (可用资金) = deposit + cash_adjust - withdraw - buys (incl. fees) + sell net proceeds
  + dividends.  ``opening`` carries a position in without moving funds.

Decisions where the plan is silent:
- ``opening`` counts as cost for the diluted cost (it is what the position cost the owner), but never as cash;
- when a position is sold down to zero its cumulative buys/sells/dividends restart, so a later re-entry does not
  inherit the old cycle's diluted cost; realized P&L stays;
- a sell larger than the shares held at that point of the history, a split with nothing held, or a delete that
  would leave a later sell without its shares are errors and write nothing; funds going negative is only a warning.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from zoneinfo import ZoneInfo

ZERO = Decimal(0)
KINDS = ("opening", "buy", "sell", "dividend", "split", "deposit", "withdraw", "cash_adjust")
CASH_KINDS = frozenset({"deposit", "withdraw", "cash_adjust"})
TRADE_KINDS = frozenset({"opening", "buy", "sell"})
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
MAX_NOTE = 200
MAX_PLAN_TEXT = 2000

REASONS = {
    "invalid_kind": "记录类型不对。",
    "invalid_symbol": "股票代码不是有效的美股代码。",
    "invalid_quantity": "股数必须大于 0。",
    "invalid_price": "价格必须大于 0。",
    "invalid_fee": "手续费不能为负。",
    "invalid_amount": "金额不对：入金、出金、分红必须大于 0，调整不能为 0。",
    "invalid_ratio": "拆股比例必须大于 0 且不等于 1（1 拆 2 填 2）。",
    "invalid_date": "日期无效，或晚于今天。",
    "invalid_number": "数字无法识别。",
    "sell_exceeds_holdings": "卖出的股数超过当时持有的股数，没有记录。",
    "no_position_to_split": "当时没有这只股票的持仓，不能拆股，没有记录。",
    "would_break_history": "删掉这一笔会让后面的卖出或拆股没有对应的持仓，没有删除。",
    "transaction_not_found": "没有找到这笔记录。",
    "invalid_plan": "计划内容无效：价格必须大于等于 0，文字不能过长。",
    "nothing_to_change": "没有要修改的内容。",
}


class PortfolioError(ValueError):
    """A refused entry; ``code`` is stable, nothing was written."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code

    @property
    def reason(self) -> str:
        return REASONS.get(self.code, "持仓操作没有完成。")


def reason(code: str) -> str:
    return REASONS.get(str(code), "持仓操作没有完成。")


# --- numbers --------------------------------------------------------------------------------------------

def to_decimal(value, *, code: str = "invalid_number") -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise PortfolioError(code)
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise PortfolioError(code) from None
    if not number.is_finite():
        raise PortfolioError(code)
    return number


def q2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def text(value: Decimal | None, places: int = 2) -> str | None:
    """A plain decimal string (no exponent, no thousands separators) or None."""
    if value is None:
        return None
    return format((q2 if places == 2 else q4)(value), "f")


def number_text(value: Decimal | None) -> str | None:
    """Shares and ratios: as many places as they have, no trailing zeros."""
    if value is None:
        return None
    return format(value.normalize(), "f") if value else "0"


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


# --- the ledger -----------------------------------------------------------------------------------------

@dataclass
class Txn:
    kind: str
    symbol: str = ""
    quantity: Decimal = ZERO
    price: Decimal = ZERO
    fee: Decimal = ZERO
    amount: Decimal = ZERO
    ratio: Decimal = ZERO
    occurred_on: date = field(default_factory=today_local)
    note: str = ""
    id: str = ""
    created_at: datetime | None = None


def order_key(txn: Txn):
    return (txn.occurred_on, txn.created_at or datetime.max.replace(tzinfo=UTC), str(txn.id))


@dataclass
class Position:
    symbol: str
    shares: Decimal = ZERO
    cost: Decimal = ZERO          # position cost, fees included
    buys: Decimal = ZERO          # cumulative buys incl. fees (opening counts at its cost) of this cycle
    sells: Decimal = ZERO         # cumulative sell net proceeds of this cycle
    dividends: Decimal = ZERO     # cumulative dividends of this cycle
    realized: Decimal = ZERO      # realized P&L over the whole history
    last_trade_on: date | None = None
    last_split_on: date | None = None

    @property
    def avg_cost(self) -> Decimal | None:
        return self.cost / self.shares if self.shares > 0 else None

    @property
    def diluted_cost(self) -> Decimal | None:
        return (self.buys - self.sells - self.dividends) / self.shares if self.shares > 0 else None


@dataclass
class Ledger:
    positions: dict[str, Position] = field(default_factory=dict)
    funds: Decimal = ZERO


def trade_cost(txn: Txn) -> Decimal:
    return txn.quantity * txn.price + txn.fee


def sell_net(txn: Txn) -> Decimal:
    return txn.quantity * txn.price - txn.fee


def replay(txns) -> Ledger:
    """Apply ``txns`` in history order.  Raises PortfolioError on an impossible history."""
    ledger = Ledger()
    for txn in sorted(txns, key=order_key):
        kind = txn.kind
        if kind == "deposit":
            ledger.funds += txn.amount
        elif kind == "withdraw":
            ledger.funds -= txn.amount
        elif kind == "cash_adjust":
            ledger.funds += txn.amount
        else:
            position = ledger.positions.setdefault(txn.symbol, Position(txn.symbol))
            if kind in {"opening", "buy"}:
                cost = trade_cost(txn)
                position.shares += txn.quantity
                position.cost += cost
                position.buys += cost
                position.last_trade_on = txn.occurred_on
                if kind == "buy":
                    ledger.funds -= cost
            elif kind == "sell":
                if txn.quantity > position.shares:
                    raise PortfolioError("sell_exceeds_holdings")
                net = sell_net(txn)
                sold_cost = position.cost * txn.quantity / position.shares
                position.cost -= sold_cost
                position.shares -= txn.quantity
                position.realized += net - sold_cost
                position.sells += net
                position.last_trade_on = txn.occurred_on
                ledger.funds += net
                if position.shares == 0:
                    position.cost = position.buys = position.sells = position.dividends = ZERO
            elif kind == "dividend":
                position.dividends += txn.amount
                ledger.funds += txn.amount
            elif kind == "split":
                if position.shares <= 0:
                    raise PortfolioError("no_position_to_split")
                position.shares *= txn.ratio
                position.last_split_on = txn.occurred_on
            else:
                raise PortfolioError("invalid_kind")
    return ledger


# --- validation -----------------------------------------------------------------------------------------

def _symbol(value) -> str:
    from .symbols import normalize_market_symbol
    try:
        return normalize_market_symbol(value)
    except ValueError:
        raise PortfolioError("invalid_symbol") from None


def _date(value, today: date) -> date:
    if value in (None, ""):
        return today
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value).strip()[:10])
        except ValueError:
            raise PortfolioError("invalid_date") from None
    if parsed > today + timedelta(days=1):  # a day of slack for the US session being ahead of the owner's date
        raise PortfolioError("invalid_date")
    return parsed


def clean_entry(fields: dict, *, today: date | None = None) -> Txn:
    """Validate one entry into a Txn.  Fills ``amount`` with the cash/cost effect for trades."""
    today = today or today_local()
    kind = fields.get("kind")
    if kind not in KINDS:
        raise PortfolioError("invalid_kind")
    note = str(fields.get("note") or "").strip()[:MAX_NOTE]
    occurred_on = _date(fields.get("occurred_on"), today)
    txn = Txn(kind=kind, occurred_on=occurred_on, note=note)
    if kind in CASH_KINDS:
        amount = to_decimal(fields.get("amount"), code="invalid_amount")
        if amount is None or amount == 0 or (kind != "cash_adjust" and amount < 0):
            raise PortfolioError("invalid_amount")
        txn.amount = amount
        return txn
    txn.symbol = _symbol(fields.get("symbol"))
    if kind in TRADE_KINDS:
        quantity = to_decimal(fields.get("quantity"), code="invalid_quantity")
        price = to_decimal(fields.get("price"), code="invalid_price")
        fee = to_decimal(fields.get("fee"), code="invalid_fee") or ZERO
        if quantity is None or quantity <= 0:
            raise PortfolioError("invalid_quantity")
        if price is None or price <= 0:
            raise PortfolioError("invalid_price")
        if fee < 0:
            raise PortfolioError("invalid_fee")
        txn.quantity, txn.price, txn.fee = quantity, price, fee
        txn.amount = sell_net(txn) if kind == "sell" else trade_cost(txn)
    elif kind == "dividend":
        amount = to_decimal(fields.get("amount"), code="invalid_amount")
        if amount is None or amount <= 0:
            raise PortfolioError("invalid_amount")
        txn.amount = amount
    else:  # split
        ratio = to_decimal(fields.get("ratio"), code="invalid_ratio")
        if ratio is None or ratio <= 0 or ratio == 1:
            raise PortfolioError("invalid_ratio")
        txn.ratio = ratio
    return txn


# --- the summary ----------------------------------------------------------------------------------------

@dataclass
class Quote:
    price: Decimal
    as_of: date | None = None
    prev_close: Decimal | None = None
    prev_date: date | None = None


def _signed(label: str, value: Decimal | None) -> str:
    """'浮动盈亏 -120.00（亏损 120.00）': the figure and its wording, so either way of writing it is the source's."""
    if value is None:
        return f"{label} 暂无"
    shown = text(value)
    if q2(value) == 0:
        return f"{label} {shown}"
    word = "盈利" if value > 0 else "亏损"
    return f"{label} {shown}（{word} {text(abs(value))}）"


def position_view(position: Position, quote: Quote | None, total_assets: Decimal | None, plan: dict | None,
                  *, today: date | None = None) -> dict:
    shares, avg, diluted = position.shares, position.avg_cost, position.diluted_cost
    view = {
        "symbol": position.symbol, "shares": number_text(shares), "cost": text(position.cost),
        "avg_cost": text(avg, 4), "diluted_cost": text(diluted, 4), "realized_pnl": text(position.realized),
        "price": None, "price_date": None, "market_value": None, "floating_pnl": None, "floating_pnl_pct": None,
        "today_pnl": None, "today_pnl_reference_only": False, "weight_pct": None,
        "plan": plan or {"plan_text": "", "add_price": None, "stop_price": None, "target_price": None},
    }
    if quote is None:
        return view
    market_value = shares * quote.price
    floating = shares * (quote.price - avg)
    view.update(price=text(quote.price, 4), price_date=quote.as_of.isoformat() if quote.as_of else None,
                market_value=text(market_value), floating_pnl=text(floating),
                floating_pnl_pct=text(floating / position.cost * 100) if position.cost > 0 else None)
    if quote.prev_close is not None:
        view["today_pnl"] = text(shares * (quote.price - quote.prev_close))
        # A trade on/after the day being measured, or a split since the previous close, makes the
        # share count (or the previous close's basis) differ from what the day was played with.
        traded = bool(position.last_trade_on and quote.as_of and position.last_trade_on >= quote.as_of)
        traded = traded or bool(position.last_split_on and quote.prev_date and position.last_split_on > quote.prev_date)
        traded = traded or bool(position.last_trade_on and today and position.last_trade_on >= today)
        view["today_pnl_reference_only"] = traded
    if total_assets and total_assets > 0:
        view["weight_pct"] = text(market_value / total_assets * 100)
    return view


def summarize(txns, quotes: dict[str, Quote] | None = None, plans: dict[str, dict] | None = None,
              *, today: date | None = None) -> dict:
    """The one summary every reader (API, agent, sentinel) is built from."""
    quotes, plans = quotes or {}, plans or {}
    ledger = replay(txns)
    held = {s: p for s, p in ledger.positions.items() if p.shares > 0}
    unpriced = sorted(s for s in held if s not in quotes)
    value = sum((p.shares * quotes[s].price for s, p in held.items() if s in quotes), ZERO)
    total = value + ledger.funds
    complete = not unpriced
    views = [position_view(p, quotes.get(s), total if complete else None, plans.get(s), today=today)
             for s, p in sorted(held.items())]
    floating = sum((Decimal(v["floating_pnl"]) for v in views if v["floating_pnl"] is not None), ZERO)
    today_pnl = sum((Decimal(v["today_pnl"]) for v in views if v["today_pnl"] is not None), ZERO)
    realized = sum((p.realized for p in ledger.positions.values()), ZERO)
    dates = [v["price_date"] for v in views if v["price_date"]]
    warnings = []
    if ledger.funds < 0:
        warnings.append("available_funds_negative")
    if unpriced:
        warnings.append("price_missing")
    return {
        "available_funds": text(ledger.funds), "positions_value": text(value), "total_assets": text(total) if complete else None,
        "total_assets_complete": complete, "floating_pnl": text(floating), "today_pnl": text(today_pnl),
        "today_pnl_reference_only": any(v["today_pnl_reference_only"] for v in views),
        "realized_pnl": text(realized), "price_date": max(dates) if dates else None, "unpriced": unpriced,
        "warnings": warnings, "positions": views,
        "plans_without_position": sorted(s for s in plans if s not in held),
    }


def warnings_after(txns) -> list[str]:
    ledger = replay(txns)
    return ["available_funds_negative"] if ledger.funds < 0 else []


WARNING_TEXT = {"available_funds_negative": "提示：这笔记录之后可用资金为负，请核对是否漏记了入金或可用资金。",
                "price_missing": "有持仓没有取到最新价，总资产与仓位占比不完整。"}


def evidence_rows(summary: dict) -> list[dict]:
    """The rows ``query_portfolio`` returns: one account row and one per position, each carrying every figure it
    states as plain numbers in ``excerpt`` (that text is the citation quote an answer's numbers are checked against)."""
    rows = []
    as_of = summary.get("price_date")
    account = [f"可用资金 {summary['available_funds']}", f"持仓市值 {summary['positions_value']}"]
    if summary["total_assets"] is not None:
        account.append(f"总资产 {summary['total_assets']}")
    account.append(_signed("浮动盈亏合计", Decimal(summary["floating_pnl"])))
    account.append(_signed("今日盈亏合计" + ("（仅供参考）" if summary["today_pnl_reference_only"] else ""), Decimal(summary["today_pnl"])))
    account.append(_signed("已实现盈亏", Decimal(summary["realized_pnl"])))
    if as_of:
        account.append(f"行情数据日期 {as_of}")
    rows.append({"id": "portfolio:account", "source_type": "portfolio", "title": "持仓账户汇总", "symbol": None,
                 "excerpt": "；".join(account) + "。", "price_date": as_of, "available_funds": summary["available_funds"],
                 "total_assets": summary["total_assets"], "warnings": summary["warnings"]})
    for view in summary["positions"]:
        parts = [f"{view['symbol']} 持仓 {view['shares']} 股", f"平均成本 {view['avg_cost']}", f"摊薄成本 {view['diluted_cost']}",
                 f"持仓成本 {view['cost']}"]
        if view["price"] is not None:
            parts += [f"最新价 {view['price']}（数据日期 {view['price_date']}）", f"市值 {view['market_value']}",
                      _signed("浮动盈亏", Decimal(view["floating_pnl"]))]
            if view["floating_pnl_pct"] is not None:
                parts.append(f"浮动盈亏比例 {view['floating_pnl_pct']}%")
            if view["today_pnl"] is not None:
                parts.append(_signed("今日盈亏" + ("（仅供参考：今天有成交）" if view["today_pnl_reference_only"] else ""), Decimal(view["today_pnl"])))
            if view["weight_pct"] is not None:
                parts.append(f"仓位占比 {view['weight_pct']}%")
        else:
            parts.append("暂无最新价")
        parts.append(_signed("已实现盈亏", Decimal(view["realized_pnl"])))
        plan = view["plan"]
        for key, label in (("add_price", "补仓价"), ("stop_price", "止损价"), ("target_price", "目标价")):
            if plan.get(key) is not None:
                parts.append(f"{label} {plan[key]}")
        if plan.get("plan_text"):
            parts.append("计划：" + plan["plan_text"])
        rows.append({"id": f"portfolio:{view['symbol']}", "source_type": "portfolio", "title": f"{view['symbol']} 持仓",
                     "symbol": view["symbol"], "excerpt": "；".join(parts) + "。", "price_date": view["price_date"],
                     **{k: view[k] for k in ("shares", "avg_cost", "diluted_cost", "price", "market_value", "floating_pnl",
                                             "today_pnl", "weight_pct") if view[k] is not None}})
    return rows


def sentinel_payload(summary: dict) -> dict:
    """What the sentinel holds while the API is down: floats, because it only compares prices to thresholds."""
    def num(value):
        return None if value is None else float(value)
    positions = [{"symbol": v["symbol"], "shares": num(v["shares"]), "avg_cost": num(v["avg_cost"]), "diluted_cost": num(v["diluted_cost"]),
                  "price": num(v["price"]), "price_date": v["price_date"], "market_value": num(v["market_value"]),
                  "weight_pct": num(v["weight_pct"])} for v in summary["positions"]]
    plans = [{"symbol": v["symbol"], "plan_text": v["plan"].get("plan_text") or "", "add_price": num(v["plan"].get("add_price")),
              "stop_price": num(v["plan"].get("stop_price")), "target_price": num(v["plan"].get("target_price"))}
             for v in summary["positions"]
             if v["plan"].get("plan_text") or any(v["plan"].get(k) is not None for k in ("add_price", "stop_price", "target_price"))]
    return {"positions": positions, "plans": plans, "total_assets": num(summary["total_assets"]),
            "available_funds": num(summary["available_funds"])}


# --- database -------------------------------------------------------------------------------------------

def _row_to_txn(row) -> Txn:
    return Txn(kind=row.kind, symbol=row.symbol or "", quantity=row.quantity or ZERO, price=row.price or ZERO, fee=row.fee or ZERO,
               amount=row.amount or ZERO, ratio=row.ratio or ZERO, occurred_on=row.occurred_on, note=row.note or "",
               id=str(row.id), created_at=row.created_at)


def load_transactions(db, owner: str) -> list:
    from sqlalchemy import select
    from .agent_chat_models import PortfolioTransaction
    return list(db.scalars(select(PortfolioTransaction).where(PortfolioTransaction.owner_hash == owner)
                           .order_by(PortfolioTransaction.occurred_on, PortfolioTransaction.created_at, PortfolioTransaction.id)))


def load_plans(db, owner: str) -> dict[str, dict]:
    from sqlalchemy import select
    from .agent_chat_models import PortfolioPlan
    return {p.symbol: plan_dict(p) for p in db.scalars(select(PortfolioPlan).where(PortfolioPlan.owner_hash == owner))}


def plan_dict(row) -> dict:
    return {"plan_text": row.plan_text or "", "add_price": text(row.add_price, 4), "stop_price": text(row.stop_price, 4),
            "target_price": text(row.target_price, 4), "updated_at": row.updated_at.isoformat() if row.updated_at else None}


def load_quotes(db, symbols) -> dict[str, Quote]:
    """Latest and previous close per symbol from market_prices (one bar per trading date, newest fetch wins)."""
    from sqlalchemy import select
    from .models import MarketPrice
    quotes = {}
    for symbol in symbols:
        bars, seen = [], set()
        for bar in db.scalars(select(MarketPrice).where(MarketPrice.symbol == symbol)
                              .order_by(MarketPrice.trading_date.desc(), MarketPrice.fetched_at.desc()).limit(8)):
            if bar.trading_date not in seen:
                seen.add(bar.trading_date)
                bars.append(bar)
            if len(bars) == 2:
                break
        if bars:
            # float(close) carries single-precision noise from some feeds (92.06999969482422); 4 places is the price.
            latest = Decimal(str(round(bars[0].close, 4)))
            prev = bars[1] if len(bars) > 1 else None
            quotes[symbol] = Quote(latest, bars[0].trading_date, Decimal(str(round(prev.close, 4))) if prev else None,
                                   prev.trading_date if prev else None)
    return quotes


def build_summary(owner: str, *, db=None) -> dict:
    from .database import SessionLocal

    def run(session):
        rows = load_transactions(session, owner)
        txns = [_row_to_txn(r) for r in rows]
        held = [s for s, p in replay(txns).positions.items() if p.shares > 0]
        summary = summarize(txns, load_quotes(session, held), load_plans(session, owner), today=today_local())
        summary["transactions"] = [transaction_dict(r) for r in reversed(rows)][:200]
        return summary

    if db is not None:
        return run(db)
    with SessionLocal() as session:
        return run(session)


def transaction_dict(row) -> dict:
    return {"id": str(row.id), "symbol": row.symbol or "", "kind": row.kind, "quantity": number_text(row.quantity) if row.quantity else None,
            "price": text(row.price, 4) if row.price else None, "fee": text(row.fee) if row.fee else None,
            "amount": text(row.amount) if row.amount else None, "ratio": number_text(row.ratio) if row.ratio else None,
            "occurred_on": row.occurred_on.isoformat(), "note": row.note or "",
            "created_at": row.created_at.isoformat() if row.created_at else None}


def sentinel_view(owner_hash: str) -> dict:
    """Called by app.sentinel_bridge for ``data/sentinel-config.json``: ``{positions, plans, total_assets}``
    (plus ``available_funds``).  Unlike the API summary its numbers are floats."""
    return sentinel_payload(build_summary(owner_hash))


def _lock(db, owner: str) -> None:
    from sqlalchemy import text as sql
    db.execute(sql("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": "portfolio:" + owner})


def record_transaction(owner: str, fields: dict, *, today: date | None = None) -> dict:
    """Validate and store one entry; refuse (writing nothing) when the history would no longer hold together."""
    from .agent_chat_models import PortfolioTransaction
    from .database import SessionLocal
    txn = clean_entry(fields, today=today)
    with SessionLocal() as db:
        _lock(db, owner)
        existing = [_row_to_txn(r) for r in load_transactions(db, owner)]
        txn.created_at = datetime.now(UTC)
        warnings = warnings_after([*existing, txn])  # replay raises when a sell/split cannot be held
        row = PortfolioTransaction(id=uuid.uuid4(), owner_hash=owner, symbol=txn.symbol, kind=txn.kind,
                                   quantity=txn.quantity, price=txn.price, fee=txn.fee, amount=txn.amount, ratio=txn.ratio,
                                   occurred_on=txn.occurred_on, note=txn.note, created_at=txn.created_at)
        db.add(row)
        db.commit()
        return {"ok": True, "status": "recorded", "id": str(row.id), "kind": txn.kind, "symbol": txn.symbol,
                "amount": text(txn.amount), "warnings": warnings, "warning_text": [WARNING_TEXT[w] for w in warnings]}


def delete_transaction(owner: str, transaction_id: str) -> dict:
    from .database import SessionLocal
    try:
        key = uuid.UUID(str(transaction_id))
    except ValueError:
        raise PortfolioError("transaction_not_found") from None
    with SessionLocal() as db:
        _lock(db, owner)
        rows = load_transactions(db, owner)
        target = next((r for r in rows if r.id == key), None)
        if target is None:
            raise PortfolioError("transaction_not_found")
        rest = [_row_to_txn(r) for r in rows if r.id != key]
        try:
            warnings = warnings_after(rest)
        except PortfolioError:
            raise PortfolioError("would_break_history") from None
        db.delete(target)
        db.commit()
        return {"ok": True, "status": "deleted", "id": str(key), "warnings": warnings,
                "warning_text": [WARNING_TEXT[w] for w in warnings]}


def set_available_funds(owner: str, target, *, today: date | None = None) -> dict:
    """The owner's hand-set available funds: a ``cash_adjust`` for the difference (none when it already matches)."""
    from .database import SessionLocal
    value = to_decimal(target, code="invalid_amount")
    if value is None:
        raise PortfolioError("invalid_amount")
    with SessionLocal() as db:
        current = replay([_row_to_txn(r) for r in load_transactions(db, owner)]).funds
    difference = value - current
    if q2(difference) == 0:
        return {"ok": True, "status": "unchanged", "available_funds": text(current), "warnings": []}
    result = record_transaction(owner, {"kind": "cash_adjust", "amount": q2(difference), "note": "手动设置可用资金"}, today=today)
    # Rounded: the stored adjustment is to the cent, so the new balance is to the cent as well.
    result["available_funds"] = text(current + q2(difference))
    result["previous_funds"] = text(current)
    return result


def set_plan(owner: str, symbol: str, fields: dict) -> dict:
    """Upsert a position's plan.  Only keys present in ``fields`` change; None clears a price (or the text)."""
    from .agent_chat_models import PortfolioPlan
    from .database import SessionLocal
    symbol = _symbol(symbol)
    changes = {}
    if "plan_text" in fields:
        plan_text = str(fields["plan_text"] or "").strip()
        if len(plan_text) > MAX_PLAN_TEXT:
            raise PortfolioError("invalid_plan")
        changes["plan_text"] = plan_text
    for key in ("add_price", "stop_price", "target_price"):
        if key in fields:
            price = to_decimal(fields[key], code="invalid_plan")
            if price is not None and price < 0:
                raise PortfolioError("invalid_plan")
            changes[key] = price
    if not changes:
        raise PortfolioError("nothing_to_change")
    with SessionLocal() as db:
        _lock(db, owner)
        row = db.get(PortfolioPlan, (owner, symbol))
        if row is None:
            row = PortfolioPlan(owner_hash=owner, symbol=symbol, plan_text="")
            db.add(row)
        for key, value in changes.items():
            setattr(row, key, value)
        row.updated_at = datetime.now(UTC)
        db.commit()
        return {"ok": True, "status": "saved", "symbol": symbol, "plan": plan_dict(row)}


def preview_entry(owner: str, fields: dict) -> dict:
    """What recording ``fields`` would do, for the confirmation card.  Raises PortfolioError like the real write."""
    from .database import SessionLocal
    txn = clean_entry(fields)
    with SessionLocal() as db:
        existing = [_row_to_txn(r) for r in load_transactions(db, owner)]
        txn.created_at = datetime.now(UTC)
        warnings = warnings_after([*existing, txn])
        funds = replay([*existing, txn]).funds
    return {"txn": txn, "warnings": warnings, "funds_after": text(funds)}


def apply_tool(name: str, owner: str, args: dict) -> dict:
    """The confirmed write tools (only reached after the owner pressed the card)."""
    args = {k: v for k, v in args.items() if not str(k).startswith("_")}
    if name == "record_trade":
        return record_transaction(owner, args)
    if name == "set_available_funds":
        return set_available_funds(owner, args["amount"])
    if name == "set_position_plan":
        symbol = args["symbol"]
        provided = {k: v for k, v in args.items() if k != "symbol" and v is not None}
        # 0 clears a price; an empty plan_text clears the text.
        for key in ("add_price", "stop_price", "target_price"):
            if key in provided and to_decimal(provided[key]) == 0:
                provided[key] = None
        return set_plan(owner, symbol, provided)
    raise PortfolioError("invalid_kind")


# --- confirmation cards ---------------------------------------------------------------------------------

KIND_LABEL = {"opening": "期初持仓", "buy": "买入", "sell": "卖出", "dividend": "分红", "split": "拆股",
              "deposit": "入金", "withdraw": "出金", "cash_adjust": "资金调整"}
WRITE_TOOLS = ("record_trade", "set_available_funds", "set_position_plan")


def describe_write(owner: str, name: str, args: dict) -> dict:
    """``{title, targets, alternative}`` for the card of a portfolio write, checked like the real write would be
    (a sell of shares not held raises PortfolioError here, so no card is minted for it)."""
    from .database import SessionLocal
    args = {k: v for k, v in args.items() if v is not None}
    if name == "record_trade":
        preview = preview_entry(owner, args)
        txn = preview["txn"]
        label = KIND_LABEL[txn.kind]
        if txn.kind in TRADE_KINDS:
            what = f"{label} {number_text(txn.quantity)} 股 {txn.symbol} @ {number_text(txn.price)}"
            what += f"，手续费 {number_text(txn.fee)}" if txn.fee else ""
            detail = f"{what}，{'卖出净得' if txn.kind == 'sell' else '含费用成本'} {text(txn.amount)}"
        elif txn.kind == "dividend":
            what = detail = f"{label} {text(txn.amount)}（{txn.symbol}）"
        else:
            what = detail = f"{txn.symbol} 1 拆 {number_text(txn.ratio)}（股数 ×{number_text(txn.ratio)}，平均成本 ÷{number_text(txn.ratio)}）"
        funds = ("不改变可用资金。" if txn.kind in {"opening", "split"} else f"记录后可用资金 {preview['funds_after']}。")
        note = "".join(WARNING_TEXT[w] for w in preview["warnings"])
        return {"title": f"记录{label} · {txn.symbol}", "targets": [{"symbol": txn.symbol, "kind": what}],
                "alternative": f"{detail}；日期 {txn.occurred_on.isoformat()}。{funds}{note}可在「持仓」页删除这一笔。"}
    if name == "set_available_funds":
        target = to_decimal(args.get("amount"), code="invalid_amount")
        if target is None:
            raise PortfolioError("invalid_amount")
        with SessionLocal() as db:
            current = replay([_row_to_txn(r) for r in load_transactions(db, owner)]).funds
        difference = q2(target - current)
        return {"title": f"设置可用资金 · {text(target)}", "targets": [{"kind": f"现在 {text(current)} → {text(target)}"}],
                "alternative": (f"差额 {text(difference)} 记为一笔资金调整（可在「持仓」页删除）。"
                                + ("" if target >= 0 else WARNING_TEXT["available_funds_negative"]))}
    if name == "set_position_plan":
        symbol = _symbol(args.get("symbol"))
        parts = [f"{label} {number_text(to_decimal(args[key]))}" if to_decimal(args[key]) else f"清除{label}"
                 for key, label in (("add_price", "补仓价"), ("stop_price", "止损价"), ("target_price", "目标价")) if key in args]
        if any(to_decimal(args[k]) is not None and to_decimal(args[k]) < 0 for k in ("add_price", "stop_price", "target_price") if k in args):
            raise PortfolioError("invalid_plan")
        if "plan_text" in args and len(str(args["plan_text"])) > MAX_PLAN_TEXT:
            raise PortfolioError("invalid_plan")
        return {"title": f"保存持仓计划 · {symbol}", "targets": [{"symbol": symbol, "kind": " · ".join(parts) or "文字计划"}],
                "alternative": ("计划：" + str(args["plan_text"]) if args.get("plan_text") else "只修改上面列出的价格，其余保持不变。")
                               + "（只是你自己的计划提醒，不是买卖建议）"}
    raise PortfolioError("invalid_kind")
