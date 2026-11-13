"""Renaming a server model catalog entry (settings › 模型配置: the 目录名 field is editable on an edit).

The rename is one transaction: the entry, every bot that names it and every model role that names it move
together, or nothing does.  Its key, default flag and context window stay with the entry.  A name the code reads
by its literal name (``background``, the claim judge's label) is refused with ``model_name_in_code``, as is a name
in use or an invalid one.  Config-file entries cannot be renamed; a PATCH without a new name is unchanged.
"""
import uuid

import pytest
from sqlalchemy import event

from app import agent_bots as bots
from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app.database import engine
from tests.test_agent_bots import GUEST, H, KEY_A, KEY_B, OWNER_HASH, _keys_absent, owner  # noqa: F401  (fixture)


def _bot(name_prefix, model):
    return bots.create_bot(OWNER_HASH, {"name": f"{name_prefix}-{uuid.uuid4().hex[:6]}", "model": model})


def test_rename_moves_the_entry_its_bots_and_its_roles_together(owner, client):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, is_default=True,
                       context_window=64_000, create=True)
    catalog.save_entry("beta", provider="qwen", model="qwen-plus", api_key=KEY_B, create=True)
    bot = _bot("改名", "alpha")
    roles.set_role(OWNER_HASH, "earnings", "alpha")
    roles.set_role(OWNER_HASH, "forecast", "beta")
    before = catalog.resolve("alpha")

    renamed = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"name": "haiku-5.5"})
    assert renamed.status_code == 200, renamed.text
    model = renamed.json()["model"]
    assert model["name"] == "haiku-5.5" and model["is_default"] is True and model["key_status"] == "configured"
    _keys_absent(renamed.text)
    listed = [m["name"] for m in client.get("/agent-chat/model-catalog", headers=H).json()["models"]]
    assert "haiku-5.5" in listed and "alpha" not in listed
    assert client.get("/agent-chat/model-catalog", headers=H).json()["default"] == "haiku-5.5"

    # The renamed entry resolves to everything the old one did: the same provider, model, endpoint, key and window.
    after = catalog.resolve("haiku-5.5")
    keys = ("provider", "model", "base_url", "api_key", "context_window")
    assert {k: after[k] for k in keys} == {k: before[k] for k in keys}
    assert after["name"] == "haiku-5.5"
    assert not catalog.exists("alpha")

    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "haiku-5.5"
    assert roles.get(OWNER_HASH, "earnings") == "haiku-5.5"
    assert roles.get(OWNER_HASH, "forecast") == "beta"  # a role naming another entry is left alone


def test_renaming_onto_a_name_in_use_is_refused_and_changes_nothing(owner, client):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, is_default=True, create=True)
    catalog.save_entry("beta", provider="qwen", model="qwen-plus", api_key=KEY_B, create=True)
    bot = _bot("占用", "alpha")
    refused = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"name": "beta"})
    assert refused.status_code == 409 and refused.json()["detail"] == "model_exists"
    assert catalog.resolve("alpha")["api_key"] == KEY_A
    assert catalog.resolve("beta")["api_key"] == KEY_B
    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "alpha"


@pytest.mark.parametrize("bad", ["BAD NAME", "", "has/slash", "-leading", "Upper"])
def test_renaming_to_an_invalid_name_is_refused(owner, client, bad):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, create=True)
    refused = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"name": bad})
    assert refused.status_code == 422 and refused.json()["detail"] == "invalid_name"
    assert catalog.exists("alpha") and not catalog.exists(bad)


def test_entries_the_code_reads_by_name_cannot_be_renamed_but_still_edit(owner, client, monkeypatch):
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_MODEL", raising=False)
    catalog.save_entry("background", provider="deepseek", model="deepseek-chat", api_key=KEY_A, create=True)
    catalog.save_entry("glm-5.3-flash", provider="deepseek", model="glm-5.3-flash", api_key=KEY_B, create=True)
    bot = _bot("后台", "background")

    # scripts/claim_shadow_report.py defaults to "background"; config/claim_judge_pin.json names the judge label.
    for name in ("background", "glm-5.3-flash"):
        refused = client.patch(f"/agent-chat/model-catalog/{name}", headers=H, json={"name": "renamed-model"})
        assert refused.status_code == 409 and refused.json()["detail"] == "model_name_in_code", name
    assert catalog.exists("background") and catalog.exists("glm-5.3-flash")
    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "background"

    # An ordinary edit of the same entry still works: only the name is held.
    edited = client.patch("/agent-chat/model-catalog/background", headers=H, json={"display_name": "后台模型"})
    assert edited.status_code == 200 and edited.json()["model"]["display_name"] == "后台模型"
    assert edited.json()["model"]["name"] == "background"


def test_while_the_environment_names_the_judge_only_that_name_is_held(owner, client, monkeypatch):
    # The pin's label is read only when CLAIM_JUDGE_SHADOW_MODEL is unset, so the environment's name is the one held.
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, create=True)
    catalog.save_entry("glm-5.3-flash", provider="deepseek", model="glm-5.3-flash", api_key=KEY_B, create=True)
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "alpha")
    refused = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"name": "alpha-2"})
    assert refused.status_code == 409 and refused.json()["detail"] == "model_name_in_code"
    renamed = client.patch("/agent-chat/model-catalog/glm-5.3-flash", headers=H, json={"name": "judge-label"})
    assert renamed.status_code == 200 and renamed.json()["model"]["name"] == "judge-label"


def test_a_config_file_entry_cannot_be_renamed_through_the_api(owner, client, monkeypatch, tmp_path):
    (tmp_path / "models.yaml").write_text(
        "models:\n  - {name: filed, provider: deepseek, model: deepseek-chat, key_env: FILED_API_KEY}\n", encoding="utf-8")
    monkeypatch.setenv("FILED_API_KEY", KEY_A)
    refused = client.patch("/agent-chat/model-catalog/filed", headers=H, json={"name": "renamed"})
    assert refused.status_code == 422 and refused.json()["detail"] == "model_from_file"
    assert catalog.exists("filed") and not catalog.exists("renamed")


def test_renaming_an_unknown_entry_is_not_found(owner, client):
    response = client.patch("/agent-chat/model-catalog/ghost", headers=H, json={"name": "anything"})
    assert response.status_code == 404 and response.json()["detail"] == "model_not_found"


def test_a_patch_without_a_new_name_or_with_the_same_one_keeps_the_name(owner, client):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, is_default=True, create=True)
    bot = _bot("同名", "alpha")
    same = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"name": "alpha", "display_name": "主力"})
    assert same.status_code == 200 and same.json()["model"]["name"] == "alpha" and same.json()["model"]["display_name"] == "主力"
    plain = client.patch("/agent-chat/model-catalog/alpha", headers=H, json={"model": "deepseek-reasoner", "is_default": True})
    assert plain.status_code == 200 and plain.json()["model"]["name"] == "alpha" and plain.json()["model"]["model"] == "deepseek-reasoner"
    assert catalog.resolve("alpha")["api_key"] == KEY_A
    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "alpha"


def test_a_rename_that_fails_after_the_bots_moved_rolls_all_of_it_back(owner, monkeypatch):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, is_default=True, create=True)
    bot = _bot("回滚", "alpha")
    roles.set_role(OWNER_HASH, "earnings", "alpha")
    # Fail the role update, which runs after the bot update in the same transaction; record what ran first.
    ran = []

    def watch(conn, cursor, statement, parameters, context, executemany):
        table = next((t for t in ("agent_bots", "agent_model_roles") if statement.lstrip().upper().startswith(f"UPDATE {t.upper()}")), None)
        if table:
            ran.append(table)
        if table == "agent_model_roles":
            raise RuntimeError("role update failed")

    event.listen(engine, "before_cursor_execute", watch)
    try:
        with pytest.raises(RuntimeError, match="role update failed"):
            catalog.save_entry("alpha", rename_to="haiku-5.5")
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    assert ran == ["agent_bots", "agent_model_roles"]
    # Nothing committed: the entry, the bot and the role all still say alpha.
    assert catalog.exists("alpha") and not catalog.exists("haiku-5.5")
    assert catalog.resolve("alpha")["api_key"] == KEY_A
    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "alpha"
    assert roles.get(OWNER_HASH, "earnings") == "alpha"


def test_a_name_taken_by_a_concurrent_save_is_refused_as_in_use(owner, monkeypatch):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, create=True)
    catalog.save_entry("beta", provider="qwen", model="qwen-plus", api_key=KEY_B, create=True)
    bot = _bot("并发", "alpha")
    # The up-front check passes (as if the other save had not committed yet); the primary-key update then collides.
    monkeypatch.setattr(catalog, "_check_rename", lambda db, old, new: None)
    with pytest.raises(catalog.CatalogError, match="model_exists"):
        catalog.save_entry("alpha", rename_to="beta")
    assert catalog.resolve("alpha")["api_key"] == KEY_A
    assert bots.get_bot(OWNER_HASH, bot["id"])["model"] == "alpha"


def test_a_guest_cannot_rename_a_catalog_entry(owner, client):
    catalog.save_entry("alpha", provider="deepseek", model="deepseek-chat", api_key=KEY_A, create=True)
    response = client.patch("/agent-chat/model-catalog/alpha", headers={"X-Chat-Session": GUEST}, json={"name": "haiku-5.5"})
    assert response.status_code == 403 and catalog.exists("alpha")
