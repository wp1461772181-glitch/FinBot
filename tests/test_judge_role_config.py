"""judge 角色：法官（审查模型）可在设置页绑定；未设时 env → pin 的旧行为一字不变。"""
import pytest

from app import agent_model_catalog as catalog
from app import agent_model_roles as roles
from app.agent_chat_models import AgentModelEntry, AgentModelRole
from app.agent_workflow import claim_judge_pin as pin
from app.database import SessionLocal
from tests.test_agent_bots import H, KEY_A, OWNER_HASH, owner  # noqa: F401  (fixture)


@pytest.fixture
def judge_env(owner, monkeypatch):
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_MODEL", raising=False)
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", raising=False)
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.commit()
    for name in ("alpha", "judgey"):
        catalog.save_entry(name, display_name=name, provider="deepseek", model=f"m-{name}", api_key=KEY_A,
                           is_default=name == "alpha", create=True)
    yield owner
    with SessionLocal() as db:
        db.query(AgentModelRole).delete()
        db.query(AgentModelEntry).delete()
        db.commit()


def test_unset_role_keeps_env_then_pin(judge_env, monkeypatch):
    assert roles.judge_owner() is None
    assert pin.shadow_model_name() == pin.load_pin()["judge"]["name"]
    assert pin.expected_model() == pin.load_pin()["judge"]["model"]
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "env-label")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "env-model")
    assert pin.shadow_model_name() == "env-label"
    assert pin.expected_model() == "env-model"


def test_role_wins_over_env_and_pin(judge_env, monkeypatch):
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "env-label")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "env-model")
    roles.set_role(OWNER_HASH, "judge", "judgey")
    assert roles.judge_owner() == OWNER_HASH
    assert pin.shadow_model_name() == "judgey"
    assert pin.expected_model() == "m-judgey"          # the field claim_shadow compares: resolved["model"]
    assert pin.expected_model() == catalog.resolve("judgey")["model"]
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_MODEL")
    monkeypatch.delenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL")
    assert pin.shadow_model_name() == "judgey" and pin.expected_model() == "m-judgey"


def test_role_takes_effect_and_clears_without_restart(judge_env):
    roles.set_role(OWNER_HASH, "judge", "judgey")
    assert pin.shadow_model_name() == "judgey"
    roles.set_role(OWNER_HASH, "judge", "alpha")
    assert pin.shadow_model_name() == "alpha" and pin.expected_model() == "m-alpha"
    roles.set_role(OWNER_HASH, "judge", None)
    assert pin.shadow_model_name() == pin.load_pin()["judge"]["name"]


def test_role_entry_gone_from_catalog_falls_back_to_env_then_pin(judge_env, monkeypatch):
    roles.set_role(OWNER_HASH, "judge", "judgey")
    catalog.delete_entry("judgey")
    assert roles.get(OWNER_HASH, "judge") == "judgey"   # the row is still there; the judge does not become "alpha"
    assert pin.shadow_model_name() == pin.load_pin()["judge"]["name"]
    assert pin.expected_model() == pin.load_pin()["judge"]["model"]
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_MODEL", "env-label")
    monkeypatch.setenv("CLAIM_JUDGE_SHADOW_EXPECT_MODEL", "env-model")
    assert pin.shadow_model_name() == "env-label" and pin.expected_model() == "env-model"


def test_unreadable_role_falls_back_instead_of_breaking_the_judge(judge_env, monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(roles, "judge_owner", boom)
    assert pin.shadow_model_name() == pin.load_pin()["judge"]["name"]


def test_set_role_and_all_roles_include_judge(judge_env):
    assert roles.ROLES == ("earnings", "forecast", "judge")
    assert roles.all_roles(OWNER_HASH) == {"earnings": None, "forecast": None, "judge": None}
    roles.set_role(OWNER_HASH, "judge", "judgey")
    assert roles.all_roles(OWNER_HASH)["judge"] == "judgey"
    assert roles.all_roles(OWNER_HASH)["forecast"] is None
    with pytest.raises(roles.RoleError, match="unknown_role"):
        roles.set_role(OWNER_HASH, "trading", "alpha")
    with pytest.raises(roles.RoleError, match="unknown_model"):
        roles.set_role(OWNER_HASH, "judge", "nope")


def test_judge_role_through_the_api(judge_env, client):
    assert client.get("/agent-chat/model-roles", headers=H).json()["roles"]["judge"] is None
    put = client.put("/agent-chat/model-roles/judge", headers=H, json={"model": "judgey"})
    assert put.status_code == 200 and put.json() == {"role": "judge", "model": "judgey"}
    assert client.get("/agent-chat/model-roles", headers=H).json()["roles"]["judge"] == "judgey"
    assert pin.shadow_model_name() == "judgey"


def test_rename_cascades_to_the_judge_role_row(judge_env):
    roles.set_role(OWNER_HASH, "judge", "judgey")
    catalog.save_entry("judgey", rename_to="judge-renamed")
    assert roles.get(OWNER_HASH, "judge") == "judge-renamed"
    assert pin.shadow_model_name() == "judge-renamed"
    assert pin.expected_model() == "m-judgey"
