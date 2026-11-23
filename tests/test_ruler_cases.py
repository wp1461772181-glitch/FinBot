import json, pytest
from ruler.cases import Case, Checks, SuiteError, load_suite

def _write(tmp_path, cases, version=1):
    path = tmp_path / "suite.json"
    path.write_text(json.dumps({"version": version, "cases": cases}, ensure_ascii=False), encoding="utf-8")
    return path

def _case(**over):
    base = {"id": "F01", "kind": "fact", "title": "t", "turns": [{"text": "问题", "checks": {}}]}
    base.update(over)
    return base

def test_loads_a_case_with_defaults(tmp_path):
    [case] = load_suite(_write(tmp_path, [_case()]))
    assert case == Case("F01", "fact", "t", (case.turns[0],))
    assert case.turns[0].text == "问题" and case.turns[0].checks == Checks()

def test_checks_are_parsed_into_tuples(tmp_path):
    checks = {"status": "complete", "include_any": [["1158.44", "115.8"], ["英伟达"]], "exclude": ["没有可核验"]}
    [case] = load_suite(_write(tmp_path, [_case(turns=[{"text": "q", "checks": checks}])]))
    assert case.turns[0].checks == Checks("complete", (("1158.44", "115.8"), ("英伟达",)), ("没有可核验",))

def test_turn_without_checks_key_gets_defaults(tmp_path):
    [case] = load_suite(_write(tmp_path, [_case(turns=[{"text": "q"}])]))
    assert case.turns[0].checks == Checks()

@pytest.mark.parametrize("bad, needle", [
    (_case(id="f1"), "id"),
    (_case(kind="chat"), "kind"),
    (_case(turns=[]), "turns"),
    (_case(turns=[{"text": "", "checks": {}}]), "text"),
    (_case(turns=[{"text": "x" * 4001, "checks": {}}]), "text"),
    (_case(extra=1), "extra"),
    (_case(turns=[{"text": "q", "checks": {"includes": []}}]), "includes"),
    (_case(turns=[{"text": "q", "checks": {"include_any": [[]]}}]), "include_any"),
    (_case(turns=[{"text": "q", "note": "x"}]), "note"),
])
def test_bad_case_is_rejected_naming_the_field(tmp_path, bad, needle):
    with pytest.raises(SuiteError) as err:
        load_suite(_write(tmp_path, [bad]))
    assert needle in str(err.value)

def test_error_names_the_case_id(tmp_path):
    with pytest.raises(SuiteError) as err:
        load_suite(_write(tmp_path, [_case(), _case(id="B07", kind="nope")]))
    assert "B07" in str(err.value)

def test_duplicate_ids_are_rejected(tmp_path):
    with pytest.raises(SuiteError) as err:
        load_suite(_write(tmp_path, [_case(), _case()]))
    assert "F01" in str(err.value)

def test_unknown_version_and_missing_file(tmp_path):
    with pytest.raises(SuiteError):
        load_suite(_write(tmp_path, [_case()], version=2))
    with pytest.raises(SuiteError):
        load_suite(tmp_path / "missing.json")

def test_order_is_preserved(tmp_path):
    cases = load_suite(_write(tmp_path, [_case(id="B02", kind="brief"), _case(id="F01")]))
    assert [c.id for c in cases] == ["B02", "F01"]

@pytest.mark.parametrize("bad, needle", [
    (_case(turns=[{"text": "   ", "checks": {}}]), "text"),
    (_case(turns=[{"text": "q", "checks": {"include_any": [["x", "  "]]}}]), "include_any"),
    (_case(turns=[{"text": "q", "checks": {"exclude": [""]}}]), "exclude"),
    (_case(title="  "), "title"),
])
def test_blank_strings_are_rejected(tmp_path, bad, needle):
    with pytest.raises(SuiteError) as err:
        load_suite(_write(tmp_path, [bad]))
    assert needle in str(err.value)

def test_boolean_version_is_rejected(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text('{"version": true, "cases": []}', encoding="utf-8")
    with pytest.raises(SuiteError):
        load_suite(path)

def test_invalid_json_is_a_suite_error(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SuiteError):
        load_suite(path)
