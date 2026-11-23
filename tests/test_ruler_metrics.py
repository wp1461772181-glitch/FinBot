from ruler.metrics import TurnResult, from_json, percentile, summarize, to_json

def r(case="F01", kind="fact", idx=0, passed=True, status="succeeded", total=1000, first_delta=400, first_event=100,
      tools=(), model_calls=2, tokens=5000, stop="answered", failed=()):
    return TurnResult(case, kind, idx, passed, list(failed), status, None, first_event, first_delta, total, list(tools),
                      model_calls, tokens, 2, stop, 10, "回答", None)

def test_percentile_nearest_rank():
    assert percentile([], 50) is None
    assert percentile([5], 90) == 5
    assert percentile([1, 2, 3, 4], 50) == 2
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9

def test_json_round_trip():
    one = r(tools=["calculate"], failed=["include_any[0]"], passed=False)
    assert from_json(to_json(one)) == one

def test_summary_counts_and_rates():
    s = summarize([r(), r("F02", passed=False, failed=["include_any[0]"]), r("B01", "brief", status="incomplete", passed=False, failed=["status"])])
    assert (s["turns"], s["cases"]) == (3, 3)
    assert s["pass_rate"] == 1 / 3 and s["failure_rate"] == 1 / 3
    assert s["failed"] == [{"case_id": "F02", "turn_index": 0, "status": "succeeded", "failed_checks": ["include_any[0]"]},
                           {"case_id": "B01", "turn_index": 0, "status": "incomplete", "failed_checks": ["status"]}]

def test_times_use_complete_turns_only():
    s = summarize([r(total=1000), r("F02", total=3000), r("F03", status="incomplete", total=99999, passed=False)])
    assert s["total_ms_p50"] == 1000 and s["total_ms_p90"] == 3000

def test_calc_share_and_tool_mean():
    s = summarize([r(tools=["query_financials", "calculate", "calculate_formula"]), r("F02", tools=["web_research"])])
    assert s["tool_calls_mean"] == 2.0 and s["calc_share"] == 0.5
    assert summarize([r()])["calc_share"] == 0.0

def test_audit_means_skip_missing_values():
    s = summarize([r(tokens=4000, model_calls=2), r("F02", tokens=None, model_calls=None)])
    assert s["token_usage_mean"] == 4000 and s["model_calls_mean"] == 2
    assert summarize([r(tokens=None, model_calls=None)])["token_usage_mean"] is None

def test_stop_reasons_and_by_kind():
    s = summarize([r(stop="answered"), r("F02", stop=None), r("B01", "brief", total=5000)])
    assert s["stop_reasons"] == {"answered": 2, "(none)": 1}
    assert s["by_kind"]["brief"] == {"turns": 1, "pass_rate": 1.0, "total_ms_p50": 5000, "total_ms_p90": 5000,
                                     "first_delta_ms_p50": 400, "first_event_ms_p50": 100}

def test_skipped_turns_count_as_not_passed_but_not_failures():
    s = summarize([r(), r("F01", idx=1, status="skipped", passed=False, total=0)])
    assert s["turns"] == 2 and s["cases"] == 1 and s["pass_rate"] == 0.5 and s["failure_rate"] == 0.0

def test_empty_input():
    s = summarize([])
    assert s["turns"] == 0 and s["pass_rate"] == 0.0 and s["total_ms_p50"] is None and s["by_kind"] == {}
