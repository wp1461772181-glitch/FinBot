#!/usr/bin/env python3
"""Reconstruct an approximate calculation regression pack from stored messages.

Output contains private conversation text. Keep it outside every git worktree.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from uuid import UUID

from sqlalchemy import create_engine, text

ERROR = 'calculation_input_unbound'
LABELS = ('in_earlier_tool_text', 'glued_suffix', 'float_tail',
          'in_bindable_of_other_ordinal', 'absent')


def _json(value, default):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _forms(value):
    raw = str(value)
    plain = raw.replace(',', '')
    forms = {raw, plain}
    match = re.fullmatch(r'(-?)(\d+)(\.\d+)?', plain)
    if match:
        sign, integer, fraction = match.groups()
        forms.add(sign + format(int(integer), ',') + (fraction or ''))
    return forms


def _candidates(item, earlier, bindable):
    value = str(item.get('value', ''))
    forms = _forms(value) if value else set()
    where, suffixes = [], set()
    for row in earlier:
        content = row['content'] or ''
        if any(form in content for form in forms):
            where.append(row['sequence'])
        for form in forms:
            suffixes.update(re.findall(re.escape(form) + r'([A-Za-z]+)', content))
    labels = []
    if where:
        labels.append('in_earlier_tool_text')
    if suffixes:
        labels.append('glued_suffix')
    if re.search(r'\.\d{8,}', value):
        labels.append('float_tail')
    if isinstance(bindable, dict) and any(
        str(ordinal) != str(item.get('source_ordinal')) and isinstance(values, list)
        and any(str(v).replace(',', '') == value.replace(',', '') for v in values)
        for ordinal, values in bindable.items()
    ):
        labels.append('in_bindable_of_other_ordinal')
    if not labels:
        labels.append('absent')
    details = {}
    if where:
        details['where'] = where
    if suffixes:
        details['suffixes'] = sorted(suffixes)
    return labels, details


def _pack(rows):
    calls = {}
    for row in rows:
        protocol = _json(row['tool_calls'], {})
        if row['role'] == 'assistant' and isinstance(protocol, dict):
            for call in protocol.get('calls', []):
                if isinstance(call, dict) and isinstance(call.get('function'), dict):
                    calls[call.get('id')] = call['function']
    tool_rows, calculate_calls, failed_inputs = [], [], []
    notes = [
        'The turn citation table cannot be reconstructed from stored messages.',
        'Stored tool rows differ from model-visible messages: failure rows can include bindable_values; successful results use different bounding.',
    ]
    for row in rows:
        if row['role'] != 'tool':
            continue
        function = calls.get(row['tool_call_id'], {})
        name = function.get('name')
        result = _json(row['content'], {})
        if not isinstance(result, dict):
            result = {}
        if result.get('truncated') is True:
            notes.append(f"Tool row {row['sequence']} was truncated (truncated=true).")
        if name == 'calculate':
            args = _json(function.get('arguments'), {})
            if not isinstance(args, dict):
                args = {}
            calculate_calls.append({'sequence': row['sequence'], 'arguments': args,
                                    'ok': result.get('ok'), 'error_code': result.get('error_code'),
                                    'bindable_values': result.get('bindable_values')})
            if result.get('error_code') == ERROR:
                for item in args.get('inputs', []):
                    if not isinstance(item, dict) or item.get('user_stated'):
                        continue
                    labels, details = _candidates(item, tool_rows, result.get('bindable_values'))
                    entry = {'call_sequence': row['sequence'], 'name': item.get('name'),
                             'value': item.get('value'), 'source_ordinal': item.get('source_ordinal'),
                             'candidates': labels}
                    entry.update(details)
                    failed_inputs.append(entry)
        tool_rows.append({'sequence': row['sequence'], 'tool_call_id': row['tool_call_id'],
                          'name': name, 'content': row['content']})
    user = next((r for r in rows if r['role'] == 'user'), rows[0])
    return {'turn_id': str(rows[0]['turn_id']), 'conversation_id': str(rows[0]['conversation_id']),
            'created_at': user['created_at'].isoformat() if user['created_at'] else None,
            'user_message': user['content'] if user['role'] == 'user' else None,
            'tool_rows': tool_rows, 'calculate_calls': calculate_calls, 'failed_inputs': failed_inputs,
            'reconstruction': {'source': 'agent_messages', 'model_view': 'approximate', 'notes': notes}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--turn', action='append', default=[])
    args = parser.parse_args(argv)
    out = Path(args.out).resolve()
    if any((parent / '.git').exists() for parent in (out, *out.parents)):
        parser.error('output directory must be outside a git repository')
    try:
        turns = [str(UUID(turn)) for turn in args.turn]
    except ValueError:
        parser.error('--turn must be a UUID')
    engine = create_engine(args.database_url)
    try:
        with engine.connect() as conn:
            if not turns:
                turns = [str(row[0]) for row in conn.execute(text(
                    "SELECT DISTINCT turn_id FROM agent_messages WHERE role = 'tool' AND content LIKE :pattern"),
                    {'pattern': '%"error_code":"calculation_input_unbound"%'})]
            packs = []
            for turn in turns:
                rows = conn.execute(text('SELECT conversation_id, turn_id, sequence, role, content, tool_calls, tool_call_id, status, created_at FROM agent_messages WHERE turn_id = :turn ORDER BY sequence'), {'turn': UUID(turn)}).mappings().all()
                if rows:
                    packs.append(_pack(rows))
    finally:
        engine.dispose()
    out.mkdir(parents=True, exist_ok=True)
    counts = Counter(label for pack in packs for item in pack['failed_inputs'] for label in item['candidates'])
    summary = {'turn_count': len(packs), 'failed_call_count': sum(c['error_code'] == ERROR for p in packs for c in p['calculate_calls']),
               'failed_input_count': sum(len(p['failed_inputs']) for p in packs),
               'candidate_counts': {label: counts[label] for label in LABELS},
               'missing_requested_turns': [t for t in turns if t not in {p['turn_id'] for p in packs}]}
    for pack in packs:
        (out / (pack['turn_id'] + '.json')).write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with (out / 'classification.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['turn_id', 'call_sequence', 'name', 'value', 'source_ordinal', 'candidates', '人工归类', '备注'])
        for pack in packs:
            for item in pack['failed_inputs']:
                writer.writerow([pack['turn_id'], item['call_sequence'], item['name'], item['value'], item['source_ordinal'], ';'.join(item['candidates']), '', ''])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
