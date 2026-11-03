"""Which catalog model does which job (``agent_model_roles(owner_hash, role, model_name)``).

``earnings`` is the earnings-release reader (earnings_reader).  ``forecast`` is the model that gives the
forecast's direction probabilities (forecast_model_provider).  No row, or a row naming a model that has since left the catalog, means the
server's default model.  The table is made by ``Base.metadata.create_all`` at startup like the catalog's."""
from __future__ import annotations

from . import agent_model_catalog as catalog
from .agent_chat_models import AgentModelRole
from .database import SessionLocal

ROLES = ("earnings", "forecast")


class RoleError(ValueError):
    pass


def get(owner_hash: str, role: str) -> str | None:
    with SessionLocal() as db:
        row = db.get(AgentModelRole, (owner_hash, role))
        return row.model_name if row else None


def all_roles(owner_hash: str) -> dict[str, str | None]:
    return {role: get(owner_hash, role) for role in ROLES}


def set_role(owner_hash: str, role: str, model_name: str | None) -> str | None:
    """Pick the model for a role; None goes back to the server default."""
    if role not in ROLES:
        raise RoleError("unknown_role")
    if model_name is not None and not catalog.exists(model_name):
        raise RoleError("unknown_model")
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


def resolve(owner_hash: str | None, role: str) -> dict:
    """Provider settings (with the key, in memory only) for the role's model; the catalog default when
    the role is unset or its model is gone.  Raises catalog.CatalogError when nothing can be used."""
    if role not in ROLES:
        raise RoleError("unknown_role")
    name = get(owner_hash, role) if owner_hash else None
    if name and not catalog.exists(name):
        name = None
    return catalog.resolve(name)


def forecast_owner() -> str | None:
    """The owner whose role=forecast row decides the forecast model.  The forecast job belongs to no chat
    session, and this is a single-owner deployment: the newest forecast row wins, none means unset."""
    from sqlalchemy import select
    with SessionLocal() as db:
        return db.scalar(select(AgentModelRole.owner_hash).where(AgentModelRole.role == "forecast")
                         .order_by(AgentModelRole.updated_at.desc(), AgentModelRole.owner_hash).limit(1))
