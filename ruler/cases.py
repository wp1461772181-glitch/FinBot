"""Question bank schema for ruler: parse and validate a JSON suite file."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

KINDS = ("fact", "brief", "compare", "followup", "recall", "general", "understand")
_RUBRIC_MAX_LENGTH = 600

_ID_PATTERN = re.compile(r"[A-Z]{1,3}[0-9]{2,3}")
_TEXT_MAX_LENGTH = 4000
_SUITE_VERSION = 1
_DEFAULT_STATUS = "succeeded"
_CASE_FIELDS = frozenset({"id", "kind", "title", "turns"})
_TURN_FIELDS = frozenset({"text", "checks", "rubric"})
_CHECK_FIELDS = frozenset({"status", "include_any", "exclude"})


@dataclass(frozen=True)
class Checks:
    status: str = _DEFAULT_STATUS
    include_any: tuple[tuple[str, ...], ...] = ()  # every group needs at least one alternative present
    exclude: tuple[str, ...] = ()  # none of these may appear


@dataclass(frozen=True)
class Turn:
    text: str
    checks: Checks
    rubric: str = ""      # what a good reply does here, for ``ruler.judge`` (the 懂你 cases); empty: the turn is not judged


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    title: str
    turns: tuple[Turn, ...]


class SuiteError(ValueError):
    """The question bank cannot be read, or it breaks the schema."""


def load_suite(path) -> list[Case]:
    path = Path(path)
    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SuiteError(f"无法读取题库 {path}: {exc}") from exc
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise SuiteError(f"题库 {path} 不是合法 JSON: {exc}") from exc

    if not isinstance(document, dict):
        raise SuiteError("题库顶层必须是对象")
    version = document.get("version")
    if version != _SUITE_VERSION or isinstance(version, bool):
        raise SuiteError(f"不支持的题库版本 {version!r}，只认 {_SUITE_VERSION}")
    raw_cases = document.get("cases")
    if not isinstance(raw_cases, list):
        raise SuiteError("题库的 cases 必须是列表")

    cases = [_parse_case(raw, index) for index, raw in enumerate(raw_cases)]
    seen_ids: set[str] = set()
    for case in cases:
        if case.id in seen_ids:
            raise SuiteError(f"题号 {case.id} 重复")
        seen_ids.add(case.id)
    return cases


def _parse_case(raw, index: int) -> Case:
    if not isinstance(raw, dict):
        raise SuiteError(f"第 {index + 1} 题必须是对象")
    case_id = raw.get("id")
    label = f"题目 {case_id}" if isinstance(case_id, str) else f"第 {index + 1} 题"
    _reject_unknown_fields(raw, _CASE_FIELDS, label)

    if not isinstance(case_id, str) or not _ID_PATTERN.fullmatch(case_id):
        raise SuiteError(f"{label}: id 必须是 1 到 3 个大写字母加 2 到 3 位数字，例如 F01、B007")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise SuiteError(f"{label}: kind 必须是 {'/'.join(KINDS)} 之一，拿到 {kind!r}")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise SuiteError(f"{label}: title 必须是非空字符串")
    raw_turns = raw.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise SuiteError(f"{label}: turns 必须是至少含一轮的列表")

    turns = tuple(
        _parse_turn(raw_turn, f"{label} 第 {number} 轮")
        for number, raw_turn in enumerate(raw_turns, start=1)
    )
    return Case(case_id, kind, title, turns)


def _parse_turn(raw, where: str) -> Turn:
    if not isinstance(raw, dict):
        raise SuiteError(f"{where}: 必须是对象")
    _reject_unknown_fields(raw, _TURN_FIELDS, where)
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > _TEXT_MAX_LENGTH:
        raise SuiteError(f"{where}: text 必须是 1 到 {_TEXT_MAX_LENGTH} 字符的非空字符串")
    rubric = raw.get("rubric", "")
    if not isinstance(rubric, str) or len(rubric) > _RUBRIC_MAX_LENGTH:
        raise SuiteError(f"{where}: rubric 必须是不超过 {_RUBRIC_MAX_LENGTH} 字符的字符串")
    return Turn(text, _parse_checks(raw.get("checks", {}), where), rubric.strip())


def _parse_checks(raw, where: str) -> Checks:
    if not isinstance(raw, dict):
        raise SuiteError(f"{where}: checks 必须是对象")
    _reject_unknown_fields(raw, _CHECK_FIELDS, f"{where} checks")

    status = raw.get("status", _DEFAULT_STATUS)
    if not isinstance(status, str) or not status.strip():
        raise SuiteError(f"{where}: status 必须是非空字符串")

    raw_groups = raw.get("include_any", [])
    if not isinstance(raw_groups, list):
        raise SuiteError(f"{where}: include_any 必须是列表")
    groups = []
    for group_index, group in enumerate(raw_groups):
        if not isinstance(group, list) or not group:
            raise SuiteError(f"{where}: include_any[{group_index}] 必须是至少含一个检查词的列表")
        groups.append(
            tuple(
                _parse_needle(needle, f"{where}: include_any[{group_index}][{needle_index}]")
                for needle_index, needle in enumerate(group)
            )
        )

    raw_exclude = raw.get("exclude", [])
    if not isinstance(raw_exclude, list):
        raise SuiteError(f"{where}: exclude 必须是列表")
    exclude = tuple(
        _parse_needle(needle, f"{where}: exclude[{needle_index}]")
        for needle_index, needle in enumerate(raw_exclude)
    )
    return Checks(status, tuple(groups), exclude)


def _parse_needle(needle, where: str) -> str:
    # An empty needle matches every answer, which would silently pass or fail a check.
    if not isinstance(needle, str) or not needle.strip():
        raise SuiteError(f"{where} 必须是非空字符串")
    return needle


def _reject_unknown_fields(raw: dict, allowed: frozenset, where: str) -> None:
    unknown = sorted(key for key in raw if key not in allowed)
    if unknown:
        raise SuiteError(f"{where}: 未知字段 {', '.join(unknown)}")
