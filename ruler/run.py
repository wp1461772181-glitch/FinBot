"""Command-line runner for ruler: ask every case, check the answers, write results and reports.

Also `ask`: put a few questions to one running API by hand, for checks on the box.
"""

import argparse
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from ruler.cases import Case, SuiteError, load_suite
from ruler.checks import run_checks
from ruler.client import ask, owner_credential
from ruler.metrics import TurnResult, from_json, summarize, to_json
from ruler.report import render, render_comparison

DEFAULT_BASE = "http://127.0.0.1:9031"
PRODUCTION_PORT = 8000
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_NORMAL_STATUSES = ("succeeded", "waiting_for_input")
_DB_ENV = "RULER_DATABASE_URL"
_DB_CONNECT_TIMEOUT_SECONDS = 3
_ERROR_MESSAGE_CHARS = 200
_AUDIT_SQL = (
    "select tool_calls from agent_messages "
    "where conversation_id = :cid and role = 'assistant' and tool_calls is not null "
    "order by created_at desc limit 1"
)


def api_alive(base: str) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{base.rstrip('/')}/health", timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def audit_of(db_url: str | None, conversation_id: str | None) -> dict:
    """Read the audit dict of the conversation's latest assistant message; {} on any failure."""
    if not db_url or not conversation_id:
        return {}
    engine = None
    try:
        # Imported here so that importing ruler.run stays light.
        from sqlalchemy import create_engine, text

        engine = create_engine(db_url, connect_args={"connect_timeout": _DB_CONNECT_TIMEOUT_SECONDS})
        with engine.connect() as connection:
            row = connection.execute(text(_AUDIT_SQL), {"cid": conversation_id}).first()
        if row is None:
            return {}
        tool_calls = row[0]
        if isinstance(tool_calls, (str, bytes)):
            tool_calls = json.loads(tool_calls)
        audit = tool_calls.get("audit") if isinstance(tool_calls, dict) else None
        return audit if isinstance(audit, dict) else {}
    except Exception:
        return {}
    finally:
        if engine is not None:
            engine.dispose()


def run_case(case: Case, *, ask, audit, catalog_model: str) -> list[TurnResult]:
    """Ask the turns of one case in order; after a failed turn the rest are recorded as skipped."""
    results: list[TurnResult] = []
    conversation_id = None
    stopped = False
    for index, turn in enumerate(case.turns):
        if stopped:
            results.append(_skipped(case, index))
            continue
        try:
            outcome = ask(turn.text, catalog_model=catalog_model, conversation_id=conversation_id)
        except Exception as exc:
            message = f"{type(exc).__name__}: {str(exc)[:_ERROR_MESSAGE_CHARS]}"
            results.append(_result(case, index, turn, "error", None, "", [], None, None, 0, message, {}))
            stopped = True
            continue
        conversation_id = outcome.conversation_id or conversation_id
        try:
            audit_fields = audit(outcome.conversation_id) or {}
        except Exception:
            audit_fields = {}
        results.append(_result(
            case, index, turn, outcome.status, outcome.reason, outcome.answer, outcome.tools,
            outcome.first_event_ms, outcome.first_delta_ms, outcome.total_ms, outcome.error, audit_fields,
        ))
        stopped = outcome.status not in _NORMAL_STATUSES
    return results


def _result(case, index, turn, status, reason, answer, tools, first_event_ms, first_delta_ms, total_ms,
            error, audit_fields) -> TurnResult:
    failed = run_checks(turn.checks, answer=answer, status=status)
    # Checks(status="any") tolerates waiting_for_input, but a hard failure must never count as passed.
    if status not in _NORMAL_STATUSES and "status" not in failed:
        failed.append("status")
    return TurnResult(
        case_id=case.id, kind=case.kind, turn_index=index, passed=not failed, failed_checks=failed,
        status=status, reason=reason, first_event_ms=first_event_ms, first_delta_ms=first_delta_ms,
        total_ms=total_ms, tools=list(tools),
        model_calls=audit_fields.get("model_calls"), token_usage=audit_fields.get("token_usage"),
        decision_steps=audit_fields.get("decision_steps"), stop_reason=audit_fields.get("stop_reason"),
        answer_chars=len(answer), answer=answer, error=error,
    )


def _skipped(case: Case, index: int) -> TurnResult:
    return TurnResult(
        case_id=case.id, kind=case.kind, turn_index=index, passed=False, failed_checks=["skipped"],
        status="skipped", reason=None, first_event_ms=None, first_delta_ms=None, total_ms=0, tools=[],
        model_calls=None, token_usage=None, decision_steps=None, stop_reason=None,
        answer_chars=0, answer="", error=None,
    )


def run_suite(cases: list[Case], *, ask, audit, catalog_model: str, parallel: int) -> list[TurnResult]:
    """Run the cases in parallel; the results keep the order of the question bank."""
    work = functools.partial(run_case, ask=ask, audit=audit, catalog_model=catalog_model)
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        per_case = list(pool.map(work, cases))
    return [result for case_results in per_case for result in case_results]


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _production_guard(base: str) -> str | None:
    """Why this base must not be asked without --allow-production, or None when it may."""
    try:
        parsed = urlparse(base)
        host, port = parsed.hostname, parsed.port
    except ValueError:
        return f"--base 无法解析: {base}"
    if not host:
        return f"--base 里没有主机名: {base}"
    if host not in _LOCAL_HOSTS:
        return f"拒绝对非本机主机 {host} 发问；确需如此请加 --allow-production"
    if port == PRODUCTION_PORT:
        return f"拒绝对生产端口 {PRODUCTION_PORT} 发问；确需如此请加 --allow-production"
    return None


def _command_run(args) -> int:
    if not args.allow_production:
        problem = _production_guard(args.base)
        if problem:
            return _fail(problem)
    try:
        cases = load_suite(args.suite)
    except SuiteError as exc:
        return _fail(str(exc))
    if args.cases:
        wanted = [name.strip() for name in args.cases.split(",") if name.strip()]
        if not wanted:
            return _fail(f"--cases 里没有题号: {args.cases!r}")
        unknown = [name for name in wanted if name not in {case.id for case in cases}]
        if unknown:
            return _fail(f"题库里没有这些题号: {', '.join(unknown)}")
        cases = [case for case in cases if case.id in wanted]
    try:
        credential = owner_credential()
    except Exception as exc:
        return _fail(f"取不到 owner 凭证: {type(exc).__name__}")
    if not api_alive(args.base):
        return _fail(f"API 探活失败: {args.base}")

    db_url = os.environ.get(_DB_ENV)
    started = datetime.now(UTC)
    results = run_suite(
        cases,
        ask=functools.partial(ask_through, args.base, credential),
        audit=functools.partial(audit_of, db_url),
        catalog_model=args.model,
        parallel=args.parallel,
    )
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(to_json(result), ensure_ascii=False) for result in results]
    (out / "results.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(
        json.dumps(summarize(results), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # what this run was, for the backstage's 质量 tab (5d-3b): the summary alone does not say which suite, model or code it measured
    meta = {"started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat(), "suite": args.suite, "cases": len(cases),
            "base": args.base, "model": args.model, "parallel": args.parallel, "note": args.note}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    passed = sum(result.passed for result in results)
    print(f"{passed}/{len(results)} 轮通过，结果写在 {out}")
    return 0


def ask_through(base: str, credential: str, text: str, **kwargs):
    # Looked up at call time so that the module-level name can be replaced in tests.
    return ask(base, credential, text, **kwargs)


def server_process(base: str) -> tuple[int, str] | None:
    """The process listening on the base's port and its working directory, or None when that cannot be found.

    Which code is under test is decided by the server on the port, not by the directory this tool
    happens to be run from, so the answer is read from the listening process itself.
    """
    try:
        port = urlparse(base).port
    except ValueError:
        return None
    if not port:
        return None
    try:
        if Path("/proc/self").exists() and shutil.which("ss"):
            listing = subprocess.run(["ss", "-H", "-ltnp", f"sport = :{port}"],
                                     capture_output=True, text=True, timeout=5).stdout
            match = re.search(r"pid=(\d+)", listing)
            if not match:
                return None
            pid = int(match.group(1))
            return pid, os.readlink(f"/proc/{pid}/cwd")
        if shutil.which("lsof"):
            listing = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                     capture_output=True, text=True, timeout=5).stdout.split()
            if not listing:
                return None
            pid = int(listing[0])
            fields = subprocess.run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                                    capture_output=True, text=True, timeout=5).stdout.splitlines()
            directory = next((field[1:] for field in fields if field.startswith("n")), None)
            return (pid, directory) if directory else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _seconds(milliseconds: int | None) -> str:
    return "无" if milliseconds is None else f"{milliseconds / 1000:.1f} 秒"


def _command_ask(args) -> int:
    """Ask a few questions by hand and print the answers, after naming the code that will answer them."""
    if not args.allow_production:
        problem = _production_guard(args.base)
        if problem:
            return _fail(problem)
    if not api_alive(args.base):
        return _fail(f"API 探活失败: {args.base}")
    here = Path.cwd().resolve()
    expected = Path(args.server_dir).resolve() if args.server_dir else here
    print(f"本工具运行在：{here}")
    found = server_process(args.base)
    if found is None:
        print("查不到端口上的服务进程，无法确认被测的是哪份代码（可能需要 root，或本机没有 ss / lsof）。")
    else:
        pid, directory = found
        print(f"被测服务：进程 {pid}，工作目录 {directory}")
        if Path(directory).resolve() != expected:
            return _fail(
                f"被测服务的工作目录是 {directory}，不是 {expected}。"
                "请到被测的那份代码目录里运行，或用 --server-dir 写明预期的目录。"
            )
    try:
        credential = owner_credential()
    except Exception as exc:
        return _fail(f"取不到 owner 凭证: {type(exc).__name__}")

    conversation_id = None
    all_normal = True
    for index, text in enumerate(args.texts, 1):
        outcome = ask_through(args.base, credential, text,
                              catalog_model=args.model, conversation_id=conversation_id)
        conversation_id = outcome.conversation_id or conversation_id
        all_normal = all_normal and outcome.status in _NORMAL_STATUSES
        detail = f"状态 {outcome.status}"
        if outcome.reason:
            detail += f"（{outcome.reason}）"
        if outcome.error:
            detail += f" · 错误 {outcome.error[:_ERROR_MESSAGE_CHARS]}"
        detail += f" · 首字 {_seconds(outcome.first_delta_ms)} · 总计 {_seconds(outcome.total_ms)}"
        if outcome.tools:
            detail += f" · 工具 {', '.join(outcome.tools)}"
        print(f"\n[{index}] 问：{text}\n    {detail}\n    答：{outcome.answer or '（空）'}")
        if getattr(args, "audit", False) and outcome.turn_id:
            print(f"    账：{turn_audit_line(outcome.turn_id)}")
    return 0 if all_normal else 1


def turn_audit_line(turn_id: str) -> str:
    """One line from the stored answer's audit: the turn's tier, each model call's tier and time, the lookup tries."""
    try:
        audit = stored_audit(turn_id)
    except Exception as exc:
        return f"读不到（{type(exc).__name__}）"
    if not audit:
        return "这一轮没有存下账"
    calls = audit.get("calls") or []
    parts = [f"档位 {audit.get('tier') or '?'}", f"模型调用 {len(calls)} 次"]
    if calls:
        parts.append("、".join(f"{c.get('tier')} {c.get('ms', 0) / 1000:.1f}s" + ("（丢弃）" if c.get("kept") is False else "") for c in calls))
    if audit.get("lookup_steps") or audit.get("lookup_redone"):
        parts.append(f"低档查资料 {audit.get('lookup_steps', 0)} 步、试跑丢弃 {audit.get('lookup_redone', 0)} 次")
    return " · ".join(parts)


def stored_audit(turn_id: str) -> dict | None:
    """The audit of the turn's stored answer (the assistant row's protocol), read from the database the environment names."""
    import uuid
    from sqlalchemy import select
    from app.agent_chat_models import AgentMessage
    from app.database import SessionLocal
    with SessionLocal() as db:
        rows = db.scalars(select(AgentMessage.tool_calls).where(AgentMessage.turn_id == uuid.UUID(turn_id), AgentMessage.role == "assistant"))
        for protocol in rows:
            if isinstance(protocol, dict) and isinstance(protocol.get("audit"), dict):
                return protocol["audit"]
    return None


def _load_summary(directory) -> dict:
    path = Path(directory) / "results.jsonl"
    # Split on "\n" only: str.splitlines() also breaks on U+2028, U+2029 and U+0085, which may occur in an answer.
    lines = path.read_text(encoding="utf-8").split("\n")
    return summarize([from_json(json.loads(line)) for line in lines if line.strip()])


def _parse_meta(pairs: list[str]) -> dict[str, str]:
    meta = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator:
            raise ValueError(f"--meta 要写成 名称=值，收到: {pair}")
        meta[key] = value
    return meta


def _command_report(args) -> int:
    try:
        meta = _parse_meta(args.meta)
    except ValueError as exc:
        return _fail(str(exc))
    try:
        summary = _load_summary(args.results)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _fail(f"读不了结果 {Path(args.results) / 'results.jsonl'}: {exc}")
    Path(args.out).write_text(render(summary, title=args.title, meta=meta), encoding="utf-8")
    return 0


def _command_compare(args) -> int:
    try:
        meta = _parse_meta(args.meta)
    except ValueError as exc:
        return _fail(str(exc))
    summaries = []
    for directory in (args.base, args.new):
        try:
            summaries.append(_load_summary(directory))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return _fail(f"读不了结果 {Path(directory) / 'results.jsonl'}: {exc}")
    text = render_comparison(summaries[0], summaries[1], title=args.title, meta=meta)
    Path(args.out).write_text(text, encoding="utf-8")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ruler.run")
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="ask every case and write results")
    run.add_argument("--suite", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--base", default=DEFAULT_BASE)
    run.add_argument("--model", default="")
    run.add_argument("--parallel", type=int, default=2)
    run.add_argument("--cases", default="")
    run.add_argument("--allow-production", action="store_true")
    run.add_argument("--note", default="", help="一句说明，比如被测的提交号；写进 meta.json，后台「质量」栏显示")

    report = commands.add_parser("report", help="render one run as Markdown")
    report.add_argument("--results", required=True)
    report.add_argument("--title", required=True)
    report.add_argument("--out", required=True)
    report.add_argument("--meta", action="append", default=[], help="名称=值，可重复")

    compare = commands.add_parser("compare", help="render two runs side by side")
    compare.add_argument("--base", required=True)
    compare.add_argument("--new", required=True)
    compare.add_argument("--title", required=True)
    compare.add_argument("--out", required=True)
    compare.add_argument("--meta", action="append", default=[], help="名称=值，可重复")

    ask_cmd = commands.add_parser("ask", help="ask a few questions by hand and print the answers")
    ask_cmd.add_argument("texts", nargs="+", help="一句或多句，多句在同一个对话里依次发")
    ask_cmd.add_argument("--base", default=DEFAULT_BASE)
    ask_cmd.add_argument("--model", default="")
    ask_cmd.add_argument("--server-dir", default="", help="被测服务应当所在的目录；默认是当前目录")
    ask_cmd.add_argument("--allow-production", action="store_true")
    ask_cmd.add_argument("--audit", action="store_true", help="每轮答完后，从库里读出这一轮每次模型调用的档位和耗时")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    handlers = {"run": _command_run, "report": _command_report, "compare": _command_compare,
                "ask": _command_ask}
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
