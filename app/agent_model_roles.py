"""Which catalog model does which job (``agent_model_roles(owner_hash, role, model_name)``).

``earnings`` is the earnings-release reader (earnings_reader).  ``forecast`` is the model that gives the
forecast's direction probabilities (forecast_model_provider).  ``judge`` is the claim judge (the review model,
agent_workflow/claim_judge_pin); it has no catalog-default fallback: no row, or a row naming a model that has left
the catalog, means the env / pinned judge.  For the other roles, no row, or a row naming a model that has since left
the catalog, means the server's default model.  ``fallback`` is the kernel's backup model: it has no default either
(``fallback_for``: unset, or an entry that has left the catalog, means no backup).  ``helper`` is the kernel's helper (``delegate``): unset, or an
entry that has left the catalog, means the model of the turn that delegates (``helper_for`` is None then; no server default stands in).  The table is made by ``Base.metadata.create_all`` at startup like the catalog's."""
from __future__ import annotations

from . import agent_model_catalog as catalog
from .agent_chat_models import AgentModelRole
from .database import SessionLocal

ROLES = ("earnings", "forecast", "judge", "fallback", "helper")


class RoleError(ValueError):
    pass


def get(owner_hash: str, role: str) -> str | None:
    with SessionLocal() as db:
        row = db.get(AgentModelRole, (owner_hash, role))
        return row.model_name if row else None


def all_roles(owner_hash: str) -> dict[str, str | None]:
    return {role: get(owner_hash, role) for role in ROLES}


def check_role(role: str, model_name: str | None) -> None:
    """The refusals of ``set_role`` (an unknown role, a model that is not in the catalog); the route and the card share them."""
    if role not in ROLES:
        raise RoleError("unknown_role")
    if model_name is not None and not catalog.exists(model_name):
        raise RoleError("unknown_model")


def set_role(owner_hash: str, role: str, model_name: str | None) -> str | None:
    """Pick the model for a role; None goes back to the server default."""
    check_role(role, model_name)
    with SessionLocal() as db:
        row = db.get(AgentModelRole, (owner_hash, role))
        if model_name is None:
            if row is not None:
                db.delete(row)
        elif row is None:
            db.add(AgentModelRole(owner_hash=owner_hash, role=role, model_name=model_name))
        else:
            row.model_name = model_name
        db.commit()
    return model_name


def resolve_with_source(owner_hash: str | None, role: str) -> tuple[dict, dict]:
    """``resolve`` plus how the model was chosen: ``{source, role_model}`` where source is ``role`` (the
    role's model is in the catalog), ``server_default`` (role unset) or ``role_model_missing`` (the role
    names a model that has left the catalog; the server default is used and ``role_model`` says which)."""
    if role not in ROLES:
        raise RoleError("unknown_role")
    if role in ("fallback", "helper"):
        raise RoleError("role_has_no_default")     # nothing stands in for a backup or a helper's model: ``fallback_for`` / ``helper_for`` read them
    name = get(owner_hash, role) if owner_hash else None
    if name and catalog.exists(name):
        return catalog.resolve(name), {"source": "role", "role_model": name}
    if name:
        return catalog.resolve(None), {"source": "role_model_missing", "role_model": name}
    return catalog.resolve(None), {"source": "server_default", "role_model": None}


def resolve(owner_hash: str | None, role: str) -> dict:
    """Provider settings (with the key, in memory only) for the role's model; the catalog default when
    the role is unset or its model is gone.  Raises catalog.CatalogError when nothing can be used."""
    return resolve_with_source(owner_hash, role)[0]


def fallback_for(owner_hash: str | None) -> dict | None:
    """Provider settings (with the key, in memory only) of the owner's backup model, or None: the role is unset, or
    names an entry that has left the catalog or has no key.  Unlike the other roles nothing stands in for it."""
    name = get(owner_hash, "fallback") if owner_hash else None
    if not name or not catalog.exists(name):
        return None
    try:
        return catalog.resolve(name)
    except catalog.CatalogError:
        return None


def helper_for(owner_hash: str | None) -> dict | None:
    """Provider settings (with the key, in memory only) of the owner's helper model, or None: the role is unset, or names an entry that has
    left the catalog or has no key.  The caller then uses the model of the turn."""
    name = get(owner_hash, "helper") if owner_hash else None
    if not name or not catalog.exists(name):
        return None
    try:
        return catalog.resolve(name)
    except catalog.CatalogError:
        return None


def _newest_role_owner(role: str) -> str | None:
    from sqlalchemy import select
    with SessionLocal() as db:
        return db.scalar(select(AgentModelRole.owner_hash).where(AgentModelRole.role == role)
                         .order_by(AgentModelRole.updated_at.desc(), AgentModelRole.owner_hash).limit(1))


def forecast_owner() -> str | None:
    """The owner whose role=forecast row decides the forecast model.  The forecast job belongs to no chat
    session, and this is a single-owner deployment: the newest forecast row wins, none means unset."""
    return _newest_role_owner("forecast")


def judge_owner() -> str | None:
    """The owner whose role=judge row decides the claim judge.  The judge runs after a turn with no owner of its
    own, and this is a single-owner deployment: the newest judge row wins, none means unset."""
    return _newest_role_owner("judge")
