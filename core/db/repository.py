"""Tenant-scoped generic repository ensuring strict multi-tenant boundary enforcement."""
from typing import Any, Generic, List, Optional, Type, TypeVar
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.session import TenantIsolationViolationError, get_current_tenant_id
from core.models.base import Base

T = TypeVar("T", bound=Base)


class TenantScopedRepository(Generic[T]):
    """Generic repository that guarantees all queries, insertions, and mutations

    are strictly constrained to the specified tenant_id.
    """

    def __init__(
        self,
        model_cls: Type[T],
        session: Session,
        tenant_id: Optional[str] = None,
    ):
        self.model_cls = model_cls
        self.session = session

        resolved_tenant_id = tenant_id or get_current_tenant_id()
        if not resolved_tenant_id:
            raise TenantIsolationViolationError(
                f"Tenant context is required to initialize {self.__class__.__name__} for {model_cls.__name__}"
            )

        if not hasattr(model_cls, "tenant_id"):
            raise TypeError(
                f"Model {model_cls.__name__} does not have a 'tenant_id' attribute and cannot be tenant-scoped"
            )

        self.tenant_id: str = resolved_tenant_id

    def get(self, id: str) -> Optional[T]:
        """Fetch a single record by primary key, strictly within the tenant boundary."""
        stmt = select(self.model_cls).where(
            self.model_cls.id == id,
            self.model_cls.tenant_id == self.tenant_id,
        )
        return self.session.scalars(stmt).first()

    def get_or_fail(self, id: str) -> T:
        """Fetch a single record by primary key or raise TenantIsolationViolationError / KeyError."""
        record = self.get(id)
        if record is None:
            raise LookupError(
                f"{self.model_cls.__name__} with id='{id}' not found for tenant '{self.tenant_id}'"
            )
        return record

    def find_one(self, **filters: Any) -> Optional[T]:
        """Find the first matching entity matching filters, scoped to the tenant."""
        stmt = select(self.model_cls).where(self.model_cls.tenant_id == self.tenant_id)
        for key, value in filters.items():
            if hasattr(self.model_cls, key):
                stmt = stmt.where(getattr(self.model_cls, key) == value)
        return self.session.scalars(stmt).first()

    def find_all(
        self,
        skip: int = 0,
        limit: int = 100,
        **filters: Any,
    ) -> List[T]:
        """Query multiple entities strictly scoped to the tenant with pagination."""
        stmt = select(self.model_cls).where(self.model_cls.tenant_id == self.tenant_id)
        for key, value in filters.items():
            if hasattr(self.model_cls, key):
                stmt = stmt.where(getattr(self.model_cls, key) == value)
        stmt = stmt.offset(skip).limit(limit)
        return list(self.session.scalars(stmt).all())

    def count(self, **filters: Any) -> int:
        """Count entities matching criteria within the tenant boundary."""
        stmt = select(func.count(self.model_cls.id)).where(
            self.model_cls.tenant_id == self.tenant_id
        )
        for key, value in filters.items():
            if hasattr(self.model_cls, key):
                stmt = stmt.where(getattr(self.model_cls, key) == value)
        return self.session.scalar(stmt) or 0

    def create(self, entity: T) -> T:
        """Persist a new entity, asserting or stamping the tenant_id boundary."""
        # Check tenant_id constraint
        entity_tenant_id = getattr(entity, "tenant_id", None)
        if entity_tenant_id is not None and entity_tenant_id != self.tenant_id:
            raise TenantIsolationViolationError(
                f"Cross-tenant creation blocked: cannot insert record with tenant_id='{entity_tenant_id}' "
                f"into repository scoped to tenant_id='{self.tenant_id}'"
            )

        setattr(entity, "tenant_id", self.tenant_id)
        self.session.add(entity)
        self.session.flush()
        return entity

    def update(self, entity: T) -> T:
        """Update an existing entity, strictly verifying tenant ownership."""
        entity_tenant_id = getattr(entity, "tenant_id", None)
        if entity_tenant_id != self.tenant_id:
            raise TenantIsolationViolationError(
                f"Cross-tenant update blocked: entity belongs to tenant '{entity_tenant_id}', "
                f"not current repository tenant '{self.tenant_id}'"
            )
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        """Delete an entity, verifying that it belongs to the current tenant."""
        entity_tenant_id = getattr(entity, "tenant_id", None)
        if entity_tenant_id != self.tenant_id:
            raise TenantIsolationViolationError(
                f"Cross-tenant deletion blocked: entity belongs to tenant '{entity_tenant_id}', "
                f"not current repository tenant '{self.tenant_id}'"
            )
        self.session.delete(entity)
        self.session.flush()

    def delete_by_id(self, id: str) -> bool:
        """Delete a record by primary key if it belongs to the current tenant."""
        record = self.get(id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.flush()
        return True
