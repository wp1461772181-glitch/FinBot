"""jin10-flash publishes Beijing wall-clock times; a source can declare the zone of its naive times."""
import json
from datetime import UTC, datetime, timedelta
from importlib import util
from pathlib import Path

import pytest
from sqlalchemy import text

from app import fin_news_engine as eng
from app.agent_chat_models import NewsItem
from app.database import Base, SessionLocal, engine

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_naive_time_parsed_as_declared_zone():
    dt, inferred = eng._parse_datetime("2026-11-24 23:08:02", NOW, "Asia/Shanghai")
    assert not inferred and dt == datetime(2026, 11, 24, 15, 8, 2, tzinfo=UTC)


def test_default_is_utc_for_other_sources():
    dt, _ = eng._parse_datetime("2026-11-24 23:08:02", NOW)
    assert dt == datetime(2026, 11, 24, 23, 8, 2, tzinfo=UTC)


def test_aware_and_epoch_ignore_declared_zone():
    assert eng._parse_datetime("2026-11-24T10:00:00+00:00", NOW, "Asia/Shanghai")[0] == datetime(2026, 11, 24, 10, tzinfo=UTC)
    assert eng._parse_datetime("2026-11-24T10:00:00Z", NOW, "Asia/Shanghai")[0] == datetime(2026, 11, 24, 10, tzinfo=UTC)
    assert eng._parse_datetime("Tue, 24 Nov 2026 10:00:00 GMT", NOW, "Asia/Shanghai")[0] == datetime(2026, 11, 24, 10, tzinfo=UTC)
    assert eng._parse_datetime(1795600000, NOW, "Asia/Shanghai")[0] == datetime.fromtimestamp(1795600000, tz=UTC)


def _raw(t):
    return {"title": "x", "url": "https://flash.jin10.com/detail/1", "summary": "s", "published_at": t}


def test_normalize_item_uses_source_timezone():
    src = {"id": "jin10-flash", "normalize": {"time_format": "auto", "timezone": "Asia/Shanghai"}}
    rec = eng.normalize_item(_raw("2026-11-24 23:08:02"), src, fetched_at=NOW)
    assert rec["published_at"] == datetime(2026, 11, 24, 15, 8, 2, tzinfo=UTC)
    other = {"id": "other", "normalize": {"time_format": "auto"}}
    rec = eng.normalize_item(_raw("2026-11-24 23:08:02"), other, fetched_at=NOW)
    assert rec["published_at"] == datetime(2026, 11, 24, 23, 8, 2, tzinfo=UTC)


def _stored_cfg(normalize):
    cfg = eng.default_config_dict()
    for s in cfg["sources"]:
        if s["id"] == "jin10-flash":
            s["normalize"] = normalize
    return cfg


def _jin10(cfg):
    return next(s for s in cfg["sources"] if s["id"] == "jin10-flash")


def test_default_config_declares_beijing_for_jin10():
    assert _jin10(eng.validate_config(eng.default_config_dict()))["normalize"]["timezone"] == "Asia/Shanghai"


def test_stored_config_without_key_still_gets_default():
    cfg = eng.validate_config(_stored_cfg({"time_format": "auto"}))
    assert _jin10(cfg)["normalize"] == {"time_format": "auto", "timezone": "Asia/Shanghai"}
    stored = eng.validate_config(_stored_cfg(None))
    assert _jin10(stored)["normalize"]["timezone"] == "Asia/Shanghai"


def test_owner_timezone_not_overwritten_and_other_sources_untouched():
    cfg = eng.validate_config(_stored_cfg({"time_format": "auto", "timezone": "UTC"}))
    assert _jin10(cfg)["normalize"]["timezone"] == "UTC"
    for s in cfg["sources"]:
        if s["id"] != "jin10-flash":
            assert "timezone" not in s["normalize"]


def test_load_config_from_stored_file_applies_default(tmp_path):
    import yaml
    path = tmp_path / "news.yaml"
    path.write_text(yaml.safe_dump(_stored_cfg({"time_format": "auto"})), encoding="utf-8")
    assert _jin10(eng.load_config(path))["normalize"]["timezone"] == "Asia/Shanghai"


# ---- repair script ----

def _load_script():
    p = Path(__file__).resolve().parent.parent / "scripts" / "repair_jin10_times.py"
    spec = util.spec_from_file_location("repair_jin10_times", p)
    mod = util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CUTOFF = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
OLD = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def rows(disposable_database):
    Base.metadata.create_all(engine, tables=[NewsItem.__table__])
    with SessionLocal() as db:
        db.query(NewsItem).delete()
        def mk(key, src, fetched, inferred=False):
            r = NewsItem(source_id=src, source_name="n", dedupe_key=key, title=key, url="https://e.com/" + key,
                         summary="", published_at=OLD, fetched_at=fetched, time_inferred=inferred, tickers=[],
                         keywords_hit=[], language="zh-CN")
            db.add(r)
            return r
        mk("a", "jin10-flash", CUTOFF - timedelta(hours=1))             # repaired
        mk("b", "jin10-flash", CUTOFF + timedelta(hours=1))             # fixed row, after cutoff
        mk("c", "jin10-flash", CUTOFF - timedelta(hours=1), True)       # inferred time
        mk("d", "yahoo-finance-rss", CUTOFF - timedelta(hours=1))       # other source
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(NewsItem).delete()
        db.commit()


def _times():
    with SessionLocal() as db:
        return {r.dedupe_key: r.published_at for r in db.query(NewsItem).all()}


def test_repair_dry_run_run_and_idempotent(rows, tmp_path, capsys):
    mod = _load_script()
    url = engine.url.render_as_string(hide_password=False)
    res = mod.run(url, CUTOFF, tmp_path, dry_run=True)
    assert res["affected"] == 1 and res["sample"][0]["old"].startswith("2026-11-24T10:00")
    assert _times()["a"] == OLD and list(tmp_path.iterdir()) == []

    res = mod.run(url, CUTOFF, tmp_path, dry_run=False)
    t = _times()
    assert res["affected"] == 1
    assert t["a"] == OLD - timedelta(hours=8)
    assert t["b"] == OLD and t["c"] == OLD and t["d"] == OLD
    backup = json.loads(Path(res["backup_path"]).read_text())
    assert len(backup) == 1 and backup[0]["published_at"].startswith("2026-11-24T10:00")
    ids = json.loads(Path(res["changed_ids_path"]).read_text())["ids"]
    assert ids == [backup[0]["id"]]
    assert "backup written" in capsys.readouterr().out

    res = mod.run(url, CUTOFF, tmp_path, dry_run=False)
    assert res["affected"] == 0 and _times()["a"] == OLD - timedelta(hours=8)


def test_repair_main_requires_env_and_never_prints_url(rows, tmp_path, monkeypatch, capsys):
    mod = _load_script()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert mod.main(["--cutoff", "2026-11-24T12:00:00Z"]) == 2
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", url)
    assert mod.main(["--cutoff", "2026-11-24T12:00:00Z", "--dry-run", "--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert url not in out.out + out.err
