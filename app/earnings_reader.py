"""Earnings-release reader (personal finance assistant plan, Task 8).

Reads one release the way a person who knows the business would, and says whether the stock is likely to
rise or fall — or that it cannot tell.  Four steps, only the first and last call a model:

* ``extract_release``  numbers out of the text; every number must be found verbatim in the text, else it is empty.
* ``compare``          pure Python: actual vs last quarter's guidance net of the company's habit of beating,
                       new guidance vs this quarter and vs a year ago, quality of the beat, the run-up.
* ``judge``            one model call over the facts, the comparison and management's words; every reason
                       carries a quote that must exist in the source or the reason is dropped.
* ``label_reaction``   what the market actually did (up / down / flat) — used by the blind test to score.

Model calls go straight through ``agent_chat_provider.decision_request`` (no tool loop).  Units: revenue in
$ billions, margins in percent, EPS in dollars; ``*_pct`` fields are percent, ``*_pp`` percentage points.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

READER_VERSION = "earnings-reader-v1"
ROLE = "earnings"
MIN_SIGMA_DAYS = 20
MOVE_FLOOR = 0.03
JUDGE_SOURCE_CHARS = 30_000
EXTRACT_SOURCE_CHARS = 60_000

Price = tuple[date, float]


# --- the market's reaction --------------------------------------------------------------------------------

def daily_sigma(closes: list[Price], exclude_dates, n: int = 126) -> float | None:
    """Std-dev of the last ``n`` daily returns of (date, close) pairs, dropping the days in ``exclude_dates``
    (earnings-reaction days).  None when fewer than 20 returns remain."""
    returns = []
    for (_, previous), (day, close) in zip(closes[:-1], closes[1:]):
        if previous:
            returns.append((day, close / previous - 1))
    returns = [r for day, r in returns[-n:] if day not in set(exclude_dates)]
    if len(returns) < MIN_SIGMA_DAYS:
        return None
    return statistics.stdev(returns)


def label_reaction(r: float, sigma: float) -> Literal["up", "down", "flat"]:
    """up / down when the move reaches max(2σ, 3%), otherwise flat."""
    threshold = max(2 * sigma, MOVE_FLOOR)
    if r >= threshold:
        return "up"
    if r <= -threshold:
        return "down"
    return "flat"


# --- data -------------------------------------------------------------------------------------------------

@dataclass
class Guidance:
    revenue_low: float | None = None
    revenue_high: float | None = None
    gross_margin: float | None = None      # non-GAAP, percent
    eps: float | None = None               # non-GAAP, dollars

    @property
    def revenue_mid(self) -> float | None:
        if self.revenue_low is None or self.revenue_high is None:
            return None
        return (self.revenue_low + self.revenue_high) / 2


@dataclass
class ReleaseFacts:
    revenue: float | None = None
    gross_margin: float | None = None
    eps: float | None = None               # non-GAAP
    eps_gaap: float | None = None
    guidance: Guidance = field(default_factory=Guidance)     # for the next quarter
    source_text: str = ""


@dataclass
class HistoryQuarter:
    """A past quarter: what it reported, and what the company had guided for it the quarter before."""
    period: str
    revenue: float | None = None
    eps: float | None = None
    gross_margin: float | None = None
    guided: Guidance | None = None
    same_quarter_last_year: bool = False


@dataclass
class Comparison:
    revenue_vs_guidance_pct: float | None = None
    eps_vs_guidance_pct: float | None = None
    gross_margin_vs_guidance_pp: float | None = None
    habitual_revenue_beat_pct: float | None = None
    habitual_eps_beat_pct: float | None = None
    revenue_beat_excess_pct: float | None = None       # this beat minus the company's usual beat
    eps_beat_excess_pct: float | None = None
    new_revenue_vs_actual_pct: float | None = None
    new_eps_vs_actual_pct: float | None = None
    new_gross_margin_vs_actual_pp: float | None = None
    new_revenue_vs_year_ago_pct: float | None = None
    new_eps_vs_year_ago_pct: float | None = None
    eps_gaap_minus_nongaap: float | None = None
    pre_release_return_20d_pct: float | None = None
    pre_release_return_60d_pct: float | None = None
    history_quarters: int = 0


@dataclass
class Judgment:
    direction: Literal["up", "down", "unclear"] = "unclear"
    confidence: Literal["high", "medium", "low"] = "low"
    reasons: list[dict] = field(default_factory=list)       # [{text, quote}]
    counter_argument: str = ""
    raw: str = ""


# --- compare (pure) ---------------------------------------------------------------------------------------

def _pct(new, base):
    if new is None or base in (None, 0):
        return None
    return (new / base - 1) * 100


def _pp(new, base):
    return None if new is None or base is None else new - base


def _median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def _sub(a, b):
    return None if a is None or b is None else a - b


def compare(facts: ReleaseFacts, prior_guidance: Guidance | None, history: list[HistoryQuarter],
            prices: list[Price]) -> Comparison:
    """The checklist: actual vs last quarter's guidance (and vs the company's habitual beat), new guidance vs
    this quarter and vs the same quarter a year ago, quality of the beat, and the stock's run-up."""
    prior = prior_guidance or Guidance()
    new = facts.guidance
    c = Comparison()
    c.revenue_vs_guidance_pct = _pct(facts.revenue, prior.revenue_mid)
    c.eps_vs_guidance_pct = _pct(facts.eps, prior.eps)
    c.gross_margin_vs_guidance_pp = _pp(facts.gross_margin, prior.gross_margin)

    c.history_quarters = len(history)
    c.habitual_revenue_beat_pct = _median(_pct(h.revenue, h.guided.revenue_mid) for h in history if h.guided)
    c.habitual_eps_beat_pct = _median(_pct(h.eps, h.guided.eps) for h in history if h.guided)
    c.revenue_beat_excess_pct = _sub(c.revenue_vs_guidance_pct, c.habitual_revenue_beat_pct)
    c.eps_beat_excess_pct = _sub(c.eps_vs_guidance_pct, c.habitual_eps_beat_pct)

    c.new_revenue_vs_actual_pct = _pct(new.revenue_mid, facts.revenue)
    c.new_eps_vs_actual_pct = _pct(new.eps, facts.eps)
    c.new_gross_margin_vs_actual_pp = _pp(new.gross_margin, facts.gross_margin)
    year_ago = next((h for h in history if h.same_quarter_last_year), None)
    if year_ago is not None:
        c.new_revenue_vs_year_ago_pct = _pct(new.revenue_mid, year_ago.revenue)
        c.new_eps_vs_year_ago_pct = _pct(new.eps, year_ago.eps)

    c.eps_gaap_minus_nongaap = _sub(facts.eps_gaap, facts.eps)
    if c.eps_gaap_minus_nongaap is not None:
        c.eps_gaap_minus_nongaap = round(c.eps_gaap_minus_nongaap, 6)

    closes = [close for _, close in prices]
    for days, name in ((20, "pre_release_return_20d_pct"), (60, "pre_release_return_60d_pct")):
        if len(closes) > days:
            setattr(c, name, _pct(closes[-1], closes[-1 - days]))
    return c


# --- model plumbing ---------------------------------------------------------------------------------------

def model_for_owner(owner_hash: str | None) -> dict:
    """The 财报判断模型 chosen on the settings page (role ``earnings``), else the server's default model."""
    from . import agent_model_roles
    return agent_model_roles.resolve(owner_hash, ROLE)


async def _call_model(model: dict, system: str, user: str) -> str:
    from .agent_chat_provider import decision_request
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    _data, message = await decision_request(model["provider"], model["model"], model["api_key"], messages, [],
                                            model.get("base_url"))
    return str(message.get("content") or "")


def _json_object(raw: str) -> dict | None:
    raw = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip(), flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(raw[start:end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _in_text(quote, haystack: str) -> bool:
    return bool(quote) and isinstance(quote, str) and len(_squash(quote)) >= 4 and _squash(quote) in haystack


# --- extract_release --------------------------------------------------------------------------------------

EXTRACT_PROMPT = """你从一份上市公司财报新闻稿里抄数字。只输出一个 JSON 对象，不要解释。
每个字段给：quote（原文里连续的一小段，必须逐字照抄，含数字）、number（字符串，原样抄数字本身，如 "16.5"、"44.1"）。
区间字段（guidance_revenue）给 low、high 两个数字字符串。revenue 类字段给 unit："B"（十亿美元）或 "M"（百万美元）。
字段：
- revenue：本季营收
- gross_margin：本季 non-GAAP 毛利率（百分数，不带 %）
- eps：本季 non-GAAP 每股收益
- eps_gaap：本季 GAAP 稀释每股收益
- guidance_revenue：公司给下一季的营收指引区间
- guidance_gross_margin：下一季 non-GAAP 毛利率指引
- guidance_eps：下一季 non-GAAP 每股收益指引
原文里没有的字段整个省略，不要猜，不要推算，不要换算币种。"""


def _number(token) -> float | None:
    if not isinstance(token, str):
        return None
    cleaned = token.replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _grounded(entry, key: str, haystack: str) -> float | None:
    """The number ``entry[key]`` if the quote is in the text verbatim and the number is in the quote."""
    if not isinstance(entry, dict) or not _in_text(entry.get("quote"), haystack):
        return None
    token = entry.get(key)
    value = _number(token)
    if value is None:
        return None
    literal = str(token).replace("$", "").replace("%", "").strip()
    quote = _squash(entry["quote"])
    # the number must stand in the quote as written, not as part of a longer number
    if not re.search(r"(?<![\d.,])" + re.escape(literal) + r"(?![\d]|\.\d)", quote.replace("$", " ")):
        return None
    return value


def _billions(entry, value: float | None) -> float | None:
    if value is None:
        return None
    return value / 1000 if str(entry.get("unit", "B")).upper() == "M" else value


async def extract_release(text: str, model: dict) -> ReleaseFacts:
    haystack = _squash(text)
    facts = ReleaseFacts(source_text=text)
    raw = await _call_model(model, EXTRACT_PROMPT, text[:EXTRACT_SOURCE_CHARS])
    data = _json_object(raw)
    if not data:
        return facts
    entry = data.get("revenue")
    facts.revenue = _billions(entry, _grounded(entry, "number", haystack))
    facts.gross_margin = _grounded(data.get("gross_margin"), "number", haystack)
    facts.eps = _grounded(data.get("eps"), "number", haystack)
    facts.eps_gaap = _grounded(data.get("eps_gaap"), "number", haystack)
    entry = data.get("guidance_revenue")
    low, high = _grounded(entry, "low", haystack), _grounded(entry, "high", haystack)
    if low is not None and high is not None:
        facts.guidance.revenue_low, facts.guidance.revenue_high = _billions(entry, low), _billions(entry, high)
    facts.guidance.gross_margin = _grounded(data.get("guidance_gross_margin"), "number", haystack)
    facts.guidance.eps = _grounded(data.get("guidance_eps"), "number", haystack)
    return facts


# --- judge ------------------------------------------------------------------------------------------------

JUDGE_PROMPT = """你是读财报的人，要像一个懂这家公司的行业分析师那样，读完这份财报后判断：发布后第一个交易日，股价是涨、是跌，还是说不准。
只输出一个 JSON 对象，不要解释。格式：
{"direction":"up|down|unclear","confidence":"high|medium|low","reasons":[{"text":"一句话理由","quote":"原文里逐字照抄的一小段"}],"counter_argument":"最有力的反方理由"}

怎么读（不要把它简化成"超预期多少个百分点"的机械门槛）：
1. 本季实际对比上季指引，但要扣掉这家公司惯常超出的幅度（comparison 里的 *_excess_pct）。公司常把指引说低，超出指引本身不算新闻，只有超出的部分比惯常更多或更少才是信息。
2. 市场更看新指引：下一季营收、毛利率、每股收益的指引，对比本季实际和往年同期（new_*_vs_actual、new_*_vs_year_ago）。新指引明显低于本季实际，哪怕本季大幅超预期，也偏跌；新指引明显高于本季，哪怕本季平淡，也偏涨。
3. 管理层对后市的说法（commentary 与原文）：需求、供给、行业放缓持续多久、对下几个季度的措辞是更肯定还是更保留。
4. 超出部分的质量：一次性收益、税率、GAAP 与 non-GAAP 的差（eps_gaap_minus_nongaap）、毛利率是否靠一次性因素。
5. 财报前股价已经涨跌了多少（pre_release_return_*）：已经大涨说明好消息已被计入，门槛更高；已经大跌则坏消息部分已计入。
6. 如果给了 after_hours_return，它是盘后的真实反应，可作参考，但不能代替你对基本面的判断。

规则：
- 把握怎么给：新指引相对本季实际的变化越大、同向的项越多（营收、毛利率、每股收益一起变差或一起变好），再加上管理层措辞同向，把握越高。财报前股价已经涨跌的部分，只有在幅度与新指引的变化相当时才明显抵消它；指引大幅下调（或上调）的幅度远大于财报前已经反映的部分时，仍可给 high。
- confidence=high 只在多条独立证据指向同一个方向、且反方理由明显弱于它们时才给；证据互相打架、关键数字缺失、或你拿不准，就给 unclear 或 low/medium。说不准就说不准，不要硬判。
- direction 只表示"发布后第一个交易日是否会出现明显的涨或跌（约 3% 以上或超出平日波动两倍）"；预计没有大动，也给 unclear。
- 每条 reason 的 quote 必须是原文（财报全文或 commentary）里连续、逐字的片段，不要改写，不要翻译，不要拼接；找不到逐字的原文就不要写这条 reason。
- 不要使用你记忆里这家公司、这个季度之后的股价或新闻；只用给你的材料。"""


def _judge_payload(facts: ReleaseFacts, comparison: Comparison, commentary: str, after_hours_return) -> str:
    from dataclasses import asdict
    payload = {"facts": {k: v for k, v in asdict(facts).items() if k != "source_text"},
               "comparison": asdict(comparison), "commentary": commentary or "",
               "after_hours_return": after_hours_return,
               "release_text": facts.source_text[:JUDGE_SOURCE_CHARS]}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def judge(facts: ReleaseFacts, comparison: Comparison, commentary: str, after_hours_return: float | None,
                model: dict) -> Judgment:
    raw = await _call_model(model, JUDGE_PROMPT, _judge_payload(facts, comparison, commentary, after_hours_return))
    result = Judgment(raw=raw)
    data = _json_object(raw)
    if not data:
        return result
    direction, confidence = data.get("direction"), data.get("confidence")
    if direction not in ("up", "down", "unclear") or confidence not in ("high", "medium", "low"):
        return result
    haystack = _squash((facts.source_text or "") + "\n" + (commentary or ""))
    reasons = []
    for item in data.get("reasons") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and _in_text(item.get("quote"), haystack):
            reasons.append({"text": item["text"].strip(), "quote": item["quote"].strip()})
    result.direction, result.confidence, result.reasons = direction, confidence, reasons
    counter = data.get("counter_argument")
    result.counter_argument = counter.strip() if isinstance(counter, str) else ""
    # A confident call needs grounded reasons; without any, it is at most a hunch.
    if result.confidence == "high" and not reasons:
        result.confidence = "medium"
    return result
