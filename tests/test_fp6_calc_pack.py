import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.agent_chat_models import AgentConversation, AgentMessage
from app.database import engine
from scripts.calc_regression_pack import main


def test_pack_from_synthetic_turns(tmp_path, disposable_database):
    AgentConversation.__table__.create(engine, checkfirst=True)
    AgentMessage.__table__.create(engine, checkfirst=True)
    cid, selected, other = uuid4(), uuid4(), uuid4()
    inputs = [
        {'name': 'a', 'value': '1234', 'source_ordinal': 1},
        {'name': 'b', 'value': '35', 'source_ordinal': 1},
        {'name': 'c', 'value': '1.12345678', 'source_ordinal': 1},
        {'name': 'd', 'value': '77', 'source_ordinal': 1},
        {'name': 'e', 'value': '88', 'source_ordinal': 1},
        {'name': 'f', 'value': '99', 'user_stated': True},
    ]
    protocol = {'calls': [{'id': 'read', 'function': {'name': 'lookup', 'arguments': '{}'}},
                          {'id': 'calc', 'function': {'name': 'calculate', 'arguments': json.dumps({'expression': 'a+b', 'inputs': inputs})}}]}
    failure = {'ok': False, 'error_code': 'calculation_input_unbound', 'bindable_values': {'2': ['77']}}
    def row(turn, seq, role, content='', **kwargs):
        return AgentMessage(conversation_id=cid, turn_id=turn, sequence=seq, role=role, content=content, **kwargs)
    with Session(engine) as session:
        session.add(AgentConversation(id=cid, owner_hash='synthetic'))
        session.add_all([row(selected, 1, 'user', 'Synthetic question'),
                         row(selected, 2, 'assistant', tool_calls=protocol),
                         row(selected, 3, 'tool', 'Synthetic: 1,234 and 35bps', tool_call_id='read'),
                         row(selected, 4, 'tool', json.dumps(failure, separators=(',', ':')), tool_call_id='calc'),
                         row(other, 5, 'user', 'Another synthetic question'),
                         row(other, 6, 'tool', '{"ok":true}', tool_call_id='unknown')])
        session.commit()
    try:
        url = engine.url.render_as_string(hide_password=False)
        assert main(['--database-url', url, '--out', str(tmp_path / 'pack')]) == 0
        pack = json.loads((tmp_path / 'pack' / f'{selected}.json').read_text())
        assert not (tmp_path / 'pack' / f'{other}.json').exists()
        assert pack['reconstruction']['model_view'] == 'approximate'
        assert pack['tool_rows'][0]['name'] == 'lookup'
        assert pack['calculate_calls'][0]['arguments']['inputs'] == inputs
        items = {item['name']: item for item in pack['failed_inputs']}
        assert set(items) == set('abcde')
        assert items['a']['candidates'] == ['in_earlier_tool_text']
        assert items['a']['where'] == [3]
        assert items['b']['candidates'] == ['in_earlier_tool_text', 'glued_suffix']
        assert items['b']['suffixes'] == ['bps']
        assert items['c']['candidates'] == ['float_tail']
        assert items['d']['candidates'] == ['in_bindable_of_other_ordinal']
        assert items['e']['candidates'] == ['absent']
        summary = json.loads((tmp_path / 'pack' / 'summary.json').read_text())
        assert (summary['turn_count'], summary['failed_call_count'], summary['failed_input_count']) == (1, 1, 5)
        with (tmp_path / 'pack' / 'classification.csv').open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5 and all(not row['人工归类'] and not row['备注'] for row in rows)
        assert main(['--database-url', url, '--out', str(tmp_path / 'extra'), '--turn', str(other)]) == 0
        extra = json.loads((tmp_path / 'extra' / f'{other}.json').read_text())
        assert extra['tool_rows'][0]['name'] is None
        assert extra['reconstruction']['model_view'] == 'approximate'
    finally:
        with Session(engine) as session:
            session.execute(delete(AgentMessage).where(AgentMessage.conversation_id == cid))
            session.execute(delete(AgentConversation).where(AgentConversation.id == cid))
            session.commit()


def test_repo_output_rejected():
    out = Path(__file__).resolve().parent / 'fp6_must_not_exist'
    with pytest.raises(SystemExit) as exc:
        main(['--database-url', 'unused', '--out', str(out)])
    assert exc.value.code != 0
    assert not out.exists()


def test_synthetic_negatives():
    path = Path(__file__).parent / 'fixtures' / 'calc_pack' / 'negatives.json'
    entries = json.loads(path.read_text())
    assert len(entries) == 14
    assert all(entry['text'] and entry['must_not_bind'] and isinstance(entry['may_bind'], list) for entry in entries)
