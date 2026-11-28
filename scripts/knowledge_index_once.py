"""Run the knowledge index's write side (app.knowledge.box_index) by hand: some passes, then what came of them.

  # shadow (writes a copy of the vector table, never the live one):
  set -a; . /opt/finbot/ruler.env; set +a; export RULER_DATABASE_URL="$DATABASE_URL" RAG_PGVECTOR_TABLE=chunks_shadow
  python -m scripts.knowledge_index_once --passes 30
  # live backfill (the background loop does the same, two minutes apart):
  set -a; . /opt/finbot/src/.env; set +a; python -m scripts.knowledge_index_once --live --passes 30

Without ``--live`` it refuses unless the shadow environment is loaded (``scripts.wake_replay.refusal``) and the vector table is not the
live ``chunks``.  Stops early when a pass finds nothing to sync and nothing to index.  Prints each pass, then the chunks written, the
embedding tokens the ledger counted for them and their price at OpenRouter's listed rate for baai/bge-m3."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRICE_PER_TOKEN = 0.00000001     # USD, OpenRouter baai/bge-m3 (read from its embeddings model list, 11-28)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="手动跑知识库入库（默认只在影子环境）")
    parser.add_argument("--passes", type=int, default=10)
    parser.add_argument("--live", action="store_true", help="写线上向量库（不加则只许影子环境和非 chunks 表）")
    parser.add_argument("--retry-failed", action="store_true", help="先把因故障用完重试次数的块放回队列")
    args = parser.parse_args(argv)
    if not args.live:
        from scripts.wake_replay import refusal
        reason = refusal()
        if reason:
            print(reason, file=sys.stderr)
            return 2
        if os.environ.get("RAG_PGVECTOR_TABLE", "chunks") == "chunks":
            print("影子环境里要设 RAG_PGVECTOR_TABLE（比如 chunks_shadow），不能写线上的 chunks 表。", file=sys.stderr)
            return 2
    from app import model_usage
    from app.knowledge import box_index
    parts, why = box_index.load_parts()
    if parts is None:
        print("没有跑：" + why, file=sys.stderr)
        return 2
    if args.retry_failed:
        print(f"放回队列 {box_index.retry_failed()} 块", flush=True)
    started = datetime.now(UTC)
    total = 0
    for number in range(1, max(1, args.passes) + 1):
        result = box_index.run_once(parts=parts)
        if result.get("skipped") or result.get("embedding_down"):
            print("这一轮没跑：" + (result.get("skipped") or "向量化服务不可用 " + result["embedding_down"]), flush=True)
            break
        added = sum((v or {}).get("documents") or 0 for v in result["synced"].values())
        new_chunks = sum((v or {}).get("chunks") or 0 for v in result["synced"].values())
        indexed = result["indexed"]
        total += indexed.get("indexed", 0)
        print(f"第 {number} 轮：新文档 {added}（新块 {new_chunks}），入库 {indexed.get('indexed', 0)} 块，失败 {indexed.get('failed', 0)}", flush=True)
        if not added and indexed.get("idle") and not indexed.get("indexed") and not indexed.get("failed"):
            break
    model_usage.flush()
    from sqlalchemy import func, select
    from app.database import SessionLocal
    from app.agent_chat_models import ModelCall
    with SessionLocal() as db:
        tokens, calls = db.execute(select(func.coalesce(func.sum(ModelCall.input_tokens), 0), func.count())
                                   .where(ModelCall.job == "knowledge-index", ModelCall.created_at >= started)).one()
    print(json.dumps({"chunks_written": total, "embedding_calls": calls, "tokens": int(tokens),
                      "usd_at_listed_price": round(int(tokens) * PRICE_PER_TOKEN, 6), "table": parts.store.table}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
