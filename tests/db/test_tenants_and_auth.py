"""Tests for tenant, user, connection models, schema constraints, and tenant isolation."""
import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.db.repository import TenantScopedRepository
from core.db.session import (
    TenantContext,
    TenantIsolationViolationError,
    create_db_engine,
    create_session_factory,
    get_current_tenant_id,
    init_db,
)
from core.models.tenants import CredentialReference, SourceConnection, Tenant, User


@pytest.fixture
def engine():
    """In-memory SQLite database engine with foreign keys enabled."""
    eng = create_db_engine("sqlite:///:memory:")
    init_db(eng)
    return eng


@pytest.fixture
def session_factory(engine):
    """Session factory for test cases."""
    return create_session_factory(engine)


@pytest.fixture
def db(session_factory):
    """Database session fixture with rollback."""
    session = session_factory()
    yield session
    session.rollback()
    session.close()


def create_sample_tenant(db, name="Acme Agency", slug="acme-agency", tier="growth"):
    """Helper to persist a test tenant."""
    tenant = Tenant(
        name=name,
        slug=slug,
        tier=tier,
        status="active",
        settings={"timezone": "America/New_York", "currency": "USD"},
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return tenant


class TestTenantAndUserModels:
    """Tests for model creation, relationships, and basic properties."""

    def test_tenant_creation_with_defaults(self, db):
        tenant = create_sample_tenant(db)
        assert tenant.id is not None
        assert tenant.name == "Acme Agency"
        assert tenant.slug == "acme-agency"
        assert tenant.tier == "growth"
        assert tenant.status == "active"
        assert tenant.settings["currency"] == "USD"
        assert tenant.created_at is not None
        assert tenant.updated_at is not None

    def test_user_creation_under_tenant(self, db):
        tenant = create_sample_tenant(db)
        user = User(
            tenant_id=tenant.id,
            email="admin@acme.com",
            full_name="Alice Admin",
            role="admin",
            auth_provider_id="keycloak-user-123",
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        assert user.id is not None
        assert user.tenant_id == tenant.id
        assert user.email == "admin@acme.com"
        assert user.role == "admin"
        assert user.tenant.slug == "acme-agency"
        assert len(tenant.users) == 1

    def test_source_connection_and_credential_reference_creation(self, db):
        tenant = create_sample_tenant(db)
        conn = SourceConnection(
            tenant_id=tenant.id,
            provider="meta_ads",
            name="Acme Meta Main",
            auth_type="oauth2",
            status="connected",
            settings={"account_id": "act_12345"},
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        assert conn.id is not None
        assert conn.tenant_id == tenant.id
        assert conn.provider == "meta_ads"

        cred = CredentialReference(
            tenant_id=tenant.id,
            connection_id=conn.id,
            vault_key_or_encrypted_blob="vault:secret/meta_token_enc",
        )
        db.add(cred)
        db.commit()
        db.refresh(cred)

        assert cred.id is not None
        assert cred.connection_id == conn.id
        assert len(conn.credential_references) == 1
        assert conn.credential_references[0].vault_key_or_encrypted_blob == "vault:secret/meta_token_enc"


class TestSchemaConstraints:
    """Tests for unique constraints and multi-tenant composite isolation."""

    def test_tenant_slug_uniqueness(self, db):
        create_sample_tenant(db, slug="agency-alpha")
        with pytest.raises(IntegrityError):
            duplicate_slug_tenant = Tenant(
                name="Agency Alpha Duplicate",
                slug="agency-alpha",
            )
            db.add(duplicate_slug_tenant)
            db.commit()
        db.rollback()

    def test_user_email_unique_within_same_tenant(self, db):
        tenant = create_sample_tenant(db)
        user1 = User(tenant_id=tenant.id, email="shared@agency.com", role="viewer")
        db.add(user1)
        db.commit()

        user2 = User(tenant_id=tenant.id, email="shared@agency.com", role="admin")
        db.add(user2)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_same_user_email_allowed_across_different_tenants(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a", name="Tenant A")
        tenant_b = create_sample_tenant(db, slug="tenant-b", name="Tenant B")

        user_a = User(tenant_id=tenant_a.id, email="consultant@agency.com", role="admin")
        user_b = User(tenant_id=tenant_b.id, email="consultant@agency.com", role="analyst")

        db.add(user_a)
        db.add(user_b)
        db.commit()

        assert user_a.id != user_b.id
        assert user_a.tenant_id == tenant_a.id
        assert user_b.tenant_id == tenant_b.id

    def test_source_connection_composite_unique_constraint(self, db):
        tenant = create_sample_tenant(db)
        conn1 = SourceConnection(
            tenant_id=tenant.id,
            provider="hubspot",
            name="Primary CRM",
            auth_type="api_key",
        )
        db.add(conn1)
        db.commit()

        # Duplicate (tenant_id, provider, name) should fail
        conn2 = SourceConnection(
            tenant_id=tenant.id,
            provider="hubspot",
            name="Primary CRM",
            auth_type="oauth2",
        )
        db.add(conn2)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_same_source_connection_name_allowed_across_different_tenants(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a")
        tenant_b = create_sample_tenant(db, slug="tenant-b")

        conn_a = SourceConnection(
            tenant_id=tenant_a.id,
            provider="stripe",
            name="Stripe Live",
            auth_type="webhook_secret",
        )
        conn_b = SourceConnection(
            tenant_id=tenant_b.id,
            provider="stripe",
            name="Stripe Live",
            auth_type="webhook_secret",
        )
        db.add(conn_a)
        db.add(conn_b)
        db.commit()

        assert conn_a.id != conn_b.id

    def test_credential_reference_composite_unique_constraint(self, db):
        tenant = create_sample_tenant(db)
        conn = SourceConnection(
            tenant_id=tenant.id,
            provider="meta_ads",
            name="Meta 1",
            auth_type="oauth2",
        )
        db.add(conn)
        db.commit()

        cred1 = CredentialReference(
            tenant_id=tenant.id,
            connection_id=conn.id,
            vault_key_or_encrypted_blob="blob-1",
        )
        db.add(cred1)
        db.commit()

        cred2 = CredentialReference(
            tenant_id=tenant.id,
            connection_id=conn.id,
            vault_key_or_encrypted_blob="blob-2",
        )
        db.add(cred2)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_cascade_deletion_on_tenant_removal(self, db):
        tenant = create_sample_tenant(db)
        user = User(tenant_id=tenant.id, email="alice@test.com")
        conn = SourceConnection(tenant_id=tenant.id, provider="stripe", name="Stripe", auth_type="api_key")
        db.add_all([user, conn])
        db.commit()

        cred = CredentialReference(tenant_id=tenant.id, connection_id=conn.id, vault_key_or_encrypted_blob="key")
        db.add(cred)
        db.commit()

        # Delete tenant
        db.delete(tenant)
        db.commit()

        # Users, connections, and credentials must be cascade deleted
        assert db.query(User).filter_by(tenant_id=tenant.id).first() is None
        assert db.query(SourceConnection).filter_by(tenant_id=tenant.id).first() is None
        assert db.query(CredentialReference).filter_by(tenant_id=tenant.id).first() is None


class TestTenantScopedRepository:
    """Tests for repository-level multi-tenant query filtering and isolation safeguards."""

    def test_repository_requires_tenant_context(self, db):
        with pytest.raises(TenantIsolationViolationError):
            TenantScopedRepository(User, db)

    def test_repository_with_explicit_tenant_id(self, db):
        tenant = create_sample_tenant(db)
        repo = TenantScopedRepository(User, db, tenant_id=tenant.id)
        assert repo.tenant_id == tenant.id

    def test_repository_with_tenant_context_manager(self, db):
        tenant = create_sample_tenant(db)
        with TenantContext(tenant.id):
            assert get_current_tenant_id() == tenant.id
            repo = TenantScopedRepository(User, db)
            assert repo.tenant_id == tenant.id
        assert get_current_tenant_id() is None

    def test_tenant_data_isolation_in_queries(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a")
        tenant_b = create_sample_tenant(db, slug="tenant-b")

        # Create user in Tenant A
        user_a = User(tenant_id=tenant_a.id, email="user.a@domain.com", full_name="User A")
        # Create user in Tenant B
        user_b = User(tenant_id=tenant_b.id, email="user.b@domain.com", full_name="User B")
        db.add_all([user_a, user_b])
        db.commit()

        # Repository scoped to Tenant A
        repo_a = TenantScopedRepository(User, db, tenant_id=tenant_a.id)
        # Repository scoped to Tenant B
        repo_b = TenantScopedRepository(User, db, tenant_id=tenant_b.id)

        # Tenant A repo should ONLY see User A
        users_in_a = repo_a.find_all()
        assert len(users_in_a) == 1
        assert users_in_a[0].id == user_a.id
        assert repo_a.get(user_b.id) is None
        assert repo_a.count() == 1

        # Tenant B repo should ONLY see User B
        users_in_b = repo_b.find_all()
        assert len(users_in_b) == 1
        assert users_in_b[0].id == user_b.id
        assert repo_b.get(user_a.id) is None
        assert repo_b.count() == 1

    def test_repository_blocks_cross_tenant_creation(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a")
        tenant_b = create_sample_tenant(db, slug="tenant-b")

        repo_a = TenantScopedRepository(User, db, tenant_id=tenant_a.id)

        # Attempt to insert an entity carrying Tenant B's ID into Tenant A's repository
        cross_tenant_user = User(tenant_id=tenant_b.id, email="infiltrator@domain.com")
        with pytest.raises(TenantIsolationViolationError) as exc_info:
            repo_a.create(cross_tenant_user)
        assert "Cross-tenant creation blocked" in str(exc_info.value)

    def test_repository_auto_stamps_tenant_id_when_unspecified(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a")
        repo_a = TenantScopedRepository(User, db, tenant_id=tenant_a.id)

        new_user = User(email="newbie@domain.com", full_name="Newbie")
        created = repo_a.create(new_user)
        db.commit()

        assert created.tenant_id == tenant_a.id
        assert repo_a.get(created.id) is not None

    def test_repository_blocks_cross_tenant_mutation_and_deletion(self, db):
        tenant_a = create_sample_tenant(db, slug="tenant-a")
        tenant_b = create_sample_tenant(db, slug="tenant-b")

        user_b = User(tenant_id=tenant_b.id, email="target@domain.com")
        db.add(user_b)
        db.commit()

        repo_a = TenantScopedRepository(User, db, tenant_id=tenant_a.id)

        # Attempt cross-tenant update
        with pytest.raises(TenantIsolationViolationError):
            repo_a.update(user_b)

        # Attempt cross-tenant delete
        with pytest.raises(TenantIsolationViolationError):
            repo_a.delete(user_b)

        # Attempt cross-tenant delete by id (should return False and NOT delete)
        deleted = repo_a.delete_by_id(user_b.id)
        assert deleted is False
        db.commit()

        # Verify user_b is still intact
        repo_b = TenantScopedRepository(User, db, tenant_id=tenant_b.id)
        assert repo_b.get(user_b.id) is not None
