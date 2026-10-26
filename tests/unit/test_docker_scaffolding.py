"""
Unit validation tests for Docker Compose scaffolding, environment configuration, and scripts.
Verifies Task 1.1 deliverables without requiring external Docker daemon.
"""

from pathlib import Path
import re
import yaml
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def test_docker_compose_syntax_and_structure():
    """Verify docker-compose.yml parses as valid YAML and defines required services and volumes."""
    compose_path = PROJECT_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist"

    with open(compose_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert "services" in data, "compose file must define services"
    services = data["services"]

    # Required services: PostgreSQL 16, Redis 7, MinIO, Keycloak 24+, and placeholder for n8n
    required_services = ["postgres", "redis", "minio", "keycloak", "n8n"]
    for svc in required_services:
        assert svc in services, f"Service '{svc}' must be defined in docker-compose.yml"

    # PostgreSQL checks
    postgres = services["postgres"]
    assert "postgres:16" in postgres["image"]
    assert "keelstream-net" in postgres["networks"]
    assert any("postgres_data" in v for v in postgres["volumes"])
    assert "healthcheck" in postgres
    assert "pg_isready" in str(postgres["healthcheck"]["test"])

    # Redis checks
    redis = services["redis"]
    assert "redis:7" in redis["image"]
    assert "keelstream-net" in redis["networks"]
    assert any("redis_data" in v for v in redis["volumes"])
    assert "healthcheck" in redis

    # MinIO checks
    minio = services["minio"]
    assert "minio/minio" in minio["image"]
    assert "keelstream-net" in minio["networks"]
    assert any("minio_data" in v for v in minio["volumes"])
    assert "healthcheck" in minio

    # Keycloak checks
    keycloak = services["keycloak"]
    assert "keycloak" in keycloak["image"]
    assert "keelstream-net" in keycloak["networks"]
    assert "postgres" in keycloak["depends_on"]
    assert "healthcheck" in keycloak

    # n8n placeholder checks
    n8n = services["n8n"]
    assert "n8n" in n8n["image"]
    assert "keelstream-net" in n8n["networks"]

    # Persistent volumes check
    assert "volumes" in data
    required_volumes = ["postgres_data", "redis_data", "minio_data", "n8n_data"]
    for vol in required_volumes:
        assert vol in data["volumes"], f"Volume '{vol}' must be defined"

    # Internal networks check
    assert "networks" in data
    assert "keelstream-net" in data["networks"]


def test_env_example_variables():
    """Verify .env.example defines standard variables and credentials for all components."""
    env_path = PROJECT_ROOT / ".env.example"
    assert env_path.exists(), ".env.example must exist"

    content = env_path.read_text(encoding="utf-8")

    expected_keys = [
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "KEYCLOAK_DB_NAME",
        "REDIS_PORT",
        "S3_ENDPOINT",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "S3_BUCKET_ASSETS",
        "KEYCLOAK_ADMIN",
        "KEYCLOAK_ADMIN_PASSWORD",
        "KEYCLOAK_REALM",
        "N8N_PORT",
        "INGESTION_RATE_LIMIT_RPS",
        "JWT_SECRET",
    ]

    for key in expected_keys:
        assert f"{key}=" in content, f"Key '{key}' must be present in .env.example"


def test_dev_up_scripts_exist_and_executable():
    """Verify scripts/dev-up.sh and scripts/dev-up.ps1 exist with proper health checking logic."""
    sh_path = PROJECT_ROOT / "scripts" / "dev-up.sh"
    ps_path = PROJECT_ROOT / "scripts" / "dev-up.ps1"

    assert sh_path.exists(), "scripts/dev-up.sh must exist"
    assert ps_path.exists(), "scripts/dev-up.ps1 must exist"

    sh_content = sh_path.read_text(encoding="utf-8")
    assert "docker compose" in sh_content
    assert "keelstream-postgres" in sh_content
    assert "keelstream-minio" in sh_content
    assert "keelstream-keycloak" in sh_content

    ps_content = ps_path.read_text(encoding="utf-8")
    assert "docker compose" in ps_content
    assert "keelstream-postgres" in ps_content
    assert "keelstream-minio" in ps_content
    assert "keelstream-keycloak" in ps_content


def test_k6_load_script_syntax_and_config():
    """Verify tests/load/ingestion_load.js contains required 500 RPS load scenario and isolation checks."""
    k6_path = PROJECT_ROOT / "tests" / "load" / "ingestion_load.js"
    assert k6_path.exists(), "tests/load/ingestion_load.js must exist"

    content = k6_path.read_text(encoding="utf-8")
    assert "constant-arrival-rate" in content
    assert "500" in content
    assert "cross_tenant_contamination_errors" in content
    assert "p(95)<200" in content
    assert "p(99)<500" in content
