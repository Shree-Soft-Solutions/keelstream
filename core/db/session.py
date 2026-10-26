"""Database engine, session management, and tenant context isolation."""
import contextvars
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base

# Thread-safe and async-safe context variable for tenant isolation
_current_tenant_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_tenant_id",
    default=None,
)


class TenantIsolationViolationError(Exception):
    """Raised when an operation violates strict multi-tenant isolation boundaries."""
    pass


def get_current_tenant_id() -> Optional[str]:
    """Retrieve the active tenant ID from context."""
    return _current_tenant_id.get()


def set_current_tenant_id(tenant_id: str) -> contextvars.Token:
    """Set the active tenant ID in context."""
    if not tenant_id:
        raise TenantIsolationViolationError("Tenant ID cannot be empty or None")
    return _current_tenant_id.set(tenant_id)


def reset_current_tenant_id(token: contextvars.Token) -> None:
    """Reset the tenant context using the saved token."""
    _current_tenant_id.reset(token)


class TenantContext:
    """Context manager to scope operations to a specific tenant."""

    def __init__(self, tenant_id: str):
        if not tenant_id:
            raise TenantIsolationViolationError("Tenant ID is required for TenantContext")
        self.tenant_id = tenant_id
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> str:
        self._token = set_current_tenant_id(self.tenant_id)
        return self.tenant_id

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._token is not None:
            reset_current_tenant_id(self._token)


@event.listens_for(Engine, "connect")
def _enforce_sqlite_foreign_keys(dbapi_connection, connection_record):
    """Enforce foreign key constraints when using SQLite engines."""
    # Check if SQLite connection
    if hasattr(dbapi_connection, "cursor"):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        except Exception:
            pass
        finally:
            cursor.close()


def create_db_engine(db_url: str = "sqlite:///:memory:", echo: bool = False) -> Engine:
    """Create a SQLAlchemy engine configured for KeelStream."""
    engine_kwargs = {"echo": echo}
    if db_url.startswith("sqlite"):
        engine_kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in db_url:
            engine_kwargs["poolclass"] = StaticPool
    return create_engine(db_url, **engine_kwargs)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a thread-safe session factory for the engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db(engine: Engine) -> None:
    """Create all schema tables in the target database."""
    # Ensure all model tables are registered with Base.metadata
    import core.models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def drop_db(engine: Engine) -> None:
    """Drop all tables from the target database."""
    import core.models  # noqa: F401
    Base.metadata.drop_all(bind=engine)


@contextmanager
def get_db_session(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    """Context manager providing a transactional database session."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
