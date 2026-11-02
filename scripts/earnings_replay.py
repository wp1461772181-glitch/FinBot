"""Offline replay of one earnings release through the whole Task 9 flow (no network except the model).

Sentinel half: ``sentinel.filings.FilingWatcher`` is run in simulated time over the recorded SEC submissions JSON, once for
every possible poll phase, to get the discovery delay.  API half: ``earnings_monitor`` runs on a throwaway local Postgres
(never the real database, nothing is sent anywhere) with recorded sources: SEC release texts, daily closes and the 1-minute
bars with pre/post-market from Yahoo; only the two model calls are live.

  python scripts/earnings_replay.py --model-file M.json --recorded DIR --accession 0000050863-26-000188 --out DIR2

Needs DATABASE_URL pointing at a scratch database.  ``--model-file`` holds the provider settings (with key) of the model
to use; written by the caller, never printed.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def discovery_delay(recorded: Path, accession: str, symbol: str, out: list[str]) -> dict:
    from sentinel.filings import FilingWatcher, in_earnings_window, parse_earnings_filings, poll_interval
    from sentinel.store import Store
    import tempfile
    submissions = json.loads((recorded / "submissions-INTC.json").read_text())
    filings = parse_earnings_filings(submissions)
    target = next(f for f in filings if f["accession"] == accession)
    previous = next(f for f in filings if f["accepted"] < target["accepted"])
    last = date.fromisoformat(previous["filed"])
    accepted = target["accepted"]
    window = in_earnings_window(accepted, last)
    every = poll_interval(accepted, last)
    out += [f"- 8-K {accession}: SEC acceptanceDateTime {accepted.isoformat()} = 美东 {accepted.astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')):%Y-%m-%d %H:%M:%S %Z}",
            f"- 上次财报日 {last}（{previous['accession']}）→ +91 天 = {last + timedelta(days=91)}；发布日距该日 {(accepted.date() - (last + timedelta(days=91))).days} 天",
            f"- 发布时刻在财报窗口内：{window}；哨兵此时轮询间隔：{every:.0f} 秒"]
    delays = []
    for phase in range(0, int(every), 1):          # the poll grid is every s seconds; the filing lands at an arbitrary point of it
        with tempfile.TemporaryDirectory() as tmp:
            seen, events = {}, []
            clock = [accepted.timestamp() - every + phase]

            def fetch(url):
                if url.endswith("company_tickers.json"):
                    return {"0": {"cik_str": 50863, "ticker": symbol, "title": "INTEL CORP"}}
                visible = [i for i, t in enumerate(submissions["filings"]["recent"]["acceptanceDateTime"])
                           if datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() <= clock[0]]
                return {"filings": {"recent": {k: [v[i] for i in visible] for k, v in submissions["filings"]["recent"].items()}}}

            watcher = FilingWatcher(Store(Path(tmp) / "s.db"), lambda: {"positions": [{"symbol": symbol, "shares": 100}]},
                                    fetch_json=fetch, post_event=lambda t, p: events.append((clock[0], p)),
                                    raise_alert=lambda s, a: 1, sleep=lambda s: None)
            for old in (f for f in filings if f["accepted"] < accepted):   # everything older is already known (seeded)
                watcher.store.add_earnings({"accession": old["accession"], "symbol": symbol, "cik": "0000050863", "held": 1,
                                            "filed": old["filed"], "accepted_at": old["accepted"].timestamp(),
                                            "primary_doc": "", "url": "", "detected_at": old["accepted"].timestamp(), "seeded": 1})
            t = clock[0]
            while not any(p["accession"] == accession for _, p in events) and t < accepted.timestamp() + 3600:
                clock[0] = t
                watcher.poll(t)
                t += 30                                   # the sentinel's filings job ticks every 30 s
            hit = [when for when, p in events if p["accession"] == accession]
            delays.append(hit[0] - accepted.timestamp() if hit else None)
    ok = [d for d in delays if d is not None]
    out += [f"- 模拟：SEC 在受理瞬间即可见（离线无法测 SEC 自身的 JSON 传播延迟）；哨兵 30 秒一拍、每家 {every:.0f} 秒一次、{len(ok)}/{len(delays)} 种轮询相位全部发现",
            f"- 发现延迟（受理 → 哨兵发出事件）：最小 {min(ok):.0f}s、中位 {statistics.median(ok):.0f}s、最大 {max(ok):.0f}s",
            f"- 对比：旧 SEC 监控每小时一次，Task 0 记录的真实滞后约 4.6 小时（16 560 s）；计划验收线 300 s"]
    return {"max": max(ok), "median": statistics.median(ok), "min": min(ok)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recorded", required=True)
    ap.add_argument("--cache", required=True, help="blind-test cache dir with the SEC release pages")
    ap.add_argument("--model-file", required=True)
    ap.add_argument("--accession", default="0000050863-26-000188")
    ap.add_argument("--symbol", default="INTC")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    recorded, cache, out_dir = Path(args.recorded), Path(args.cache), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = ["# 发现延迟（哨兵侧离线回放）", ""]
    delay = discovery_delay(recorded, args.accession, args.symbol, lines)
    (out_dir / "discovery.md").write_text("\n".join(lines) + "\n")

    import re
    from app import earnings_monitor as em
    from app import earnings_reader as er
    from app import agent_telegram as tg
    from app.agent_chat_models import AgentInboxItem, AgentTelegramBind, AgentTelegramMessage, EarningsEvent
    from app.agent_chat_store import owner_hash
    from app.database import Base, SessionLocal, engine
    from app.secret_box import encrypt_secret
    from app.market_data import DailyPrice  # noqa: F401
    from sentinel.filings import parse_earnings_filings

    Base.metadata.create_all(engine)
    tg.ensure_columns()
    owner = owner_hash("replay-owner-" + "x" * 30)
    with SessionLocal() as db:
        for model in (AgentTelegramMessage, AgentInboxItem, EarningsEvent):
            db.query(model).delete()
        if db.get(AgentTelegramBind, owner) is None:
            db.add(AgentTelegramBind(owner_hash=owner, bot_token_cipher=encrypt_secret("123456789:AAH" + "x" * 32), chat_id=1, user_id=1))
        db.commit()

    submissions = json.loads((recorded / "submissions-INTC.json").read_text())
    filings = parse_earnings_filings(submissions)
    target = next(f for f in filings if f["accession"] == args.accession)
    px = json.loads(next(cache.glob(f"px-{args.symbol}-*.json")).read_text())["chart"]["result"][0]
    offset = px["meta"].get("gmtoffset", 0)
    closes = [(datetime.fromtimestamp(t + offset, UTC).date(), float(c)) for t, c in zip(px["timestamp"], px["indicators"]["quote"][0]["close"]) if c is not None]
    y = json.loads((recorded / "yahoo-1m-INTC.json").read_text())["chart"]["result"][0]
    bars = [(datetime.fromtimestamp(t, UTC), c) for t, c in zip(y["timestamp"], y["indicators"]["quote"][0]["close"]) if c is not None]
    from app.sec_filings import _html_text

    class Recorded:
        def earnings_filings(self, symbol, cik):
            return filings

        def release_text(self, symbol, cik, accession):
            page = next(cache.glob(f"doc-{accession}-*"), None)
            return _html_text(page.read_bytes()) if page else None

        def daily_closes(self, symbol):
            return closes

        def extended_move(self, symbol, accepted, until=None):
            return em.move_from_bars(bars, accepted, until)

        def holding_for(self, owner_hash_, symbol):   # the owner's real position (plan-progress.md, Task 6 acceptance)
            price = dict(closes)[target["accepted"].astimezone(em.NY).date()]
            funds = 7688.0
            return {"shares": 100.0, "avg_cost": 23.12, "price": price, "weight_pct": 100 * (100 * price) / (funds + 100 * price),
                    "plan_text": "", "add_price": None, "available_funds": funds}

    class Reader:
        """The real earnings_reader; only the model settings come from a file."""
        READER_VERSION = er.READER_VERSION
        compare, daily_sigma, label_reaction = staticmethod(er.compare), staticmethod(er.daily_sigma), staticmethod(er.label_reaction)
        extract_release, judge = staticmethod(er.extract_release), staticmethod(er.judge)

        def model_for_owner(self, owner_):
            return json.loads(Path(args.model_file).read_text())

    detected = target["accepted"] + timedelta(seconds=delay["max"])
    em.receive_event({"accession": args.accession, "symbol": args.symbol, "cik": "0000050863", "held": True, "url": "https://www.sec.gov/Archives/edgar/data/50863/" + args.accession.replace("-", ""),
                      "accepted_at": target["accepted"].isoformat(), "detected_at": detected.isoformat()}, owner)
    sources, reader = Recorded(), Reader()
    em.tick(detected + timedelta(minutes=3), sources=sources, reader=reader)
    em.tick(target["accepted"] + timedelta(minutes=31), sources=sources, reader=reader)
    with SessionLocal() as db:
        event = db.query(EarningsEvent).one()
        detail, status = event.detail, event.followup_status
        rows = db.query(AgentInboxItem).filter(AgentInboxItem.kind == "filing").order_by(AgentInboxItem.created_at).all()
        bodies = {r.dedupe_key.rsplit(":", 1)[1]: r.body for r in rows}
        pushed = db.query(AgentTelegramMessage).count()
    (out_dir / "first-message.md").write_text(bodies.get("first", "（没有发出）") + "\n")
    follow = bodies.get("followup")
    (out_dir / "followup-message.md").write_text((follow or f"（没有发出：followup_status={status}）") + "\n")
    (out_dir / "judge-detail.json").write_text(json.dumps({"followup_status": status, "telegram_messages_queued": pushed,
                                                           **{k: v for k, v in detail.items() if k in ("followup", "model", "reader_version", "comparison")}},
                                                          ensure_ascii=False, indent=2, default=str))
    print(json.dumps({"discovery_max_s": delay["max"], "followup_status": status, "has_followup": follow is not None,
                      "direction": (detail.get("followup") or {}).get("direction"), "confidence": (detail.get("followup") or {}).get("confidence")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
