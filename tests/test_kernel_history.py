"""History for kernel turns: the boundary between the two history layers moves only on a fixed grid, so a long
conversation's history is a stable prefix from one turn to the next (the cost of a turn is what is NOT repeated)."""
import random
from uuid import UUID

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


def test_without_a_grid_nothing_changes():
    rows, ends = build(80)
    for n in (5, 30, 80):
        sub = rows[:ends[n - 1]]
        plain = layer_rows(sub, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3)
        assert plain == layer_rows(sub, [], l1_bytes=L1, l2_bytes=L2, l3_bytes=L3, anchor_grid=None)
        # the old rule, spelled out: layer 1 is the newest complete turns that fit
        assert plain["l1_turns"] == len(layers.complete_turns(plain["l1_rows"]))
    assert "anchor_grid" in layer_rows.__code__.co_varnames[:layer_rows.__code__.co_argcount + layer_rows.__code__.co_kwonlyargcount]


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
    # two conversations that differ only in the summary: the one with it never keeps a covered turn, and from
    # the turn the summary lands the prefix is stable again (it moves with the grid, not with the summary)
    for n in range(101, 201):
        context = context_at(rows, ends, n, ANCHOR_GRID, segments=summary)
        assert context["summary_upto"] == upto
        assert all(t.first_sequence > upto for t in context["half_turns"] + context["overflow"])
    seen = [starts(context_at(rows, ends, n, ANCHOR_GRID, segments=summary)) for n in range(101, 201)]
    changes = sum(a != b for a, b in zip(seen, seen[1:]))
    assert changes <= (rows[ends[199] - 1]["sequence"] - upto) // ANCHOR_GRID + 2
    # the turn the summary arrives on: the boundary moves once (the old text is replaced by the summary's)
    before, after = context_at(rows, ends, 130, ANCHOR_GRID), context_at(rows, ends, 130, ANCHOR_GRID, segments=summary)
    assert render(before) != render(after)


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
