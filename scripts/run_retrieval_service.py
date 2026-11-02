#!/usr/bin/env python3
"""Mac-side retrieval service (BGE-M3, reranker, Milvus, index builder).

POST /retrieve, POST /rerank, GET /health; every call needs X-Retrieval-Token
(= RAG_REMOTE_TOKEN). The API on Muse sets RAG_REMOTE_URL and never loads torch.
This process owns indexing: keep RAG_INDEXING_ENABLED=true only here.

  RAG_ENABLED=true RAG_REMOTE_TOKEN=... python scripts/run_retrieval_service.py [--port 8765]
"""
from __future__ import annotations

import argparse
import hmac
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Header, HTTPException  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

TOKEN = os.getenv("RAG_REMOTE_TOKEN", "")


class RetrieveRequest(BaseModel):
    strategy: str = Field(pattern="^(dense|bm25|hybrid|hybrid_rerank)$")
    query: str | None = None
    filter: str
    limit: int = Field(default=50, ge=1, le=50)
    generation: str | None = None
    owner_hash: str | None = None
    cutoff: str | None = None


class RerankRequest(BaseModel):
    query: str
    passages: list[str] = Field(max_length=50)


def check_token(value: str | None) -> None:
    if not TOKEN or not value or not hmac.compare_digest(value, TOKEN):
        raise HTTPException(401, "bad_token")


def check_scope(filter_expr: str, owner_hash: str | None) -> None:
    """The filter is built by the API; refuse one whose private scope differs from the declared owner."""
    owners = set(re.findall(r'owner_hash == "([^"]*)"', filter_expr))
    if owner_hash is None and ('scope == "private"' in filter_expr or owners):
        raise HTTPException(403, "scope_mismatch")
    if owner_hash is not None and owners - {owner_hash}:
        raise HTTPException(403, "scope_mismatch")


def build_app() -> FastAPI:
    from app.knowledge import runtime as rt

    @asynccontextmanager
    async def lifespan(_app):
        if not TOKEN:
            raise RuntimeError("RAG_REMOTE_TOKEN must be set")
        if os.getenv("RAG_REMOTE_URL"):
            raise RuntimeError("RAG_REMOTE_URL must not be set on the retrieval service")
        from app.database import SessionLocal
        from app.knowledge.source_sync import start_source_sync, stop_source_sync

        rt.start_runtime_background()
        start_source_sync(SessionLocal)
        try:
            yield
        finally:
            stop_source_sync()
            rt.stop_runtime()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health(x_retrieval_token: str | None = Header(default=None)):
        check_token(x_retrieval_token)
        runtime = rt.get_runtime()
        if runtime is None:
            raise HTTPException(503, "runtime_not_ready")
        return {**runtime.health(), "threshold": runtime.threshold}

    @app.post("/retrieve")
    async def retrieve(body: RetrieveRequest, x_retrieval_token: str | None = Header(default=None)):
        check_token(x_retrieval_token)
        check_scope(body.filter, body.owner_hash)
        runtime = rt.get_runtime()
        if runtime is None:
            raise HTTPException(503, "runtime_not_ready")
        if body.generation and body.generation != runtime.settings.generation:
            raise HTTPException(409, "generation_mismatch")
        if body.strategy != "dense" and not body.query:
            raise HTTPException(422, "query_required")
        hits = await runtime.search_strategy(body.strategy, body.query or "", body.filter, body.limit)
        return {"hits": [{"id": str(h["id"]), "distance": float(h.get("distance", 0.0))} for h in hits]}

    @app.post("/rerank")
    async def rerank(body: RerankRequest, x_retrieval_token: str | None = Header(default=None)):
        check_token(x_retrieval_token)
        runtime = rt.get_runtime()
        if runtime is None:
            raise HTTPException(503, "runtime_not_ready")
        pairs = await runtime.rerank(body.query, body.passages)
        return {"pairs": [[int(i), float(s)] for i, s in pairs]}

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")  # reachable over the tailnet; the token guards it
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    uvicorn.run(build_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
