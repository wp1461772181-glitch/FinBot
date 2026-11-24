"""History for kernel turns: the boundary between the two history layers moves only on a fixed grid, so a long
conversation's history is a stable prefix from one turn to the next (the cost of a turn is what is NOT repeated)."""
import asyncio
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

import app.agent_context as layers
from app.agent_context import ANCHOR_GRID, layer_rows

L1, L2, L3 = 24000, 16000, 4000


def build(turns=300, seed=7):
    """Rows of a conversation: (rows, ends) where ends[i] is the number of rows after turn i+1.
    Sizes vary; some turns carry large tool batches (many rows), some answers carry citations."""
    rng = random.Random(seed)
    rows, ends, seq = [], [], 0

    def add(role, content, turn, **extra):
        nonlocal seq
        seq += 1
        rows.append({"role": role, "content": content, "turn_id": str(UUID(int=turn)), "sequence": seq,
                     "status": "complete", "tool_calls": extra.get("tool_calls"), "tool_call_id": extra.get("tool_call_id")})

    for turn in range(1, turns + 1):
        add("user", f"question {turn} " + "q" * rng.randint(20, 260), turn)
        if rng.random() < 0.4:
            for call in range(rng.randint(1, 6)):
                add("assistant", "", turn, tool_calls={"calls": [{"id": f"c{turn}{call}", "function": {"name": "search_news"}}]})
                add("tool", "x" * rng.randint(50, 900), turn, tool_call_id=f"c{turn}{call}")
        answer = f"answer {turn} " + "a" * rng.randint(30, 400)
        if rng.random() < 0.3:
            answer += " [1]"
            protocol = {"citations": [{"ordinal": 1, "title": f"Filing {turn}", "source_type": "official_filing", "quote": "q"}]}
        else:
            protocol = None
        add("assistant", answer, turn, tool_calls=protocol)
        ends.append(len(rows))
    return rows, ends


def context_at(rows, ends, n, grid, segments=(), **sizes):
    upto_rows = rows[:ends[n - 1]]
    return layer_rows(upto_rows, list(segments), l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=grid, **sizes)


def render(context):
    """What the endpoint sends before the question (agent_chat_stream: layer 2, then layer 1)."""
    messages = layers.history_messages(context.get("half_turns", []), omitted=len(context.get("overflow") or []))
    for group in layers.complete_turns(context["l1_rows"]):
        messages.extend(layers.project_turn_history(group))
    return messages


def starts(context):
    l1 = context["l1_rows"][0]["turn_id"] if context["l1_rows"] else None
    half = context["half_turns"][0].turn_id if context["half_turns"] else None
    return l1, half, len(context["overflow"])


def own_messages(rows, ends, n):
    first = ends[n - 2] if n > 1 else 0
    return layers.project_turn_history(rows[first:ends[n - 1]])


BASE_COMMIT = "0f83e07"       # the last commit before the grid: its agent_context.py is the rule every old-engine turn keeps


def old_module():
    try:
        text = subprocess.run(["git", "show", f"{BASE_COMMIT}:app/agent_context.py"], cwd=Path(__file__).parent.parent,
                              capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git or the base commit is not available")
    spec = importlib.util.spec_from_loader("app.agent_context_base", loader=None)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "app"
    sys.modules[spec.name] = module            # the module's dataclass looks itself up here
    try:
        exec(compile(text, f"{BASE_COMMIT}:app/agent_context.py", "exec"), module.__dict__)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_without_a_grid_nothing_changes():
    old = old_module()
    for seed in range(1, 11):
        rows, ends = build(120, seed)
        for n in (3, 20, 47, 80, 120):
            sub = rows[:ends[n - 1]]
            for segments in ([], [{"seq": 1, "from_sequence": 1, "upto_sequence": sub[len(sub) // 3]["sequence"], "content": "s"}]):
                args = dict(l1_bytes=L1, l2_bytes=L2, l3_bytes=L3)
                expected = old.layer_rows(sub, segments, **args)
                # Turn is a different class in the old module: compare what it holds
                for result in (layer_rows(sub, segments, **args), layer_rows(sub, segments, anchor_grid=None, **args)):
                    assert repr(result) == repr(expected), (seed, n)


def test_history_prefix_is_stable_between_anchor_moves():
    rows, ends = build(300)
    previous = context_at(rows, ends, 1, ANCHOR_GRID)
    moved = 0
    full = 0
    for n in range(2, 301):
        current = context_at(rows, ends, n, ANCHOR_GRID)
        if starts(current) == starts(previous):
            assert render(current) == render(previous) + own_messages(rows, ends, n), f"prefix broke at turn {n}"
        else:
            moved += 1
        full += bool(current["half_turns"] and current["overflow"])
        previous = current
    assert full > 100, "the layers must be full for the test to mean anything"
    assert moved <= len(rows) // ANCHOR_GRID + 2, (moved, len(rows) // ANCHOR_GRID)


def test_the_same_rows_with_the_old_rule_slide_every_turn():
    rows, ends = build(300)
    moved = 0
    for n in range(60, 300):
        if starts(context_at(rows, ends, n, None)) != starts(context_at(rows, ends, n + 1, None)):
            moved += 1
    assert moved > 100


def test_layers_still_fit_their_budgets_and_are_adjacent():
    rows, ends = build(300)
    for n in (40, 150, 300):
        context = context_at(rows, ends, n, ANCHOR_GRID)
        assert context["l1_bytes"] <= L1
        assert sum(layers.half_size(t) for t in context["half_turns"]) <= L2
        complete = layers.complete_turns(rows[:ends[n - 1]])
        l1_turns = layers.complete_turns(context["l1_rows"])
        kept = [str(g[0]["turn_id"]) for g in l1_turns]
        assert kept == [str(g[0]["turn_id"]) for g in complete[len(complete) - len(l1_turns):]]
        pieces = [t.turn_id for t in context["overflow"]] + [t.turn_id for t in context["half_turns"]] + kept
        assert pieces == [str(g[0]["turn_id"]) for g in complete]


def test_a_summary_moves_the_boundary_once():
    rows, ends = build(200)
    upto = rows[ends[99] - 1]["sequence"]                  # a summary covers the turns up to turn 100
    summary = [{"seq": 1, "from_sequence": 1, "upto_sequence": upto, "content": "s"}]

    def view(n, landed):
        return context_at(rows, ends, n, ANCHOR_GRID, segments=summary if landed else ())

    def extends(n, landed):
        return render(view(n, landed)) == render(view(n - 1, landed)) + own_messages(rows, ends, n)

    # the summary lands on the turn k: before it the segment list is empty, from k on it is the one above
    k = next(k for k in range(125, 190) if starts(view(k - 2, False)) == starts(view(k - 1, False))
             and starts(view(k, True)) == starts(view(k + 1, True)))
    assert extends(k - 1, False)                                          # just before: a pure extension
    assert render(view(k, True)) != render(view(k - 1, False)) + own_messages(rows, ends, k)   # on it: it moves
    assert not render(view(k, True))[:len(render(view(k - 1, False)))] == render(view(k - 1, False))
    assert extends(k + 1, True)                                           # just after: a pure extension again
    assert all(t.first_sequence > upto for t in view(k, True)["half_turns"] + view(k, True)["overflow"])


def test_fallback_when_one_cell_is_larger_than_layer_one():
    rows, ends = build(120)
    for n in (60, 120):
        plain = context_at(rows, ends, n, None)
        tight = layer_rows(rows[:ends[n - 1]], [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=100_000)
        # a grid of 100000 sequence numbers has only the first-turn anchor, which cannot fit: today's rule
        assert tight["l1_rows"] == plain["l1_rows"]
        assert [t.turn_id for t in tight["half_turns"]] == [t.turn_id for t in plain["half_turns"]]
        assert len(tight["overflow"]) == len(plain["overflow"])


def test_only_the_newest_500_rows_are_fetched():
    rows, ends = build(300)
    fetched = rows[:ends[299]][-500:]                      # the store reads the newest 500 rows
    assert fetched[0]["sequence"] > 1
    huge = dict(l1_bytes=10 ** 9, l2_bytes=10 ** 9, l3_bytes=L3)
    complete = layers.complete_turns(fetched)
    by_turn = {str(g[0]["turn_id"]): g[0]["sequence"] for g in complete}

    def first_turn(context):
        return by_turn[layers.complete_turns(context["l1_rows"])[0][0]["turn_id"]]

    # everything fits, so layer 1 would start at the first fetched turn; that turn is not a known first turn
    # and not on a cell edge unless the grid says so, so layer 1 starts at the first real anchor instead
    cut = layer_rows(fetched, [], anchor_grid=ANCHOR_GRID, **huge)
    first = complete[0][0]["sequence"]
    expected = next(g[0]["sequence"] for prev, g in zip(complete, complete[1:])
                    if g[0]["sequence"] // ANCHOR_GRID != prev[0]["sequence"] // ANCHOR_GRID)
    assert first_turn(cut) == expected and expected > first
    assert [t.first_sequence for t in cut["half_turns"]][0] == first    # the turns before it go to layer 2
    # the whole conversation reaches back, so its first turn is an anchor and layer 1 may start there
    whole = layer_rows(rows[:ends[299]], [], anchor_grid=ANCHOR_GRID, **huge)
    assert whole["l1_rows"][0]["turn_id"] == str(UUID(int=1))
    # after a summary, the first turn past it is an anchor when the rows reach back to it
    upto = rows[ends[9] - 1]["sequence"]
    summarised = layer_rows(rows[:ends[299]], [{"seq": 1, "from_sequence": 1, "upto_sequence": upto, "content": "s"}],
                            anchor_grid=ANCHOR_GRID, **huge)
    assert summarised["l1_rows"][0]["turn_id"] == str(UUID(int=11))


def test_when_no_anchor_lies_in_layer_two_it_follows_the_old_rule_alone():
    rows, ends = build(300)
    tiny = 1500                                               # a few turns: shorter than the gap between two anchors
    checked = 0
    for n in range(60, 300, 7):
        sub = rows[:ends[n - 1]]
        context = layer_rows(sub, [], l1_bytes=L1, l2_bytes=tiny, l3_bytes=L3, anchor_grid=ANCHOR_GRID)
        complete = layers.complete_turns(sub)
        ids = [str(g[0]["turn_id"]) for g in complete]
        l1_ids = [str(g[0]["turn_id"]) for g in layers.complete_turns(context["l1_rows"])]
        first = ids.index(l1_ids[0])
        assert first == 0 or complete[first][0]["sequence"] // ANCHOR_GRID != complete[first - 1][0]["sequence"] // ANCHOR_GRID
        half = [t.turn_id for t in context["half_turns"]]
        older = ids[:first]
        assert sum(layers.half_size(t) for t in context["half_turns"]) <= tiny
        assert half == older[len(older) - len(half):] and half            # the newest turns that fit, next to layer 1
        starts_on = complete[ids.index(half[0])][0]["sequence"] // ANCHOR_GRID
        previous = complete[ids.index(half[0]) - 1][0]["sequence"] // ANCHOR_GRID
        checked += starts_on == previous                                  # layer 2 starts mid-cell: today's rule
    assert checked >= 5


# --- the summariser reads the same view the turn saw ----------------------------------------------------------

class Store:
    """What ``agent_chat_store`` offers the summariser: ``layer_rows`` over fixed rows, recording how it was asked."""

    def __init__(self, rows):
        self.rows, self.asked, self.appended = rows, [], []

    async def conversation_context(self, conversation_id, credential, **kwargs):
        self.asked.append(kwargs)
        grid = ANCHOR_GRID if kwargs.get("anchored") else None
        return layer_rows(self.rows, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=grid)

    async def append_summary(self, conversation_id, from_sequence, upto_sequence, content):
        self.appended.append((from_sequence, upto_sequence))
        return True

    def install(self, monkeypatch):
        import app.agent_chat_provider as provider
        import app.agent_chat_store as store

        async def model(*args, **kwargs):
            return {}, {"content": json.dumps({"summary": "用户连续询问。"}, ensure_ascii=False)}

        monkeypatch.setattr(store, "conversation_context", self.conversation_context)
        monkeypatch.setattr(store, "append_summary", self.append_summary)
        monkeypatch.setattr(provider, "decision_request", model)


def anchored_only_overflow():
    rows, ends = build(300)
    sub = rows[:ends[79]]                                      # 80 turns: the grid leaves overflow the old rule does not
    anchored = layer_rows(sub, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=ANCHOR_GRID)
    plain = layer_rows(sub, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3)
    assert anchored["overflow"] and not plain["overflow"] and layers.should_compact(anchored) and not layers.should_compact(plain)
    return sub, anchored


def test_the_summariser_takes_the_turns_the_grid_moved_out_of_both_layers(monkeypatch):
    import app.agent_context_summary as summary
    sub, anchored = anchored_only_overflow()
    store = Store(sub)
    store.install(monkeypatch)
    done = asyncio.run(summary.summarize_pending("cid", "c", provider="p", model="m", api_key="k" * 12, base_url=None,
                                                 l1_bytes=L1, l2_bytes=L2, anchored=True))
    assert done and store.asked == [{"l1_bytes": L1, "l2_bytes": L2, "anchored": True}]
    (first, last), = store.appended
    kept = {str(g[0]["turn_id"]): g for g in layers.complete_turns(anchored["l1_rows"])}
    l1_first = min(g[0]["sequence"] for g in (g for g in layers.complete_turns(sub) if str(g[0]["turn_id"]) in kept))
    assert first == anchored["overflow"][0].first_sequence and last < l1_first      # never a turn layer 1 keeps
    # the automatic compression is triggered by the anchored view too, and takes the same oldest turn
    store.appended.clear()
    result = asyncio.run(summary._guarded("cid", "c", provider="p", model="m", api_key="k" * 12, base_url=None,
                                          anchored=True))
    assert result is not None and store.asked[-1] == {"window": None, "anchored": True}


def test_an_unanchored_conversation_is_asked_exactly_as_before(monkeypatch):
    import app.agent_context_summary as summary
    sub, _ = anchored_only_overflow()
    store = Store(sub)
    store.install(monkeypatch)
    asyncio.run(summary.summarize_pending("cid", "c", provider="p", model="m", api_key="k" * 12, base_url=None,
                                          l1_bytes=L1, l2_bytes=L2))
    assert asyncio.run(summary._guarded("cid", "c", provider="p", model="m", api_key="k" * 12, base_url=None)) is None
    asyncio.run(summary.compact_conversation("cid", "c", provider="p", model="m", api_key="k" * 12, base_url=None, manual=True))
    assert store.asked == [{"l1_bytes": L1, "l2_bytes": L2}, {"window": None}, {"window": None}]


# --- what the endpoint really reads: the newest N rows, not the whole conversation -----------------------------

def build_fixed(turns, per_turn):
    """``per_turn`` rows a turn: the question, tool batches (two rows each), the answer."""
    rows, ends, seq = [], [], 0

    def add(role, content, turn, **extra):
        nonlocal seq
        seq += 1
        rows.append({"role": role, "content": content, "turn_id": str(UUID(int=turn)), "sequence": seq, "status": "complete",
                     "tool_calls": extra.get("tool_calls"), "tool_call_id": extra.get("tool_call_id")})

    for turn in range(1, turns + 1):
        add("user", f"question {turn} " + "q" * (40 + turn % 97), turn)
        for call in range((per_turn - 2) // 2):
            add("assistant", "", turn, tool_calls={"calls": [{"id": f"c{turn}{call}", "function": {"name": "search_news"}}]})
            add("tool", "x" * 300, turn, tool_call_id=f"c{turn}{call}")
        add("assistant", f"answer {turn} " + "a" * (60 + turn % 131), turn)
        ends.append(len(rows))
    return rows, ends


def fetched_context(rows, ends, n, *, limit, cut):
    """``conversation_context`` as the store does it: the newest ``limit`` rows, then (anchored) the window cut."""
    sub = rows[:ends[n - 1]]
    fetched = sub[-limit:]
    front = False
    if cut:
        fetched, front = layers.window_rows(fetched, 0, len(sub) >= limit, ANCHOR_GRID)
    return layer_rows(fetched, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3,
                      anchor_grid=ANCHOR_GRID if cut else None, anchor_front=front)


def breaks_and_moves(per_turn, *, limit, cut, turns=400):
    rows, ends = build_fixed(turns, per_turn)
    previous = fetched_context(rows, ends, 1, limit=limit, cut=cut)
    moves = broken = 0
    for n in range(2, turns + 1):
        current = fetched_context(rows, ends, n, limit=limit, cut=cut)
        if starts(current) != starts(previous):
            moves += 1
        elif render(current) != render(previous) + own_messages(rows, ends, n):
            broken += 1
        previous = current
    return moves, broken, len(rows)


@pytest.mark.parametrize("per_turn", [8, 14])
def test_the_history_stays_a_stable_prefix_through_the_rows_the_store_reads(per_turn):
    moves, broken, total = breaks_and_moves(per_turn, limit=layers.ANCHORED_ROWS, cut=True)
    assert broken == 0
    assert moves <= 2 * (total // ANCHOR_GRID) + 2        # a layer move and a window move per cell at most


@pytest.mark.parametrize("per_turn", [8, 14])
def test_the_old_slicing_breaks_the_prefix_every_turn(per_turn):
    # no cut, 500 rows: the window's front drops one turn at a time once the conversation has more than 500 rows
    moves, broken, total = breaks_and_moves(per_turn, limit=500, cut=False)
    assert moves > 2 * (total // ANCHOR_GRID) + 2


def test_the_cut_leaves_a_whole_grid_line_and_marks_the_front_an_anchor():
    rows, ends = build_fixed(100, 8)
    fetched = rows[300:]
    cut, front = layers.window_rows(fetched, 0, True, ANCHOR_GRID)
    assert front and cut[0]["sequence"] == 320 and cut == [r for r in fetched if r["sequence"] >= 320]
    assert layers.window_rows(fetched, 0, False, ANCHOR_GRID) == (fetched, False)          # not truncated: untouched
    assert layers.window_rows(rows, 0, True, ANCHOR_GRID) == (rows, False)                  # reaches the start


def test_the_store_reads_500_rows_unanchored_and_more_anchored(monkeypatch):
    import app.agent_chat_store as store
    limits = []

    class Result:
        def all(self):
            return []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def scalars(self, statement):
            limits.append(statement._limit_clause.value if statement._limit_clause is not None else None)
            return Result()

    async def yes(*args):
        return True

    monkeypatch.setattr(store, "Session", Session)
    monkeypatch.setattr(store, "verify_conversation", yes)
    cid = str(UUID(int=5))
    asyncio.run(store.conversation_context(cid, "c"))
    assert limits == [500, None]
    limits.clear()
    asyncio.run(store.conversation_context(cid, "c", anchored=True))
    assert limits == [layers.ANCHORED_ROWS, None] and layers.ANCHORED_ROWS == 2000
