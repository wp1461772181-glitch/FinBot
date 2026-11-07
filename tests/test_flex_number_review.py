import json
import asyncio
from types import SimpleNamespace

import pytest

from app.agent_workflow.flex_number_review import compare_groups, positions, run_shadow, verify
from app.agent_workflow.citation_issuance import CitationIssuer


def leaf(id, ref, quote, value, unit='', unit_quote=''):
    return dict(id=id, source_ref=ref, quote=quote, value=value, unit=unit, unit_quote=unit_quote)


def result(kind, **kwargs):
    return dict(kind=kind, responsibility='current', relation='supported', **kwargs)


def test_microsoft_difference_and_uncertain_relation_still_replays():
    source = {'1': 'Revenue 900.07 亿美元 and 764.41 亿美元'}
    nodes = [leaf('a', '1', '900.07 亿美元', '900.07', '亿', '亿'),
             leaf('b', '1', '764.41 亿美元', '764.41', '亿', '亿'),
             {'id': 'diff', 'expression': 'a-b', 'inputs': {'a': 'a', 'b': 'b'}, 'unit': 'USD'}]
    p = {'id': 0, 'figure': '135.7 亿'}
    assert verify(result('derived', nodes=nodes, result_node='diff'), p, source)['status'] == 'supported'
    r = result('derived', nodes=nodes, result_node='diff'); r['relation'] = 'uncertain'
    assert verify(r, p, source)['arithmetic'] == 'matches'


@pytest.mark.parametrize('value,written', [('19,171','191.71 亿'), ('27,461','274.61 亿'), ('51,313','513.13 亿')])
def test_amazon_conversion_and_tenfold_error(value, written):
    sources = {'29': 'Amounts in millions. Operating income 19,171 27,461 37,576 51,313'}
    r = result('direct', source_ref='29', quote='Operating income 19,171 27,461 37,576 51,313',
               value=value, unit='million', unit_quote='Amounts in millions')
    assert verify(r, {'id': 0, 'figure': written}, sources)['status'] == 'supported'
    assert verify(r, {'id': 0, 'figure': str(float(written.split()[0])/10)+' 亿'}, sources)['status'] == 'finding'


def test_tesla_multistep_and_same_quantity_difference():
    sources = {'1': 'Net income 3,794 million USD; EPS 1.08 USD; price 358.22 USD'}
    nodes = [leaf('income','1','Net income 3,794','3,794','million','million'),
             leaf('eps','1','EPS 1.08','1.08'), leaf('price','1','price 358.22','358.22'),
             {'id':'shares','expression':'a/b','inputs':{'a':'income','b':'eps'},'unit':'shares'},
             {'id':'cap','expression':'a*b','inputs':{'a':'shares','b':'price'},'unit':'USD'}]
    good = result('derived', nodes=nodes, result_node='cap')
    for id in (0, 1):
        assert verify(good, {'id': id, 'figure':'1.26 万亿'}, sources)['status'] == 'supported'
    wrong = verify(good, {'id':2,'figure':'1,258.4 亿'}, sources)
    assert wrong['reason'] == 'arithmetic_difference'
    pos = [{'id':0,'figure':'1.26 万亿'}, {'id':2,'figure':'1,258.4 亿'}]
    assert compare_groups([[0,2]],pos)[0]['reason'] == 'same_quantity_difference'
    nodes[-1]['expression'] = 'a/b'
    assert verify(good, {'id':0,'figure':'1.26 万亿'}, sources)['status'] == 'finding'


def test_historical_responsibility_and_citation_issuance():
    sources = {'28': 'Market cap 741.38 亿美元 as of 2024-07-31', '27': 'PE ratio 23.83 as of 2026-09-30'}
    r = result('direct', source_ref='28', quote='741.38 亿美元', value='741.38', unit='亿', unit_quote='亿')
    r['responsibility'] = 'historical'
    assert verify(r, {'id':0,'figure':'741.38 亿'}, sources)['responsibility'] == 'historical'
    r['responsibility'] = 'current'
    assert verify(r, {'id':0,'figure':'741.38 亿'}, sources)['responsibility'] == 'current'
    issuer = CitationIssuer(sources); issuer.register_block('b1', 1)
    issue = issuer.issue({'anchor': {'block_id':'b1','revision':1}, 'source_ref':'27', 'quote':'PE ratio 23.83'})
    assert issue['ok'] and issue['item']['source_ref'] == '27'
    assert issuer.issue({'anchor': {'block_id':'b1','revision':1}, 'source_ref':'28','quote':'fabricated'})['error'] == 'quote_not_in_snapshot'
    assert [p['figure'] for p in positions('营业利润 191.71 [28→注]')]==['191.71']


def test_shadow_retries_and_saves_invalid_raw_without_public_mutation(tmp_path, monkeypatch):
    monkeypatch.setenv('FLEX_NUMBER_SHADOW','on'); monkeypatch.setenv('CLAIM_JUDGE_SHADOW_DIR',str(tmp_path))
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_MODEL','test')
    calls = []
    async def call(model, system, user):
        calls.append(json.loads(user))
        return {}, {'content': 'invalid json'}
    async def resolve(name): return {'api_key':'x'}
    turn = SimpleNamespace(owner=True, state={'turn_id':'t'}, citations=[])
    result0 = {'answer':'Revenue 135.7', 'unverified_lines':[]}
    asyncio.run(run_shadow(turn,result0,call=call,resolve=resolve))
    assert len(calls)==2 and calls[1]['retry']
    rows = [json.loads(line) for line in next((tmp_path/'flex-numbers').glob('*.jsonl')).read_text().splitlines()]
    assert [r['raw_response'] for r in rows if r['kind']=='response'] == ['invalid json']*2
    assert rows[-1]['pending_ids'] == [0] and result0 == {'answer':'Revenue 135.7','unverified_lines':[]}


def test_issuance_rejects_unknown_stale_ambiguous_and_does_not_reuse_ids():
    issuer = CitationIssuer({'s': 'repeated repeated; one-off'})
    issuer.register_block('b', 1)
    def item(ref, quote, revision=1):
        return {'anchor': {'block_id': 'b', 'revision': revision}, 'source_ref': ref, 'quote': quote}
    assert issuer.issue(item('outside', 'one-off'))['error'] == 'source_not_in_turn'
    assert issuer.issue(item('s', 'repeated'))['error'] == 'quote_ambiguous'
    first = issuer.issue(item('s', 'one-off'))['item']
    issuer.register_block('b', 2)
    assert issuer.issue(item('s', 'one-off'))['error'] == 'anchor_revision_changed'
    second = issuer.issue(item('s', 'one-off', 2))['item']
    assert first['citation_id'] != second['citation_id']


def test_shadow_daily_budget_limits_attempts_and_records_skip(tmp_path, monkeypatch):
    monkeypatch.setenv('FLEX_NUMBER_SHADOW', 'on')
    monkeypatch.setenv('FLEX_NUMBER_DAILY_CALL_LIMIT', '1')
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_DIR', str(tmp_path))
    monkeypatch.setenv('CLAIM_JUDGE_SHADOW_MODEL', 'test')
    calls = []
    async def call(*args):
        calls.append(1)
        return {}, {'content': 'invalid'}
    async def resolve(name): return {'api_key': 'x'}
    turn = SimpleNamespace(owner=True, state={}, citations=[])
    asyncio.run(run_shadow(turn, {'answer': 'Revenue 123'}, call=call, resolve=resolve))
    rows = [json.loads(line) for line in next((tmp_path / 'flex-numbers').glob('*.jsonl')).read_text().splitlines()]
    assert len(calls) == 1
    assert rows[-1]['status'] == 'budget_exhausted'
    assert rows[-1]['pending_ids'] == [0]


def test_shadow_scheduling_does_not_wait_for_review(monkeypatch):
    from app.agent_workflow import flex_number_review as flex
    monkeypatch.setenv('FLEX_NUMBER_SHADOW', 'on')
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        captured = []
        async def slow(turn, result):
            captured.append((turn, result))
            started.set()
            await release.wait()
        monkeypatch.setattr(flex, 'run_shadow', slow)
        turn = SimpleNamespace(owner=True, state={'turn_id': 'one'}, citations=[])
        result = {'answer': '123'}
        flex.schedule_shadow(turn, result)
        result['answer'] = 'changed'
        await started.wait()
        assert captured[0][1]['answer'] == '123'
        assert flex._TASKS
        release.set()
        await asyncio.gather(*list(flex._TASKS))
    asyncio.run(check())


def test_unit_evidence_must_really_contain_unit_and_leaf_value():
    source = {'1': 'Revenue 19,171; unit million'}
    item = result('direct', source_ref='1', quote='Revenue 19,171', value='19,171', unit='million', unit_quote='Revenue')
    assert verify(item, {'id': 0, 'figure':'191.71 亿'}, source)['reason'] == 'unit_binding_unconfirmed'
    item['unit_quote'] = 'unit million'; item['value'] = '19'
    assert verify(item, {'id': 0, 'figure':'191.71 亿'}, source)['reason'] == 'operand_value_unconfirmed'
