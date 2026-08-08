# TradePilot AI — database engine, session, and initialization.
#
# In plain terms: this file is what actually connects to the SQLite
# database file on disk. Everything else (models.py, crud.py) builds on
# top of what's defined here.
#
# The database file defaults to database/tradepilot.db in this project,
# but can be overridden with the DATABASE_URL environment variable — the
# test suite uses this to point at a throwaway in-memory database instead,
# so tests never touch the real file.

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DB_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = DB_DIR / "tradepilot.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """Base class every table model inherits from."""


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    """
    SQLite ignores foreign keys unless you turn them on for every
    connection. Without this, a Capture/Evaluation/etc. row could point at
    a run_id that doesn't exist and SQLite wouldn't complain — which would
    quietly break the audit trail.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db(target_engine: Engine | None = None) -> None:
    """
    Create every table that doesn't already exist yet.

    Safe to call more than once — it never drops or overwrites existing
    tables or data.
    """
    from database import models  # noqa: F401 -- registers tables on Base.metadata

    Base.metadata.create_all(bind=target_engine or engine)


def get_session():
    """FastAPI-style dependency: yields a session, always closes it after."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
