import json
from ruler.cases import Case, Checks, Turn
from ruler.client import TurnOutcome
from ruler import run as ruler_run

def outcome(answer="营收 1158.44 亿", status="succeeded", cid="c1", tools=()):
    return TurnOutcome(status, None, answer, cid, "t1", 100, 400, 1000, list(tools), 50, None)

def case(cid="F01", kind="fact", turns=1, needle="1158.44"):
    return Case(cid, kind, "t", tuple(Turn(f"问{i}", Checks(include_any=((needle,),))) for i in range(turns)))

def test_single_turn_passes_and_carries_audit():
    asked = []
    def ask(text, *, catalog_model, conversation_id):
        asked.append((text, catalog_model, conversation_id)); return outcome(tools=["calculate"])
    [res] = ruler_run.run_case(case(), ask=ask, catalog_model="m",
                               audit=lambda cid: {"model_calls": 3, "token_usage": 7000, "decision_steps": 2, "stop_reason": "answered"})
    assert asked == [("问0", "m", None)]
    assert res.passed and res.failed_checks == [] and res.tools == ["calculate"]
    assert (res.model_calls, res.token_usage, res.decision_steps, res.stop_reason) == (3, 7000, 2, "answered")
    assert (res.case_id, res.kind, res.turn_index, res.answer_chars) == ("F01", "fact", 0, len("营收 1158.44 亿"))

def test_later_turns_reuse_the_conversation():
    seen = []
    def ask(text, *, catalog_model, conversation_id):
        seen.append(conversation_id); return outcome(cid="conv-9")
    results = ruler_run.run_case(case(turns=3), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert seen == [None, "conv-9", "conv-9"] and [r.turn_index for r in results] == [0, 1, 2]

def test_failed_turn_skips_the_rest_of_the_case():
    calls = []
    def ask(text, *, catalog_model, conversation_id):
        calls.append(text); return outcome(status="incomplete", answer="")
    results = ruler_run.run_case(case(turns=3), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert calls == ["问0"]
    assert [r.status for r in results] == ["incomplete", "skipped", "skipped"]
    assert not any(r.passed for r in results) and results[0].failed_checks[0] == "status"

def test_waiting_for_input_does_not_stop_the_case():
    statuses = iter(["waiting_for_input", "succeeded"])
    c = Case("R01", "recall", "t", (Turn("记一下", Checks(status="any")), Turn("问", Checks(include_any=(("1158.44",),)))))
    results = ruler_run.run_case(c, audit=lambda cid: {}, catalog_model="", ask=lambda text, **kw: outcome(status=next(statuses)))
    assert [r.status for r in results] == ["waiting_for_input", "succeeded"] and [r.passed for r in results] == [True, True]

def test_wrong_answer_fails_but_next_turn_still_runs():
    answers = iter(["没提到", "营收 1158.44"])
    results = ruler_run.run_case(case(turns=2), audit=lambda cid: {}, catalog_model="",
                                 ask=lambda text, **kw: outcome(answer=next(answers)))
    assert [r.passed for r in results] == [False, True]

def test_audit_failure_leaves_fields_empty():
    def boom(cid): raise RuntimeError("db down")
    [res] = ruler_run.run_case(case(), ask=lambda text, **kw: outcome(), audit=boom, catalog_model="")
    assert res.passed and res.token_usage is None and res.stop_reason is None

def test_ask_raising_is_recorded_not_propagated():
    def ask(text, **kw): raise RuntimeError("boom")
    [res] = ruler_run.run_case(case(), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert res.status == "error" and not res.passed and "RuntimeError" in (res.error or "")

def test_suite_keeps_case_order_when_parallel():
    cases = [case(f"F{n:02d}") for n in range(1, 9)]
    results = ruler_run.run_suite(cases, ask=lambda text, **kw: outcome(), audit=lambda cid: {}, catalog_model="", parallel=4)
    assert [r.case_id for r in results] == [c.id for c in cases]

def test_audit_of_without_database_is_empty():
    assert ruler_run.audit_of(None, "c1") == {} and ruler_run.audit_of("postgresql://x", None) == {}
    assert ruler_run.audit_of("postgresql+psycopg://nobody@127.0.0.1:1/none", "c1") == {}

def _suite(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 1, "cases": [
        {"id": "F01", "kind": "fact", "title": "t", "turns": [{"text": "q", "checks": {"include_any": [["1158.44"]]}}]},
        {"id": "F02", "kind": "fact", "title": "t", "turns": [{"text": "q"}]}]}), encoding="utf-8")
    return path

def test_run_refuses_production_port(tmp_path, capsys):
    code = ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--base", "http://127.0.0.1:8000"])
    assert code == 2 and "8000" in capsys.readouterr().err and not (tmp_path / "o" / "results.jsonl").exists()

def test_run_writes_results_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome())
    out = tmp_path / "o"
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(out), "--cases", "F01"]) == 0
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["case_id"] for row in rows] == ["F01"] and "cred" not in (out / "results.jsonl").read_text()
    assert json.loads((out / "summary.json").read_text())["pass_rate"] == 1.0

def test_run_exits_2_when_api_is_down(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: False)
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o")]) == 2

def test_unknown_case_filter_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--cases", "Z99"]) == 2
    assert "Z99" in capsys.readouterr().err

def test_report_and_compare_write_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome())
    for name in ("a", "b"):
        ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / name)])
    assert ruler_run.main(["report", "--results", str(tmp_path / "a"), "--title", "基线", "--out", str(tmp_path / "r.md"), "--meta", "模型=haiku"]) == 0
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# 基线") and "haiku" in (tmp_path / "r.md").read_text(encoding="utf-8")
    assert ruler_run.main(["compare", "--base", str(tmp_path / "a"), "--new", str(tmp_path / "b"), "--title", "对比", "--out", str(tmp_path / "c.md")]) == 0
    assert "持平" in (tmp_path / "c.md").read_text(encoding="utf-8")

def test_status_any_does_not_excuse_a_hard_failure():
    c = Case("R02", "recall", "t", (Turn("记一下", Checks(status="any")), Turn("问", Checks(status="any"))))
    results = ruler_run.run_case(c, audit=lambda cid: {}, catalog_model="", ask=lambda text, **kw: outcome(status="error"))
    assert results[0].passed is False and results[0].failed_checks == ["status"]
    def boom(text, **kw): raise RuntimeError("boom")
    [res] = ruler_run.run_case(Case("R03", "recall", "t", (Turn("q", Checks(status="any")),)), ask=boom, audit=lambda cid: {}, catalog_model="")
    assert res.passed is False and res.failed_checks == ["status"]
