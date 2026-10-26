# KeelStream

KeelStream is a revenue attribution and performance intelligence project. This repository currently includes a containerized local development stack and a Vue attribution dashboard.

## Prerequisites

- Git
- A running container engine with Compose support:
  - Docker Desktop / Docker Compose v2, or
  - Podman with `podman compose` and a working Compose provider
- For running the frontend outside containers or building it locally: Node.js 20 or newer and npm

On Windows, run the commands below in PowerShell. On macOS or Linux, use a shell from the project root and replace `Copy-Item` with `cp` where needed.

## Start the project

1. Clone the repository and open its root directory:

   ```powershell
   cd keelstream
   ```

2. Create your local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

   Review `.env` and change any ports that are already in use. For example, if port `8080` is occupied, set `KEYCLOAK_PORT=8081`. If you change that port, also update `KEYCLOAK_URL` and `KEYCLOAK_ISSUER_URL` to use `8081`.

   The credentials in `.env.example` are development defaults only. Do not use them in a shared or production environment, and do not commit `.env`.

3. Build and start the stack. Choose the command for your container engine:

   ```powershell
   # Docker
   docker compose up --build -d

   # Podman
   podman compose up --build -d
   ```

   The first start downloads the container images and builds the frontend image, so it may take a few minutes. PostgreSQL initializes its additional databases on the first start using `scripts/init-db/`.

4. Check service status:

   ```powershell
   # Use the same engine command as above
   docker compose ps
   # or
   podman compose ps
   ```

   Wait for the database, Redis, object storage, and Keycloak health checks to pass. Then open the dashboard at <http://localhost:3000>.

## Local services

| Service | Local address | Notes |
| --- | --- | --- |
| Attribution dashboard | <http://localhost:3000> | Vue app served by Nginx; host port is `FRONTEND_PORT`. |
| Keycloak | <http://localhost:8080> | Host port is `KEYCLOAK_PORT`; development admin credentials are in `.env`. |
| PostgreSQL | `localhost:5432` | Main database: `db_keelstream_core`; user, password, and port are in `.env`. |
| Redis | `localhost:6379` | Host port is `REDIS_PORT`. |
| RustFS S3 API | <http://localhost:9000> | S3-compatible endpoint; credentials are in `.env`. |
| RustFS console | <http://localhost:9001> | Host port is `S3_CONSOLE_PORT`. |
| n8n (optional) | <http://localhost:5678> | Starts only with the `workflows` profile. |

Compose publishes these ports by default: `3000`, `8080`, `5432`, `6379`, `9000`, `9001`, and (when enabled) `5678`. If one is already in use, change its corresponding host port in `.env` before starting the stack. The port before the colon in each Compose mapping is the host port.

## Optional services and development

Start the optional n8n workflow service along with the default stack:

```powershell
docker compose --profile workflows up --build -d
# or
podman compose --profile workflows up --build -d
```

To work on the frontend directly with Vite instead of the container:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Vite prints the local development URL (normally <http://localhost:5173>). To make a production frontend build, run `npm run build` from `frontend`.

## Common commands

Run these from the repository root, using `docker compose` or `podman compose` consistently:

```powershell
# Follow logs
podman compose logs -f

# Follow one service
podman compose logs -f frontend

# Stop and remove containers and the network, preserving named data volumes
podman compose down

# Stop the default services and optional profile services
podman compose --profile workflows down
```

To remove persistent database, Redis, RustFS, and n8n data as well, use `podman compose down -v` (or `docker compose down -v`). This permanently deletes local service data.

## Current project scope

The frontend currently displays the attribution dashboard with local mock data. Although the Compose stack includes Keycloak, the frontend is not yet wired to authentication or a backend API. The Python modules and tests in `core/` and `tests/` are project components, not a separately configured API service in Compose. Refer to [`plan/plan.md`](plan/plan.md) for implementation status and planned work.
