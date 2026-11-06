"""Number review (数字二审, ``num-v1``): the batched judge reads the turn's sources again for the figures the gate
could not source.  Tests use a fake judge and the production gate (``rejected_lines`` / ``entries``) to build the
unverified list, so the shapes are the ones ``finish()`` hands over.  Synchronous tests drive the coroutine with
``asyncio.run``; nothing here needs a database or a model."""
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent_workflow import number_review as nr
from app.agent_workflow.claim_shadow_store import scan_counters
from app.agent_workflow.evidence import HINT_REASONS, answer_verified_figures, rejected_lines
from app.agent_workflow.unverified import entries

FOOTNOTE = '\n\n（另有 %d 处表述未能与来源核对，已保留并标注“证据不足”。）'
HALF_POINT = "Contoso cut its policy rate by half a percentage point."


@pytest.fixture(autouse=True)
def clean_state():
    nr.reset_state()
    yield
    nr.reset_state()


@pytest.fixture
def switched_on(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAIM_NUMBER_REVIEW", "on")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    monkeypatch.delenv("CLAIM_NUMBER_REVIEW_DAILY_CALLS", raising=False)
    return tmp_path


class FakeTrace:
    @asynccontextmanager
    async def step(self, kind, *, enabled=True, step=None):
        yield SimpleNamespace(id=None, ms=None)

    async def end(self, node, **kwargs):
        return None


class FakeTurn:
    def __init__(self, citations, *, owner=True, user_text=""):
        self.citations = citations
        self.owner = owner
        self.state = {"turn_id": "turn-1"}
        self.audit = {}
        self.unverified_lines = []
        self.last_issues = []
        self.stop_partial = False
        self.trace = FakeTrace()
        self._user_text = user_text

    def user_stated_text(self):
        return self._user_text


class FakeJudge:
    """Stands in for the model: records each call, returns ``reply`` (or raises ``error``, or waits ``delay``)."""

    def __init__(self, reply=None, *, error=None, delay=0.0):
        self.reply = reply
        self.error = error
        self.delay = delay
        self.calls = []

    async def __call__(self, model, system, user):
        self.calls.append({"model": model, "system": system, "user": json.loads(user)})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {"usage": {"prompt_tokens": 11}}, {"content": json.dumps(self.reply, ensure_ascii=False)}


async def _resolve(name):
    return {"name": name, "provider": "deepseek", "model": "deepseek-v4-flash", "api_key": "key"}


def _result(answer, citations, *, user_text=""):
    """The result ``finish()`` returns for a checked answer: its unverified lines and the footnote it appends."""
    verified = answer_verified_figures(answer, citations, user_text=user_text)
    rejected = rejected_lines(answer, citations, require_citations=True, check_claims=True,
                              user_text=user_text, verified=verified)
    unverified = entries(rejected, citations, user_text=user_text, verified=verified)
    return {"answer": answer + FOOTNOTE % len(rejected), "status": "partially_succeeded", "reason": rejected[0][1],
            "unverified_lines": unverified, "citations": citations}


def _run(coro):
    return asyncio.run(coro)


def _settle(turn, result, judge, **kwargs):
    return _run(nr.settle(turn, result, call=judge, resolve=_resolve, **kwargs))


def _half_point_case(answer="Contoso 把政策利率下调了 0.5% [1]。"):
    citations = [{"ordinal": 1, "quote": HALF_POINT, "source_type": "web", "title": "Contoso PR"}]
    return citations, answer


def test_switch_off_by_default_never_calls_the_judge(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAIM_NUMBER_REVIEW", raising=False)
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "background")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_DIR", str(tmp_path))
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    before = json.dumps(result, ensure_ascii=False, sort_keys=True)
    judge = FakeJudge({"results": []})
    out = _settle(FakeTurn(citations), result, judge)
    assert judge.calls == []
    assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before


def test_stop_file_disables_the_review(switched_on):
    (switched_on / "STOP").write_text("")
    citations, answer = _half_point_case()
    judge = FakeJudge({"results": []})
    _settle(FakeTurn(citations), _result(answer, citations), judge)
    assert judge.calls == []


def test_found_word_form_takes_the_figure_off_and_turns_the_line_into_a_hint(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    assert result["unverified_lines"][0]["numbers"] == ["0.5%"]
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"}]}]})
    turn = FakeTurn(citations)
    out = _settle(turn, result, judge)
    assert len(judge.calls) == 1
    (item,) = out["unverified_lines"]
    assert item["reason"] == nr.NUMBER_READ and item["numbers"] == []
    assert item["evidence"] == [{"kind": "found", "figure": "0.5%", "ordinal": 1,
                                 "quote": "cut its policy rate by half a percentage point", "read_as": "0.5%"}]
    assert item["ordinal"] == 1
    assert nr.NUMBER_READ in HINT_REASONS
    assert out["status"] == "succeeded" and out["reason"] is None
    assert FOOTNOTE[:10] not in out["answer"] and "另有" not in out["answer"]
    assert turn.last_issues == [] and "unverified_lines" not in turn.audit


def test_derived_figure_with_quoted_operands_is_taken_off_with_its_method(switched_on):
    # The gate's closure does not reach a difference the answer's marker does not cover, so 1.4 is flagged;
    # the operand that holds 40.1 is in a source the sentence does not cite.
    citations = [{"ordinal": 1, "quote": "Northwind close 41.5", "source_type": "web", "title": "Q"},
                 {"ordinal": 2, "quote": "Northwind previous close 40.1", "source_type": "web", "title": "Q"}]
    answer = "Northwind 单日股价上涨 1.4 元 [1]。"
    result = _result(answer, citations)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "1.4", "status": "derived",
         "operands": [{"name":"a", "quote":"Northwind close 41.5", "value":"41.5"},
                      {"name":"b", "quote":"Northwind previous close 40.1", "value":"40.1"}],
         "expression": "a-b", "relations": dict.fromkeys(("subject", "metric", "unit", "period", "denominator"), "yes")}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    (item,) = out["unverified_lines"]
    assert item["reason"] == "number_computed"
    assert item["evidence"] == [{"kind": "derived", "figure": "1.4",
                                 "operands": [{"ordinal": 1, "quote": "Northwind close 41.5"},
                                              {"ordinal": 2, "quote": "Northwind previous close 40.1"}],
                                 "calculation_status": "checked"}]


def test_conflict_keeps_the_line_and_adds_the_conflicting_source_text(switched_on):
    citations = [{"ordinal": 1, "quote": "Northwind revenue grew 6.2% in the quarter.", "source_type": "web",
                  "title": "Q"}]
    answer = "Northwind 营收增长 8.5% [1]。"
    result = _result(answer, citations)
    before = result["unverified_lines"][0]
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "8.5%", "status": "conflict", "quote": "revenue grew 6.2% in the quarter."}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    (item,) = out["unverified_lines"]
    assert item["reason"] == before["reason"] and item["numbers"] == ["8.5%"]
    assert item["evidence"] == [{"kind": "conflict", "figure": "8.5%", "ordinal": 1,
                                 "quote": "revenue grew 6.2% in the quarter."}]
    assert out["status"] == "partially_succeeded"
    assert out["answer"] == result["answer"]


def test_none_leaves_the_entry_and_the_answer_exactly_as_they_were(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    before = json.dumps(result, ensure_ascii=False, sort_keys=True)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [{"figure": "0.5%", "status": "none", "quote": ""}]}]})
    turn = FakeTurn(citations)
    out = _settle(turn, result, judge)
    assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before
    assert turn.unverified_lines == [] and turn.last_issues == []


def test_quote_changed_by_one_word_is_not_verbatim_and_counts_as_none(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    before = json.dumps(result, ensure_ascii=False, sort_keys=True)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a point", "read_as": "0.5%"}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before


def test_read_value_that_is_not_the_same_figure_counts_as_none(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    before = json.dumps(result, ensure_ascii=False, sort_keys=True)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.6%"}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before


def test_judge_timeout_or_error_leaves_every_flag_and_never_raises(switched_on):
    citations, answer = _half_point_case()
    for judge in (FakeJudge({}, error=RuntimeError("boom")), FakeJudge({}, delay=1.0)):
        result = _result(answer, citations)
        before = json.dumps(result, ensure_ascii=False, sort_keys=True)
        turn = FakeTurn(citations)
        out = _settle(turn, result, judge, timeout=0.01)
        assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before
        assert turn.audit["number_review"]["status"] in {"timeout", "provider_error"}
        assert turn.unverified_lines == []


def test_unparsable_reply_leaves_every_flag(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    before = json.dumps(result, ensure_ascii=False, sort_keys=True)

    async def garbage(model, system, user):
        return {}, {"content": "not json at all"}

    out = _run(nr.settle(FakeTurn(citations), result, call=garbage, resolve=_resolve))
    assert json.dumps(out, ensure_ascii=False, sort_keys=True) == before


def test_one_sentence_with_two_figures_is_partly_read(switched_on):
    citations = [{"ordinal": 1, "quote": HALF_POINT, "source_type": "web", "title": "Contoso PR"}]
    answer = "Contoso 营收增长 8.5%，并把政策利率下调 0.5% [1]。"
    result = _result(answer, citations)
    assert {item["reason"] for item in result["unverified_lines"]} == {"unsupported_numeric_claim"}
    assert result["unverified_lines"][0]["numbers"] == ["8.5%", "0.5%"]
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"},
        {"figure": "8.5%", "status": "none", "quote": ""}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    (item,) = out["unverified_lines"]
    assert item["reason"] == "unsupported_numeric_claim"
    assert item["numbers"] == ["8.5%"]
    assert [e["kind"] for e in item["evidence"]] == ["found"]
    assert out["status"] == "partially_succeeded"
    assert "另有 1 处" in out["answer"]


def test_twelve_lines_per_turn_then_the_rest_keep_their_flags_and_the_ledger_says_so(switched_on):
    citations = [{"ordinal": 1, "quote": "Unrelated source text.", "source_type": "web", "title": "Q"}]
    answer = "\n".join(f"公司{i} 营收增长 {i + 10}% [1]。" for i in range(13))
    result = _result(answer, citations)
    assert len(result["unverified_lines"]) == 13
    judge = FakeJudge({"results": []})
    out = _settle(FakeTurn(citations), result, judge)
    assert len(judge.calls) == 1
    assert len(judge.calls[0]["user"]["lines"]) == nr.MAX_ENTRIES
    assert out["unverified_lines"] == result["unverified_lines"]
    rows = _ledger_rows(switched_on)
    entry_rows = [row for row in rows if row["kind"] == "entry"]
    assert len(entry_rows) == 13
    assert [row["kind"] for row in rows if row["kind"] == "call"] == ["call"]
    assert sum(1 for row in entry_rows if row["sent"] is False and row["kept_reason"] == "over_cap") == 1


def test_line_with_no_figure_in_source_text_but_bound_to_the_wrong_source_is_sent(switched_on):
    citations = [{"ordinal": 1, "quote": HALF_POINT, "source_type": "web", "title": "Contoso PR"},
                 {"ordinal": 2, "quote": "Northwind margin was 0.5% in the year.", "source_type": "web", "title": "NW"}]
    answer = "Contoso 把政策利率下调了 0.5% [1]。"
    result = _result(answer, citations)
    (item,) = result["unverified_lines"]
    assert item["numbers"] == []  # the figure is held by source 2: the gate's own list is empty
    assert item["reason"] == "unsupported_numeric_claim"
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "Northwind margin was 0.5% in the year.", "read_as": "0.5%"}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    assert len(judge.calls) == 1
    assert judge.calls[0]["user"]["lines"][0]["numbers"] == ["0.5%"]
    (after,) = out["unverified_lines"]
    assert after["reason"] == nr.NUMBER_READ and after["ordinal"] == 2


def test_non_numeric_reason_keeps_its_flag_even_when_every_figure_is_read(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    (item,) = result["unverified_lines"]
    item["reason"] = "unsupported_claim"
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"}]}]})
    out = _settle(FakeTurn(citations), result, judge)
    (after,) = out["unverified_lines"]
    assert after["reason"] == "unsupported_claim"
    assert after["numbers"] == []
    assert [e["kind"] for e in after["evidence"]] == ["found"]


def test_owner_turn_writes_ledger_channel_numbers_and_the_first_channel_counts_ignore_it(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"}]}]})
    _settle(FakeTurn(citations, owner=True), result, judge)
    rows = _ledger_rows(switched_on)
    assert {row["channel"] for row in rows} == {"numbers"}
    call = next(row for row in rows if row["kind"] == "call")
    assert call["package"]["ordinals"] == [1]
    source = call["package"]["sources"]["1"]
    assert source["text_sent"] and source["sha256"]
    entry = next(row for row in rows if row["kind"] == "entry")
    assert entry["after"] == "hint" and entry["gate_reason"] == "unsupported_numeric_claim"
    assert entry["results"][0]["status"] == "found" and entry["results"][0]["quote_ordinal"] == 1
    assert not {"counted", "sentences", "answer_sha256"} & set(entry)
    first = scan_counters(switched_on)
    assert first.counted_turns == 0 and first.calls_today == 0 and first.seen_answer_hashes == set()


def test_guest_turn_is_reviewed_but_not_written_to_the_ledger(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    judge = FakeJudge({"results": []})
    _settle(FakeTurn(citations, owner=False), result, judge)
    assert len(judge.calls) == 1
    assert not (switched_on / "numbers").exists()


def test_daily_cap_stops_the_call(switched_on, monkeypatch):
    monkeypatch.setenv("CLAIM_NUMBER_REVIEW_DAILY_CALLS", "0")
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    judge = FakeJudge({"results": []})
    turn = FakeTurn(citations)
    _settle(turn, result, judge)
    assert judge.calls == []
    assert turn.audit["number_review"] == {"skipped": "daily_cap", "eligible": 1}


def test_stopped_turn_keeps_its_partial_status_when_the_footnote_goes(switched_on):
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    turn = FakeTurn(citations)
    turn.stop_partial = True
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"}]}]})
    out = _settle(turn, result, judge)
    assert out["unverified_lines"][0]["reason"] == nr.NUMBER_READ
    assert out["status"] == "partially_succeeded"


def test_package_keeps_sixteen_sources_and_names_the_rest():
    citations = [{"ordinal": n, "quote": f"Source {n} says {n}.", "source_type": "web", "title": f"S{n}"}
                 for n in range(1, 21)]
    answer = " ".join(f"句子{n} [{n}]。" for n in range(1, 21))
    sources, metas, dropped, used = nr._package([], citations)
    assert [s.ordinal for s in sources] == list(range(1, 17))
    assert dropped == [17, 18, 19, 20]
    assert set(metas) == {str(n) for n in range(1, 17)}
    assert used == sum(len(s.text) for s in sources) and used <= nr.MAX_PACKAGE_CHARS


def _ledger_rows(shadow_dir: Path):
    ledger = shadow_dir / "numbers"
    rows = []
    for name in sorted(ledger.iterdir()):
        for line in name.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_neighbour_markers_follow_the_same_table_or_paragraph_only():
    lines = ["Intro [9]", "| a | 1 [2] |", "| b | 2 |", "| c | 3 [4] |", "", "Next paragraph [7]"]
    citations = [{"ordinal": n, "quote": "x", "source_type": "web", "title": f"S{n}"} for n in (2, 4, 7, 9)]
    assert nr._neighbour_markers(lines, 2, citations) == [2, 4]
    assert nr._neighbour_markers(lines, 5, citations) == []


def test_report_script_lists_hints_and_samples_kept(switched_on, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "number_review_report", Path(__file__).resolve().parents[1] / "scripts" / "number_review_report.py")
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    citations, answer = _half_point_case()
    result = _result(answer, citations)
    judge = FakeJudge({"results": [{"id": 0, "numbers": [
        {"figure": "0.5%", "status": "found", "quote": "cut its policy rate by half a percentage point",
         "read_as": "0.5%"}]}]})
    _settle(FakeTurn(citations), result, judge)
    assert report.main(["--dir", str(switched_on), "--sample", "5"]) == 0
    out = capsys.readouterr().out
    assert "降为提示（全部 1 条）" in out
    assert "原句：Contoso 把政策利率下调了 0.5% [1]。" in out
    assert "来源 [1] 写作「cut its policy rate by half a percentage point」，读作 0.5%" in out
    assert "保留的抽样（0 / 0 条" in out


def test_derived_requires_relations_and_auditable_arithmetic():
    sources = [nr.JudgeSource(1, 'close 41.5'), nr.JudgeSource(2, 'previous 40.1')]
    raw = {'status': 'derived', 'operands': [{'name': 'a', 'quote': 'close 41.5', 'value': '41.5'},
                                            {'name': 'b', 'quote': 'previous 40.1', 'value': '40.1'}],
           'expression': 'a-b', 'relations': dict.fromkeys(('subject', 'metric', 'unit', 'period', 'denominator'), 'yes')}
    assert nr._verdict('1.4', raw, {1.4}, sources)['status'] == 'derived'
    assert nr._verdict('1.5', raw, {1.5}, sources)['reason'] == 'arithmetic_difference'
    assert nr._verdict('1.4', {**raw, 'relations': {**raw['relations'], 'period': 'uncertain'}}, {1.4}, sources)['status'] == 'none'
    assert nr._verdict('1.4', {**raw, 'expression': 'a/0'}, {1.4}, sources)['status'] == 'none'
