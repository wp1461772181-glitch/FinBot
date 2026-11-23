from ruler.cases import Checks
from ruler.checks import normalize, run_checks

def test_normalize_number_spellings_agree():
    forms = ["1,158.44 亿美元", "1158.44亿美元", "１，１５８．４４ 亿美元", "1 158.44 亿美元"]
    assert len({normalize(f) for f in forms}) == 1

def test_normalize_keeps_decimal_and_list_commas():
    assert "20.39" in normalize("增长 20.39%")
    assert normalize("AAPL, MSFT") == "aapl, msft"          # a comma not between digits stays
    assert normalize("2026,11") == "2026,11"                # not a thousands group (two digits after)

def test_normalize_lowercases_and_collapses_space():
    assert normalize("  NVDA\n\n  Q3 ") == "nvda q3"

def test_all_pass_returns_empty():
    checks = Checks(include_any=(("1158.44",), ("英伟达", "nvda")), exclude=("没有可核验",))
    assert run_checks(checks, answer="NVDA 本季营收 1,158.44 亿美元", status="succeeded") == []

def test_failures_are_named_by_position():
    checks = Checks(include_any=(("1158.44",), ("毛利率",)), exclude=("营收", "不存在"))
    failed = run_checks(checks, answer="本季营收 900 亿", status="succeeded")
    assert failed == ["include_any[0]", "include_any[1]", "exclude[0]"]

def test_status_mismatch_is_reported_first():
    assert run_checks(Checks(), answer="", status="incomplete") == ["status"]

def test_needles_are_normalized_too():
    assert run_checks(Checks(include_any=(("1,158.44 亿",),)), answer="1158.44亿", status="succeeded") == []

def test_repeated_thousands_separators_fold_away():
    assert normalize("1,158,000 亿") == "1158000亿"
    assert normalize("１，０００") == "1000"


def test_status_any_accepts_every_status():
    assert run_checks(Checks(status="any"), answer="x", status="waiting_for_input") == []


def test_default_status_is_succeeded():
    assert Checks().status == "succeeded"
    assert run_checks(Checks(), answer="", status="waiting_for_input") == ["status"]


def test_number_needles_respect_digit_boundaries():
    c = Checks(include_any=(("13.4",),))
    assert run_checks(c, answer="增长 13.4%", status="succeeded") == []
    assert run_checks(c, answer="营收 113.4 亿", status="succeeded") == ["include_any[0]"]
    assert run_checks(c, answer="营收 13.45 亿", status="succeeded") == ["include_any[0]"]
    assert run_checks(c, answer="比率 0.13.4", status="succeeded") == ["include_any[0]"]


def test_integer_needle_does_not_match_inside_a_decimal():
    c = Checks(include_any=(("68",),))
    assert run_checks(c, answer="警戒线是 68%", status="succeeded") == []
    assert run_checks(c, answer="警戒线是68。", status="succeeded") == []
    assert run_checks(c, answer="是 168", status="succeeded") == ["include_any[0]"]
    assert run_checks(c, answer="是 68.5%", status="succeeded") == ["include_any[0]"]


def test_text_needles_keep_substring_matching():
    assert run_checks(Checks(include_any=(("aapl",), ("q3",))), answer="AAPL 的 FY2027Q3", status="succeeded") == []


def test_full_dollar_figure_is_one_number():
    c = Checks(include_any=(("115844",),))
    assert run_checks(c, answer="营收 115,844 百万美元", status="succeeded") == []
    assert run_checks(c, answer="营收 115,844,000,000 美元", status="succeeded") == ["include_any[0]"]


def test_exclude_needles_use_the_same_boundaries():
    c = Checks(exclude=("68",))
    assert run_checks(c, answer="是 168", status="succeeded") == []
    assert run_checks(c, answer="是 68%", status="succeeded") == ["exclude[0]"]
