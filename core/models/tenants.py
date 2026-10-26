"""Tenant, User, Source Connection, and Credential Reference database models."""
from typing import Any, Dict, List, Optional
from datetime import datetime
from sqlalchemy import (
    DateTime,
    ForeignKey,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.models.base import Base, TenantScopedMixin, TimestampMixin, generate_uuid


class Tenant(Base, TimestampMixin):
    """Tenant model representing an agency or customer organization."""
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )
    tier: Mapped[str] = mapped_column(
        String(50),
        default="starter",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="active",
        nullable=False,
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    source_connections: Mapped[List["SourceConnection"]] = relationship(
        "SourceConnection",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Tenant id={self.id} slug={self.slug} tier={self.tier}>"


class User(Base, TenantScopedMixin, TimestampMixin):
    """User account scoped strictly to a single tenant organization."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(
        String(50),
        default="viewer",
        nullable=False,
    )
    auth_provider_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    # Relationship to Tenant
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="users",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} tenant_id={self.tenant_id} email={self.email} role={self.role}>"


class SourceConnection(Base, TenantScopedMixin, TimestampMixin):
    """External platform connection (e.g., Meta Ads, HubSpot, Stripe) for a tenant."""
    __tablename__ = "source_connections"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    auth_type: Mapped[str] = mapped_column(
        String(50),
        default="oauth2",
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    settings: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        back_populates="source_connections",
    )
    credential_references: Mapped[List["CredentialReference"]] = relationship(
        "CredentialReference",
        back_populates="connection",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "provider",
            "name",
            name="uq_source_connections_tenant_provider_name",
        ),
    )

    def __repr__(self) -> str:
        return f"<SourceConnection id={self.id} tenant_id={self.tenant_id} provider={self.provider} name={self.name}>"


class CredentialReference(Base, TenantScopedMixin, TimestampMixin):
    """Secure credential reference or encrypted token blob tied to a source connection."""
    __tablename__ = "credential_references"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=generate_uuid,
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("source_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    vault_key_or_encrypted_blob: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Relationships
    connection: Mapped["SourceConnection"] = relationship(
        "SourceConnection",
        back_populates="credential_references",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "connection_id",
            name="uq_credential_references_tenant_connection",
        ),
    )

    def __repr__(self) -> str:
        return f"<CredentialReference id={self.id} tenant_id={self.tenant_id} connection_id={self.connection_id}>"
