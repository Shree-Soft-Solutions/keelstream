#!/usr/bin/env bash
# =============================================================================
# KeelStream Local Environment Provisioning & Health Verification Script
# Spins up PostgreSQL 16, Redis 7, MinIO S3, and Keycloak 24+ containers.
# =============================================================================

set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
NC="\033[0m"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo -e "${BOLD}${CYAN}====================================================${NC}"
echo -e "${BOLD}${CYAN}   KeelStream Local Container Stack Provisioner     ${NC}"
echo -e "${BOLD}${CYAN}====================================================${NC}"

# 1. Check prerequisites
if ! command -v docker &> /dev/null; then
  echo -e "${RED}[ERROR] Docker is not installed or not in PATH.${NC}"
  echo "Please install Docker Desktop or Engine: https://docs.docker.com/get-docker/"
  exit 1
fi

if ! docker compose version &> /dev/null; then
  echo -e "${RED}[ERROR] Docker Compose (v2) is not available.${NC}"
  exit 1
fi

# 2. Setup environment variables
if [ ! -f .env ]; then
  echo -e "${YELLOW}[!] .env not found. Copying defaults from .env.example...${NC}"
  cp .env.example .env
  echo -e "${GREEN}[✓] .env initialized.${NC}"
else
  echo -e "${GREEN}[✓] .env found.${NC}"
fi

# 3. Create required directory mounts if not present
mkdir -p scripts/init-db config/keycloak

# 4. Parse optional arguments
PROFILE_FLAG=""
if [[ "${1:-}" == "--with-n8n" || "${1:-}" == "--all" ]]; then
  echo -e "${CYAN}[*] Enabling n8n workflow orchestration profile...${NC}"
  PROFILE_FLAG="--profile workflows"
fi

# 5. Spin up Docker containers
echo -e "${CYAN}[*] Starting container services in detached mode...${NC}"
docker compose $PROFILE_FLAG up -d

# 6. Polling health status
echo -e "${CYAN}[*] Polling container health checks (max 90s)...${NC}"
SERVICES=("keelstream-postgres" "keelstream-redis" "keelstream-minio" "keelstream-keycloak")
TIMEOUT=90
ELAPSED=0

for SERVICE in "${SERVICES[@]}"; do
  echo -n "Waiting for $SERVICE to report healthy... "
  ELAPSED=0
  while true; do
    STATUS=$(docker inspect --format='{{json .State.Health.Status}}' "$SERVICE" 2>/dev/null || echo "\"starting\"")
    STATUS=$(echo "$STATUS" | tr -d '"')

    if [ "$STATUS" = "healthy" ]; then
      echo -e "${GREEN}HEALTHY${NC}"
      break
    elif [ "$STATUS" = "unhealthy" ]; then
      echo -e "${RED}UNHEALTHY!${NC}"
      echo -e "${RED}Logs for $SERVICE:${NC}"
      docker logs --tail 25 "$SERVICE"
      exit 1
    fi

    sleep 3
    ELAPSED=$((ELAPSED + 3))
    if [ $ELAPSED -ge $TIMEOUT ]; then
      echo -e "${YELLOW}TIMEOUT (proceeding with caution)${NC}"
      break
    fi
    echo -n "."
  done
done

# 7. Endpoint connectivity checks
echo -e "\n${BOLD}${GREEN}====================================================${NC}"
echo -e "${BOLD}${GREEN}   KeelStream Local Environment Ready!             ${NC}"
echo -e "${BOLD}${GREEN}====================================================${NC}"
echo -e "Service Endpoints:"
echo -e "  - ${BOLD}PostgreSQL 16:${NC} localhost:5432 (User: keelstream, DB: db_keelstream_core)"
echo -e "  - ${BOLD}Redis 7:${NC}       localhost:6379"
echo -e "  - ${BOLD}MinIO S3 API:${NC}  http://localhost:9000 (Access: minioadmin / minioadmin)"
echo -e "  - ${BOLD}MinIO Console:${NC} http://localhost:9001"
echo -e "  - ${BOLD}Keycloak IAM:${NC}  http://localhost:8080 (Admin: admin / admin)"
if [[ "$PROFILE_FLAG" != "" ]]; then
  echo -e "  - ${BOLD}n8n Workflows:${NC} http://localhost:5678"
fi
echo -e "----------------------------------------------------"
echo -e "To view live logs:    ${CYAN}docker compose logs -f${NC}"
echo -e "To stop containers:   ${CYAN}docker compose down${NC}"
echo -e "====================================================\n"
