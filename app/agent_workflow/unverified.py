"""Lines the source check could not support are kept and marked, never deleted.

The check used to drop a rejected line and the rewrite was told to delete what it could not
source; one wrong ``[n]`` then cost the owner a sentence whose source had in fact been fetched.
Here the code first re-points a citation slip it can prove, the rewrite may only fix ``[n]``
markers, and whatever still does not check out stays in the answer, reported as
``unverified_lines: [{line, reason, numbers}]`` so every surface can flag it.
"""
from __future__ import annotations
import re

_MARKER=re.compile(r'\[\d+\]')
_NUMBER=re.compile(r'\d[\d,]*(?:\.\d+)?\s?(?:%|万亿|亿|万|千|百万|[Mm]illion|[Bb]illion|bn|[MBK])?')
_LEAD=re.compile(r'^\s*(?:[-*+•]\s+|\d+[.)、]\s*|>\s*)')
SOURCE_BUDGET=24000
SOURCE_LIMIT=12


def line_key(line):
    """A line with its markers, list bullet, table bars and spacing removed: the identity of a sentence."""
    text=_MARKER.sub('',str(line or ''))
    text=_LEAD.sub('',text).replace('|',' ')
    return re.sub(r'\s+','',text)


def markers(line):
    return [int(n) for n in re.findall(r'\[(\d+)\]',str(line or ''))]


def _holders(value,citations):
    from .evidence import citation_check_text
    from .semantic import figure_values
    return [int(c['ordinal']) for c in citations if isinstance(c,dict) and str(c.get('ordinal') or '').isdigit()
            and value in figure_values(citation_check_text(c))]


def line_numbers(line,citations):
    """The unchecked figures of one line as written in it (unsupported or insufficient), and which of them no source holds at all."""
    from .evidence import number_check
    from .semantic import figure_values
    try:rejected=set(v for part in number_check(line,citations) for v in part)
    except Exception:rejected=set()
    written=[]
    for token in _NUMBER.findall(_MARKER.sub('',line)):
        values=set(figure_values(token))
        if values&rejected:written.append((token.strip(),values&rejected))
    return rejected,written


def entries(rejected,citations):
    """``[{line, reason, numbers}]``: ``numbers`` are the figures written in the line that no source states."""
    out=[]
    for line,code in rejected:
        _,written=line_numbers(line,citations)
        missing=[token for token,values in written if not any(_holders(v,citations) for v in values)]
        out.append({'line':line[:400],'reason':str(code),'numbers':list(dict.fromkeys(missing))})
    return out


def remap_citations(draft,rejected,citations):
    """Re-point a ``[n]`` slip when exactly one source holds every figure the check rejected on the line.

    Deterministic and conservative: only a line whose single marker names a source that does not hold
    its figures is touched.  Returns ``(new_draft, [{line, from, to}])``.
    """
    changes=[];text=draft
    for line,_ in rejected:
        rejected_values,_ = line_numbers(line,citations)
        used=markers(line)
        if not rejected_values or len(set(used))!=1:continue
        common=None
        for value in rejected_values:
            owners=set(_holders(value,citations));common=owners if common is None else common&owners
        if not common or len(common)!=1:continue
        target=next(iter(common))
        if target==used[0]:continue
        fixed=re.sub(r'\[%d\]'%used[0],'[%d]'%target,line)
        if line in text:
            text=text.replace(line,fixed,1);changes.append({'line':line[:200],'from':used[0],'to':target})
    return text,changes


def cited_sources(rejected,citations,holders=None,*,on_cut=None):
    """Quotes of the sources the rejected lines cite and of the sources that hold their figures.

    Each quote is whole; the sources are taken in priority order (cited first) until the budget is
    spent, and the rest are left out as sources.  ``on_cut(original_chars, kept_chars, left_out)`` hears of it."""
    wanted=[]
    for line,_ in rejected:wanted.extend(markers(line))
    for ordinals in (holders or {}).values():wanted.extend(int(o) for o in ordinals)
    wanted=list(dict.fromkeys(wanted))
    by_ordinal={int(c['ordinal']):c for c in citations if isinstance(c,dict) and str(c.get('ordinal') or '').isdigit()}
    sources=[{'ordinal':n,'title':str(by_ordinal[n].get('title') or '')[:160],'quote':str(by_ordinal[n].get('quote') or '')}
             for n in wanted if n in by_ordinal]
    kept=[];used=0
    for source in sources:
        cost=len(source['quote'])+len(source['title'])
        if kept and (used+cost>SOURCE_BUDGET or len(kept)>=SOURCE_LIMIT):break
        kept.append(source);used+=cost
    if on_cut and len(kept)<len(sources):
        on_cut(sum(len(s['quote'])+len(s['title']) for s in sources),used,[s['ordinal'] for s in sources[len(kept):]])
    return kept


def merge_repair(draft,rewrite):
    """Take only the ``[n]`` edits of a rewrite: every line of the draft stays, the rewrite's version of
    it is used when it is the same sentence, and lines the rewrite added are ignored."""
    candidates={}
    for line in rewrite.split('\n'):
        key=line_key(line)
        if key:candidates[key]=line
    return '\n'.join(candidates.get(line_key(line),line) if line_key(line) else line for line in draft.split('\n'))
