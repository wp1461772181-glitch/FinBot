"""Verify an interpreted issuer/ticker pair using official data, never an alias table."""
import re,time
from .references import normalized

_cache=None
_cached_at=0.0

def ticker_records():
    global _cache,_cached_at
    if _cache is not None and time.monotonic()-_cached_at<3600:return _cache
    from ..sec_filings import SecEdgarProvider,SEC_TICKERS_URL
    value=SecEdgarProvider()._get_json(SEC_TICKERS_URL)
    rows=[r for r in value.values() if isinstance(r,dict) and isinstance(r.get('title'),str) and isinstance(r.get('ticker'),str)]
    if not rows:raise ValueError('entity_mapping_unavailable')
    _cache=rows;_cached_at=time.monotonic()
    return rows

def issuer_words(value):
    legal={'inc','incorporated','corp','corporation','ltd','limited','plc','sa'}
    words=re.findall(r'[a-z0-9]+',normalized(value).casefold())
    while words and words[-1] in legal:words.pop()
    return words

def resolve_ticker(company):
    """Fill an omitted code only for one unambiguous official issuer match."""
    words=issuer_words(company)
    if not words or len(words[0])<3:return None
    try:
        rows=ticker_records()
        exact={r['ticker'] for r in rows if issuer_words(r['title'])==words}
        if exact:return next(iter(exact)) if len(exact)==1 else None
        symbols={r['ticker'] for r in rows if issuer_words(r['title'])[:len(words)]==words}
        return next(iter(symbols)) if len(symbols)==1 else None
    except Exception:return None

def sec_title(symbol):
    """The official SEC title of a listed ticker, or None when SEC does not list it."""
    if not symbol:return None
    try:
        return next((r['title'] for r in ticker_records() if r['ticker'].casefold()==str(symbol).casefold()),None)
    except Exception:return None

def verified_pair(company,symbol):
    if not company or not symbol:return False
    words=issuer_words(company)
    if not words or len(words[0])<3:return False
    try:
        return any(r['ticker'].casefold()==symbol.casefold() and issuer_words(r['title'])[:len(words)]==words for r in ticker_records())
    except Exception:return False

# Words that say what kind of thing an issuer is, not which one: 'Eli Lilly and Company' and 'ELI LILLY & Co' are one name.
_NAME_FILLER=frozenset({'and','the','of','co','company','companies','corp','corporation','inc','incorporated','ltd','limited','plc','sa','llc','group','holding','holdings'})
# A rewrite writes 微软（Microsoft，NASDAQ: MSFT）: the listing venue is not a claim about which company it is.
_EXCHANGES=frozenset({'nyse','nasdaq','amex','otc'})

def name_fits_title(name,title):
    """Looser than verified_pair, for a model's own form of a name: one side's distinctive words all appear in the other.
    'Bank of America' does not fit BANK OF NOVA SCOTIA, whose only shared distinctive word is 'bank'."""
    ours=[w for w in issuer_words(name) if w not in _NAME_FILLER]
    theirs=[w for w in issuer_words(title) if w not in _NAME_FILLER]
    if not ours or not theirs:return False
    shorter,longer=sorted((ours,theirs),key=len)
    return set(shorter)<=set(longer)

def mapped_title(names,symbol):
    """The SEC title when a model's mapping of a name to this ticker can stand: SEC lists the ticker and no Latin name
    the model gave contradicts its title.  A name with no Latin words cannot be compared, so it cannot contradict."""
    title=sec_title(symbol)
    if not title:return None
    for name in names:
        name=str(name or '').strip()
        if not re.search(r'[A-Za-z]',name) or name.casefold()==str(symbol).casefold() or name.casefold() in _EXCHANGES:continue
        if not name_fits_title(name,title):return None
    return title
