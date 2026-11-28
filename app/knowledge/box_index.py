"""The knowledge index's write side on the box (11-28): sync new sources, chunk them, embed with OpenRouter, write pgvector.

Until 11-13 the index was written on the Mac (local BGE-M3, Milvus).  On the box only the read side was rebuilt (``finbot-rag-slim``:
OpenRouter embeds the query, pgvector's ``chunks`` table answers it), so nothing new reached the index after 11-03.  This module gives
the existing pipeline (``sync_source_batch`` -> ``ingest_documents`` -> ``index_pending``) the three parts it lacked there:

* a tokenizer for chunking: ``tokenizers`` reading bge-m3's own ``tokenizer.json``, the file ``AutoTokenizer`` read, so chunks come
  out as before;
* an embedder: OpenRouter ``baai/bge-m3``, the model the read side embeds queries with, so stored and query vectors agree;
* a vector store: the ``chunks`` table the read side reads, column for column.

No key is copied anywhere: the OpenRouter key and the pgvector login are read from the two files on the box that already hold them
(``RAG_EMBED_ENV_FILE``, ``RAG_PGVECTOR_ENV_FILE``).  When a part is missing (no file, no ``tokenizers``) ``load_parts`` says why and
the loop does nothing, so a checkout, CI and the shadow API are unaffected.  Each embedding call is a row of the model-call ledger
(purpose ``knowledge``, job ``knowledge-index``) with its tokens.
"""
from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

EMBED_URL = "https://openrouter.ai/api/v1/embeddings"
EMBED_MODEL = "baai/bge-m3"          # the read side's model (finbot-rag-slim EMBED_MODEL)
DIMENSIONS = 1024
KINDS = ("faq", "sec", "upload", "analysis", "web")
DEFAULT_TOKENIZER = "/opt/finbot/knowledge/bge-m3-tokenizer.json"
DEFAULT_EMBED_ENV = "/opt/finbot/rag-slim/env"
DEFAULT_PGVECTOR_ENV = "/opt/finbot/pgvector.env"
ATTEMPTS = 3
RETRYABLE = (429, 500, 502, 503, 504)
MAX_CHUNKS = 40                       # per run of the loop (every two minutes): a large 10-K (~600 chunks) is in within half an hour
BATCH = 16                            # chunks per embedding request and per upsert


def read_env_file(path: str) -> dict:
    """KEY=VALUE lines of a file (comments and blank lines skipped).  The values are never logged."""
    values = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if value[:1] in "\"'" and len(value) > 1 and value[-1] == value[0]:
                value = value[1:-1]
            elif " #" in value:
                value = value.split(" #", 1)[0].rstrip()      # an inline comment after an unquoted value
            values[key.strip()] = value
    return values


class FileTokenizer:
    """bge-m3's ``tokenizer.json`` through ``tokenizers``: what chunking counts tokens with (``chunking.Tokenizer``)."""

    def __init__(self, path: str):
        from tokenizers import Tokenizer
        self._tokenizer = Tokenizer.from_file(path)
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()

    def encode(self, text: str, add_special_tokens: bool = True, **_kwargs) -> list[int]:
        return self._tokenizer.encode(text, add_special_tokens=add_special_tokens).ids


class OpenRouterEmbedder:
    """``encode(texts) -> vectors`` (``index_pending``'s embedder), unit length like the vectors already stored."""

    def __init__(self, key: str, *, client=None, url: str = EMBED_URL, model: str = EMBED_MODEL):
        import httpx
        self._key = key
        self._client = client or httpx.Client(timeout=httpx.Timeout(60.0, connect=10.0))
        self._url = url
        self._model = model

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: BLE001
            pass

    def encode(self, texts: list[str]) -> list[list[float]]:
        from .. import model_usage
        began = time.monotonic()
        last = None
        data = None
        for attempt in range(ATTEMPTS):
            if attempt:
                time.sleep(1.0 * attempt)
            try:
                response = self._client.post(self._url, json={"model": self._model, "input": list(texts), "encoding_format": "float"},
                                             headers={"Authorization": "Bearer " + self._key})
            except Exception as exc:  # noqa: BLE001 - the request's own details (the key) never reach the log
                last = RuntimeError(f"embedding_{type(exc).__name__}")
                continue
            if response.status_code in RETRYABLE:
                last = RuntimeError(f"embedding_status_{response.status_code}")
                continue
            if response.status_code >= 400:      # a refused key or request: sending it again changes nothing
                last = RuntimeError(f"embedding_status_{response.status_code}")
                break
            try:
                data = response.json()
            except Exception as exc:  # noqa: BLE001
                last = RuntimeError(f"embedding_{type(exc).__name__}")
                continue
            break
        if data is None:
            model_usage.record(provider="openrouter", model=self._model, ok=False, error=str(last), ms=round((time.monotonic() - began) * 1000))
            raise last or RuntimeError("embedding_failed")
        rows = sorted(data.get("data") or [], key=lambda row: row.get("index", 0))
        vectors = [_unit(row.get("embedding") or []) for row in rows]
        if len(vectors) != len(texts) or any(len(v) != DIMENSIONS for v in vectors):
            model_usage.record(provider="openrouter", model=self._model, ok=False, error="embedding_shape", ms=round((time.monotonic() - began) * 1000))
            raise RuntimeError("embedding_shape")
        usage = data.get("usage") or {}
        model_usage.record(provider="openrouter", model=self._model, ok=True, ms=round((time.monotonic() - began) * 1000),
                           usage={"prompt_tokens": usage.get("prompt_tokens") or usage.get("total_tokens") or 0,
                                  "total_tokens": usage.get("total_tokens") or usage.get("prompt_tokens") or 0})
        return vectors


def _unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)


class PgVectorStore:
    """The read side's ``chunks`` table as ``index_pending``'s vector store (``ensure_collection`` / ``upsert`` / ``get``)."""

    COLUMNS = ("id", "source_hash", "content_hash", "generation", "scope", "visibility", "owner_hash", "symbol", "source_type",
               "available_at", "text")

    def __init__(self, login: dict, *, table: str = "chunks", connect=None):
        if not table.replace("_", "").isalnum():
            raise ValueError("invalid_table")
        self._login = login
        self.table = table
        self._connect = connect

    def connect(self):
        if self._connect is not None:
            return self._connect()
        import psycopg
        return psycopg.connect(host=self._login.get("host", "127.0.0.1"), port=int(self._login.get("port", 55435)),
                               user=self._login["user"], password=self._login["password"], dbname=self._login["dbname"], connect_timeout=5)

    def ensure_collection(self, generation: str) -> None:
        """The table must hold only this generation (the read side refuses a table with two): writing another would break it."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT DISTINCT generation FROM {self.table} LIMIT 2")
            found = {row[0] for row in cur.fetchall()}
        if found - {generation}:
            raise RuntimeError("vector_store_other_generation")

    def upsert(self, rows: list[dict]) -> None:
        if not rows:
            return
        columns = ", ".join((*self.COLUMNS, "embedding"))
        marks = ", ".join(["%s"] * len(self.COLUMNS) + ["%s::vector"])
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in (*self.COLUMNS[1:], "embedding"))
        sql = f"INSERT INTO {self.table} ({columns}) VALUES ({marks}) ON CONFLICT (id) DO UPDATE SET {updates}"
        with self.connect() as conn, conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, [*(row[c] for c in self.COLUMNS), "[" + ",".join(repr(float(x)) for x in row["embedding"]) + "]"])
            conn.commit()

    def get(self, ids: list[str]) -> dict:
        if not ids:
            return {}
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT id, source_hash, content_hash, generation FROM {self.table} WHERE id = ANY(%s)", [list(ids)])
            return {row[0]: {"id": row[0], "source_hash": row[1], "content_hash": row[2], "generation": row[3]} for row in cur.fetchall()}


@dataclass
class Parts:
    tokenizer: FileTokenizer
    embedder: OpenRouterEmbedder
    store: PgVectorStore


def load_parts(environ=os.environ) -> tuple[Parts | None, str | None]:
    """The three parts, or None and why not (a missing file or library: not an error, the box is the only place that has them)."""
    tokenizer_path = environ.get("RAG_TOKENIZER_PATH", DEFAULT_TOKENIZER)
    embed_env = environ.get("RAG_EMBED_ENV_FILE", DEFAULT_EMBED_ENV)
    pg_env = environ.get("RAG_PGVECTOR_ENV_FILE", DEFAULT_PGVECTOR_ENV)
    for path, what in ((tokenizer_path, "tokenizer"), (embed_env, "embedding key file"), (pg_env, "pgvector login file")):
        if not Path(path).is_file():
            return None, f"no {what} at {path}"
    try:
        tokenizer = FileTokenizer(tokenizer_path)
    except ImportError:
        return None, "the tokenizers package is not installed"
    key = read_env_file(embed_env).get("OPENROUTER_API_KEY", "")
    if not key:
        return None, "no OPENROUTER_API_KEY in the embedding key file"
    pg = read_env_file(pg_env)
    login = {"user": pg.get("PGVECTOR_USER", ""), "password": pg.get("PGVECTOR_PASSWORD", ""), "dbname": pg.get("PGVECTOR_DB", ""),
             "port": pg.get("PGVECTOR_PORT", "55435"), "host": pg.get("PGVECTOR_HOST", "127.0.0.1")}
    if not (login["user"] and login["password"] and login["dbname"]):
        return None, "the pgvector login file lacks user, password or database"
    return Parts(tokenizer, OpenRouterEmbedder(key), PgVectorStore(login, table=environ.get("RAG_PGVECTOR_TABLE", "chunks"))), None


def current_generation() -> str:
    from .chunking import CHUNKER_VERSION, FORMAT_VERSION
    from .repository import embedding_generation
    from .settings import MODEL_ID, MODEL_REVISION
    return embedding_generation(MODEL_ID, MODEL_REVISION, FORMAT_VERSION, CHUNKER_VERSION)


def run_once(session_factory=None, parts: Parts | None = None, *, max_chunks: int = MAX_CHUNKS, batch: int = BATCH,
             kinds=KINDS) -> dict:
    """One pass: each source kind syncs one small page into documents and chunks, then up to ``max_chunks`` pending chunks are
    embedded and written.  Returns what happened (the loop logs it)."""
    from .. import model_usage
    from .indexing import index_pending
    from .source_sync import sync_source_batch
    if session_factory is None:
        from ..database import SessionLocal as session_factory
    if parts is None:
        parts, why = load_parts()
        if parts is None:
            return {"skipped": why}
    generation = current_generation()
    try:
        # First: the read side refuses a table with two generations, so nothing is synced for a generation it could not take.
        parts.store.ensure_collection(generation)
    except Exception as exc:  # noqa: BLE001
        return {"skipped": "vector store: " + (str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)}
    synced = {}
    for kind in kinds:
        try:
            result = sync_source_batch(session_factory, parts.tokenizer, generation, source_type=kind, batch_size=5)
            # ``documents`` / ``chunks``: what this page added (an unchanged source is ``skipped``); ``scanned`` is the page itself.
            synced[kind] = {k: result[k] for k in ("scanned", "documents", "chunks", "skipped") if k in result}
        except Exception:  # noqa: BLE001 - one source kind's trouble does not stop the others or the indexing
            log.exception("knowledge sync of %s failed", kind)
            synced[kind] = {"error": True}
    with model_usage.purpose("knowledge", job="knowledge-index"):
        # One word first: while the embedding service is down (or the key refused) a batch would fail and use up its chunks'
        # retries (four, then they stay failed); this pass waits for the next instead.
        if not _has_work(session_factory, generation):
            return {"generation": generation[:8], "synced": synced, "indexed": {"indexed": 0, "failed": 0, "idle": 1}}
        try:
            parts.embedder.encode(["ping"])
        except Exception as exc:  # noqa: BLE001
            return {"generation": generation[:8], "synced": synced, "indexed": {"indexed": 0, "failed": 0, "idle": 0},
                    "embedding_down": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}
        indexed = index_pending(session_factory, parts.embedder, parts.store, generation, max_tasks=max_chunks,
                                worker_id="box-index", batch_size=batch)
    return {"generation": generation[:8], "synced": synced, "indexed": indexed}


def _has_work(session_factory, generation: str) -> bool:
    """Whether a chunk of this generation is waiting to be indexed (what ``claim_task`` would look at)."""
    from datetime import UTC, datetime
    from sqlalchemy import and_, exists, or_, select
    from .models import KnowledgeIndexTask as Task
    now = datetime.now(UTC)
    with session_factory() as session:
        return bool(session.scalar(select(exists().where(Task.generation == generation, or_(
            Task.status == "pending",
            and_(Task.status == "failed", Task.attempts < 4, or_(Task.next_attempt_at.is_(None), Task.next_attempt_at <= now)),
            and_(Task.status == "leased", Task.lease_until <= now))))))


def retry_failed(session_factory=None, generation: str | None = None) -> int:
    """Put the chunks whose indexing failed (an outage that used up their retries) back in the queue; how many."""
    from sqlalchemy import update
    from .models import KnowledgeIndexTask
    if session_factory is None:
        from ..database import SessionLocal as session_factory
    with session_factory() as session, session.begin():
        result = session.execute(update(KnowledgeIndexTask).where(
            KnowledgeIndexTask.generation == (generation or current_generation()), KnowledgeIndexTask.status == "failed",
            KnowledgeIndexTask.error_code == "index_operation_failed").values(status="pending", attempts=0, next_attempt_at=None))
        return result.rowcount or 0


def shadow_writing_live(environ=os.environ) -> bool:
    """The shadow API (database finbot_ruler) about to write the live vector table: its state is not the live one's."""
    import urllib.parse
    database = urllib.parse.urlparse(environ.get("DATABASE_URL", "")).path.lstrip("/")
    return database == "finbot_ruler" and environ.get("RAG_PGVECTOR_TABLE", "chunks") == "chunks"
