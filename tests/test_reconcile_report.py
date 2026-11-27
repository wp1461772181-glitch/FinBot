"""5d-1: ``scripts/reconcile_report.py`` runs on the shadow database only and writes nothing."""
from scripts import reconcile_report, wake_replay

SHADOW = "postgresql://u@h/finbot_ruler"


def test_the_guard_is_the_wake_replays():
    assert reconcile_report.refusal is wake_replay.refusal
    assert "RULER_DATABASE_URL" in reconcile_report.refusal({"DATABASE_URL": "postgresql://live"})
    assert "不是影子库" in reconcile_report.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": "postgresql://live"})
    assert "finbot_ruler" in reconcile_report.refusal({"RULER_DATABASE_URL": "postgresql://u@h/finbot", "DATABASE_URL": "postgresql://u@h/finbot"})
    assert reconcile_report.refusal({"RULER_DATABASE_URL": SHADOW, "DATABASE_URL": SHADOW}) is None


def test_main_exits_2_before_touching_a_database_outside_the_shadow(monkeypatch, capsys):
    import app.kernel.reconcile as reconcile

    def forbidden(*_a, **_k):
        raise AssertionError("a database was read")
    monkeypatch.setattr(reconcile, "kernel_answers", forbidden)
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    assert reconcile_report.main([]) == 2
    assert "RULER_DATABASE_URL" in capsys.readouterr().err
    monkeypatch.setenv("RULER_DATABASE_URL", SHADOW)
    monkeypatch.setenv("DATABASE_URL", "postgresql://live")
    assert reconcile_report.main([]) == 2
    assert "不是影子库" in capsys.readouterr().err


def test_a_limit_below_one_is_refused(capsys):
    assert reconcile_report.main(["--limit", "0"]) == 2
    assert "--limit" in capsys.readouterr().err


def test_the_summary_counts_the_flag_rate_over_the_checked_answers_and_lists_every_flagged_line():
    results = [("a", {"version": 1, "figures": 3, "flagged": [{"line": "利润是 8888 美元", "values": ["8888"]},
                                                            {"line": "现金是 9999 美元", "values": ["9999"]}]}),
               ("b", {"version": 1, "figures": 2, "flagged": []}),
               ("c", {"version": 1, "error": "KeyError"})]
    report = reconcile_report.summary(results)
    assert report["answers"] == 3 and report["checked"] == 2 and report["flagged_answers"] == 1 and report["flag_rate"] == 0.5
    assert report["figures"] == 5 and report["flagged_lines"] == 2
    assert report["flagged"] == [{"message_id": "a", "line": "利润是 8888 美元", "values": ["8888"]},
                                 {"message_id": "a", "line": "现金是 9999 美元", "values": ["9999"]}]
    assert report["errors"] == [{"message_id": "c", "error": "KeyError"}]
    assert reconcile_report.summary([])["flag_rate"] is None


def test_it_writes_nothing():
    source = open(reconcile_report.__file__, encoding="utf-8").read()
    assert "store(" not in source and "check_and_store" not in source and ".commit(" not in source


def test_a_planted_figure_is_one_no_source_states():
    from scripts.reconcile_report import plant
    planted, token = plant("营收 1,275.77 亿美元 [1]，毛利率 59.7%。")
    assert token == "1,747.80" and token in planted and "1,275.77" not in planted
    assert plant("没有数字。") == ("没有数字。", None)
