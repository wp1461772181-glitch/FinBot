from collections import Counter
from ruler.cases import load_suite
from ruler.suites import make_baseline_v1 as gen

def test_bank_loads_with_the_planned_mix():
    cases = load_suite("ruler/suites/baseline-v1.json")
    assert len(cases) == 60 and sum(len(c.turns) for c in cases) == 86
    assert Counter(c.kind for c in cases) == {"fact": 15, "brief": 10, "compare": 10, "followup": 10, "recall": 8, "general": 7}

def test_committed_bank_matches_the_generator():
    import json
    assert json.load(open("ruler/suites/baseline-v1.json", encoding="utf-8")) == gen.build()

def test_num_lists_natural_spellings_and_no_loose_ones():
    assert {"33.20", "33.2", "3.320", "3.32", "3320", "3320000000"} <= set(gen.num(33.20))
    assert "13.4" not in gen.num(133.77) and "133.8" in gen.num(133.77) and "13.377" in gen.num(133.77)
    assert {"1158.44", "1158.4", "1158", "115.844", "115.84", "115.8", "115844", "115844000000"} <= set(gen.num(1158.44))
    assert "0.72" not in gen.num(7.18) and "7.2" not in gen.num(7.18) and "7.18" in gen.num(7.18)

def test_pct_forms():
    assert gen.pct(74.82) == ["74.82", "74.8"] and "19.58" in gen.pct(19.589)
