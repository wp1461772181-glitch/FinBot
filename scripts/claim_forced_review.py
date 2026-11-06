"""Forced-candidate stress test for the short review (round-8 spec section 3-D).

The judge is bypassed: each case builds a contradiction candidate by hand (quote_verified=True, quote from the
source) and feeds it straight to ``review_candidate``.  Every case here is a sentence that should NOT open the door
(clean, unverifiable, the P4 'that week' cases, the control traps C1-C3, and synthetic honest twins), so a
``passed=True`` is a false door opening.  Each case runs with subtype ``number`` and with subtype ``state``.

Sets:
  S1  185 corpus sentences the r8 judge marked ``supported`` with a verified quote (gold clean or unverifiable).
      The quote is the judge's own quote from r8.  Context: same-turn neighbours (+-2 sentences).
  S2  practice controls C1-C3 from .local/trap-practice-r7.json.  Quote: the source line containing 'Q2 2026'.
  S3  bf23fa72's six sentences (P4 class).  Quote: the line of source [18]/[19] that contains '10%'.
      Context: same-turn neighbours.
  S4  synthetic honest twins, generated here from templates (never taken from the 185 corpus): six kinds,
      20 each.  Each sentence is correct; the quote is the row or line that looks like a contradiction.

Only ids are written to the output (no corpus text).  Acceptance (spec 3-D): S1+S2+S4 sentences passing under
either subtype <= 1; S3 passing = 0.  Run it on v1 first (baseline), then on v2.

Usage:
    MODEL_EGRESS_PROXY="$HTTPS_PROXY" python scripts/claim_forced_review.py \
        --model deepseek-flash --provider deepseek --base-url https://api.deepseek.com \
        --key-env DEEPSEEK_API_KEY --env-file ~/workspace/projects/FinBot/.env --out .local/forced-review-v2.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_workflow.claim_judge import JudgeResult, JudgeSource, _find_quote  # noqa: E402
from app.agent_workflow.claim_short_review import REVIEW_VERSION, review_candidate  # noqa: E402

HIDDEN = Path(os.path.expanduser('~/workspace/goals/finbot/hidden_files'))
R8 = ROOT / '.local' / 'replay185-deepseek-flash-r8.json'
PRACTICE = ROOT / '.local' / 'trap-practice-r7.json'
SUBTYPES = ('number', 'state')
SETS = ('S1', 'S2', 'S3', 'S4')
TWIN_KINDS = ('daily_vs_52w_high', 'total_vs_float_mktcap', 'fiscal_vs_calendar', 'gaap_vs_adjusted',
              'alias_same_holder', 'same_table_other_period')
TWIN_PER_KIND = 20
TWIN_SEED = 8201

NAMES = ['Vantor Systems', 'Keel Ridge Corp', 'Lumen Harbour Inc', 'Aster Fold Group', 'Corvane Labs',
         'Mistral Pier Co', 'Quarry Lane Holdings', 'Sorrel Basin Inc', 'Thistle Gate Ltd', 'Veil Crest Corp']


def _corpus_items():
    """Read-only: the frozen 185 corpus plus the r8 judge rows (gold with the erratum applied)."""
    corpus = json.loads((HIDDEN / 'corpus185.json').read_text())
    r8 = {(r['turn'], int(r['idx'])): r for r in json.loads(R8.read_text())['rows']}
    return corpus, r8


def _neighbour_context(seq: list[tuple[int, str]], idx: int) -> str:
    pos = next(i for i, (j, _) in enumerate(seq) if j == idx)
    picked = seq[max(0, pos - 2):pos] + seq[pos + 1:pos + 3]
    return '\n'.join(text for _, text in picked)


def _line_with(text: str, needle: str) -> str | None:
    for line in text.split('\n'):
        if needle in line:
            return line.strip()
    return None


def build_s1(corpus, r8, turns):
    cases = []
    for item in corpus:
        turn, idx = item['turn_id'][:8], int(item['idx'])
        row = r8.get((turn, idx))
        if not row or row['verdict'] != 'supported' or not row.get('quote') or row['gold'] not in ('clean', 'unverifiable'):
            continue
        sources = [JudgeSource(o, m['text'], m['type'], False) for o in item['ordinals']
                   for m in [item['cited'].get(str(o))] if m]
        ordinal = _find_quote(row['quote'], sources)
        if ordinal is None:
            continue
        cases.append({'set': 'S1', 'id': f'{turn}#{idx}', 'sentence': item['text'], 'sources': sources,
                      'quote': row['quote'], 'quote_ordinal': ordinal,
                      'context': _neighbour_context(turns[turn], idx)})
    return cases


def build_s2(pack_path: Path):
    cases = []
    for it in json.loads(pack_path.read_text(encoding='utf-8')):
        if it['class'] not in ('C1', 'C2', 'C3'):
            continue
        sources = [JudgeSource(s['ordinal'], s['text'], s.get('source_type'), bool(s.get('complete')))
                   for s in it['sources']]
        quote = next(_line_with(s.text, 'Q2 2026') for s in sources)
        cases.append({'set': 'S2', 'id': it['id'], 'sentence': it['sentence'], 'sources': sources,
                      'quote': quote, 'quote_ordinal': sources[0].ordinal, 'context': ''})
    return cases


def build_s3(corpus, turns):
    cases = []
    for item in corpus:
        if item['turn_id'][:8] != 'bf23fa72':
            continue
        idx = int(item['idx'])
        sources = [JudgeSource(o, m['text'], m['type'], False) for o in item['ordinals']
                   for m in [item['cited'].get(str(o))] if m]
        for source in sources:
            if source.ordinal not in (18, 19):
                continue
            quote = _line_with(source.text, '10%')
            if quote:
                cases.append({'set': 'S3', 'id': f'bf23fa72#{idx}', 'sentence': item['text'], 'sources': sources,
                              'quote': quote, 'quote_ordinal': source.ordinal,
                              'context': _neighbour_context(turns['bf23fa72'], idx)})
                break
    return cases


def _twin(kind: str, rng: random.Random, k: int):
    """Return (sentence, source_text, quote) for one honest twin.  The sentence is correct in every case."""
    name = NAMES[(k + len(kind)) % len(NAMES)]
    if kind == 'daily_vs_52w_high':
        h52 = round(rng.uniform(80, 300), 2)
        high = round(h52 * rng.uniform(0.7, 0.95), 2)
        low = round(high * 0.97, 2)
        day = f'2026-0{rng.randint(1, 9)}-{rng.randint(10, 28)}'
        text = f'* [1] date={day} high={high} low={low}（当日）\n* [1] 52-week high: {h52} (as of {day})'
        return f'{name} 的 52 周最高价为 {h52} 美元 [1]', text, text.split('\n')[0]
    if kind == 'total_vs_float_mktcap':
        mc = round(rng.uniform(5, 900), 1)
        flo = round(mc * rng.uniform(0.4, 0.9), 1)
        text = f'* [1] Float market cap: ${flo} billion (shares available to trade)\n* [1] Total market cap: ${mc} billion'
        # Source is in $ billions; 1 billion USD = 10 亿美元, so the sentence value is mc * 10 (unit-aligned).
        return f'{name} 市值约 {round(mc * 10, 1)} 亿美元 [1]', text, text.split('\n')[0]
    if kind == 'fiscal_vs_calendar':
        cal = round(rng.uniform(1, 90), 2)
        fy = round(cal * rng.uniform(0.6, 1.4), 2)
        text = (f'| Period | Revenue ($bn) |\n|---|---|\n| Fiscal Q2 FY2026 (ended 2026-07-31) | {fy} |\n'
                f'| Calendar Q2 2026 (Apr-Jun) | {cal} |')
        # Source header is "Revenue ($bn)"; the calendar value is in $ billions, so 1 bn = 10 亿美元: cal * 10.
        return (f'{name} 2026 年第二季度（日历口径）营收为 {round(cal * 10, 2)} 亿美元 [1]', text,
                '| Fiscal Q2 FY2026 (ended 2026-07-31) | ' + f'{fy} |')
    if kind == 'gaap_vs_adjusted':
        gaap = round(rng.uniform(0.1, 9), 2)
        adj = round(gaap * rng.uniform(1.1, 1.8), 2)
        text = f'* [1] Q2 2026 non-GAAP (adjusted) EPS: ${adj}\n* [1] Q2 2026 GAAP EPS: ${gaap}'
        return f'{name} 第二季度 GAAP 每股收益为 {gaap} 美元 [1]', text, text.split('\n')[0]
    if kind == 'alias_same_holder':
        short = name.split()[0] + ' Hld.'
        shares_w = rng.randrange(10, 9000)
        text = f'* [{name} Holdings ({short})] held {shares_w * 10_000:,} shares in Q2 2026'
        return f'{short} 在 2026 年第二季度持有约 {shares_w} 万股 [1]', text, text
    # same_table_other_period
    g2 = round(rng.uniform(-30, 30), 1)
    g3 = round(rng.uniform(-30, 30), 1)
    text = f'| Period | YoY revenue growth |\n|---|---|\n| Q2 2026 | {g2}% |\n| Q3 2026 | {g3}% |'
    return f'{name} 2026 年第三季度营收同比变动为 {g3}% [1]', text, f'| Q2 2026 | {g2}% |'


def build_s4():
    rng = random.Random(TWIN_SEED)
    cases = []
    for kind in TWIN_KINDS:
        for k in range(TWIN_PER_KIND):
            sentence, text, quote = _twin(kind, rng, k)
            source = JudgeSource(1, text, 'web', True)
            cases.append({'set': 'S4', 'id': f'{kind}-{k:02d}', 'sentence': sentence, 'sources': [source],
                          'quote': quote, 'quote_ordinal': 1, 'context': '', 'kind': kind})
    return cases


def build_cases(pack_path: Path):
    corpus, r8 = _corpus_items()
    turns: dict[str, list[tuple[int, str]]] = {}
    for item in corpus:
        turns.setdefault(item['turn_id'][:8], []).append((int(item['idx']), item['text']))
    for seq in turns.values():
        seq.sort()
    return build_s1(corpus, r8, turns) + build_s2(pack_path) + build_s3(corpus, turns) + build_s4()


async def run_case(case: dict, subtype: str, model, sem: asyncio.Semaphore, timeout: float) -> dict:
    candidate = JudgeResult(status='ok', verdict='contradiction', subtype=subtype, quote=case['quote'],
                            quote_verified=True, quote_ordinal=case['quote_ordinal'])
    async with sem:
        review = None
        for t in (timeout, timeout * 3):   # one retry on timeout, same as the replay's judge retry
            review = await review_candidate(case['sentence'], case['context'], case['sources'], candidate, model,
                                            timeout_seconds=t)
            if review['status'] != 'timeout':
                break
    return {'set': case['set'], 'id': case['id'], 'subtype': subtype, 'status': review['status'],
            'passed': bool(review['passed']), 'answers': review.get('answers'),
            'blockers': [list(b) for b in review['blockers']] if 'blockers' in review else None,
            'context_chars': len(case['context']),
            'quote_exact': any(s.ordinal == case['quote_ordinal'] and case['quote'] in s.text
                               for s in case['sources'])}


def summarise(rows: list[dict], cases: list[dict]) -> dict:
    out = {}
    for s in SETS:
        rs = [r for r in rows if r['set'] == s]
        ids = {c['id'] for c in cases if c['set'] == s}
        out[s] = {
            'candidates': len(ids), 'runs': len(rs),
            'sentences_passed_any_subtype': len({r['id'] for r in rs if r['passed']}),
            'runs_passed': sum(r['passed'] for r in rs),
            'quote_not_exact': sum(not r['quote_exact'] for r in rs),
            'by_subtype': {st: {'passed': sum(r['passed'] for r in rs if r['subtype'] == st),
                                'status': dict(Counter(r['status'] for r in rs if r['subtype'] == st))}
                           for st in SUBTYPES},
            'blockers_histogram': dict(Counter(f'{k}={v}' for r in rs for k, v in (r['blockers'] or []))),
        }
    out['S1+S2+S4_sentences_passed_any_subtype'] = sum(out[s]['sentences_passed_any_subtype'] for s in ('S1', 'S2', 'S4'))
    out['S3_runs_passed'] = out['S3']['runs_passed']
    return out


async def main_async(args) -> None:
    if args.env_file:
        from dotenv import dotenv_values
        key = dotenv_values(args.env_file).get(args.key_env) or ''
    else:
        key = os.environ.get(args.key_env) or ''
    if not key:
        raise SystemExit(f'missing key in {args.key_env}')
    model = {'provider': args.provider, 'model': args.model, 'api_key': key, 'base_url': args.base_url}
    cases = build_cases(Path(args.pack))
    sem = asyncio.Semaphore(args.concurrency)
    tasks = [run_case(c, st, model, sem, args.timeout) for c in cases for st in SUBTYPES]
    rows = await asyncio.gather(*tasks)
    summary = summarise(rows, cases)
    Path(args.out).write_text(json.dumps({'review_version': REVIEW_VERSION, 'model': args.model,
                                          'provider': args.provider, 'context': 'same-turn neighbours (+-2)',
                                          'summary': summary, 'rows': rows}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--provider', required=True)
    p.add_argument('--base-url', default=None)
    p.add_argument('--key-env', required=True)
    p.add_argument('--env-file', default=None)
    p.add_argument('--pack', default=str(PRACTICE))
    p.add_argument('--out', required=True)
    p.add_argument('--concurrency', type=int, default=8)
    p.add_argument('--timeout', type=float, default=45.0)
    asyncio.run(main_async(p.parse_args()))


if __name__ == '__main__':
    main()
