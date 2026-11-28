"""The knowledge index's write side on the box (app.knowledge.box_index).  No network, no pgvector: the HTTP client and the
connection are stand-ins; the chunking and index tasks are the real ones on the test database."""
import json
import math
from pathlib import Path

import pytest

from app.knowledge import box_index

TOKENIZER = Path(__file__).resolve().parents[1] / "data/knowledge/models/bge-m3/tokenizer.json"


# --- the tokenizer: the same counts as the AutoTokenizer the Mac-side index used --------------------------------------------------

@pytest.mark.skipif(not TOKENIZER.is_file(), reason="bge-m3's tokenizer.json is only on the maintainer's machine and the box")
def test_the_file_tokenizer_counts_like_the_transformers_one():
    transformers = pytest.importorskip("transformers")
    mine = box_index.FileTokenizer(str(TOKENIZER))
    theirs = transformers.AutoTokenizer.from_pretrained(str(TOKENIZER.parent), local_files_only=True)
    for text in ("Revenue was $114.8 billion, up 12% year over year.", "苹果第四季度营收 1,144.77 亿美元，同比增长约 11.7%。",
                 "Item 1A. Risk Factors\n\nThe Company's business is subject to " * 40):
        assert mine.encode(text, add_special_tokens=True) == theirs.encode(text, add_special_tokens=True)


# --- the embedder ---------------------------------------------------------------------------------------------------------------

class Response:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http %s" % self.status_code)


class Client:
    def __init__(self, *responses):
        self.responses, self.sent = list(responses), []

    def post(self, url, json=None, headers=None):
        self.sent.append({"url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


def vector(scale=2.0):
    return [scale] + [0.0] * (box_index.DIMENSIONS - 1)


@pytest.fixture
def ledger(monkeypatch):
    from app import model_usage
    rows = []
    monkeypatch.setattr(model_usage, "record", lambda **kw: rows.append(kw))
    monkeypatch.setattr(box_index.time, "sleep", lambda s: None)
    return rows


def test_the_embedder_sends_one_batch_returns_unit_vectors_in_order_and_records_the_tokens(ledger):
    body = {"data": [{"index": 1, "embedding": vector(3.0)}, {"index": 0, "embedding": vector(2.0)}], "usage": {"prompt_tokens": 42, "total_tokens": 42}}
    client = Client(Response(200, body))
    vectors = box_index.OpenRouterEmbedder("sk-test", client=client).encode(["a", "b"])
    assert [math.isclose(sum(x * x for x in v), 1.0) for v in vectors] == [True, True]
    (sent,) = client.sent
    assert sent["url"] == box_index.EMBED_URL and sent["json"] == {"model": "baai/bge-m3", "input": ["a", "b"], "encoding_format": "float"}
    assert sent["headers"] == {"Authorization": "Bearer sk-test"}
    assert ledger[0]["ok"] is True and ledger[0]["provider"] == "openrouter" and ledger[0]["usage"]["prompt_tokens"] == 42


def test_the_embedder_retries_a_busy_upstream_and_never_logs_the_key(ledger):
    client = Client(Response(503), Response(200, {"data": [{"index": 0, "embedding": vector()}], "usage": {"total_tokens": 3}}))
    assert len(box_index.OpenRouterEmbedder("sk-test", client=client).encode(["a"])) == 1
    assert len(client.sent) == 2
    failing = Client(Response(500), Response(500), Response(500))
    with pytest.raises(RuntimeError) as failed:
        box_index.OpenRouterEmbedder("sk-secret", client=failing).encode(["a"])
    assert "sk-secret" not in str(failed.value) and ledger[-1]["ok"] is False and "sk-secret" not in json.dumps(ledger)


def test_a_reply_of_the_wrong_shape_is_refused(ledger):
    client = Client(Response(200, {"data": [{"index": 0, "embedding": [1.0, 2.0]}]}))
    with pytest.raises(RuntimeError, match="embedding_shape"):
        box_index.OpenRouterEmbedder("k", client=client).encode(["a"])


# --- the vector store -----------------------------------------------------------------------------------------------------------

class Cursor:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.db.executed.append((sql, params))
        self.rows = self.db.answers.pop(0) if self.db.answers else []

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commits += 1


class DB:
    def __init__(self, *answers):
        self.answers, self.executed, self.commits = list(answers), [], 0

    def connect(self):
        return Connection(self)


def row(i="c1"):
    return {"id": i, "source_hash": "s", "content_hash": "h", "generation": "g", "scope": "public", "visibility": "public", "owner_hash": "",
            "symbol": "AAPL", "source_type": "official_filing", "available_at": 1, "text": "Revenue", "embedding": [0.5, 0.5]}


def test_the_store_refuses_a_table_that_holds_another_generation():
    store = box_index.PgVectorStore({}, connect=DB([("old",)]).connect)
    with pytest.raises(RuntimeError, match="vector_store_other_generation"):
        store.ensure_collection("g")
    box_index.PgVectorStore({}, connect=DB([("g",)]).connect).ensure_collection("g")
    box_index.PgVectorStore({}, connect=DB([]).connect).ensure_collection("g")       # an empty table takes any generation


def test_the_store_upserts_every_column_the_read_side_reads_and_gets_the_receipts():
    db = DB()
    store = box_index.PgVectorStore({}, table="chunks_shadow", connect=db.connect)
    store.upsert([row("c1"), row("c2")])
    (sql, params), _ = db.executed
    assert sql.startswith("INSERT INTO chunks_shadow (id, source_hash, content_hash, generation, scope, visibility, owner_hash, symbol, "
                          "source_type, available_at, text, embedding)") and "ON CONFLICT (id) DO UPDATE" in sql
    assert params[0] == "c1" and params[-1] == "[0.5,0.5]" and db.commits == 1
    db.answers.append([("c1", "s", "h", "g")])
    assert store.get(["c1"]) == {"c1": {"id": "c1", "source_hash": "s", "content_hash": "h", "generation": "g"}}


def test_a_table_name_that_is_not_a_plain_identifier_is_refused():
    with pytest.raises(ValueError):
        box_index.PgVectorStore({}, table="chunks; DROP TABLE chunks")


# --- loading the parts ----------------------------------------------------------------------------------------------------------

def test_missing_parts_say_why_and_nothing_runs(tmp_path):
    parts, why = box_index.load_parts({"RAG_TOKENIZER_PATH": str(tmp_path / "none.json")})
    assert parts is None and "tokenizer" in why
    tok = tmp_path / "t.json"
    tok.write_text("{}")
    embed = tmp_path / "embed.env"
    embed.write_text("OTHER=1\n")
    pg = tmp_path / "pg.env"
    pg.write_text("PGVECTOR_USER=u\nPGVECTOR_PASSWORD=p\nPGVECTOR_DB=d\n")
    environ = {"RAG_TOKENIZER_PATH": str(tok), "RAG_EMBED_ENV_FILE": str(embed), "RAG_PGVECTOR_ENV_FILE": str(pg)}
    box_index_tokenizer = box_index.FileTokenizer
    try:
        box_index.FileTokenizer = lambda path: object()
        parts, why = box_index.load_parts(environ)
        assert parts is None and why == "no OPENROUTER_API_KEY in the embedding key file"
        embed.write_text("OPENROUTER_API_KEY=sk-x\n")
        parts, why = box_index.load_parts({**environ, "RAG_PGVECTOR_TABLE": "chunks_shadow"})
        assert why is None and parts.store.table == "chunks_shadow" and parts.store._login["port"] == "55435"
    finally:
        box_index.FileTokenizer = box_index_tokenizer


def test_the_loop_does_nothing_where_the_parts_are_missing(monkeypatch):
    from app import background
    monkeypatch.setattr(box_index, "load_parts", lambda environ=None: (None, "no tokenizer at /nowhere"))
    calls = []
    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch", lambda *a, **k: calls.append(a))
    background.run_knowledge_index()
    assert calls == []
    monkeypatch.setenv("FINBOT_KNOWLEDGE_INDEX", "off")
    monkeypatch.setattr(box_index, "run_once", lambda **k: pytest.fail("switched off"))
    background.run_knowledge_index()


# --- one pass, on the real chunking and index tasks ------------------------------------------------------------------------------

def test_one_pass_syncs_chunks_embeds_and_writes(monkeypatch):
    synced, embedded, written = [], [], []

    class Embedder:
        def encode(self, texts):
            embedded.append(list(texts))
            return [vector() for _ in texts]

    class Store:
        def ensure_collection(self, generation):
            pass

        def upsert(self, rows):
            written.extend(rows)

        def get(self, ids):
            return {}

    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch",
                        lambda factory, tok, gen, *, source_type, batch_size: synced.append(source_type) or {"scanned": 0, "accepted": 0})
    seen = {}

    def index_pending(factory, embedder, store, generation, **kwargs):
        seen.update(kwargs, generation=generation)
        embedder.encode(["x"])
        return {"indexed": 1, "failed": 0, "idle": 0}
    monkeypatch.setattr("app.knowledge.indexing.index_pending", index_pending)
    monkeypatch.setattr(box_index, "_has_work", lambda factory, generation: True)
    parts = box_index.Parts(tokenizer=object(), embedder=Embedder(), store=Store())
    result = box_index.run_once(session_factory=object(), parts=parts)
    assert synced == list(box_index.KINDS) and seen["max_tasks"] == box_index.MAX_CHUNKS and seen["batch_size"] == box_index.BATCH
    assert seen["generation"] == box_index.current_generation() and result["indexed"]["indexed"] == 1 and embedded == [["ping"], ["x"]]


class Gen:
    """A store whose table holds ``found`` (the right generation unless told otherwise)."""

    def __init__(self, ok=True):
        self.ok = ok

    def ensure_collection(self, generation):
        if not self.ok:
            raise RuntimeError("vector_store_other_generation")


def test_one_source_kind_failing_does_not_stop_the_others_or_the_indexing(monkeypatch):
    def sync(factory, tok, gen, *, source_type, batch_size):
        if source_type == "sec":
            raise RuntimeError("boom")
        return {"scanned": 1, "accepted": 1}
    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch", sync)
    monkeypatch.setattr("app.knowledge.indexing.index_pending", lambda *a, **k: {"indexed": 0, "failed": 0, "idle": 1})
    monkeypatch.setattr(box_index, "_has_work", lambda factory, generation: False)
    result = box_index.run_once(session_factory=object(), parts=box_index.Parts(object(), object(), Gen()))
    assert result["synced"]["sec"] == {"error": True} and result["synced"]["faq"] == {"scanned": 1, "accepted": 1}


def test_the_generation_is_the_one_the_vector_store_holds_on_the_box():
    """The read side refuses a table with two generations: the write side must compute the one already stored (8abb…, 11-28)."""
    assert box_index.current_generation().startswith("8abb1488")


def test_the_hand_run_refuses_the_live_table_outside_the_shadow(monkeypatch, capsys):
    from scripts import knowledge_index_once
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    assert knowledge_index_once.main(["--passes", "1"]) == 2
    monkeypatch.setenv("RULER_DATABASE_URL", "postgresql://u@h/finbot_ruler")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u@h/finbot_ruler")
    monkeypatch.delenv("RAG_PGVECTOR_TABLE", raising=False)
    assert knowledge_index_once.main(["--passes", "1"]) == 2
    assert "chunks" in capsys.readouterr().err



def test_a_refused_key_is_not_sent_again(ledger):
    client = Client(Response(401), Response(200, {}))
    with pytest.raises(RuntimeError, match="embedding_status_401"):
        box_index.OpenRouterEmbedder("k", client=client).encode(["a"])
    assert len(client.sent) == 1


def test_the_env_file_takes_export_quotes_and_inline_comments(tmp_path):
    path = tmp_path / "e.env"
    path.write_text('export OPENROUTER_API_KEY=sk-1 # the shared key\nA="b # c"\n# x=y\nB=\'q\'\n')
    assert box_index.read_env_file(str(path)) == {"OPENROUTER_API_KEY": "sk-1", "A": "b # c", "B": "q"}


def test_another_generation_in_the_table_skips_the_pass_before_anything_is_synced(monkeypatch):
    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch", lambda *a, **k: pytest.fail("synced"))
    result = box_index.run_once(session_factory=object(), parts=box_index.Parts(object(), object(), Gen(ok=False)))
    assert result == {"skipped": "vector store: vector_store_other_generation"}


def test_an_embedding_outage_leaves_the_chunks_for_the_next_pass(monkeypatch):
    class Down:
        def encode(self, texts):
            raise RuntimeError("embedding_status_503")
    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch", lambda *a, **k: {"scanned": 0, "accepted": 0})
    monkeypatch.setattr("app.knowledge.indexing.index_pending", lambda *a, **k: pytest.fail("indexed while the service was down"))
    monkeypatch.setattr(box_index, "_has_work", lambda factory, generation: True)
    result = box_index.run_once(session_factory=object(), parts=box_index.Parts(object(), Down(), Gen()))
    assert result["embedding_down"] == "embedding_status_503"


def test_nothing_waiting_means_no_embedding_call(monkeypatch):
    class Counting:
        calls = 0

        def encode(self, texts):
            Counting.calls += 1
            return [vector()]
    monkeypatch.setattr("app.knowledge.source_sync.sync_source_batch", lambda *a, **k: {"scanned": 0, "accepted": 0})
    monkeypatch.setattr(box_index, "_has_work", lambda factory, generation: False)
    result = box_index.run_once(session_factory=object(), parts=box_index.Parts(object(), Counting(), Gen()))
    assert Counting.calls == 0 and result["indexed"]["idle"] == 1


def test_the_shadow_database_never_writes_the_live_table():
    assert box_index.shadow_writing_live({"DATABASE_URL": "postgresql://u@h/finbot_ruler"}) is True
    assert box_index.shadow_writing_live({"DATABASE_URL": "postgresql://u@h/finbot_ruler", "RAG_PGVECTOR_TABLE": "chunks_shadow"}) is False
    assert box_index.shadow_writing_live({"DATABASE_URL": "postgresql://u@h/finbot"}) is False


def test_the_loop_loads_the_parts_once_and_keeps_them(monkeypatch):
    from app import background
    loads, passes = [], []
    monkeypatch.setattr(background, "_KNOWLEDGE_PARTS", None)
    monkeypatch.setattr(box_index, "shadow_writing_live", lambda environ=None: False)
    monkeypatch.setattr(box_index, "load_parts", lambda environ=None: loads.append(1) or ("parts", None))
    monkeypatch.setattr(box_index, "run_once", lambda parts=None, **k: passes.append(parts) or {"synced": {}, "indexed": {}})
    background.run_knowledge_index()
    background.run_knowledge_index()
    assert loads == [1] and passes == ["parts", "parts"]


# --- the contract with the real index tasks: receipts that ack (tests the PgVectorStore's SQL against a stand-in table) ----------

class FakeTable:
    """Interprets the three statements PgVectorStore sends; keeps rows like the ``chunks`` table (id is text)."""

    def __init__(self):
        self.rows = {}
        self.db = self

    def connect(self):
        table = self

        class C:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def cursor(self):
                return self

            def commit(self):
                pass

            def execute(self, sql, params=None):
                if sql.startswith("SELECT DISTINCT generation"):
                    self.result = [(g,) for g in {r["generation"] for r in table.rows.values()}][:2]
                elif sql.startswith("INSERT INTO"):
                    names = [c.strip() for c in sql.split("(", 1)[1].split(")", 1)[0].split(",")]
                    record = dict(zip(names, params))
                    table.rows[str(record["id"])] = record
                    self.result = []
                else:
                    wanted = set(params[0])
                    self.result = [(r["id"], r["source_hash"], r["content_hash"], r["generation"]) for i, r in table.rows.items() if i in wanted]

            def fetchall(self):
                return self.result
        return C()


@pytest.fixture
def knowledge_db(disposable_database):
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeIndexTask
    from scripts.migrate_knowledge import migrate
    migrate(engine)
    yield lambda: Session(engine)
    with Session(engine) as s, s.begin():
        s.query(KnowledgeIndexTask).delete(); s.query(KnowledgeChunk).delete(); s.query(KnowledgeDocument).delete()


def test_real_index_tasks_ack_on_the_stores_receipts_and_retry_failed_requeues(knowledge_db):
    from datetime import UTC, datetime
    from app.knowledge.indexing import index_pending
    from app.knowledge.models import KnowledgeChunk, KnowledgeIndexTask
    from app.knowledge.repository import ingest_documents
    from app.knowledge.sources import SourceDocument

    class Words:
        def encode(self, text, **kwargs):
            return text.split()

    class Embed:
        def encode(self, texts):
            return [vector() for _ in texts]

    generation = box_index.current_generation()
    source = SourceDocument("fixture", "box-index-fixture", "v1", "b" * 64, "official_filing", "DEMO", "public", "public", None, "10-Q",
                            "https://example.test", None, datetime.now(UTC), datetime.now(UTC), False, "markdown",
                            "# Results\nRevenue was USD 123 million.\n\n# Risks\nSupply is tight.")
    with knowledge_db() as s, s.begin():
        assert ingest_documents(s, [source], Words(), generation)["chunks"] >= 1
    table = FakeTable()
    store = box_index.PgVectorStore({}, connect=table.connect)
    result = index_pending(knowledge_db, Embed(), store, generation, max_tasks=10, batch_size=16)
    with knowledge_db() as s:
        ready = s.query(KnowledgeChunk).filter_by(generation=generation, status="ready").count()
        complete = s.query(KnowledgeIndexTask).filter_by(generation=generation, status="complete").count()
    assert result["failed"] == 0 and result["indexed"] == ready == complete == len(table.rows) >= 1
    assert all(len(row["embedding"]) > 2 and row["generation"] == generation for row in table.rows.values())
    with knowledge_db() as s, s.begin():
        task = s.query(KnowledgeIndexTask).filter_by(generation=generation).first()
        task.status, task.error_code, task.attempts = "failed", "index_operation_failed", 4
    assert box_index.retry_failed(knowledge_db) == 1
    with knowledge_db() as s:
        assert s.query(KnowledgeIndexTask).filter_by(generation=generation, status="pending", attempts=0).count() == 1
