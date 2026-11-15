"""SW1C omitted-readings digest (spec-sw1c §6.1, U0–U9): the digest of what evidence_payload leaves out.

Turns are built with Turn.__new__ (as test_truncation_governance does); no database is touched. U1 and U3 use the real
figure_rows output (through rows_of); the other shapes use the same keys with a padded excerpt, about the size of a real row.
"""
import itertools
import json
import re

import pytest

from app.agent_workflow import direct, truncation
from app.agent_workflow.direct import Turn
from app.agent_workflow.financials import METRIC_LABELS_ZH
from test_sw1b_closing_complete import rows_of
from sw1_filings import aapl_filings, msft_filings, nvda_filings

SWITCH = 'FINBOT_SW1C_OMITTED_DIGEST'
SWITCHES = (SWITCH, 'FINBOT_SW1B_CLOSING_COMPLETE', 'FINBOT_SW1B_SAMPLE_AGGREGATE', 'FINBOT_SW1_READ_WIDEN',
            'FINBOT_SW1_ABSENCE_RECHECK', 'FINBOT_SW1_FRESHNESS', 'FINBOT_SW1_EXISTENCE_KNOWLEDGE', 'FINBOT_SW1_RESOLVER_RULES')
FILLER = '填充' * 350          # 700 characters of padding: an excerpt about the size a real row has on the box
Q3_SYMBOLS = ['AAPLX', 'MSFTX', 'NVDAX', 'AMZNX', 'GOOGX']


@pytest.fixture(autouse=True)
def switches_default(monkeypatch):
    for name in SWITCHES:
        monkeypatch.delenv(name, raising=False)


# ---- helpers -------------------------------------------------------------------------------------------------------

def turn_with(symbols=None):
    """A bare Turn as test_truncation_governance builds it; ``symbols=None`` leaves ``scope`` unset (K4)."""
    turn = Turn.__new__(Turn)
    turn.audit = {}
    turn.feedback = []
    turn.sets = []
    turn.figure_ledger = []
    turn.calc_attempts = []
    if symbols is not None:
        turn.scope = {'symbols': list(symbols)}
    return turn


def fig(symbol, citation, metric='revenue', period_end='2026-06-27', label='FY2026 Q3', value=82_886_000_000, span='quarter'):
    """A reported-figure row with the keys figure_rows gives."""
    return {'source_type': 'reported_figure', 'symbol': symbol, 'metric': metric,
            'label': 'Revenue' if metric == 'revenue' else 'Gross profit', 'unit': 'USD', 'value': value,
            'period_end': period_end, 'period_span': span, 'period_label': f'{label}（{period_end} 截止）',
            'citation': citation, 'excerpt': FILLER}


def obs(name, rows):
    return {'name': name, 'arguments': {}, 'accepted_evidence': True, 'result': {'ok': True, 'data': rows}}


def calc_obs(ordinal, inputs, value='77673.00', expression='a-b'):
    """A successful calculate observation, as execute_read keeps it: the calculate result plus its [n]."""
    return {'name': 'calculate', 'arguments': {'expression': expression, 'inputs': inputs}, 'accepted_evidence': True,
            'result': {'ok': True, 'data': [{'value': value, 'expression': expression, 'inputs': inputs, 'parents': [],
                                              'derived': True, 'citation': f'[{ordinal}]'}]}}


def ordinal_of_line(line):
    marker = re.match(r'\[(\d+)\]', line)
    return int(marker[1]) if marker else None


def lines_of(digest):
    """The digest's lines after the head (the tail line included when present)."""
    return digest.split('\n')[1:]


def data_citations(text):
    """The citations of the rows the DATA message shows."""
    found = set()
    for observation in json.loads(text[text.index('[{'):]):
        for row in (observation.get('result') or {}).get('data') or []:
            if isinstance(row, dict) and row.get('citation'):
                found.add(row['citation'])
    return found


def company_rows(symbol, first, periods=30):
    """30 periods x 2 metrics for one company, citations from ``first`` on; returns (rows, next free citation)."""
    rows, ordinal = [], first
    for i in range(periods):
        for metric in ('revenue', 'gross_profit'):
            rows.append(fig(symbol, f'[{ordinal}]', metric=metric, period_end=f'{2000 + i}-12-31', label=f'FY{2000 + i} Q4'))
            ordinal += 1
    return rows, ordinal


def q3_two_shape():
    """Q3#2: 13 reads (AAPLX and MSFTX twice, then NVDAX, AMZNX, GOOGX three times each) and 15 calculations; the first
    five calculations take their inputs from AAPLX and MSFTX rows, the rest from the later three companies."""
    filings = {'AAPLX': aapl_filings(), 'MSFTX': msft_filings(), 'NVDAX': nvda_filings(),
               'AMZNX': nvda_filings(), 'GOOGX': nvda_filings()}
    counter = itertools.count(1)
    rows_by = {}
    for symbol in Q3_SYMBOLS:
        rows = rows_of(symbol, filings[symbol])
        for row in rows:
            row['citation'] = f'[{next(counter)}]'
            row['excerpt'] = (row['excerpt'] + FILLER)[:700]
        rows_by[symbol] = rows
    reads = ['AAPLX'] * 2 + ['MSFTX'] * 2 + ['NVDAX'] * 3 + ['AMZNX'] * 3 + ['GOOGX'] * 3
    observations = [obs('query_financials', [dict(row) for row in rows_by[symbol]]) for symbol in reads]
    for i in range(15):
        ordinal = next(counter)
        if i < 5:
            a, b = rows_by['AAPLX'][i]['citation'], rows_by['MSFTX'][i]['citation']
        else:
            later = Q3_SYMBOLS[2 + i % 3]
            a, b = rows_by[later][0]['citation'], rows_by[later][1]['citation']
        observations.append(calc_obs(ordinal, [{'name': 'a', 'value': '331839', 'source_ordinal': int(a[1:-1])},
                                               {'name': 'b', 'value': '114634', 'source_ordinal': int(b[1:-1])}]))
    return observations, rows_by


# ---- U0: fit_observations_detail ------------------------------------------------------------------------------------

def _shape_u0(kind):
    if kind == 'no_omission':
        return [obs('web_research', [fig('CO1', '[1]', period_end='2026-01-01')]) for _ in range(3)], 22000
    if kind == 'over_ten':
        return [obs('web_research', [fig('CO1', f'[{n}]')]) for n in range(12)], 22000
    if kind == 'half_cut':
        return [obs('query_financials', [fig('CO1', f'[{10 * n + r}]') for r in range(4)]) for n in range(4)], 5000
    return ([obs('query_financials', [fig('CO1', f'[{n}]')]) for n in range(12)]
            + [{'name': 'web_research', 'accepted_evidence': True, 'result': {'ok': True}},
               {'name': 'x', 'accepted_evidence': True, 'result': 'not a dict of rows'}], 3000)


@pytest.mark.parametrize('kind', ['no_omission', 'over_ten', 'half_cut', 'no_data_observations'])
def test_u0_detail_matches_the_old_four_tuple_and_drops_exactly_the_rest(kind):
    observations, budget = _shape_u0(kind)
    old = truncation.fit_observations(observations, budget)
    detail = truncation.fit_observations_detail(observations, budget)
    assert old == detail[:4]
    kept, dropped = detail[0], detail[4]
    in_order = [row for obs_ in observations if isinstance(obs_.get('result'), dict)
                and isinstance(obs_['result'].get('data'), list) for row in obs_['result']['data']]
    kept_ids = {id(row) for obs_ in kept if isinstance(obs_.get('result'), dict) and isinstance(obs_['result'].get('data'), list)
                for row in obs_['result']['data']}
    assert [id(row) for _, row in dropped] == [id(row) for row in in_order if id(row) not in kept_ids]
    if kind == 'no_omission':
        assert dropped == []


# ---- U1: the Q3#2 shape ----------------------------------------------------------------------------------------------

def test_u1_q3_two_shape_is_listed_in_full_for_the_two_companies_and_the_first_five_calculations(monkeypatch):
    observations, rows_by = q3_two_shape()
    monkeypatch.setenv(SWITCH, 'off')
    off = turn_with(Q3_SYMBOLS)
    off_text = off.evidence_payload(observations)
    off_messages = off.evidence_messages(observations)
    monkeypatch.delenv(SWITCH)
    on = turn_with(Q3_SYMBOLS)
    on_text = on.evidence_payload(observations)
    on_messages = on.evidence_messages(observations)

    assert on_text == off_text                                              # (a)
    assert len(off_messages) == 1 and len(on_messages) == 2                 # (b)
    assert on_messages[0] == off_messages[0]
    digest = on_messages[1]['content']
    lines = digest.split('\n')
    assert lines[0] == direct.OMITTED_DIGEST_HEAD
    for symbol in ('AAPLX', 'MSFTX'):                                       # (c) every quarter row in full
        for row in rows_by[symbol]:
            expected = f"{row['citation']} {symbol} {METRIC_LABELS_ZH[row['metric']]} " \
                       f"{row['period_label'].split('（')[0]} {direct.figure_value_text(row)}"
            assert expected in lines, expected
    calc_citations = [obs_['result']['data'][0]['citation'] for obs_ in observations if obs_['name'] == 'calculate']
    for citation in calc_citations[:5]:                                     # (d) the first five calculations, with inputs
        assert any(line.startswith(f'{citation} 计算结果') and '（输入 [' in line for line in lines), citation
    for citation in calc_citations[5:]:                                     # ... and not the later ten
        assert all(ordinal_of_line(line) != int(citation[1:-1]) for line in lines), citation
    heads = [ordinal_of_line(line) for line in lines[1:] if ordinal_of_line(line) is not None]
    assert len(heads) == len(set(heads))                                    # (e) each number once
    audit = on.audit['omitted_digest']
    assert audit['figures'] == sum('计算结果' not in line for line in lines[1:] if ordinal_of_line(line) is not None)
    assert audit['calcs'] == 5 and audit['chars'] == len(digest)            # (f)
    assert audit['symbols'][:2] == ['AAPLX', 'MSFTX']
    assert 'omitted_digest_trimmed' not in on.audit                         # (g)


# ---- U2: nothing omitted --------------------------------------------------------------------------------------------

def test_u2_nothing_omitted_means_one_message_and_no_digest_audit(monkeypatch):
    observations = [obs('query_financials', [fig('CO1', f'[{n}]')]) for n in range(1, 4)]
    turn = turn_with(['CO1'])
    text, digest = turn.evidence_parts(observations)
    assert digest == ''
    assert turn.evidence_messages(observations) == [{'role': 'system', 'content': text}]
    assert 'omitted_digest' not in turn.audit and 'truncation_events' not in turn.audit


# ---- U3: the Q3#3 shape ----------------------------------------------------------------------------------------------

def test_u3_the_two_oldest_companies_are_listed_and_the_third_is_listed_from_its_back_half():
    counter = itertools.count(1)
    symbols = [f'CO{i}' for i in range(1, 10)]
    rows_by = {}
    for symbol in symbols:
        # CO3 has six rows so that the budget cut falls inside its read (three rows kept, three left out).
        rows_by[symbol] = [fig(symbol, f'[{next(counter)}]', metric='revenue', period_end=f'20{20 + i}-12-31',
                               label=f'FY20{20 + i} Q4') for i in range(6 if symbol == 'CO3' else 3)]
    observations = [obs('query_financials', [dict(row) for row in rows_by[symbol]]) for symbol in symbols]
    # The newest read repeats the first row of the oldest company: one citation, in the DATA and out of the ledger.
    repeated = dict(rows_by['CO1'][0])
    observations[-1]['result']['data'].append(repeated)
    turn = turn_with(symbols)
    text, digest = turn.evidence_parts(observations)
    shown = data_citations(text)
    listed = {line.split(' ')[0] for line in lines_of(digest) if ordinal_of_line(line) is not None}
    c1, c2, c3 = rows_by['CO1'], rows_by['CO2'], rows_by['CO3']

    # The shape: the two oldest companies are gone from the DATA (CO1's first row only as the repeat); CO3 keeps its front.
    assert all(row['citation'] in shown for row in c3[:3]) and all(row['citation'] not in shown for row in c3[3:])
    assert repeated['citation'] in shown and repeated['citation'] not in listed   # in the DATA, so not in the ledger
    left_out = {row['citation'] for row in c1[1:] + c2} | {row['citation'] for row in c3[3:]}
    assert left_out <= listed and not (shown & listed)


def with_limit(monkeypatch, value):
    monkeypatch.setattr(direct, 'OMITTED_DIGEST_LIMIT', value)


def recent_filler(n=10):
    """Empty recent observations: they keep the older ones out of the payload without adding any row."""
    return [obs('web_research', []) for _ in range(n)]


# ---- U4: the limit ---------------------------------------------------------------------------------------------------

def test_u4_five_companies_of_thirty_periods_are_cut_round_by_round_and_each_keeps_its_newest(monkeypatch):
    symbols = [f'CO{i}' for i in range(5)]
    observations, ordinal = [], 1
    for symbol in symbols:
        rows, ordinal = company_rows(symbol, ordinal)
        observations.append(obs('query_financials', rows))
    observations += recent_filler()
    with_limit(monkeypatch, 10 ** 6)
    assert len(turn_with(symbols).evidence_parts(observations)[1]) > 6000       # precondition: the limit is what cuts
    with_limit(monkeypatch, 6000)
    turn = turn_with(symbols)
    text, digest = turn.evidence_parts(observations)
    body = digest.split('\n')
    assert body[0] == direct.OMITTED_DIGEST_HEAD and len(digest) <= 6000
    removed = int(re.fullmatch(r'（另有 (\d+) 条更早的已读数已省略）', body[-1])[1])
    kept_lines = body[1:-1]
    assert len(kept_lines) + removed == 5 * 60
    assert turn.audit['omitted_digest_trimmed'] == removed
    meta = {int(row['citation'][1:-1]): (row['symbol'], row['period_end'])
            for observation in observations for row in observation['result']['data']}
    for symbol in symbols:
        kept = [ordinal_of_line(line) for line in kept_lines if line.split(' ')[1] == symbol]
        assert 8 <= len(kept) < 60                                              # every company kept some, and was cut
        newest = sorted((o for o, (s, _) in meta.items() if s == symbol), key=lambda o: (meta[o][1], o), reverse=True)
        assert kept == newest[:len(kept)]                                       # and what is kept is its newest


def test_u4b_twenty_companies_of_ten_rows_keep_at_least_one_each(monkeypatch):
    symbols = [f'CO{i:02d}' for i in range(20)]
    observations, ordinal = [], 1
    for symbol in symbols:
        rows = []
        for i in range(10):
            rows.append(fig(symbol, f'[{ordinal}]', period_end=f'{2000 + i}-12-31', label=f'FY{2000 + i} Q4'))
            ordinal += 1
        observations.append(obs('query_financials', rows))
    observations += recent_filler()
    newest_eight = [('query_financials', row) for observation in observations[:20] for row in observation['result']['data'][-8:]]
    with_limit(monkeypatch, 10 ** 6)
    assert len(turn_with(symbols).omitted_digest([], newest_eight)) > 6000      # precondition: eight each is still over
    with_limit(monkeypatch, 6000)
    turn = turn_with(symbols)
    text, digest = turn.evidence_parts(observations)
    body = digest.split('\n')
    assert len(digest) <= 6000
    kept_symbols = [line.split(' ')[1] for line in body[1:-1]]
    assert set(kept_symbols) == set(symbols)                                    # (i) each company keeps one line
    removed = 200 - len(body[1:-1])
    assert body[-1] == direct.OMITTED_DIGEST_TAIL.format(n=removed)
    assert turn.audit['omitted_digest_trimmed'] == removed


def test_u4b_two_hundred_companies_of_one_row_go_whole_groups_last_first(monkeypatch):
    symbols = [f'S{i:03d}' for i in range(200)]
    observations = [obs('query_financials', [fig(s, f'[{n}]', period_end='2026-06-27', label='FY2026 Q3')])
                    for n, s in enumerate(symbols, 1)]
    observations += recent_filler()
    one_each = [('query_financials', observation['result']['data'][0]) for observation in observations[:200]]
    with_limit(monkeypatch, 10 ** 6)
    assert len(turn_with(None).omitted_digest([], one_each)) > 6000             # precondition: one each is still over
    with_limit(monkeypatch, 6000)
    turn = turn_with(None)                                                       # no scope at all (K4)
    text, digest = turn.evidence_parts(observations)
    body = digest.split('\n')
    assert len(digest) <= 6000
    kept_symbols = [line.split(' ')[1] for line in body[1:-1]]
    k = len(kept_symbols)
    assert kept_symbols == symbols[:k]                                          # whole groups, last first
    assert turn.audit['omitted_digest_trimmed'] == 200 - k
    assert body[-1] == direct.OMITTED_DIGEST_TAIL.format(n=200 - k)


# ---- U5: sources the digest does not list ------------------------------------------------------------------------------

def test_u5_excerpts_quotes_price_sets_and_formula_results_left_out_give_no_digest(monkeypatch):
    observations = [
        obs('search_knowledge', [{'source_type': 'official_filing', 'citation': f'[{n}]', 'excerpt': FILLER} for n in (1, 2)]),
        obs('web_research', [{'source_type': 'web', 'citation': '[5]', 'excerpt': FILLER}]),
        obs('query_stock_prices', [{'source_type': 'price_set', 'citation': f'[{n}]', 'value': 1, 'excerpt': FILLER} for n in range(10, 14)]),
        obs('calculate_formula', [{'source_type': 'calculation', 'citation': '[20]', 'value': '3.2', 'excerpt': FILLER}]),
    ]
    observations += [obs('web_research', [{'source_type': 'web', 'citation': f'[{n}]', 'excerpt': FILLER}]) for n in range(30, 40)]
    turn = turn_with(['CO0'])
    text, digest = turn.evidence_parts(observations)
    assert 'Left out' in text                                                   # precondition: something was left out
    assert digest == '' and 'omitted_digest' not in turn.audit
    monkeypatch.setenv(SWITCH, 'off')
    off = turn_with(['CO0'])
    assert turn.evidence_messages(observations) == off.evidence_messages(observations)


# ---- U6: switch off -----------------------------------------------------------------------------------------------------

def test_u6_switch_off_gives_the_old_single_message_and_no_digest_audit(monkeypatch):
    observations, _ = q3_two_shape()
    monkeypatch.setenv(SWITCH, 'off')
    turn = turn_with(Q3_SYMBOLS)
    messages = turn.evidence_messages(observations)
    assert len(messages) == 1 and 'Left out' in messages[0]['content']          # precondition: something was left out
    assert 'omitted_digest' not in turn.audit and 'omitted_digest_trimmed' not in turn.audit


# ---- U7: the B1 ledger does not change the digest --------------------------------------------------------------------

def test_u7_the_digest_text_is_the_same_with_or_without_the_b1_ledger(monkeypatch):
    observations, _ = q3_two_shape()
    on = turn_with(Q3_SYMBOLS)
    for observation in observations:
        if observation['name'] == 'query_financials':
            on.note_figures(observation['result']['data'])
    _, on_digest = on.evidence_parts(observations)
    monkeypatch.setenv('FINBOT_SW1B_CLOSING_COMPLETE', 'off')
    off = turn_with(Q3_SYMBOLS)
    for observation in observations:
        if observation['name'] == 'query_financials':
            off.note_figures(observation['result']['data'])
    assert off.figure_ledger == []
    _, off_digest = off.evidence_parts(observations)
    assert on_digest and on_digest == off_digest
    by_ordinal = {entry['ordinal']: entry for entry in on.figure_ledger}
    for line in lines_of(on_digest):
        number = ordinal_of_line(line)
        if number is None or '计算结果' in line:
            continue
        entry = by_ordinal[number]
        assert line == f"[{number}] {entry['symbol']} {entry['metric_zh']} {entry['period_label_short']} {entry['value_text']}"


# ---- U8: the audit follows the last build -----------------------------------------------------------------------------

def test_u8_the_audit_is_overwritten_by_each_build_and_cleared_when_there_is_nothing_to_list(monkeypatch):
    turn = turn_with(None)
    # (1) a build that cuts
    big, ordinal = [], 1
    for i in range(5):
        rows, ordinal = company_rows(f'CO{i}', ordinal)
        big.append(obs('query_financials', rows))
    _, digest = turn.evidence_parts(big + recent_filler())
    assert digest and 'omitted_digest_trimmed' in turn.audit and 'omitted_digest' in turn.audit
    # (2) a build with a small omission that fits: the digest stays, the trimmed count goes
    small = [obs('query_financials', [fig('CO9', '[900]'), fig('CO9', '[901]', period_end='2025-12-31', label='FY2025 Q4')])]
    _, digest = turn.evidence_parts(small + recent_filler())
    assert digest and 'omitted_digest_trimmed' not in turn.audit and turn.audit['omitted_digest']['figures'] == 2
    # (3) a build whose omitted numbers all show again in the DATA: no digest, both keys gone
    again = [obs('query_financials', [fig('CO9', '[500]')])]
    shown = [obs('web_research', [{'source_type': 'web', 'citation': '[500]', 'excerpt': 'x'}])] + recent_filler(9)
    text, digest = turn.evidence_parts(again + shown)
    assert 'Left out' in text and digest == ''
    assert 'omitted_digest' not in turn.audit and 'omitted_digest_trimmed' not in turn.audit


# ---- U9: calculate result text and the input clause ------------------------------------------------------------------

@pytest.mark.parametrize('raw,shown', [('77673.00', '77,673.00'), ('77673', '77,673'), ('-1234.5', '-1,234.5'),
                                       ('abc', 'abc'), (None, 'None')])
def test_u9_calc_value_text_keeps_the_stored_decimals_and_adds_separators(raw, shown):
    assert direct.calc_value_text(raw) == shown


def test_u9_the_calc_line_names_the_source_numbers_and_the_user_words_as_the_clause_allows():
    observations = [
        calc_obs(109, [{'name': 'a', 'value': '331839', 'source_ordinal': 68}, {'name': 'b', 'value': '253205', 'source_ordinal': 67}]),
        calc_obs(115, [{'name': 'a', 'value': '12.4', 'source_ordinal': 44}, {'name': 'b', 'value': '7', 'user_stated': True}], value='12.40'),
        calc_obs(116, [{'name': 'a', 'value': '12', 'user_stated': True}], value='12'),
        calc_obs(117, [{'name': 'a', 'value': '1', 'source_ordinal': None}], value='abc'),
    ] + recent_filler()
    turn = turn_with(None)
    _, digest = turn.evidence_parts(observations)
    lines = set(lines_of(digest))
    assert '[109] 计算结果 77,673.00（输入 [68][67]）' in lines
    assert '[115] 计算结果 12.40（输入 [44]、用户原话里的数）' in lines
    assert '[116] 计算结果 12（输入 用户原话里的数）' in lines
    assert '[117] 计算结果 abc' in lines


# ---- R3: the heaviest shape stays under the running-request guard -----------------------------------------------------

def test_r3_the_heaviest_shape_with_the_digest_stays_under_the_running_request_guard():
    from app.agent_tool_catalog import schemas
    from app.agent_workflow.state import AgentRuntimeContext

    async def emit(_):
        pass
    symbols = [f'CO{i}' for i in range(5)]
    observations, ordinal = [], 1
    for symbol in symbols:                                                       # 5 companies x 40 rows, all cut
        rows = []
        for i in range(40):
            rows.append(fig(symbol, f'[{ordinal}]', period_end=f'{2000 + i}-12-31', label=f'FY{2000 + i} Q4'))
            ordinal += 1
        observations.append(obs('query_financials', rows))
    for k in range(30):                                                          # 30 calculations
        observations.append(calc_obs(ordinal, [{'name': 'a', 'value': '1', 'source_ordinal': 1},
                                               {'name': 'b', 'value': '2', 'source_ordinal': 2}], value=f'{k}.00'))
        ordinal += 1
    context = AgentRuntimeContext('custom', 'test', 'dummy', identity_credential='guest')
    turn = Turn('公司营收', context, emit, [], {})
    turn.scope = {'symbols': symbols}
    turn.observations = observations
    protocol = []
    for batch in range(6):                                                       # six batches, each result about 30 KB
        protocol.append({'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': f'call-{batch}', 'type': 'function', 'function': {'name': 'query_financials', 'arguments': '{}'}}]})
        protocol.append({'role': 'tool', 'tool_call_id': f'call-{batch}',
                         'content': json.dumps({'ok': True, 'data': [{'excerpt': FILLER}] * 40}, ensure_ascii=False)})
    turn.protocol = protocol
    messages = turn.tool_messages()
    digests = [m for m in messages if str(m.get('content') or '').startswith(direct.OMITTED_DIGEST_HEAD)]
    assert len(digests) == 1 and len(digests[0]['content']) <= 6000
    tool_schemas = max(turn.exposed_tools(), schemas(owner=True), key=lambda s: len(json.dumps(s)))
    size = len(json.dumps(messages, ensure_ascii=False).encode()) + len(json.dumps(tool_schemas).encode())
    assert size < turn._running_bytes(), (size, turn._running_bytes())
