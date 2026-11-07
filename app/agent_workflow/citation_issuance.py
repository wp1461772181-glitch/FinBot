"""Turn-local, snapshot-bound citation issuance (protocol v2, behind ``FLEX_CITATION_PROTOCOL``).

``CitationIssuer`` is the primitive: it only accepts a source of this turn's evidence pool, a quote that is
verbatim in that source's snapshot, and an anchor on the current revision of the answer block.  It answers
every refusal with a receipt the model can act on.  Protocol v2 is off by default; v1 (hand-written ``[n]``
markers) is untouched.
"""
from __future__ import annotations

import os
from copy import deepcopy

PROTOCOL_V1 = 'v1'
PROTOCOL_V2 = 'v2'
ANSWER_BLOCK = 'answer'
ANSWER_REVISION = 1
PREVIEW_CHARS = 160
WINDOW_CHARS = 500

ISSUE_CITATION_SCHEMA = {
    'type': 'function',
    'function': {
        'name': 'issue_citation',
        'description': (
            'Attach a citation to the answer you are writing. Give the source_ref of a source in this turn\'s evidence '
            'and a quote copied verbatim from that source. Optional context_spans are verbatim unit or column-header '
            'text from the same source. Write the answer without [n] markers: the citation is shown only when this '
            'tool accepts it. A rejected call tells you what was wrong and which sources and text are available; '
            'fix the call and try again.'),
        'parameters': {
            'type': 'object',
            'properties': {
                'source_ref': {'type': 'string', 'description': 'Ordinal of a source in this turn\'s evidence.'},
                'quote': {'type': 'string', 'description': 'Verbatim text from that source.'},
                'context_spans': {'type': 'array', 'items': {'type': 'string'},
                                  'description': 'Verbatim unit or header text from the same source.'},
            },
            'required': ['source_ref', 'quote'],
        },
    },
}


def citation_protocol() -> str:
    """v2 only when the switch says so; anything else (unset, 'off', typo) is v1."""
    return PROTOCOL_V2 if os.environ.get('FLEX_CITATION_PROTOCOL', 'off').strip().lower() == 'on' else PROTOCOL_V1


class CitationIssuer:
    def __init__(self, sources: dict[str, str]):
        self.sources = dict(sources)
        self.blocks: dict[str, int] = {}
        self.nodes: list[dict] = []
        self._next_ordinal = 1

    def register_block(self, block_id: str, revision: int) -> None:
        self.blocks[block_id] = revision
        self.nodes = [n for n in self.nodes if n['anchor']['block_id'] != block_id or n['anchor']['revision'] == revision]

    def refresh(self, sources: dict[str, str]) -> None:
        """Replace the evidence pool with this turn's current snapshots.  Issued nodes survive; a source that
        disappeared from the pool takes its nodes with it."""
        self.sources = dict(sources)
        self.nodes = [n for n in self.nodes if n['source_ref'] in self.sources]

    def _bindable(self) -> list[dict]:
        return [{'source_ref': ref, 'preview': text[:PREVIEW_CHARS]} for ref, text in self.sources.items()]

    def issue(self, item: dict) -> dict:
        anchor = item.get('anchor') or {}
        block = anchor.get('block_id')
        if block not in self.blocks or self.blocks[block] != anchor.get('revision'):
            return {'ok': False, 'error': 'anchor_revision_changed', 'current_revision': self.blocks.get(block)}
        ref = item.get('source_ref')
        if ref not in self.sources:
            return {'ok': False, 'error': 'source_not_in_turn', 'available_sources': self._bindable()}
        source = self.sources[ref]
        quote = item.get('quote')
        if not isinstance(quote, str) or not quote or quote not in source:
            return {'ok': False, 'error': 'quote_not_in_snapshot', 'request': quote, 'source_ref': ref,
                    'window': source[:WINDOW_CHARS]}
        offsets = [i for i in range(len(source)) if source.startswith(quote, i)]
        if len(offsets) != 1:
            # Each hit in its own window, so the model can copy a longer span that names only one of them.
            hits = [{'offset': i, 'window': source[max(0, i - 40):i + len(quote) + 40]} for i in offsets[:8]]
            return {'ok': False, 'error': 'quote_ambiguous', 'source_ref': ref, 'hits': hits}
        spans = item.get('context_spans') or []
        if not isinstance(spans, list) or any(not isinstance(s, str) or not s or s not in source for s in spans):
            return {'ok': False, 'error': 'context_not_in_snapshot', 'source_ref': ref, 'window': source[:WINDOW_CHARS]}
        candidate = {'anchor': deepcopy(anchor), 'source_ref': ref, 'quote': quote,
                     'quote_offset': offsets[0], 'context_spans': list(spans)}
        existing = next((n for n in self.nodes if all(n.get(k) == v for k, v in candidate.items())), None)
        if existing:
            return {'ok': True, 'item': deepcopy(existing)}
        node = {**candidate, 'citation_id': f'citation-{self._next_ordinal}', 'ordinal': self._next_ordinal,
                'quote_verified': True}
        self._next_ordinal += 1
        self.nodes.append(node)
        return {'ok': True, 'item': deepcopy(node)}


def new_turn_issuer(sources: dict[str, str]) -> CitationIssuer:
    """The issuer a v2 turn uses: one answer block at its first revision."""
    issuer = CitationIssuer(sources)
    issuer.register_block(ANSWER_BLOCK, ANSWER_REVISION)
    return issuer


def issue_for_turn(issuer: CitationIssuer, args) -> dict:
    """Tool entry: the model supplies source, quote and spans; the server supplies the anchor."""
    if not isinstance(args, dict):
        return {'ok': False, 'error': 'invalid_arguments'}
    item = {'anchor': {'block_id': ANSWER_BLOCK, 'revision': ANSWER_REVISION},
            'source_ref': str(args.get('source_ref') or ''), 'quote': args.get('quote'),
            'context_spans': args.get('context_spans') or []}
    return issuer.issue(item)
