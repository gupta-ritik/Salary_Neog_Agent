# Salary Negotiation Agent Docker setup

This setup runs three containers:
- `frontend`: Next.js on host port 3000
- `backend`: FastAPI on host port 8002 (container port 8000)
- `redis`: internal Redis cache at `redis:6379`

The Enterprise Knowledge Platform on port 8000 and Text-to-SQL Agent on port 8001 are not changed.

## Assumptions to verify
1. The root project contains `requirement.txt` (singular), as shown in the provided directory listing.
2. `backend/api.py` defines `api = FastAPI(...)`.
3. `frontend/package-lock.json` exists and the frontend has `build` and `start` scripts.
4. The root `.env` contains `DATABASE_URL` and required LLM credentials. Do not commit `.env`.
5. The frontend reads `NEXT_PUBLIC_API_URL` for browser API requests.

## Run
From the project root:
```powershell
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 backend
docker compose logs --tail=100 frontend
```

Open:
- Frontend: http://localhost:3000
- Backend docs: http://localhost:8002/docs

## Stop only this project
```powershell
docker compose down
```
This does not delete the Redis volume. To delete cached Redis data too, use `docker compose down -v` only if you intentionally want to clear it.

## Important checks
- If the dependency file is actually `requirements.txt`, change `COPY requirement.txt ./requirements.txt` in the root Dockerfile to `COPY requirements.txt ./requirements.txt`.
- If there is no `frontend/package-lock.json`, replace `RUN npm ci` with `RUN npm install` in `frontend/Dockerfile`, though committing a lockfile is preferred.
- If the frontend is configured to call a hard-coded `http://localhost:8000`, update its API base URL to use `process.env.NEXT_PUBLIC_API_URL || "http://localhost:8002"`.
- The backend uses the `redis` hostname inside Compose. Do not set `REDIS_URL` to `localhost` inside the backend container.
- Docker Compose reads `.env` for interpolation, and `env_file: .env` passes its values into the backend container. Keep secrets out of image layers and source control.
