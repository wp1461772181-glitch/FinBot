"""Turn-local, snapshot-bound citation issuance primitives (experimental protocol v1)."""
from __future__ import annotations

from copy import deepcopy


class CitationIssuer:
    def __init__(self, sources: dict[str, str]):
        self.sources = dict(sources)
        self.blocks: dict[str, int] = {}
        self.nodes: list[dict] = []
        self._next_ordinal = 1

    def register_block(self, block_id: str, revision: int) -> None:
        self.blocks[block_id] = revision
        self.nodes = [n for n in self.nodes if n['anchor']['block_id'] != block_id or n['anchor']['revision'] == revision]

    def issue(self, item: dict) -> dict:
        anchor = item.get('anchor') or {}
        block = anchor.get('block_id')
        if block not in self.blocks or self.blocks[block] != anchor.get('revision'):
            return {'ok': False, 'error': 'anchor_revision_changed', 'current_revision': self.blocks.get(block)}
        ref = item.get('source_ref')
        if ref not in self.sources:
            return {'ok': False, 'error': 'source_not_in_turn', 'available_sources': list(self.sources)}
        source = self.sources[ref]
        quote = item.get('quote')
        if not isinstance(quote, str) or not quote or quote not in source:
            return {'ok': False, 'error': 'quote_not_in_snapshot', 'request': quote, 'window': source[:500]}
        offsets = [i for i in range(len(source)) if source.startswith(quote, i)]
        if len(offsets) != 1:
            return {'ok': False, 'error': 'quote_ambiguous', 'offsets': offsets}
        spans = item.get('context_spans') or []
        if not isinstance(spans, list) or any(not isinstance(s, str) or not s or s not in source for s in spans):
            return {'ok': False, 'error': 'context_not_in_snapshot'}
        candidate = {'anchor': deepcopy(anchor), 'source_ref': ref, 'quote': quote,
                     'quote_offset': offsets[0], 'context_spans': list(spans)}
        existing = next ( (n for n in self.nodes if all(n.get(k) == v for k, v in candidate.items())), None)
        if existing:
            return {'ok': True, 'item': deepcopy(existing)}
        node = {**candidate, 'citation_id': f'citation-{self._next_ordinal}', 'ordinal': self._next_ordinal,
                'quote_verified': True}
        self._next_ordinal += 1
        self.nodes.append(node)
        return {'ok': True, 'item': deepcopy(node)}
