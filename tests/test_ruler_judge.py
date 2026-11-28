"""ruler.judge: the 懂你 turns are judged on five points; the parsing, the prompt, the means and the comparison (no model is called)."""
import json

import pytest

from ruler import judge
from ruler.cases import SuiteError, load_suite
from ruler.metrics import TurnResult


def result(case_id, index, answer, status="succeeded"):
    return TurnResult(case_id=case_id, kind="understand", turn_index=index, passed=True, failed_checks=[], status=status, reason=None,
                      first_event_ms=1, first_delta_ms=1, total_ms=1, tools=[], model_calls=1, token_usage=1, decision_steps=1,
                      stop_reason=None, answer_chars=len(answer), answer=answer, error=None)


SCORES = {"intent": 2, "no_needless_question": 2, "fit": 1, "knows_him": 2, "no_boilerplate": 0}


def test_scores_are_read_from_a_reply_with_text_around_the_json():
    raw = "好的：\n```json\n" + json.dumps({"scores": SCORES, "note": "结尾是套话"}, ensure_ascii=False) + "\n```"
    assert judge.parse_scores(raw) == (SCORES, "结尾是套话")


@pytest.mark.parametrize("raw", ["没有 JSON", '{"scores": {"intent": 3}}', '{"scores": {"intent": 2}}', '{"note": "x"}',
                                 json.dumps({"scores": {**SCORES, "fit": True}})])
def test_a_reply_that_is_not_five_scores_of_0_to_2_is_refused(raw):
    with pytest.raises(judge.JudgeError):
        judge.parse_scores(raw)


def test_the_judged_turn_comes_with_the_turns_before_it_and_its_rubric():
    items = judge.judged_turns("ruler/suites/understand-v1.json", [result("U01", 0, "英伟达、博通……"), result("U01", 1, "确实很狠")])
    first = next(i for i in items if i["case_id"] == "U01")
    assert first["turn_index"] == 1 and first["earlier"] == [("费城半导体指数主要收纳了哪些巨头企业？", "英伟达、博通……")]
    prompt = judge.build_prompt(first["title"], first["earlier"], first["question"], first["answer"], first["rubric"])
    assert "【第 1 轮 助手】英伟达、博通……" in prompt and "【被评的这一轮 用户】这些企业看着就挺狠呐" in prompt and "不反问" in prompt
    missing = next(i for i in items if i["case_id"] == "U02")
    assert missing["status"] == "missing" and missing["answer"] == ""


def test_a_reply_that_cannot_be_read_is_asked_once_more_then_left_out_of_the_means():
    replies = iter(["乱码", json.dumps({"scores": SCORES, "note": "好"}), "乱码", "还是乱码"])
    items = [{"case_id": "U01", "turn_index": 1, "title": "t", "question": "q", "answer": "a", "status": "succeeded", "earlier": [], "rubric": "r"},
             {"case_id": "U02", "turn_index": 0, "title": "t", "question": "q", "answer": "a", "status": "succeeded", "earlier": [], "rubric": "r"}]
    scored = judge.score(items, lambda system, user: next(replies))
    assert scored[0]["total"] == 7 and "error" not in scored[0]
    assert scored[1]["scores"] is None and scored[1]["error"].startswith("JudgeError")
    summary = judge.summarize(scored)
    assert summary["judged"] == 1 and summary["errors"] == 1 and summary["total_mean"] == 7 and summary["by_criterion"]["fit"] == 1


def test_the_comparison_shows_each_point_and_the_turns_that_moved():
    base_items = [{"case_id": "U01", "turn_index": 1, "title": "感叹", "scores": dict.fromkeys(judge.KEYS, 1), "total": 5, "note": "反问了"}]
    new_items = [{"case_id": "U01", "turn_index": 1, "title": "感叹", "scores": dict.fromkeys(judge.KEYS, 2), "total": 10, "note": "好"}]
    base = {"model": "m", "items": base_items, "summary": judge.summarize(base_items)}
    new = {"model": "m", "items": new_items, "summary": judge.summarize(new_items)}
    text = judge.compare_markdown(base, new, "对比")
    assert "| 总分（满分 10） | 5.00 | 10.00 | 高了 5.00 |" in text and "| 接住本意（满分 2） | 1.00 | 2.00 | 高了 1.00 |" in text
    assert "| U01 | 感叹 | 5 | 10 | 好 |" in text


def test_a_rubric_must_be_a_short_string(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 1, "cases": [{"id": "U01", "kind": "understand", "title": "t",
                                                         "turns": [{"text": "q", "rubric": "x" * 601}]}]}), encoding="utf-8")
    with pytest.raises(SuiteError):
        load_suite(path)


def test_the_understand_suite_judges_every_case_once():
    cases = load_suite("ruler/suites/understand-v1.json")
    assert len(cases) == 20 and all(c.kind == "understand" for c in cases)
    assert all(sum(1 for t in c.turns if t.rubric) == 1 for c in cases)
