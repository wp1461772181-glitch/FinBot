"""The search is given ids only; rows are read and verified for the chunks it returns, never for the whole eligible set."""
from types import SimpleNamespace

from app.knowledge import retrieval


def test_rows_are_loaded_only_for_wanted_ids_that_are_eligible():
    asked = []

    def load(wanted):
        asked.append(list(wanted))
        return [(SimpleNamespace(id=value), "doc") for value in wanted if value != "b"]      # "b" fails verification

    eligible = retrieval._Eligible(["a", "b", "c"], load)
    assert bool(eligible) and list(eligible) == ["a", "b", "c"] and len(eligible) == 3
    rows = eligible.rows(["a", "b", "a", "zzz"])            # "zzz" was never eligible: it is not even looked up
    assert asked == [["a", "b"]] and set(rows) == {"a"}       # the chunk that fails verification does not get out
    assert eligible.rows([]) == {} and asked == [["a", "b"]]
    assert not retrieval._Eligible([], load)
