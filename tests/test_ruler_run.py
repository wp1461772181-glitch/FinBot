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


def _run_args(tmp_path, base):
    return ["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--base", base]

def _stub_api(monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome())

def test_guard_refuses_a_non_local_host(tmp_path, capsys):
    assert ruler_run.main(_run_args(tmp_path, "https://example.com")) == 2
    assert "example.com" in capsys.readouterr().err

def test_guard_refuses_the_production_port_on_localhost(tmp_path, capsys):
    assert ruler_run.main(_run_args(tmp_path, "http://127.0.0.1:8000")) == 2
    assert "8000" in capsys.readouterr().err

def test_guard_lets_a_local_shadow_port_through(tmp_path, monkeypatch):
    _stub_api(monkeypatch)
    assert ruler_run.main(_run_args(tmp_path, "http://localhost:9031")) == 0

def test_guard_refuses_an_unparsable_base(tmp_path, capsys):
    assert ruler_run.main(_run_args(tmp_path, "http://127.0.0.1:notaport")) == 2
    assert "Traceback" not in capsys.readouterr().err

def test_allow_production_passes_the_guard(tmp_path, monkeypatch):
    _stub_api(monkeypatch)
    assert ruler_run.main(_run_args(tmp_path, "http://127.0.0.1:8000") + ["--allow-production"]) == 0

def test_repeated_meta_flags_are_all_kept(tmp_path, monkeypatch):
    _stub_api(monkeypatch)
    ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "a")])
    ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "b")])
    assert ruler_run.main(["report", "--results", str(tmp_path / "a"), "--title", "基线", "--out", str(tmp_path / "r.md"),
                           "--meta", "模型=haiku", "--meta", "代码版本=abc123"]) == 0
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "haiku" in text and "abc123" in text
    assert ruler_run.main(["compare", "--base", str(tmp_path / "a"), "--new", str(tmp_path / "b"), "--title", "对比",
                           "--out", str(tmp_path / "c.md"), "--meta", "模型=haiku", "--meta", "代码版本=abc123"]) == 0
    text = (tmp_path / "c.md").read_text(encoding="utf-8")
    assert "haiku" in text and "abc123" in text

def test_meta_without_equals_is_an_error(tmp_path, monkeypatch, capsys):
    _stub_api(monkeypatch)
    ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "a")])
    assert ruler_run.main(["report", "--results", str(tmp_path / "a"), "--title", "t", "--out", str(tmp_path / "r.md"), "--meta", "模型haiku"]) == 2
    assert "模型haiku" in capsys.readouterr().err

def test_results_with_unicode_line_separators_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome(answer="营收  1158.44 亿 结束\x85"))
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "a"), "--cases", "F01"]) == 0
    assert ruler_run.main(["report", "--results", str(tmp_path / "a"), "--title", "t", "--out", str(tmp_path / "r.md")]) == 0
    summary = ruler_run._load_summary(tmp_path / "a")
    assert summary["turns"] == 1

def test_empty_cases_filter_is_an_error(tmp_path, monkeypatch, capsys):
    _stub_api(monkeypatch)
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--cases", " , "]) == 2
    assert not (tmp_path / "o" / "results.jsonl").exists()

def test_malformed_results_row_is_a_message_not_a_traceback(tmp_path, monkeypatch, capsys):
    _stub_api(monkeypatch)
    ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "a")])
    rows = [json.loads(line) for line in (tmp_path / "a" / "results.jsonl").read_text(encoding="utf-8").split("\n") if line]
    for name, mutate in (("missing", lambda r: r.pop("answer")), ("extra", lambda r: r.update(bogus=1))):
        mutate(rows[0])
        bad = tmp_path / name
        bad.mkdir()
        (bad / "results.jsonl").write_text(json.dumps(rows[0], ensure_ascii=False) + "\n", encoding="utf-8")
        assert ruler_run.main(["report", "--results", str(bad), "--title", "t", "--out", str(tmp_path / "r.md")]) == 2
        assert "results.jsonl" in capsys.readouterr().err
        assert ruler_run.main(["compare", "--base", str(bad), "--new", str(tmp_path / "a"), "--title", "t", "--out", str(tmp_path / "c.md")]) == 2
        capsys.readouterr()
        rows[0] = json.loads((tmp_path / "a" / "results.jsonl").read_text(encoding="utf-8").split("\n")[0])


def _stub_ask_command(monkeypatch, tmp_path, *, server, outcomes=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "server_process", lambda base: server)
    asked = []
    replies = list(outcomes or [])
    def fake_ask(base, cred, text, **kw):
        asked.append((text, kw.get("conversation_id")))
        return replies.pop(0) if replies else outcome(cid="conv-1")
    monkeypatch.setattr(ruler_run, "ask", fake_ask)
    return asked

def test_ask_names_the_code_under_test_and_prints_the_answers(tmp_path, monkeypatch, capsys):
    asked = _stub_ask_command(monkeypatch, tmp_path, server=(4321, str(tmp_path)))
    assert ruler_run.main(["ask", "第一句", "第二句"]) == 0
    printed = capsys.readouterr().out
    assert asked == [("第一句", None), ("第二句", "conv-1")]
    assert "进程 4321" in printed and str(tmp_path) in printed and "营收 1158.44 亿" in printed
    assert "cred" not in printed

def test_ask_refuses_a_server_running_from_another_directory(tmp_path, monkeypatch, capsys):
    asked = _stub_ask_command(monkeypatch, tmp_path, server=(4321, "/opt/finbot/src"))
    assert ruler_run.main(["ask", "问"]) == 2
    assert "/opt/finbot/src" in capsys.readouterr().err and asked == []

def test_ask_accepts_a_stated_server_directory(tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"; other.mkdir()
    asked = _stub_ask_command(monkeypatch, tmp_path, server=(4321, str(other)))
    assert ruler_run.main(["ask", "问", "--server-dir", str(other)]) == 0 and len(asked) == 1

def test_ask_goes_ahead_but_says_so_when_the_server_cannot_be_identified(tmp_path, monkeypatch, capsys):
    asked = _stub_ask_command(monkeypatch, tmp_path, server=None)
    assert ruler_run.main(["ask", "问"]) == 0
    assert "查不到" in capsys.readouterr().out and len(asked) == 1

def test_ask_exits_1_when_a_turn_does_not_end_normally(tmp_path, monkeypatch, capsys):
    _stub_ask_command(monkeypatch, tmp_path, server=None, outcomes=[outcome(status="http_500", answer="")])
    assert ruler_run.main(["ask", "问"]) == 1
    assert "http_500" in capsys.readouterr().out

def test_ask_refuses_the_production_port_without_the_flag(tmp_path, monkeypatch, capsys):
    asked = _stub_ask_command(monkeypatch, tmp_path, server=None)
    assert ruler_run.main(["ask", "问", "--base", "http://127.0.0.1:8000"]) == 2
    assert "8000" in capsys.readouterr().err and asked == []

def test_server_process_is_none_for_a_port_nobody_listens_on():
    assert ruler_run.server_process("http://127.0.0.1:1") is None
    assert ruler_run.server_process("http://127.0.0.1:notaport") is None
