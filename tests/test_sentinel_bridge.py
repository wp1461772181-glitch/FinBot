import json
import stat

from app import sentinel_bridge


def test_snapshot_written_0600_and_tolerates_missing_sections(tmp_path, monkeypatch):
    path = tmp_path / "sentinel-config.json"
    monkeypatch.setattr(sentinel_bridge, "snapshot_path", lambda: path)
    monkeypatch.setattr(sentinel_bridge, "_research_queue", lambda owner: ["AAPL"])
    monkeypatch.setattr(sentinel_bridge, "_telegram", lambda owner: (_ for _ in ()).throw(RuntimeError("db down")))
    sentinel_bridge.write_sentinel_snapshot("owner")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    data = json.loads(path.read_text())
    assert data["research_queue"] == ["AAPL"] and data["telegram"] == {} and data["positions"] == []


def _req(host, headers):
    from types import SimpleNamespace
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


def test_sentinel_endpoint_guard(monkeypatch):
    import pytest
    from fastapi import HTTPException
    from app.sentinel_api import require_sentinel
    monkeypatch.setenv("SENTINEL_TOKEN", "tok")
    require_sentinel(_req("127.0.0.1", {"X-Sentinel-Token": "tok"}))
    for host, headers in [("10.0.0.2", {"X-Sentinel-Token": "tok"}), ("127.0.0.1", {"X-Sentinel-Token": "bad"}),
                          ("127.0.0.1", {"X-Sentinel-Token": "tok", "X-Forwarded-For": "1.2.3.4"})]:
        with pytest.raises(HTTPException):
            require_sentinel(_req(host, headers))
    monkeypatch.delenv("SENTINEL_TOKEN")
    with pytest.raises(HTTPException):
        require_sentinel(_req("127.0.0.1", {"X-Sentinel-Token": ""}))
