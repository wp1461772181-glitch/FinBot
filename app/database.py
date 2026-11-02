import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, "").strip() or default))
    except ValueError:
        return default


# Supabase 免费版总连接上限按 15 控制：API 进程 5+3，其他进程设 DB_POOL_SIZE=1 DB_MAX_OVERFLOW=1。
# 没有连接超时时，数据库连不上会卡很久，所以显式设置 connect_timeout（秒）。
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_int_env("DB_POOL_SIZE", 5),
    max_overflow=_int_env("DB_MAX_OVERFLOW", 10),
    pool_recycle=300,
    connect_args={"connect_timeout": max(1, _int_env("DB_CONNECT_TIMEOUT", 10))},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
