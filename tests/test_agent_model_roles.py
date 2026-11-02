"""agent_model_roles：财报判断模型按角色存，默认走服务器默认模型。"""
import pytest

from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app.agent_chat_models import AgentModelRole
from app.database import SessionLocal
from tests.test_agent_bots import GUEST, H, KEY_A, OWNER_HASH, owner  # noqa: F401  (fixture)


@pytest.fixture
def two_models(owner):
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.commit()
    for name in ("alpha", "bravo"):
        catalog.save_entry(name, display_name=name, provider="deepseek", model=f"m-{name}", api_key=KEY_A,
                           is_default=name == "alpha", create=True)
    return owner


def test_default_role_resolves_to_server_default(two_models):
    assert roles.get(OWNER_HASH, "earnings") is None
    assert roles.resolve(OWNER_HASH, "earnings")["name"] == "alpha"


def test_set_role_and_clear(two_models):
    roles.set_role(OWNER_HASH, "earnings", "bravo")
    assert roles.get(OWNER_HASH, "earnings") == "bravo"
    assert roles.resolve(OWNER_HASH, "earnings")["name"] == "bravo"
    assert roles.get(OWNER_HASH, "forecast") is None            # roles are independent
    roles.set_role(OWNER_HASH, "earnings", None)
    assert roles.get(OWNER_HASH, "earnings") is None


def test_unknown_role_or_model_rejected(two_models):
    with pytest.raises(roles.RoleError):
        roles.set_role(OWNER_HASH, "trading", "alpha")
    with pytest.raises(roles.RoleError):
        roles.set_role(OWNER_HASH, "earnings", "nope")


def test_deleted_model_falls_back_to_default(two_models):
    roles.set_role(OWNER_HASH, "earnings", "bravo")
    catalog.delete_entry("bravo")
    assert roles.resolve(OWNER_HASH, "earnings")["name"] == "alpha"


def test_endpoints_owner_only_and_never_leak_keys(two_models, client):
    assert client.get("/agent-chat/model-roles", headers={"X-Chat-Session": GUEST}).status_code == 403
    got = client.get("/agent-chat/model-roles", headers=H).json()
    assert got["roles"]["earnings"] is None and got["roles"]["forecast"] is None
    put = client.put("/agent-chat/model-roles/earnings", headers=H, json={"model": "bravo"})
    assert put.status_code == 200 and put.json() == {"role": "earnings", "model": "bravo"}
    assert client.get("/agent-chat/model-roles", headers=H).json()["roles"]["earnings"] == "bravo"
    assert client.put("/agent-chat/model-roles/earnings", headers=H, json={"model": "nope"}).status_code == 422
    assert client.put("/agent-chat/model-roles/bogus", headers=H, json={"model": None}).status_code == 422
    assert KEY_A not in put.text
