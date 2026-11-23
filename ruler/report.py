"""Markdown report for ruler: one run, or a base-versus-new comparison, in Simplified Chinese."""

KIND_NAMES = {
    "fact": "简单事实",
    "brief": "财报简述",
    "compare": "多公司比较",
    "followup": "追问",
    "recall": "回忆细节",
    "general": "不查资料",
}

_NO_DATA = "无数据"
_NO_CASES = "没有这类题"
_NOT_COMPARABLE = "无法比较"
_UNCHANGED = "持平"
_NOT_APPLICABLE = "—"
_NOT_YET_STAGE_3 = "未测（阶段 3 加题）"
_NOT_YET_STAGE_4 = "未测（阶段 4 加题）"

# A fast-answer promise reports these two parts, each with a median and a P90.
_FAST_PARTS = (("出第一个字", "first_delta_ms"), ("答完", "total_ms"))


def render(summary: dict, *, title: str, meta: dict[str, str]) -> str:
    """Render one run's summary as a Markdown report."""
    sections = [
        _title_block(title, meta, [f"轮数：{summary['turns']}，题数：{summary['cases']}"]),
        _section("七条承诺", _table(["承诺", "指标", "结果"], _single_promise_rows(summary))),
        _section("按题型", _kind_table(summary["by_kind"])),
        _section("用量", _table(["指标", "结果"], _single_usage_rows(summary))),
        _section("收场原因", _stop_table(summary["stop_reasons"])),
        _section("没通过的题", _failed_table(summary["failed"])),
    ]
    return "\n\n".join(sections) + "\n"


def render_comparison(base: dict, new: dict, *, title: str, meta: dict[str, str]) -> str:
    """Render a base-versus-new comparison of two summaries as a Markdown report."""
    sections = [
        _title_block(title, meta, [f"轮数：基线 {base['turns']}，新版 {new['turns']}"]),
        _section("七条承诺", _table(["承诺", "指标", "基线", "新版", "变化"], _compare_promise_rows(base, new))),
        _section("按题型", _table(["题型", "指标", "基线", "新版", "变化"],
                                _compare_kind_rows(base["by_kind"], new["by_kind"]), empty="没有轮次")),
        _section("用量", _table(["指标", "基线", "新版", "变化"], _compare_usage_rows(base, new))),
        _section("收场原因", _table(["收场原因", "基线", "新版", "变化"],
                                  _compare_stop_rows(base["stop_reasons"], new["stop_reasons"]),
                                  empty="没有收场记录")),
        _section("没通过的题", "\n\n".join(["### 基线", _failed_table(base["failed"]),
                                          "### 新版", _failed_table(new["failed"])])),
    ]
    return "\n\n".join(sections) + "\n"


def _title_block(title: str, meta: dict[str, str], extra: list[str]) -> str:
    bullets = [f"- {key}：{value}" for key, value in meta.items()] + [f"- {line}" for line in extra]
    return "\n".join([f"# {title}", "", *bullets])


def _section(heading: str, body: str) -> str:
    return f"## {heading}\n\n{body}"


def _table(headers: list[str], rows: list[list], *, empty: str = "无") -> str:
    if not rows:
        return empty
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join(lines)


def _cell(value) -> str:
    return str(value).replace("|", "\\|")


def _seconds(ms: float | None) -> str:
    return _NO_DATA if ms is None else f"{ms / 1000:.1f} 秒"


def _percent(rate: float | None) -> str:
    return _NO_DATA if rate is None else f"{round(rate * 100)}%"


def _count(value: float | None, digits: int, unit: str) -> str:
    return _NO_DATA if value is None else f"{value:,.{digits}f}{unit}"


def _time_change(base: float | None, new: float | None) -> str:
    if base is None or new is None:
        return _NO_DATA
    delta = new - base
    seconds = abs(delta) / 1000
    if round(seconds, 1) == 0:
        return _UNCHANGED
    return f"{'快了' if delta < 0 else '慢了'} {seconds:.1f} 秒"


def _rate_change(base: float | None, new: float | None) -> str:
    if base is None or new is None:
        return _NO_DATA
    points = round(new * 100) - round(base * 100)
    if points == 0:
        return _UNCHANGED
    direction = "上升" if points > 0 else "下降"
    return f"{direction} {abs(points)} 个百分点"


def _count_change(base: float | None, new: float | None, digits: int, unit: str) -> str:
    if base is None or new is None:
        return _NO_DATA
    base_value, new_value = round(base, digits), round(new, digits)
    if base_value == new_value:
        return _UNCHANGED
    direction = "增加" if new_value > base_value else "减少"
    return f"{direction} {abs(new_value - base_value):,.{digits}f}{unit}"


# Per-kind metrics: (label, summary key, value text, change text).
_KIND_METRICS = (
    ("通过率", "pass_rate", _percent, _rate_change),
    ("答完中位数", "total_ms_p50", _seconds, _time_change),
    ("答完 P90", "total_ms_p90", _seconds, _time_change),
    ("出第一个字中位数", "first_delta_ms_p50", _seconds, _time_change),
    ("出现第一个进展中位数", "first_event_ms_p50", _seconds, _time_change),
)


def _kind_order(kinds) -> list[str]:
    known = list(KIND_NAMES)
    return sorted(kinds, key=lambda kind: known.index(kind) if kind in known else len(known))


def _recall_rate(summary: dict) -> float | None:
    recall = summary["by_kind"].get("recall")
    return None if recall is None else recall["pass_rate"]


def _recall_text(rate: float | None) -> str:
    return _NO_CASES if rate is None else f"回忆细节题通过率 {_percent(rate)}"


def _fast_text(summary: dict) -> str:
    return "；".join(
        f"{label}：中位数 {_seconds(summary[key + '_p50'])}、P90 {_seconds(summary[key + '_p90'])}"
        for label, key in _FAST_PARTS
    )


def _fast_change(base: dict, new: dict) -> str:
    return "；".join(
        f"{label}：中位数 {_time_change(base[key + '_p50'], new[key + '_p50'])}"
        f"、P90 {_time_change(base[key + '_p90'], new[key + '_p90'])}"
        for label, key in _FAST_PARTS
    )


def _reliable_text(summary: dict) -> str:
    return f"检查通过率 {_percent(summary['pass_rate'])}；失败率 {_percent(summary['failure_rate'])}"


def _single_promise_rows(summary: dict) -> list[list[str]]:
    return [
        ["回得快", "出第一个字的中位数和 P90；答完的中位数和 P90", _fast_text(summary)],
        ["看得见", "出现第一个进展的中位数", f"中位数 {_seconds(summary['first_event_ms_p50'])}"],
        ["可靠", "检查通过率；失败率", _reliable_text(summary)],
        ["记得准", "回忆细节题的通过率", _recall_text(_recall_rate(summary))],
        ["懂你", _NOT_APPLICABLE, _NOT_YET_STAGE_4],
        ["交得出去", _NOT_APPLICABLE, _NOT_YET_STAGE_3],
        ["能插话", _NOT_APPLICABLE, _NOT_YET_STAGE_3],
    ]


def _compare_promise_rows(base: dict, new: dict) -> list[list[str]]:
    base_recall, new_recall = _recall_rate(base), _recall_rate(new)
    if base_recall is None or new_recall is None:
        recall_change = _NOT_COMPARABLE
    else:
        recall_change = _rate_change(base_recall, new_recall)
    return [
        ["回得快", "出第一个字的中位数和 P90；答完的中位数和 P90",
         _fast_text(base), _fast_text(new), _fast_change(base, new)],
        ["看得见", "出现第一个进展的中位数",
         f"中位数 {_seconds(base['first_event_ms_p50'])}",
         f"中位数 {_seconds(new['first_event_ms_p50'])}",
         f"中位数 {_time_change(base['first_event_ms_p50'], new['first_event_ms_p50'])}"],
        ["可靠", "检查通过率；失败率",
         _reliable_text(base), _reliable_text(new),
         f"检查通过率 {_rate_change(base['pass_rate'], new['pass_rate'])}"
         f"；失败率 {_rate_change(base['failure_rate'], new['failure_rate'])}"],
        ["记得准", "回忆细节题的通过率", _recall_text(base_recall), _recall_text(new_recall), recall_change],
        ["懂你", _NOT_APPLICABLE, _NOT_YET_STAGE_4, _NOT_YET_STAGE_4, _NOT_APPLICABLE],
        ["交得出去", _NOT_APPLICABLE, _NOT_YET_STAGE_3, _NOT_YET_STAGE_3, _NOT_APPLICABLE],
        ["能插话", _NOT_APPLICABLE, _NOT_YET_STAGE_3, _NOT_YET_STAGE_3, _NOT_APPLICABLE],
    ]


def _kind_table(by_kind: dict) -> str:
    rows = []
    for kind in _kind_order(by_kind):
        stats = by_kind[kind]
        rows.append([
            KIND_NAMES.get(kind, kind),
            stats["turns"],
            _percent(stats["pass_rate"]),
            _seconds(stats["total_ms_p50"]),
            _seconds(stats["total_ms_p90"]),
            _seconds(stats["first_delta_ms_p50"]),
            _seconds(stats["first_event_ms_p50"]),
        ])
    return _table(["题型", "轮数", "通过率", "答完中位数", "答完 P90", "出第一个字中位数", "出现第一个进展中位数"],
                  rows, empty="没有轮次")


def _compare_kind_rows(base_kinds: dict, new_kinds: dict) -> list[list[str]]:
    rows = []
    for kind in _kind_order(dict.fromkeys([*base_kinds, *new_kinds])):
        name = KIND_NAMES.get(kind, kind)
        base, new = base_kinds.get(kind), new_kinds.get(kind)
        for label, key, value_text, change_text in _KIND_METRICS:
            if base is None or new is None:
                # A kind that appears on one side only has nothing to compare against.
                rows.append([name, label,
                             _NO_CASES if base is None else value_text(base[key]),
                             _NO_CASES if new is None else value_text(new[key]),
                             _NOT_COMPARABLE])
            else:
                rows.append([name, label, value_text(base[key]), value_text(new[key]),
                             change_text(base[key], new[key])])
    return rows


def _single_usage_rows(summary: dict) -> list[list[str]]:
    return [
        ["每轮工具调用数", _count(summary["tool_calls_mean"], 1, " 次")],
        ["计算类调用占比", _percent(summary["calc_share"])],
        ["每轮模型调用数", _count(summary["model_calls_mean"], 1, " 次")],
        ["每轮 token 数", _count(summary["token_usage_mean"], 0, " token")],
    ]


def _compare_usage_rows(base: dict, new: dict) -> list[list[str]]:
    return [
        ["每轮工具调用数", _count(base["tool_calls_mean"], 1, " 次"), _count(new["tool_calls_mean"], 1, " 次"),
         _count_change(base["tool_calls_mean"], new["tool_calls_mean"], 1, " 次")],
        ["计算类调用占比", _percent(base["calc_share"]), _percent(new["calc_share"]),
         _rate_change(base["calc_share"], new["calc_share"])],
        ["每轮模型调用数", _count(base["model_calls_mean"], 1, " 次"), _count(new["model_calls_mean"], 1, " 次"),
         _count_change(base["model_calls_mean"], new["model_calls_mean"], 1, " 次")],
        ["每轮 token 数", _count(base["token_usage_mean"], 0, " token"), _count(new["token_usage_mean"], 0, " token"),
         _count_change(base["token_usage_mean"], new["token_usage_mean"], 0, " token")],
    ]


def _stop_table(stop_reasons: dict) -> str:
    ordered = sorted(stop_reasons.items(), key=lambda item: (-item[1], item[0]))
    return _table(["收场原因", "轮数"], [[reason, f"{count} 轮"] for reason, count in ordered],
                  empty="没有收场记录")


def _compare_stop_rows(base: dict, new: dict) -> list[list[str]]:
    def total(reason: str) -> int:
        return base.get(reason, 0) + new.get(reason, 0)

    reasons = sorted(set(base) | set(new), key=lambda reason: (-total(reason), reason))
    return [
        [reason, f"{base.get(reason, 0)} 轮", f"{new.get(reason, 0)} 轮",
         _count_change(base.get(reason, 0), new.get(reason, 0), 0, " 轮")]
        for reason in reasons
    ]


def _failed_table(failed: list[dict]) -> str:
    rows = [
        [item["case_id"], f"第 {item['turn_index'] + 1} 轮", item["status"],
         "、".join(item["failed_checks"]) or "无"]
        for item in failed
    ]
    return _table(["题号", "轮次", "状态", "没过的检查"], rows, empty="没有未通过的题")
