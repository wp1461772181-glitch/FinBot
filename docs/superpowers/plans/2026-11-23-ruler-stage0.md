# 尺子（阶段 0）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 做出一套可重复运行的评测工具（尺子）：把一批固定的真实问题发给一个与线上隔离的 FinBot，量出速度、对错和用量，产出旧流程的基线报告。

**Architecture:** 仓库根目录新增独立包 `ruler/`（不放进 `app/`，产品代码不依赖它）。它通过 HTTP 调用 `/agent-chat/stream`，每道题开一段新对话，用确定性的检查判对错，把每轮结果写成 JSONL，再汇总成中文报告。评测跑在盒子上的「影子环境」里：从昨晚的备份恢复出一个影子库，另起一个 API 进程指向它，线上的对话、记忆、提醒都不受影响，而且新旧内核以后可以对着同一份数据比。

**Tech Stack:** Python 标准库（`urllib`、`json`、`dataclasses`、`argparse`、`concurrent.futures`、`unicodedata`）；读审计字段用仓库已有的 SQLAlchemy；测试用 pytest。不新增依赖。

**Spec:** `/Users/wupeng/Monash/monash-ai/projects/market-evidence-agent/docs/finbot-new-kernel-plan-2026-11-22.zh-CN.md`（第二节七条承诺、第十节尺子、第十二节阶段 0）。设计稿没有提交进仓库，按这个绝对路径读。

## 范围

本计划只做阶段 0 里的「尺子 + 基线」。阶段 0 的另一半「好／不好反馈接进题库」要动网页、接口和数据表，是独立的一块，另写计划。

本计划不做：插话和交办的题目（旧流程不支持，阶段 3 连同运行器支持一起加）；用模型当裁判判要点；按模型单价折算成钱（先记 token 数）。

## Global Constraints

- 工作目录是工作树 `/Users/wupeng/Monash/monash-ai/projects/market-evidence-agent/.claude/worktrees/ruler`，分支 `claude/ruler-stage0`。只在这里改文件。
- 测试命令：`/Users/wupeng/Monash/monash-ai/projects/market-evidence-agent/.venv-rag/bin/python -m pytest -q -W ignore <文件>`。
- 不新增第三方依赖。`ruler/` 里除 `run.py` 的 `audit_of` 和 `client.py` 的 `owner_credential` 外，不 import `app`。
- 凭证和密钥只在进程内使用，不打印、不写进结果文件、不进仓库。
- 运行器默认只连 `http://127.0.0.1:9031`（影子 API）。目标端口是 8000（线上）时必须拒绝，除非显式带 `--allow-production`。
- 代码注释和标识符用英文，报告正文用简体中文。代码风格照 `app/agent_wechat.py`（正常排版，不要学 `direct.py` 的紧凑长行）。
- 任务 1 到 4 按顺序一个个做，每个任务由实施者自己提交，只 `git add` 本任务列出的文件，不 push。
- 提交信息格式 `feat(ruler): …`，结尾带 `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`。

## Review Focus

1. **回答流中途断掉**（API 崩了、没有 `done` 事件）：这一轮记为 `incomplete`，整次评测继续跑，不抛异常。→ 任务 2、任务 4 各有测试。
2. **同一个数字的不同写法**：`1,158.44`、`1158.44`、全角 `１１５８．４４`、数字和单位之间有无空格。检查必须都认。→ 任务 1。
3. **误连线上**：`--base` 指向 8000 端口时拒绝运行。→ 任务 4。
4. **题库写错**：未知字段、重复题号、空问题，要报出是哪一题哪个字段，不能静默忽略。→ 任务 1。
5. **审计库连不上**：结果照写，审计字段为空，不崩。→ 任务 4。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `ruler/__init__.py` | 空文件（任务 1 创建） |
| `ruler/cases.py` | 题目的数据结构，读取并校验题库文件 |
| `ruler/checks.py` | 文本归一化；对一条回答执行检查 |
| `ruler/client.py` | 向 API 发一轮问题，边收边计时，整理成结果 |
| `ruler/metrics.py` | 每轮结果的数据结构；汇总成指标 |
| `ruler/report.py` | 把指标渲染成中文 Markdown 报告（单次、对比） |
| `ruler/run.py` | 命令行：跑题库、出报告、做对比；读审计字段 |
| `ruler/suites/baseline-v1.json` | 题库（主控编写，任务 6） |
| `scripts/ruler_shadow.sh` | 在盒子上建立、查看、拆除影子环境（主控编写，任务 5） |
| `tests/test_ruler_cases.py`、`test_ruler_checks.py`、`test_ruler_client.py`、`test_ruler_metrics.py`、`test_ruler_report.py`、`test_ruler_run.py` | 测试 |
| `docs/reports/2026-11-ruler-baseline.md` | 基线报告（任务 7 产出） |

---

### Task 1: 题目结构和检查

**Files:**
- Create: `ruler/__init__.py`（空文件）, `ruler/cases.py`, `ruler/checks.py`
- Test: `tests/test_ruler_cases.py`, `tests/test_ruler_checks.py`

**Interfaces:**
- Produces（任务 4 依赖，名字和类型必须一致）：

```python
# ruler/cases.py
KINDS = ("fact", "brief", "compare", "followup", "recall", "general")

@dataclass(frozen=True)
class Checks:
    status: str = "complete"
    include_any: tuple[tuple[str, ...], ...] = ()   # every group needs at least one alternative present
    exclude: tuple[str, ...] = ()                   # none of these may appear

@dataclass(frozen=True)
class Turn:
    text: str
    checks: Checks

@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    title: str
    turns: tuple[Turn, ...]

class SuiteError(ValueError): ...

def load_suite(path) -> list[Case]: ...

# ruler/checks.py
def normalize(text: str) -> str: ...
def run_checks(checks: Checks, *, answer: str, status: str) -> list[str]: ...
```

- 题库文件格式：

```json
{"version": 1, "cases": [
  {"id": "F01", "kind": "fact", "title": "英伟达最近一季营收",
   "turns": [{"text": "英伟达最近一个季度营收是多少？",
              "checks": {"include_any": [["1158.44", "115.844"]], "exclude": ["没有可核验"]}}]}
]}
```

- [ ] **Step 1: 写 `tests/test_ruler_cases.py`**

```python
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
```

- [ ] **Step 2: 运行，确认失败**（`ModuleNotFoundError: ruler.cases`）
- [ ] **Step 3: 实现 `ruler/cases.py`**。题号格式 `^[A-Z]{1,3}\d{2,3}$`；`kind` 必须在 `KINDS` 里；`title` 非空；`turns` 至少一项；`text` 长度 1 到 4000；`include_any` 的每一组至少一个非空字符串；题目、轮次、检查三层都拒绝未知字段。所有校验错误抛 `SuiteError`，消息里带题号（能取到时）和字段名。JSON 解析失败、文件不存在也转成 `SuiteError`。
- [ ] **Step 4: 运行，确认通过**
- [ ] **Step 5: 写 `tests/test_ruler_checks.py`**

```python
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
    assert run_checks(checks, answer="NVDA 本季营收 1,158.44 亿美元", status="complete") == []

def test_failures_are_named_by_position():
    checks = Checks(include_any=(("1158.44",), ("毛利率",)), exclude=("营收", "不存在"))
    failed = run_checks(checks, answer="本季营收 900 亿", status="complete")
    assert failed == ["include_any[0]", "include_any[1]", "exclude[0]"]

def test_status_mismatch_is_reported_first():
    assert run_checks(Checks(), answer="", status="incomplete") == ["status"]

def test_needles_are_normalized_too():
    assert run_checks(Checks(include_any=(("1,158.44 亿",),)), answer="1158.44亿", status="complete") == []
```

- [ ] **Step 6: 运行，确认失败**
- [ ] **Step 7: 实现 `ruler/checks.py`**。`normalize`：先 `unicodedata.normalize("NFKC", …)`，转小写；去掉「前面是数字、后面恰好跟三位数字」的逗号和空格（千分位），可重复应用；数字与紧随其后的中日韩文字之间的空格去掉；其余连续空白压成一个空格并去掉首尾。`run_checks`：回答和每个待查字符串都先归一化再做子串判断；返回失败项名字的列表，顺序为 `status`、各 `include_any[i]`、各 `exclude[j]`。
- [ ] **Step 8: 运行两个测试文件，确认全部通过**

---

### Task 2: 发问并计时的客户端

**Files:**
- Create: `ruler/client.py`
- Test: `tests/test_ruler_client.py`

**Interfaces:**
- Produces：

```python
@dataclass
class TurnOutcome:
    status: str                  # done 事件的 status；或 "incomplete" / "error" / "http_<code>" / "unreachable"
    reason: str | None
    answer: str
    conversation_id: str | None
    turn_id: str | None
    first_event_ms: int | None   # 第一个不是 conversation 的事件
    first_delta_ms: int | None   # 第一个 text 非空的 delta
    total_ms: int
    tools: list[str]             # 每个 tool_start 的 name，按出现顺序
    thinking_ms: int | None      # done 事件里的 thinking_ms
    error: str | None

def owner_credential() -> str: ...
def ask(base: str, credential: str, text: str, *, catalog_model: str = "",
        conversation_id: str | None = None, timeout: float = 1300, clock=time.monotonic) -> TurnOutcome: ...
```

- 接口事实（已核对 `app/agent_chat_stream.py`）：`POST {base}/agent-chat/stream`，请求头 `X-Chat-Session: <credential>`、`Content-Type: application/json`，请求体 `{"message": text, "catalog_model": catalog_model}`，有 `conversation_id` 时加上。响应是 SSE：每个事件一行 `event: <名字>` 加一行或多行 `data: <json>`，空行结束。事件有 `conversation`（`conversation_id`、`turn_id`）、`status`、`tool_start`（`name`）、`tool_result`、`assistant_tool_request`、`delta`（`text`）、`citations`、`clarification`、`done`（`status`、`reason`、`thinking_ms`）、`error`。HTTP 409 的响应体是 `{"detail": "conversation_busy"}`。
- `owner_credential()`：`from app.agent_chat_identity import _load_config`，取返回值的第 4 项；没有配置时抛 `RuntimeError("no owner credential configured")`。

- [ ] **Step 1: 写 `tests/test_ruler_client.py`**。用标准库 `http.server.ThreadingHTTPServer` 在随机端口起一个假的流式服务（fixture `server`，接受一个「脚本」：若干 `(延迟秒, 原始字节)`，逐段 `wfile.write` 并 `flush`；记录收到的请求体和请求头），测试：

```python
def test_happy_path_collects_answer_ids_tools_and_times(server): ...
    # 脚本：conversation → tool_start(name=query_financials) → tool_start(name=calculate)
    #       → 0.05s → delta("营收 ") → delta("1158") → done(status=complete, thinking_ms=1200)
    # 断言：status=="complete"，answer=="营收 1158"，conversation_id/turn_id 取自 conversation 事件，
    #       tools==["query_financials","calculate"]，thinking_ms==1200，
    #       0 <= first_event_ms <= first_delta_ms <= total_ms，且 first_delta_ms >= 40

def test_request_carries_message_model_conversation_and_credential(server): ...
    # ask(base, "cred-xyz", "问题", catalog_model="haiku-5.5", conversation_id="c1")
    # 断言：请求体 == {"message":"问题","catalog_model":"haiku-5.5","conversation_id":"c1"}；
    #       请求头 X-Chat-Session == "cred-xyz"；不带 conversation_id 时请求体里没有这个键

def test_stream_cut_without_done_is_incomplete(server): ...
    # 脚本：conversation → delta("半句") 然后直接关连接
    # 断言：status=="incomplete"，answer=="半句"，error is None，没有异常

def test_error_event_sets_status_error(server): ...
    # 脚本：conversation → error({"code":"provider_unavailable","message":"x"})
    # 断言：status=="error"，error=="provider_unavailable"

def test_http_409_is_reported_with_detail(server): ...
    # 服务返回 409 和 {"detail":"conversation_busy"}
    # 断言：status=="http_409"，error=="conversation_busy"，total_ms >= 0

def test_unreachable_server(): ...
    # ask("http://127.0.0.1:1", ...)；断言 status=="unreachable"，answer==""

def test_empty_delta_does_not_count_as_first_delta(server): ...
    # 脚本：conversation → delta("") → 0.05s → delta("字") → done
    # 断言：first_delta_ms >= 40

def test_multi_line_data_and_utf8_split_across_chunks(server): ...
    # 一个 delta 的 data 分两行 data: 行；一个汉字的三个字节分在两次写入里
    # 断言：answer 正确，无替换字符

def test_credential_never_appears_in_outcome(server): ...
    # 409 和 error 两种情况下，repr(outcome) 里都没有凭证字符串
```

- [ ] **Step 2: 运行，确认失败**
- [ ] **Step 3: 实现 `ruler/client.py`**。用 `urllib.request`；逐行读响应、用增量 UTF-8 解码器；计时用传入的 `clock`，起点是发请求之前。任何网络异常、解析异常都落到上面定义的某个 `status`，`ask` 不向外抛异常。
- [ ] **Step 4: 运行，确认通过**

---

### Task 3: 指标汇总和报告

**Files:**
- Create: `ruler/metrics.py`, `ruler/report.py`
- Test: `tests/test_ruler_metrics.py`, `tests/test_ruler_report.py`

**Interfaces:**
- Produces：

```python
# ruler/metrics.py
CALC_TOOLS = ("calculate", "calculate_formula")

@dataclass
class TurnResult:
    case_id: str; kind: str; turn_index: int
    passed: bool; failed_checks: list[str]
    status: str; reason: str | None
    first_event_ms: int | None; first_delta_ms: int | None; total_ms: int
    tools: list[str]
    model_calls: int | None; token_usage: int | None; decision_steps: int | None; stop_reason: str | None
    answer_chars: int; answer: str; error: str | None

def to_json(result: TurnResult) -> dict: ...
def from_json(data: dict) -> TurnResult: ...
def percentile(values: list[float], p: float) -> float | None: ...   # nearest-rank；空列表返回 None
def summarize(results: list[TurnResult]) -> dict: ...

# ruler/report.py
def render(summary: dict, *, title: str, meta: dict[str, str]) -> str: ...
def render_comparison(base: dict, new: dict, *, title: str, meta: dict[str, str]) -> str: ...
```

- `summarize` 的返回结构（键名固定，任务 4 和报告都用）：

```python
{"turns": int, "cases": int,
 "pass_rate": float,            # passed 的轮数 / 总轮数
 "failure_rate": float,         # status 不在 ("succeeded", "waiting_for_input", "skipped") 里的轮数 / 总轮数
 "total_ms_p50": float | None, "total_ms_p90": float | None,
 "first_delta_ms_p50": float | None, "first_delta_ms_p90": float | None,
 "first_event_ms_p50": float | None,
 "tool_calls_mean": float,      # 每轮工具调用数的平均
 "calc_share": float,           # 名字在 CALC_TOOLS 里的调用数 / 全部工具调用数；没有调用时 0.0
 "model_calls_mean": float | None, "token_usage_mean": float | None,   # 只在有值的轮次上平均；全为 None 时 None
 "stop_reasons": dict[str, int],          # stop_reason 为 None 的记在 "(none)"
 "by_kind": {kind: {"turns": int, "pass_rate": float, "total_ms_p50": float | None,
                    "total_ms_p90": float | None, "first_delta_ms_p50": float | None,
                    "first_event_ms_p50": float | None}},
 "failed": [{"case_id": str, "turn_index": int, "status": str, "failed_checks": list[str]}]}  # 按输入顺序
```

- 时间类的分位数只在 `status == "succeeded"` 的轮次上算。`status == "skipped"` 的轮次计入 `turns`，在 `pass_rate` 里算没通过，不算进 `failure_rate`，也不进任何时间统计。`cases` 是不同 `case_id` 的个数。

- [ ] **Step 1: 写 `tests/test_ruler_metrics.py`**

```python
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
```

- [ ] **Step 2: 运行，确认失败**；**Step 3: 实现 `ruler/metrics.py`**；**Step 4: 运行，确认通过**
- [ ] **Step 5: 写 `tests/test_ruler_report.py`**

```python
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
```

- [ ] **Step 6: 运行，确认失败**
- [ ] **Step 7: 实现 `ruler/report.py`**。报告结构：一级标题；元信息列表；「七条承诺」表（列：承诺、指标、结果）；「按题型」表；「用量」小节（每轮工具调用数、计算类调用占比、每轮模型调用数、每轮 token 数）；「收场原因」；「没通过的题」。七条承诺各行的内容：

| 承诺 | 指标文字 |
|---|---|
| 回得快 | 出第一个字的中位数和 P90；答完的中位数和 P90 |
| 看得见 | 出现第一个进展的中位数（`first_event_ms_p50`） |
| 可靠 | 检查通过率；失败率（`failure_rate`） |
| 记得准 | `by_kind["recall"]` 的通过率；没有这类题时写「没有这类题」 |
| 懂你 | 固定写「未测（阶段 4 加题）」 |
| 交得出去 | 固定写「未测（阶段 3 加题）」 |
| 能插话 | 固定写「未测（阶段 3 加题）」 |

题型中文名：`fact` 简单事实、`brief` 财报简述、`compare` 多公司比较、`followup` 追问、`recall` 回忆细节、`general` 不查资料。毫秒一律显示成「X.X 秒」；比率显示成不带小数的百分数；`None` 一律显示「无数据」。对比报告同样的表，每个指标三列：基线、新版、变化。时间的变化写「快了 X.X 秒」或「慢了 X.X 秒」；比率的变化写「上升 N 个百分点」或「下降 N 个百分点」；相同写「持平」。
- [ ] **Step 8: 运行两个测试文件，确认通过**

---

### Task 4: 命令行运行器

**Files:**
- Create: `ruler/run.py`
- Modify: `ruler/cases.py`, `ruler/checks.py`, `tests/test_ruler_cases.py`, `tests/test_ruler_checks.py`（Step 0）
- Test: `tests/test_ruler_run.py`

**Interfaces:**
- Consumes：任务 1 的 `Case`、`Turn`、`Checks`、`load_suite`、`run_checks`；任务 2 的 `TurnOutcome`、`ask`、`owner_credential`；任务 3 的 `TurnResult`、`to_json`、`from_json`、`summarize`、`render`、`render_comparison`。
- Produces：

```python
def audit_of(db_url: str | None, conversation_id: str | None) -> dict: ...
def run_case(case: Case, *, ask, audit, catalog_model: str) -> list[TurnResult]: ...
def run_suite(cases: list[Case], *, ask, audit, catalog_model: str, parallel: int) -> list[TurnResult]: ...
def main(argv: list[str]) -> int: ...
```

- `ask` 的调用形式是 `ask(text, catalog_model=..., conversation_id=...) -> TurnOutcome`（`main` 里用 `functools.partial` 把 `base` 和凭证绑进去）；`audit` 的调用形式是 `audit(conversation_id) -> dict`。
- `audit_of`：`db_url` 或 `conversation_id` 为空时返回 `{}`。否则用 SQLAlchemy 执行 `select tool_calls from agent_messages where conversation_id = :cid and role = 'assistant' and tool_calls is not null order by created_at desc limit 1`，把该列按 JSON 解析（已是 dict 就直接用），返回其中的 `audit` 字典；任何异常都返回 `{}`。
- 命令行：

```text
python -m ruler.run run --suite PATH --out DIR [--base http://127.0.0.1:9031] [--model ""] [--parallel 2]
                        [--cases F01,B02] [--allow-production]
python -m ruler.run report  --results DIR --title TEXT --out FILE.md [--meta 键=值 ...]
python -m ruler.run compare --base DIR --new DIR --title TEXT --out FILE.md [--meta 键=值 ...]
```

`run` 写 `DIR/results.jsonl`（每轮一行 `to_json`）和 `DIR/summary.json`。审计库地址读环境变量 `RULER_DATABASE_URL`，没有就不读审计。

- [ ] **Step 0: 把成功状态改成接口真实的叫法（改任务 1 的文件）**。实测 `/agent-chat/stream` 的 `done.status` 成功时是 `"succeeded"`，等用户点确认卡时是 `"waiting_for_input"`，没有 `"complete"`。改动：
  - `ruler/cases.py`：`Checks.status` 的默认值改为 `"succeeded"`。
  - `ruler/checks.py`：`checks.status == "any"` 时不检查状态；其余不变。
  - `tests/test_ruler_cases.py`、`tests/test_ruler_checks.py`：把测试数据里的 `"complete"` 全部改成 `"succeeded"`；在 `test_ruler_checks.py` 里加两条测试：

```python
def test_status_any_accepts_every_status():
    assert run_checks(Checks(status="any"), answer="x", status="waiting_for_input") == []

def test_default_status_is_succeeded():
    assert Checks().status == "succeeded"
    assert run_checks(Checks(), answer="", status="waiting_for_input") == ["status"]
```

  这四个文件也算本任务的文件，一起提交。

- [ ] **Step 1: 写 `tests/test_ruler_run.py`**

```python
import json
from ruler.cases import Case, Checks, Turn
from ruler.client import TurnOutcome
from ruler import run as ruler_run

def outcome(answer="营收 1158.44 亿", status="succeeded", cid="c1", tools=()):
    return TurnOutcome(status, None, answer, cid, "t1", 100, 400, 1000, list(tools), 50, None)

def case(cid="F01", kind="fact", turns=1, needle="1158.44"):
    return Case(cid, kind, "t", tuple(Turn(f"问{i}", Checks(include_any=((needle,),))) for i in range(turns)))

def test_single_turn_passes_and_carries_audit():
    asked = []
    def ask(text, *, catalog_model, conversation_id):
        asked.append((text, catalog_model, conversation_id)); return outcome(tools=["calculate"])
    [res] = ruler_run.run_case(case(), ask=ask, catalog_model="m",
                               audit=lambda cid: {"model_calls": 3, "token_usage": 7000, "decision_steps": 2, "stop_reason": "answered"})
    assert asked == [("问0", "m", None)]
    assert res.passed and res.failed_checks == [] and res.tools == ["calculate"]
    assert (res.model_calls, res.token_usage, res.decision_steps, res.stop_reason) == (3, 7000, 2, "answered")
    assert (res.case_id, res.kind, res.turn_index, res.answer_chars) == ("F01", "fact", 0, len("营收 1158.44 亿"))

def test_later_turns_reuse_the_conversation():
    seen = []
    def ask(text, *, catalog_model, conversation_id):
        seen.append(conversation_id); return outcome(cid="conv-9")
    results = ruler_run.run_case(case(turns=3), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert seen == [None, "conv-9", "conv-9"] and [r.turn_index for r in results] == [0, 1, 2]

def test_failed_turn_skips_the_rest_of_the_case():
    calls = []
    def ask(text, *, catalog_model, conversation_id):
        calls.append(text); return outcome(status="incomplete", answer="")
    results = ruler_run.run_case(case(turns=3), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert calls == ["问0"]
    assert [r.status for r in results] == ["incomplete", "skipped", "skipped"]
    assert not any(r.passed for r in results) and results[0].failed_checks[0] == "status"

def test_waiting_for_input_does_not_stop_the_case():
    statuses = iter(["waiting_for_input", "succeeded"])
    c = Case("R01", "recall", "t", (Turn("记一下", Checks(status="any")), Turn("问", Checks(include_any=(("1158.44",),)))))
    results = ruler_run.run_case(c, audit=lambda cid: {}, catalog_model="", ask=lambda text, **kw: outcome(status=next(statuses)))
    assert [r.status for r in results] == ["waiting_for_input", "succeeded"] and [r.passed for r in results] == [True, True]

def test_wrong_answer_fails_but_next_turn_still_runs():
    answers = iter(["没提到", "营收 1158.44"])
    results = ruler_run.run_case(case(turns=2), audit=lambda cid: {}, catalog_model="",
                                 ask=lambda text, **kw: outcome(answer=next(answers)))
    assert [r.passed for r in results] == [False, True]

def test_audit_failure_leaves_fields_empty():
    def boom(cid): raise RuntimeError("db down")
    [res] = ruler_run.run_case(case(), ask=lambda text, **kw: outcome(), audit=boom, catalog_model="")
    assert res.passed and res.token_usage is None and res.stop_reason is None

def test_ask_raising_is_recorded_not_propagated():
    def ask(text, **kw): raise RuntimeError("boom")
    [res] = ruler_run.run_case(case(), ask=ask, audit=lambda cid: {}, catalog_model="")
    assert res.status == "error" and not res.passed and "RuntimeError" in (res.error or "")

def test_suite_keeps_case_order_when_parallel():
    cases = [case(f"F{n:02d}") for n in range(1, 9)]
    results = ruler_run.run_suite(cases, ask=lambda text, **kw: outcome(), audit=lambda cid: {}, catalog_model="", parallel=4)
    assert [r.case_id for r in results] == [c.id for c in cases]

def test_audit_of_without_database_is_empty():
    assert ruler_run.audit_of(None, "c1") == {} and ruler_run.audit_of("postgresql://x", None) == {}
    assert ruler_run.audit_of("postgresql+psycopg://nobody@127.0.0.1:1/none", "c1") == {}

def _suite(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"version": 1, "cases": [
        {"id": "F01", "kind": "fact", "title": "t", "turns": [{"text": "q", "checks": {"include_any": [["1158.44"]]}}]},
        {"id": "F02", "kind": "fact", "title": "t", "turns": [{"text": "q"}]}]}), encoding="utf-8")
    return path

def test_run_refuses_production_port(tmp_path, capsys):
    code = ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--base", "http://127.0.0.1:8000"])
    assert code == 2 and "8000" in capsys.readouterr().err and not (tmp_path / "o" / "results.jsonl").exists()

def test_run_writes_results_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome())
    out = tmp_path / "o"
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(out), "--cases", "F01"]) == 0
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [row["case_id"] for row in rows] == ["F01"] and "cred" not in (out / "results.jsonl").read_text()
    assert json.loads((out / "summary.json").read_text())["pass_rate"] == 1.0

def test_run_exits_2_when_api_is_down(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: False)
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o")]) == 2

def test_unknown_case_filter_is_an_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    assert ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / "o"), "--cases", "Z99"]) == 2
    assert "Z99" in capsys.readouterr().err

def test_report_and_compare_write_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(ruler_run, "owner_credential", lambda: "cred")
    monkeypatch.setattr(ruler_run, "api_alive", lambda base: True)
    monkeypatch.setattr(ruler_run, "ask", lambda base, cred, text, **kw: outcome())
    for name in ("a", "b"):
        ruler_run.main(["run", "--suite", str(_suite(tmp_path)), "--out", str(tmp_path / name)])
    assert ruler_run.main(["report", "--results", str(tmp_path / "a"), "--title", "基线", "--out", str(tmp_path / "r.md"), "--meta", "模型=haiku"]) == 0
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# 基线") and "haiku" in (tmp_path / "r.md").read_text(encoding="utf-8")
    assert ruler_run.main(["compare", "--base", str(tmp_path / "a"), "--new", str(tmp_path / "b"), "--title", "对比", "--out", str(tmp_path / "c.md")]) == 0
    assert "持平" in (tmp_path / "c.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: 运行，确认失败**
- [ ] **Step 3: 实现 `ruler/run.py`**。模块顶层 `from ruler.client import ask, owner_credential`，并定义 `api_alive(base) -> bool`（`GET {base}/health`，5 秒超时，200 为真；测试会替换这三个名字）。`run_case` 里 `ask` 或 `audit` 抛异常都要接住：`ask` 抛的记成 `status="error"`、`error="<异常类名>: <消息前 200 字>"`；`audit` 抛的当成 `{}`。一轮的 `status` 不在 `("succeeded", "waiting_for_input")` 里时（流断了、出错、连不上），本题后面的轮次不再发问，各记一条 `status="skipped"`、`passed=False`、`failed_checks=["skipped"]`、`total_ms=0`。`run_suite` 用线程池按题并行，输出按题库顺序。`main` 的退出码：正常 0；端口 8000 且没带 `--allow-production`、API 探活失败、`--cases` 里有不存在的题号、题库加载失败，都返回 2 并把原因写到标准错误。
- [ ] **Step 4: 运行 `tests/test_ruler_run.py`，再运行全部 `tests/test_ruler_*.py`，确认通过**

---

### Task 5（主控）: 影子环境

**Files:**
- Create: `scripts/ruler_shadow.sh`；Modify: `deployment/heibao/README.md`（加一节）

在盒子上执行的脚本，三个子命令：

- `up`：在 `finbot-postgres` 容器里把最新的 `/opt/finbot/backups/db/finbot-*.dump` 恢复进库 `finbot_ruler`（已存在则先删再建；脚本里库名写死，且只允许操作以 `finbot_ruler` 开头的库名）；用 `systemd-run --unit=finbot-ruler-api` 起第二个 API 进程，端口 9031，环境与线上相同但 `DATABASE_URL` 指向 `finbot_ruler`、`BACKGROUND_LOOPS=false`，`MemoryMax=600M`；等 `/health` 返回 200。启动前检查可用内存不少于 800 MB，不够就拒绝。
- `status`：影子库是否存在、来自哪份备份、影子 API 是否在跑。
- `down`：停掉 `finbot-ruler-api`，删除 `finbot_ruler` 库。

- [ ] 写脚本；在盒子上 `up`，确认 `curl 127.0.0.1:9031/health` 正常、线上四个服务仍然 active、线上库的会话数没有变化。
- [ ] 用一道题手动跑通：`python -m ruler.run run --suite <单题文件> --out /tmp/ruler-smoke`，确认结果行里有计时、工具列表和审计字段。

### Task 6（主控）: 题库

**Files:**
- Create: `ruler/suites/baseline-v1.json`

六十道题，题型配比：简单事实 15、财报简述 10、多公司比较 10、追问 10（每题 2 轮）、回忆细节 8（每题 3 轮：先说出一个细节，中间隔一轮别的问题，再问回来）、不查资料 7。

- [ ] 从线上库取 owner 真实问过的问题作底稿，只留涉及公开公司的问题；持仓金额、个人计划等个人信息不进题库（仓库是公开的）。
- [ ] 每道题的应有数字从影子库里查出并写进 `include_any`，写上等价写法（例如 `1158.44` 亿和 `115.844` 十亿）。财报简述题至少检查公司、期间、营收三项。
- [ ] `python -c "from ruler.cases import load_suite; print(len(load_suite('ruler/suites/baseline-v1.json')))"` 输出 60。

### Task 7（主控）: 跑基线，出报告

- [ ] 在影子环境上跑全量：`--parallel 2`，模型用模型目录的默认项；记录代码版本、备份文件名、模型名。
- [ ] 抽查 10 条没通过的题：是回答真的错了，还是检查写得太严。检查写错的改题库后只重跑那几题（`--cases`）。
- [ ] `python -m ruler.run report … --out docs/reports/2026-11-ruler-baseline.md`；报告末尾手写一段「怎么读这份基线」和已知局限（外部搜索结果会变、单次运行有波动）。
- [ ] `scripts/ruler_shadow.sh down`；全量 pytest；提 PR；CI 通过后合并。合并不需要发布：`ruler/` 不被线上服务加载。

## Self-Review 记录

- 设计稿 10.1「内容」：题型里的「插话、交办」本计划明确不做，报告里对应行写「未测（阶段 3 加题）」。其余五类加「不查资料」已覆盖。
- 设计稿 10.1「量什么」：七条承诺各有一行；「每轮花费」本计划用 token 数代替，没有折算成钱。
- 设计稿 10.1「怎么用」：`compare` 子命令和影子库快照支持以后新旧对比。新内核按 bot 切换，而尺子走的是不带 bot 的入口，阶段 1 需要给尺子一个选择内核的办法，这一点留给阶段 1 的计划。
- 接口名核对：`TurnOutcome`、`TurnResult`、`Checks`、`run_checks`、`summarize`、`render`、`render_comparison`、`ask`、`audit_of`、`api_alive` 在各任务中写法一致。
