"""Replay the 185-sentence gold corpus through the claim judge and the candidate gate.

Offline tool: no database, no answer flow.  It reads the frozen corpus and gold (read-only) and applies the
gold erratum (``.local/spec-gold-erratum.md``): 4af91120 idx4 and idx5 count as clean.  Each sentence goes
through ``judge_claims``; a contradiction candidate then goes through ``review_candidate`` and an attribution
candidate through ``review_attribution`` (the short review).  A sentence "opens the door" when a contradiction candidate passes its short review.
Attribution review passes are reported separately and do not open the production public gate.

Usage:
    python scripts/claim_replay_185.py --model deepseek-flash --provider deepseek \
        --base-url https://api.deepseek.com --key-env DEEPSEEK_API_KEY --out .local/replay185-deepseek-flash.json

The API key is read from the environment variable named by ``--key-env`` (or from ``--env-file``) and is never
written to the output.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent_workflow.claim_judge import JudgeSource, judge_claims  # noqa: E402
from app.agent_workflow.claim_short_review import REVIEW_VERSION, review_attribution, review_candidate  # noqa: E402

HIDDEN = Path(os.path.expanduser('~/workspace/goals/finbot/hidden_files'))
ERRATUM_CLEAN = {('4af91120', 4), ('4af91120', 5)}  # spec-gold-erratum: idx4/idx5 are clean sentences


def load_items(corpus_path: Path, gold_path: Path):
    corpus = json.loads(corpus_path.read_text())
    gold = {(g['turn'], g['idx']): g for g in json.loads(gold_path.read_text())}
    items = []
    for c in corpus:
        key = (c['turn_id'][:8], c['idx'])
        label = gold[key]['gold']
        if key in ERRATUM_CLEAN:
            label = 'clean'
        sources = []
        for o in c['ordinals']:
            m = c['cited'].get(str(o))
            if m:
                sources.append(JudgeSource(o, m['text'], m['type'], False))
        items.append({'turn': key[0], 'idx': key[1], 'text': c['text'], 'sources': sources,
                      'gold': label, 'gold_raw': gold[key]['gold']})
    return items


def adjacent_contexts(items):
    """Answer context for the short review: the same turn's neighbouring sentences (up to 2 before and 2 after,
    ordered by idx).  Keyed by (turn, idx).  The judge never sees this; only the review does (as in production,
    where the review gets the paragraph)."""
    by_turn = {}
    for it in items:
        by_turn.setdefault(it['turn'], []).append((it['idx'], it['text']))
    out = {}
    for turn, seq in by_turn.items():
        seq.sort()
        for pos, (idx, _) in enumerate(seq):
            picked = seq[max(0, pos - 2):pos] + seq[pos + 1:pos + 3]
            out[(turn, idx)] = '\n'.join(text for _, text in picked)
    return out


async def review_with_retry(fn, timeout_seconds):
    """Same policy as the judge: one retry with three times the timeout."""
    review = None
    for timeout in (timeout_seconds, timeout_seconds * 3):
        review = await fn(timeout)
        if review['status'] != 'timeout':
            break
    return review


async def judge_item(item, model, sem, timeout_seconds, context=''):
    async with sem:
        result = None
        for timeout in (timeout_seconds, timeout_seconds * 3):
            result = await judge_claims(item['text'], item['sources'], model, timeout_seconds=timeout)
            if result.status != 'timeout':
                break
        row = {'turn': item['turn'], 'idx': item['idx'], 'gold': item['gold'], 'gold_raw': item['gold_raw'],
               'status': result.status, 'verdict': result.verdict, 'subtype': result.subtype,
               'quote_verified': result.quote_verified, 'reason': result.reason, 'quote': result.quote,
               'latency_ms': result.latency_ms, 'error_code': result.error_code,
               'attribution_candidates': len(result.attribution_candidates),
               'review': None, 'blockers': None, 'door_open': False}
        if result.status != 'ok':
            return row
        if result.verdict == 'contradiction' and result.quote_verified:
            review = await review_with_retry(lambda t: review_candidate(
                item['text'], context, item['sources'], result, model, timeout_seconds=t), timeout_seconds)
            row['review'] = {'status': review['status'], 'passed': review['passed'], 'answers': review.get('answers'),
                             'blockers': [list(b) for b in review.get('blockers', [])]}
            row['blockers'] = row['review']['blockers'] if review['status'] == 'ok' else None
            row['door_open'] = bool(review['passed'])
        for figure in result.attribution_candidates:
            review = await review_attribution(item['text'], context, item['sources'], figure['text'], model,
                                              timeout_seconds=timeout_seconds)
            row.setdefault('attribution_reviews', []).append({'status': review['status'],
                                                              'passed': review['passed'],
                                                              'answers': review.get('answers')})
        return row


def summarize(rows, context_mode):
    judged = [r for r in rows if r['status'] == 'ok']
    reviewed = [r for r in rows if r['review'] is not None]
    problems = [r for r in rows if r['gold'] == 'problem']
    cleans = [r for r in rows if r['gold'] == 'clean']
    unver = [r for r in rows if r['gold'] == 'unverifiable']
    def flagged(r):
        return r['status'] == 'ok' and r['verdict'] != 'supported'
    out = {
        'answer_context': context_mode,
        'total': len(rows),
        'judged_ok': len(judged),
        'status_counts': dict(Counter(r['status'] for r in rows)),
        'gold_counts': {'problem': len(problems), 'clean': len(cleans), 'unverifiable': len(unver)},
        'problem_judge_flagged': sum(1 for r in problems if flagged(r)),
        'problem_contradiction_only': sum(1 for r in problems if r['verdict'] == 'contradiction'),
        'problem_door_open': sum(1 for r in problems if r['door_open']),
        'clean_judge_flagged': sum(1 for r in cleans if flagged(r)),
        'clean_contradiction': sum(1 for r in cleans if r['verdict'] == 'contradiction'),
        'clean_door_open': sum(1 for r in cleans if r['door_open']),
        'unverifiable_door_open': sum(1 for r in unver if r['door_open']),
        'problem_missed_by_door': [f"{r['turn']}#{r['idx']}" for r in problems if not r['door_open']],
        'clean_door_open_list': [f"{r['turn']}#{r['idx']}" for r in cleans if r['door_open']],
        'contradiction_candidates': sum(1 for r in rows if r['verdict'] == 'contradiction' and r['quote_verified']),
        'attribution_reviews_passed': sum(bool(a['passed']) for r in rows
                                          for a in r.get('attribution_reviews', [])),
        'reviewed': len(reviewed),
        'reviewed_status': dict(Counter(r['review']['status'] for r in reviewed)),
        'reviewed_by_gold': dict(Counter(r['gold'] for r in reviewed)),
        'door_open_by_gold': {g: sum(1 for r in rows if r['gold'] == g and r['door_open'])
                              for g in ('problem', 'clean', 'unverifiable')},
        'blockers_histogram': dict(Counter(f'{k}={v}' for r in reviewed for k, v in r['review']['blockers'])),
    }
    return out


async def main_async(args):
    if args.env_file:
        from dotenv import dotenv_values
        env = dotenv_values(args.env_file)
        key = env.get(args.key_env) or ''
    else:
        key = os.environ.get(args.key_env) or ''
    if not key:
        raise SystemExit(f'missing key in {args.key_env}')
    model = {'provider': args.provider, 'model': args.model, 'api_key': key, 'base_url': args.base_url}
    items = load_items(Path(args.corpus), Path(args.gold))
    contexts = adjacent_contexts(items) if args.context == 'adjacent' else {}
    sem = asyncio.Semaphore(args.concurrency)
    started = time.time()
    tasks = [judge_item(item, model, sem, args.timeout,
                        contexts.get((item['turn'], item['idx']), '')) for item in items]
    rows = []
    for done, fut in enumerate(asyncio.as_completed(tasks), 1):
        rows.append(await fut)
        if done % 25 == 0:
            print(f'{done}/{len(items)} ({time.time() - started:.0f}s)', flush=True)
    rows.sort(key=lambda r: (r['turn'], r['idx']))
    summary = summarize(rows, args.context)
    Path(args.out).write_text(json.dumps({'model': args.model, 'provider': args.provider,
                                          'review_version': REVIEW_VERSION, 'answer_context': args.context,
                                          'rows': rows, 'summary': summary}, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', required=True)
    p.add_argument('--provider', required=True)
    p.add_argument('--base-url', default=None)
    p.add_argument('--key-env', required=True)
    p.add_argument('--env-file', default=None)
    p.add_argument('--corpus', default=str(HIDDEN / 'corpus185.json'))
    p.add_argument('--gold', default=str(HIDDEN / 'gold-final.json'))
    p.add_argument('--out', required=True)
    p.add_argument('--concurrency', type=int, default=4)
    p.add_argument('--timeout', type=float, default=45.0)
    p.add_argument('--context', choices=['adjacent', 'none'], default='adjacent',
                   help="answer_context for the short review: same-turn neighbours (adjacent) or '' (none, control)")
    asyncio.run(main_async(p.parse_args()))


if __name__ == '__main__':
    main()
