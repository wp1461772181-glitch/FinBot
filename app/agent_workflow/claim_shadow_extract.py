"""Pure functions for LLM claim judge stage 2 (shadow mode): sentence extraction & source adaptation.

Spec: ``.local/design-judge-stage2.md`` §2.
No database, file, environment, or network access.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Sequence

from .claim_judge import (
    MAX_SOURCE_CHARS,
    MAX_SOURCES,
    JudgeSource,
)
from .evidence import (
    _BULLET,
    _NUMERIC_ONLY_SOURCE_TYPES,
    _event_matches,
    _passage_sources,
    _reviewable_lines,
    citation_markers,
    cited_passages,
    is_inference_label,
    reports_absence,
    CLAIM_FEATURES,
)

MAX_SENTENCES = 12

ALLOWED_SOURCE_TYPES = frozenset({
    "official_filing",
    "saved_filing",
    "reported_figure",
    "saved_price",
    "saved_price_set",
    "market_quote",
    "web",
    "web_news",
    "configured_news",
    "research_faq",
    "saved_forecast",
})

KNOWN_SOURCE_TYPES = frozenset({
    *ALLOWED_SOURCE_TYPES,
    "saved_material",
    "calculation",
    "formula_calculation",
    "portfolio",
    "saved_workspace",
    "uploaded_media",
    "ai_analysis",
    "saved_ai_analysis",
    "system_state",
    "unavailable",
})

_SOURCE_LIST_LINE = re.compile(
    r"^(?:(?:[-*+]|\d+[.)])\s*)?(?:\[\d+\]|来源[:：]|参考(?:来源|文献|资料)[:：]|引用(?:来源)?[:：])"
)


@dataclass(frozen=True)
class Candidate:
    idx: int
    text: str
    ordinals: tuple[int, ...]
    tier: int
    original_idx: int = 0


class SelectionResult(tuple):
    """3-tuple (candidates, skipped, unknown_types) with extra stats."""

    def __new__(
        cls,
        candidates: list[Candidate],
        skipped: dict[str, int],
        unknown_types: list[str],
        sentences_over_cap: int = 0,
        sentence_candidates: int = 0,
    ):
        instance = super().__new__(cls, (candidates, skipped, unknown_types))
        instance.candidates = candidates
        instance.skipped = skipped
        instance.unknown_types = unknown_types
        instance.sentences_over_cap = sentences_over_cap
        instance.sentence_candidates = sentence_candidates
        return instance


def _is_heading(stripped: str) -> bool:
    return stripped.startswith("#") or bool(re.fullmatch(r"\*\*[^*]+\*\*\s*", stripped))


def _is_too_short(text: str) -> bool:
    clean = re.sub(r"\[\d+\]", "", text)
    clean_chars = re.sub(r"[\s\W_]+", "", clean)
    return len(clean_chars) < 6


def _is_allowed_source_direct(c: dict) -> bool:
    if c.get("scope") not in (None, "public") or c.get("visibility") not in (None, "public"):
        return False
    fields = c.get("fields")
    if fields is not None and not isinstance(fields, dict):
        return False
    material_type = (fields or {}).get("material_type")
    if material_type in ("portfolio", "saved_workspace", "uploaded_media"):
        return False
    st = c.get("source_type") or ""
    if st in ALLOWED_SOURCE_TYPES:
        return True
    if st == "saved_material":
        fields = c.get("fields")
        if not isinstance(fields, dict):
            return False
        return fields.get("material_type") == "official_filing"
    return False


def is_private_citation(c: dict, all_citations: Sequence[dict]) -> tuple[bool, str | None]:
    """Check if citation is private under §2.3 whitelist rules.

    Returns (is_private, unknown_source_type_name_or_None).
    """
    st = c.get("source_type") or ""
    unknown = st if st and st not in KNOWN_SOURCE_TYPES else None

    if c.get("scope") not in (None, "public") or c.get("visibility") not in (None, "public"):
        return True, unknown

    # An ordinal identifies one source. Ambiguous duplicates must not let a
    # public record mask private or conflicting material with the same marker.
    ordinal = c.get("ordinal")
    if ordinal is not None and any(
        other is not c and str(other.get("ordinal")) == str(ordinal) and other != c
        for other in all_citations if isinstance(other, dict)
    ):
        return True, unknown

    fields = c.get("fields")
    if fields is not None and not isinstance(fields, dict):
        return True, unknown
    material_type = (fields or {}).get("material_type")
    if st != "saved_material" and material_type in ("portfolio", "saved_workspace", "uploaded_media"):
        return True, unknown

    if st in ALLOWED_SOURCE_TYPES:
        return False, unknown

    if st == "saved_material":
        fields = fields or {}
        if fields.get("material_type") == "official_filing":
            return False, unknown
        return True, unknown

    if st in {"calculation", "formula_calculation"}:
        # A calculation can use user-stated inputs even in an otherwise public
        # turn. Require recorded input provenance, not just public neighbours.
        # Formula inputs have a different provenance format and remain local
        # until that format is checked here as well.
        calculation = c.get("calculation")
        if st != "calculation" or not isinstance(calculation, dict):
            return True, unknown
        inputs = calculation.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            return True, unknown
        for item in inputs:
            if not isinstance(item, dict) or item.get("user_stated") or item.get("origin") == "user_stated":
                return True, unknown
            ordinal = item.get("source_ordinal")
            matches = [other for other in all_citations if isinstance(other, dict)
                       and str(other.get("ordinal")) == str(ordinal)] if ordinal is not None else []
            if (len(matches) != 1 or not _is_allowed_source_direct(matches[0])
                    or is_private_citation(matches[0], all_citations)[0]):
                return True, unknown
        # Also reject mixed turns and chains whose full provenance is unknown.
        for other in all_citations:
            if other is not c and not _is_allowed_source_direct(other):
                return True, unknown
        return False, unknown

    # All others (portfolio, saved_workspace, uploaded_media, ai_analysis, unknown, etc.) are private
    return True, unknown


def classify_tier(passage: str, sources: Sequence[dict]) -> int:
    """Classify sentence tier according to §2.5:

    Tier 1: 事件句 (hits CLAIM_FEATURES via _event_matches)
    Tier 2: 定性句 (no numbers other than calendar years)
    Tier 3: 含数字句 (other sentences with numbers)
    Tier 4: 纯数字来源 (cited sources all in _NUMERIC_ONLY_SOURCE_TYPES and not Tier 1)
    """
    if any(_event_matches(passage, terms)[1] for terms in CLAIM_FEATURES):
        return 1

    if sources and all(s.get("source_type") in _NUMERIC_ONLY_SOURCE_TYPES for s in sources):
        return 4

    clean = re.sub(r"\[\d+\]", "", passage)
    clean_no_years = re.sub(r"\b(?:19|20)\d{2}(?:年)?\b|\b\d{4}年\b", "", clean)
    if not re.search(r"\d", clean_no_years):
        return 2

    return 3


def select_sentences(
    answer: str,
    citations: Sequence[dict],
    max_sentences: int = MAX_SENTENCES,
) -> SelectionResult:
    """Select sentences to judge from answer and citations, applying §2 skip rules and §2.5 tiers."""
    skipped: dict[str, int] = {
        "table_row": 0,
        "source_list": 0,
        "heading": 0,
        "inference": 0,
        "absence": 0,
        "too_short": 0,
        "duplicate": 0,
        "unavailable_source": 0,
        "private_source": 0,
    }
    unknown_types: list[str] = []
    candidates: list[Candidate] = []
    seen_passages: set[str] = set()
    indexed = {str(c["ordinal"]): c for c in citations if isinstance(c, dict) and "ordinal" in c}

    for _line, stripped, checked in _reviewable_lines(answer, citations):
        if checked is None:
            continue

        if stripped.startswith("|"):
            if citation_markers(stripped, citations):
                skipped["table_row"] += 1
            continue

        if _SOURCE_LIST_LINE.match(stripped):
            if citation_markers(stripped, citations):
                skipped["source_list"] += 1
            continue

        if _is_heading(stripped):
            if citation_markers(stripped, citations):
                skipped["heading"] += 1
            continue

        bullet = _BULLET.match(stripped)
        line_body = checked[bullet.end():] if bullet else checked

        for passage in cited_passages(line_body):
            p = passage.strip()
            if not p:
                continue

            markers = citation_markers(p, citations)
            if not markers:
                continue

            if is_inference_label(p):
                skipped["inference"] += 1
                continue

            if reports_absence(p):
                skipped["absence"] += 1
                continue

            if _is_too_short(p):
                skipped["too_short"] += 1
                continue

            squashed = re.sub(r"\s+", " ", p).strip()
            if squashed in seen_passages:
                skipped["duplicate"] += 1
                continue
            seen_passages.add(squashed)

            p_sources = _passage_sources(p, citations, indexed)
            raw_cited = [indexed[m] for m in markers if m in indexed]
            if not p_sources:
                if raw_cited and all(s.get("source_type") == "unavailable" for s in raw_cited):
                    skipped["unavailable_source"] += 1
                continue

            if all(s.get("source_type") == "unavailable" for s in p_sources):
                skipped["unavailable_source"] += 1
                continue

            has_private = False
            for s in p_sources:
                is_priv, unk = is_private_citation(s, citations)
                if unk and unk not in unknown_types:
                    unknown_types.append(unk)
                if is_priv:
                    has_private = True

            if has_private:
                skipped["private_source"] += 1
                continue

            ordinals_list: list[int] = []
            for m in markers:
                try:
                    val = int(m)
                    if str(val) in indexed and val not in ordinals_list:
                        ordinals_list.append(val)
                except (ValueError, TypeError):
                    continue

            ordinals = tuple(ordinals_list[:MAX_SOURCES])
            tier = classify_tier(p, p_sources)
            candidates.append(Candidate(
                idx=len(candidates),
                text=p,
                ordinals=ordinals,
                tier=tier,
                original_idx=len(candidates),
            ))

    total_candidates = len(candidates)
    sorted_candidates = sorted(candidates, key=lambda c: (c.tier, c.original_idx))
    selected = sorted_candidates[:max_sentences]
    over_cap = max(0, total_candidates - max_sentences)

    final_candidates = [
        Candidate(
            idx=i,
            text=c.text,
            ordinals=c.ordinals,
            tier=c.tier,
            original_idx=c.original_idx,
        )
        for i, c in enumerate(selected)
    ]

    return SelectionResult(
        candidates=final_candidates,
        skipped=skipped,
        unknown_types=unknown_types,
        sentences_over_cap=over_cap,
        sentence_candidates=total_candidates,
    )


def to_judge_source(citation: dict) -> tuple[JudgeSource, dict]:
    """Adapt a single citation dictionary into (JudgeSource, storage_metadata_dict) per §2.4."""
    fields = citation.get("fields")
    field_lines: list[str] = []
    if isinstance(fields, dict) and fields:
        for k, v in fields.items():
            if v is not None:
                field_lines.append(f"{k}={v}")
    else:
        for key in ("title", "symbol", "trading_date", "published_at", "filed_at"):
            val = citation.get(key)
            if val is not None and str(val).strip():
                field_lines.append(f"{key}={val}")

    field_text = "\n".join(field_lines)[:600] if field_lines else ""
    quote = str(citation.get("quote") or "").strip()

    figures = str(citation.get("figures") or "").strip()
    figures_text = figures if figures and (figures not in quote) else ""

    evidence_quotes = citation.get("evidence_quotes") or []
    seen_quotes: set[str] = {s for s in (field_text, quote, figures_text) if s}
    extra_quotes: list[str] = []
    for eq in evidence_quotes:
        if isinstance(eq, str) and eq.strip() and eq.strip() not in seen_quotes:
            extra_quotes.append(eq.strip())
            seen_quotes.add(eq.strip())

    check_text = str(citation.get("check_text") or "").strip()
    check_remainder = ""
    if check_text:
        q_stripped = quote.strip("… \t\r\n")
        if q_stripped and check_text.startswith(q_stripped):
            check_remainder = check_text[len(q_stripped):].lstrip()
        else:
            check_remainder = check_text

    segments = [s for s in (field_text, quote, figures_text, *extra_quotes, check_remainder) if s]
    assembled_text = "\n".join(segments)

    chars_total = len(assembled_text)
    sha256 = hashlib.sha256(assembled_text.encode("utf-8")).hexdigest()
    truncated = chars_total > MAX_SOURCE_CHARS
    text_sent = assembled_text[:MAX_SOURCE_CHARS]

    complete = bool(citation.get("saved_text") == "full_document" and not truncated)

    ordinal = int(citation.get("ordinal", 0))
    source_type = citation.get("source_type")

    source = JudgeSource(
        ordinal=ordinal,
        text=text_sent,
        source_type=source_type,
        complete=complete,
    )

    meta = {
        "source_type": source_type,
        "saved_text": citation.get("saved_text"),
        "title": citation.get("title"),
        "source_url": citation.get("source_url") or citation.get("url"),
        "published_at": citation.get("published_at") or citation.get("filed_at") or citation.get("trading_date"),
        "chars_total": chars_total,
        "sha256": sha256,
        "text_sent": text_sent,
        "complete_sent": complete,
        "truncated": truncated,
    }

    return source, meta


def to_judge_sources(
    ordinals: Sequence[int],
    citations: Sequence[dict],
) -> tuple[list[JudgeSource], dict[str, dict]]:
    """Convert cited ordinals into (list[JudgeSource], sources_metadata_dict) per §2.4."""
    indexed = {int(c["ordinal"]): c for c in citations if isinstance(c, dict) and "ordinal" in c}
    sources: list[JudgeSource] = []
    meta_dict: dict[str, dict] = {}

    for ord_val in ordinals[:MAX_SOURCES]:
        c = indexed.get(ord_val)
        if c and not is_private_citation(c, citations)[0]:
            src, meta = to_judge_source(c)
            sources.append(src)
            meta_dict[str(ord_val)] = meta

    return sources, meta_dict
