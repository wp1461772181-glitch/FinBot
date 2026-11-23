from ruler.metrics import summarize
from ruler.report import render, render_comparison
from tests.test_ruler_metrics import r

META = {"日期": "2026-11-23", "模型": "haiku-5.5", "代码版本": "649c96d"}

def test_report_has_title_meta_and_the_seven_promises():
    text = render(summarize([r(total=42000, first_delta=30000)]), title="尺子基线", meta=META)
    assert text.startswith("# 尺子基线\n")
    for value in META.values():
        assert value in text
    for promise in ("回得快", "懂你", "记得准", "交得出去", "可靠", "能插话", "看得见"):
        assert promise in text
    assert "未测（阶段 4 加题）" in text       # 懂你
    assert text.count("未测（阶段 3 加题）") == 2   # 交得出去、能插话

def test_times_are_shown_in_seconds_with_one_decimal():
    text = render(summarize([r(total=42000, first_delta=30500)]), title="t", meta={})
    assert "42.0 秒" in text and "30.5 秒" in text

def test_missing_values_read_as_no_data():
    text = render(summarize([r(tokens=None, model_calls=None)]), title="t", meta={})
    assert "无数据" in text and "None" not in text

def test_recall_row_uses_recall_kind_or_says_no_cases():
    assert "没有这类题" in render(summarize([r()]), title="t", meta={})
    text = render(summarize([r("R01", "recall", passed=True), r("R02", "recall", passed=False)]), title="t", meta={})
    assert "50%" in text

def test_failed_cases_are_listed():
    text = render(summarize([r("F09", passed=False, failed=["include_any[0]"])]), title="t", meta={})
    assert "F09" in text and "include_any[0]" in text

def test_by_kind_table_uses_chinese_kind_names():
    text = render(summarize([r(kind="fact"), r("B01", "brief")]), title="t", meta={})
    assert "简单事实" in text and "财报简述" in text

def test_comparison_shows_both_sides_and_direction():
    base = summarize([r(total=40000)]); new = summarize([r(total=10000)])
    text = render_comparison(base, new, title="新旧对比", meta=META)
    assert "40.0 秒" in text and "10.0 秒" in text and "快了 30.0 秒" in text

def test_comparison_flags_a_drop_in_pass_rate():
    base = summarize([r(), r("F02")]); new = summarize([r(), r("F02", passed=False, failed=["include_any[0]"])])
    text = render_comparison(base, new, title="t", meta={})
    assert "下降" in text and "100%" in text and "50%" in text
