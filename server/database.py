"""PostgreSQL engine and session helpers."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base


def build_engine(database_url: str) -> Engine:
    options: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite:"):
        options["connect_args"] = {"check_same_thread": False}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            options["poolclass"] = StaticPool
    else:
        options["pool_size"] = 5
        options["max_overflow"] = 10
        options["connect_args"] = {"connect_timeout": 5}
    return create_engine(database_url, **options)


def build_session_factory(engine: Engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def initialize_database(engine: Engine) -> None:
    """Create the small Task 4 schema on first run.

    For a production deployment, replace create_all with versioned migrations.
    """

    Base.metadata.create_all(engine)


def check_database(engine: Engine) -> bool:
    with engine.connect() as connection:
        return connection.execute(text("SELECT 1")).scalar_one() == 1
