# Salary Negotiation Agent

An interactive salary-negotiation simulator that lets a user negotiate with an AI recruiter, explore different recruiter personalities, and review negotiation outcomes and performance statistics.

This README covers the application architecture, local development, Docker deployment, environment configuration, API endpoints, Redis caching, troubleshooting, and common commands.

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Technology stack](#technology-stack)
- [Prerequisites](#prerequisites)
- [Project structure](#project-structure)
- [Configuration](#configuration)
- [Run the application with Docker](#run-the-application-with-docker-recommended)
- [Run the application locally](#run-the-application-locally)
- [Backend API](#backend-api)
- [Redis caching and rate limiting](#redis-caching-and-rate-limiting)
- [Database and persistence](#database-and-persistence)
- [Testing and verification](#testing-and-verification)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)

## Overview

The Salary Negotiation Agent simulates a conversation between a candidate and an AI recruiter. The backend orchestrates negotiation state and turns with LangGraph, invokes the configured language model, persists graph checkpoints and completed results, and exposes REST endpoints consumed by the Next.js frontend.

The application also includes Redis caching for frequently requested dashboard data and Redis-backed rate limiting for game creation and message submission.

## Architecture

```text
Browser
  |
  | http://localhost:3000
  v
Next.js frontend
  |
  | HTTP requests to http://localhost:8002
  v
FastAPI backend (container port 8000)
  |                 |                    |
  |                 |                    +--> LLM provider (configured by environment)
  |                 |
  |                 +--> Redis
  |                      - games cache (15-second TTL)
  |                      - stats cache (60-second TTL)
  |                      - rate-limit counters
  |
  +--> PostgreSQL
       - LangGraph checkpoints
       - completed game results
       - tactic/result analytics
```

### Local ports in the current setup

| Application | Host address | Notes |
|---|---|---|
| Salary Negotiation frontend | `http://localhost:3000` | Next.js UI |
| Salary Negotiation backend | `http://localhost:8002` | Host port mapped to container port `8000` |
| Backend API documentation | `http://localhost:8002/docs` | FastAPI Swagger UI |
| Redis | Internal Compose network | Backend uses `redis:6379`; Redis is not published to the host by the supplied Compose configuration |
| Enterprise Knowledge Platform | `http://localhost:8000` | Separate application; do not stop it to run this project |
| Text-to-SQL Agent | `http://localhost:8001` | Separate application |

The Salary Negotiation backend uses host port `8002` to avoid colliding with the Enterprise Knowledge Platform currently running on host port `8000`.

## Features

- AI-driven, multi-turn salary negotiation.
- LangGraph-based workflow and persisted conversation state.
- Configurable recruiter personalities (for example, `hardliner`, `friendly`, and `stalling`, if enabled by the current game configuration).
- Negotiation messages and offer tracking.
- Game result persistence and score summaries.
- Dashboard statistics by recruiter personality and negotiation tactic.
- PostgreSQL-backed LangGraph checkpoints and result tables.
- Redis cache for game-list and statistics responses.
- Redis-backed rate limits for game creation and message submission.
- Docker Compose deployment for frontend, backend, and Redis.

Feature availability and labels depend on the checked-out application code and frontend version.

## Technology stack

- **Frontend:** Next.js, React, TypeScript (as used by the frontend project).
- **Backend:** Python, FastAPI, Uvicorn.
- **Agent orchestration:** LangGraph.
- **LLM integration:** Configured provider/model (the project has used Groq; check the current environment and `complete_stage.py`).
- **Persistence:** PostgreSQL and LangGraph `PostgresSaver`.
- **Caching and rate limiting:** Redis 7.
- **Containers:** Docker and Docker Compose.

## Prerequisites

For Docker-based use:

1. Docker Desktop installed and running on Windows.
2. The application repository with its Docker Compose file and Dockerfiles.
3. A root `.env` file containing the required database and LLM configuration.
4. Network access to the configured PostgreSQL and LLM provider, when hosted externally.

For local development:

- A compatible Python version for the backend dependencies.
- Node.js and npm for the frontend.
- A configured PostgreSQL database.
- Redis is optional for local backend startup because the backend is designed to continue without Redis, but cache and rate-limit behavior will not be active when Redis is unavailable.

## Project structure

The exact repository layout can vary. The current Docker configuration expects a structure broadly similar to:

```text
Salary_neog/
├── backend/
│   ├── api.py
│   └── complete_stage.py
├── frontend/
│   ├── package.json
│   ├── package-lock.json
│   └── ...
├── requirement.txt
├── Dockerfile
├── docker-compose.yml
├── .dockerignore
├── .env                 # local secrets; do not commit
└── start_salary_negotiation.ps1  # optional local startup helper
```

The backend Dockerfile shared for this project copies `backend/` into the image and installs dependencies from the root-level `requirement.txt`. If your dependency file is named `requirements.txt` instead, update the Dockerfile copy instruction to match the actual filename.

The frontend Dockerfile uses `npm ci`, so `frontend/package-lock.json` should be present and committed.

## Configuration

Create a root `.env` file next to `docker-compose.yml`. Do not commit this file to source control.

The backend code requires `DATABASE_URL` for PostgreSQL and reads `REDIS_URL` from the environment. Compose should set `REDIS_URL=redis://redis:6379/0` for the backend container.

Example shape (replace placeholders with real values; do not include quotes unless your dotenv format requires them):

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

# Add the provider/model settings required by complete_stage.py.
GROQ_API_KEY=replace_with_your_key
GROQ_MODEL=replace_with_your_model

# Optional settings; defaults are shown here.
ALLOWED_ORIGIN=http://localhost:3000
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_CREATE_GAME=5
RATE_LIMIT_MESSAGES=10
```

Notes:

- The exact LLM environment-variable names depend on the current `complete_stage.py` and model initialization. Confirm them in that file before adding variables.
- Do not paste actual API keys or database passwords into this README.
- In Docker, use the Compose service name `redis` for Redis. `localhost` inside the backend container means the backend container itself, not the Redis container.
- The frontend API URL must point to `http://localhost:8002` for browser requests in the current local Docker setup. The frontend Dockerfile passes `NEXT_PUBLIC_API_URL` as a build argument; ensure the frontend code reads this variable and that the value is set before building.

## Run the application with Docker (recommended)

Run all commands from the project root, where `docker-compose.yml` or `compose.yaml` is located.

### 1. Start Docker Desktop

Open Docker Desktop and wait until its engine is running.

### 2. Validate the Compose configuration

```powershell
docker compose config
```

Resolve any errors before continuing.

### 3. Build and start the services

```powershell
docker compose up -d --build
```

This builds the images and starts the frontend, backend, and Redis in the background. The backend should be published as host port `8002` mapped to container port `8000`.

### 4. Check container status

```powershell
docker compose ps
```

Expected services are the frontend, backend, and Redis. Redis should eventually report healthy if the health check is configured.

### 5. Open the application

- Frontend: <http://localhost:3000>
- Backend Swagger docs: <http://localhost:8002/docs>
- Backend OpenAPI schema: <http://localhost:8002/openapi.json>

### 6. View logs

```powershell
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
docker compose logs --tail=100 redis
```

Follow logs live:

```powershell
docker compose logs -f
```

Press `Ctrl+C` to stop following logs. This does not stop the containers.

### 7. Start the project later

After Docker Desktop is running, from the project root:

```powershell
docker compose up -d
```

### 8. Rebuild after changing code or Docker files

```powershell
docker compose up -d --build
```

If you need a clean rebuild because stale build layers are suspected:

```powershell
docker compose build --no-cache
docker compose up -d
```

Use `--no-cache` only when necessary; it makes builds slower.

### 9. Stop the application

```powershell
docker compose down
```

This stops and removes this Compose project's containers and network. It does not normally delete the named Redis volume.

To remove the Redis volume and cached data too, run the following only if you intentionally want to clear it:

```powershell
docker compose down -v
```

Do not use `docker stop` or `docker compose down` from another project's directory to manage this application; target the Salary Negotiation project's Compose file.

## Run the application locally

Local mode is useful when editing code and debugging. Do not run a local backend on port `8002` at the same time as the Docker backend published on that port.

### Start the backend

Open PowerShell in the backend directory:

```powershell
cd C:\Users\ritik.gupta\Downloads\Salary_neog\backend
```

Activate the virtual environment. If the environment is at the project root:

```powershell
..\venv\Scripts\Activate.ps1
```

If it is inside the backend directory instead:

```powershell
.\venv\Scripts\Activate.ps1
```

Install dependencies using the actual dependency file path/name in your repository, if needed. For a root-level `requirement.txt`:

```powershell
python -m pip install -r ..\requirement.txt
```

Start the backend locally:

```powershell
python -m uvicorn api:api --reload --host 127.0.0.1 --port 8002
```

This assumes `backend/api.py` defines the FastAPI instance named `api`. Keep the terminal open.

### Start the frontend

Open a second PowerShell terminal:

```powershell
cd C:\Users\ritik.gupta\Downloads\Salary_neog\frontend
npm ci
npm run dev
```

Open <http://localhost:3000>.

Ensure the frontend's local environment configuration points to:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8002
```

Restart the Next.js development server after changing environment variables.

### Local Redis behavior

The backend can continue when Redis is unavailable, but caching and Redis-backed rate limiting are disabled in that case. If you want to test caching locally, start Redis and set `REDIS_URL` to the address reachable from the local Python process, such as `redis://localhost:6379/0` when Redis publishes that port on the host. This local URL differs from the Compose service URL.

## Backend API

The routes below are defined by the provided backend code. Request bodies and response shapes can evolve with the implementation.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/games` | List recent games from LangGraph checkpoints |
| `POST` | `/games` | Create a new negotiation game |
| `GET` | `/games/{game_id}` | Retrieve the current state of a game |
| `POST` | `/games/{game_id}/messages` | Submit a candidate message and advance the negotiation |
| `GET` | `/stats` | Return completed-game, personality, tactic, and score statistics |

Interactive API documentation is available at `http://localhost:8002/docs` when the Docker backend is running.

### Example API checks in PowerShell

List games:

```powershell
Invoke-RestMethod http://localhost:8002/games
```

Read statistics:

```powershell
Invoke-RestMethod http://localhost:8002/stats
```

Inspect registered paths:

```powershell
(Invoke-RestMethod http://localhost:8002/openapi.json).paths.PSObject.Properties.Name
```

An empty games list or zero scores can be a valid response if no games have been saved yet. A `404` for the routes above usually means the request reached the wrong application/port or the running backend does not contain the expected routes.

## Redis caching and rate limiting

The backend code implements Redis cache helpers and optional Redis rate limiting.

### Cache behavior

| Data | Redis key | TTL |
|---|---|---:|
| Game list | `salary_agent:games` | 15 seconds |
| Dashboard statistics | `salary_agent:stats` | 60 seconds |

The backend invalidates both cache keys after game creation and after a negotiation message is processed successfully. Redis failures are logged and treated as cache misses or skipped cache writes so the backend can continue without caching.

### Rate limiting

The backend uses an atomic Redis Lua script to count requests in a fixed time window.

| Action | Default limit | Default window |
|---|---:|---:|
| Create a game | 5 requests | 60 seconds |
| Submit a message | 10 requests | 60 seconds |

These values can be configured with `RATE_LIMIT_CREATE_GAME`, `RATE_LIMIT_MESSAGES`, and `RATE_LIMIT_WINDOW_SECONDS`. When the limit is exceeded, the API returns HTTP `429 Too Many Requests` with a `Retry-After` header. If Redis is unavailable, the current implementation fails open and logs the failure.

### Redis checks

Check service status:

```powershell
docker compose ps redis
```

Inspect Redis logs:

```powershell
docker compose logs --tail=100 redis
```

Ping Redis from its container:

```powershell
docker compose exec redis redis-cli ping
```

Expected output:

```text
PONG
```

## Database and persistence

PostgreSQL is the authoritative persistence layer in the backend:

- LangGraph checkpoints store graph/thread state.
- Result tables store completed negotiation outcomes and scoring/analytics data.
- The backend runs database setup during application startup.

The backend expects `DATABASE_URL` to be set. The exact URL depends on whether PostgreSQL is hosted by Neon or another provider, or is running locally/in Docker. A database hostname such as `localhost` inside a container usually refers to that same container; use the appropriate host reachable from the container.

Do not point the Salary Negotiation Agent at another application's database unless that is intentional and the schemas are compatible.

## Testing and verification

### Basic startup checks

1. `docker compose ps` shows frontend, backend, and Redis running.
2. `http://localhost:3000` loads the frontend.
3. `http://localhost:8002/docs` shows the Salary Negotiation Simulator API.
4. `GET /games` returns a response.
5. `GET /stats` returns a response.
6. Redis health check passes and `redis-cli ping` returns `PONG`.

### Check caching

Call `/stats` twice and inspect backend logs for cache-hit messages. The first call may query PostgreSQL; a subsequent call within the 60-second TTL can be served from Redis unless the cache was invalidated or Redis is unavailable.

For meaningful performance comparisons, record multiple uncached and cached measurements under the same conditions, and report the number of runs and the average/median latency. Do not infer performance from a single request.

### Testing scripts

The repository may contain local-only scripts such as:

- `testing_groq.py`
- `testing_hugging.py`
- `testing_open_router.py`

These are for manual provider testing and are intentionally excluded from the Docker build context by `.dockerignore`. They remain available on your host machine.

## Troubleshooting

### Frontend loads but shows `Not Found`

Check the browser's Network tab and confirm requests use `http://localhost:8002`, not port `8000`. In this setup, port `8000` belongs to the separate Enterprise Knowledge Platform. Check the backend OpenAPI schema to confirm the expected routes are registered.

### Port is already in use

Check the process listening on a port:

```powershell
Get-NetTCPConnection -LocalPort 8002 -State Listen
```

Do not stop processes blindly: identify the owning process first. Keep the other applications on ports `8000` and `8001` running.

### Backend container exits

```powershell
docker compose logs --tail=200 backend
```

Look for missing environment variables, database connectivity failures, missing Python packages, or an incorrect Uvicorn module path. The current backend image expects `api.py` at `/app/api.py` and a FastAPI instance named `api`.

### `ModuleNotFoundError`

Confirm that the backend Docker build installs the correct dependency file and copies the intended backend source. For local development, activate the correct virtual environment and install dependencies from the repository's dependency file.

### Database connection error

Verify `DATABASE_URL`, database availability, SSL options required by the provider, and whether the hostname is reachable from inside Docker. Review backend logs for the complete error.

### Redis unavailable

Check `docker compose ps` and `docker compose logs redis`. In Docker, the backend's Redis URL should normally be `redis://redis:6379/0`, where `redis` is the Compose service name.

### Frontend API URL is stale

`NEXT_PUBLIC_*` values can be embedded at frontend build time. Confirm the frontend Docker build receives `NEXT_PUBLIC_API_URL=http://localhost:8002`, then rebuild the frontend:

```powershell
docker compose build frontend
docker compose up -d frontend
```

### Rebuild does not reflect changes

Confirm you edited the files used by the current Docker build context and that `.dockerignore` is not excluding required source files. Rebuild the affected service after checking its Dockerfile and Compose configuration.

## Security notes

- Never commit `.env` or real credentials to Git.
- Use a secret manager or deployment platform's secret mechanism for production credentials.
- Do not expose Redis publicly unless there is a specific secured operational need.
- The current backend rate limiter fails open when Redis is unavailable. If rate limiting is a security requirement in production, consider changing that behavior and monitoring Redis failures.
- The provided CORS configuration defaults to `http://localhost:3000`; configure `ALLOWED_ORIGIN` appropriately for the deployed frontend.
- Use production server settings for deployment. `--reload` is intended for local development, not production.
- Keep dependencies and base images updated, and rebuild images after security updates.

## Quick command reference

| Task | Command |
|---|---|
| Validate Compose | `docker compose config` |
| Build and launch | `docker compose up -d --build` |
| Check services | `docker compose ps` |
| Follow all logs | `docker compose logs -f` |
| Backend logs | `docker compose logs -f backend` |
| Rebuild frontend | `docker compose build frontend` |
| Start without rebuilding | `docker compose up -d` |
| Stop this Compose app | `docker compose down` |
| Check Redis | `docker compose exec redis redis-cli ping` |
| Local backend | `python -m uvicorn api:api --reload --host 127.0.0.1 --port 8002` |

---

**Maintainer note:** This documentation reflects the backend code and Docker configuration shared for this project. Before committing it, verify that the service names, dependency filename, frontend scripts, `.env` variable names, and `NEXT_PUBLIC_API_URL` handling match the current repository.
