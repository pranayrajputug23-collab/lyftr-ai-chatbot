# Lyftr AI

Lyftr AI is a React/Vite chat frontend and FastAPI backend. The backend uses LiteLLM for model requests, ordered API-key failover and response caching, with SQLite for conversation history.

## Live URLs

No public deployment has been configured or verified. For local Docker runs:

- Frontend: <http://localhost:3000>
- Backend readiness: <http://localhost:8000/health>

## Run locally: with Docker and without

### Docker prerequisites

- Docker Desktop for Windows with the WSL 2 backend, or Docker Engine and the Docker Compose plugin on another operating system.
- GNU Make for the `make` shortcuts. On Windows, run Make from WSL or another shell that provides GNU Make. If `make` is unavailable, the equivalent `docker compose` commands are shown below.
- Two valid provider API keys for live AI replies and failover. The app can start without keys, but its health endpoint will report that the backend is not ready and chat requests cannot succeed.

### Install and start Docker Desktop on Windows

1. Check Docker's current Windows requirements and download instructions at [Install Docker Desktop on Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
2. Download and run the Docker Desktop installer. The per-user installation and WSL 2 backend are the usual choices for a personal development machine.
3. Restart Windows if the installer requests it, then launch **Docker Desktop** from the Start menu.
4. Wait for Docker Desktop to show that the engine is running. In PowerShell, confirm `docker --version` and `docker compose version` both work.

Docker Desktop's supported Windows versions and WSL requirements can change, so use the linked Docker guide for current system requirements.

### Configure keys and start the containers

From the project root, make a local environment file and edit it:

```powershell
Copy-Item .env.example .env
notepad .env
```

Replace `your_key_1,your_key_2` in `LLM_API_KEYS` with two valid keys for the configured provider. Keep `.env` local; it is ignored by Git and excluded from Docker build contexts. The `.env.example` file contains placeholders only. Compose reads the root `.env` for variable interpolation and passes only the configured values to the backend container, as described in [Docker's Compose environment-variable guide](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).

Start the project:

```sh
make up
```

This runs `docker compose up --build -d`. If GNU Make is unavailable, use that Docker Compose command directly. Compose builds both images and starts the backend and frontend in the background.

Open <http://localhost:3000> for the chat UI. The browser sends requests to same-origin `/api/...`; Nginx forwards them to the backend over the private Compose network. The browser never needs to resolve the Docker-only hostname `backend`. The backend can also be checked directly at <http://localhost:8000/health>.

Useful commands:

```sh
make logs       # follow both services' logs
make rebuild    # rebuild images without using the build cache
make down       # stop/remove containers and the Compose network
```

`make down` and `make clean` preserve the SQLite volume. Avoid `docker compose down -v` when you want to keep conversation history; `-v` deletes named volumes.

### Check status and database persistence

Use `docker compose ps` to see both service states. Once the backend has keys configured and has started, its health check should return:

```json
{"status":"ok","keys_configured":2,"cache_enabled":true}
```

To inspect how many messages are stored without changing the database:

```sh
docker compose exec -T backend python -c "import sqlite3; c=sqlite3.connect('file:/data/app.db?mode=ro', uri=True); print(c.execute('SELECT COUNT(*) FROM messages').fetchone()[0])"
```

The backend's `DATABASE_URL` defaults to `sqlite:////data/app.db`. Compose mounts the named volume `lyftr_ai_sqlite_data` at `/data`; SQLite therefore writes to that persistent volume rather than the container's writable layer. Removing or rebuilding containers does not remove the volume.

To deliberately reset chat history, stop the project and remove the named volume explicitly:

```sh
docker compose down
docker volume rm lyftr_ai_sqlite_data
```

This deletes all stored conversations and cannot be undone. The next `make up` creates an empty volume again. For important local history, make a backup before resetting.

### Run without Docker

Run the backend in one terminal. Python 3.10 or newer is required by the backend dependencies.

Windows PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:LLM_API_KEYS = "your_key_1,your_key_2"
$env:DATABASE_URL = "sqlite:///./app.db"
$env:ALLOWED_ORIGINS = "http://localhost:3000"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

macOS/Linux:

```sh
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export LLM_API_KEYS="your_key_1,your_key_2"
export DATABASE_URL="sqlite:///./app.db"
export ALLOWED_ORIGINS="http://localhost:3000"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

In a second terminal, run the frontend:

```sh
cd frontend
```

On Windows, copy the example with `Copy-Item .env.example .env.local`; on macOS/Linux, use `cp .env.example .env.local`. Then run:

```sh
npm ci
npm run dev
```

The Vite server listens on port 3000 and reads `VITE_API_BASE_URL=http://localhost:8000` from `frontend/.env.local`. The frontend's Docker build instead sets `VITE_API_BASE_URL=/api`; these are separate development and container configurations.

To run checks without Docker:

```sh
# from frontend/
npm test
npm run build

# from backend/ with the virtual environment active
python -m pytest -q
```

### Troubleshooting

- **`make` is not recognized:** Install/use GNU Make, or run `docker compose up --build -d` and `docker compose down` directly.
- **Docker daemon is unavailable:** Start Docker Desktop and wait until its engine is ready, then retry.
- **Port 3000 or 8000 is already in use:** Stop the other process or change the host-side port mapping in `docker-compose.yml`.
- **Backend health is 503/unhealthy:** Check that `.env` contains at least two comma-separated keys and review `docker compose logs backend`. The health check verifies database reachability and a loaded key pool; it does not validate provider credentials.
- **Chat reports that providers are unavailable:** Check provider/model compatibility and the validity/quota of backend keys. Provider keys are configured only in the root `.env`, never in frontend files.
- **Frontend shows a gateway error:** Check `docker compose ps` and `docker compose logs backend frontend`. Nginx proxies `/api/` to the Compose `backend` service. Do not set the browser API URL to `http://backend:8000`; that name is only resolvable inside Docker.
- **Local frontend cannot reach the backend:** Confirm `frontend/.env.local` has `VITE_API_BASE_URL=http://localhost:8000`, restart Vite after editing it, and check the backend's `ALLOWED_ORIGINS` value.
- **History appears empty after recreating containers:** Confirm the Compose volume still exists with `docker volume inspect lyftr_ai_sqlite_data` and that `DATABASE_URL` points to `/data/app.db`.

## Design decisions: key fallback, caching, SQLite session storage

- **Key fallback:** The backend tries configured keys in order and retries rate limits, quota exhaustion and provider 5xx errors. `ENABLE_FAILURE_SIMULATION=true` enables the request-specific `X-Simulate-Failure` demonstration header.
- **Caching:** LiteLLM's built-in local cache uses the model and complete prompt messages. Session IDs are not sent to LiteLLM. Docker defaults `LITELLM_CACHE_TYPE=local` and `CACHE_ENABLED=true`.
- **SQLite:** SQLite is the only database. The named Compose volume is mounted at `/data`; the backend stores assistant metadata as JSON and commits each successful user/assistant exchange transactionally.
- **Browser routing:** Docker builds the static frontend with `/api` as its API base. Nginx proxies `/api/chat` to `backend:8000/chat` on the Compose network, while the browser only requests its own origin.
- **Secrets:** The root `.env` is used for local Compose interpolation, excluded from the Docker build context, and ignored by Git. Real API keys do not belong in Dockerfiles, frontend environment variables, or image build arguments.

## Verification: how to see failover, cache hits and per-message token usage

- **Failover:** Set `ENABLE_FAILURE_SIMULATION=true` in `.env`, restart with `make up`, then send a request with the `X-Simulate-Failure: key_1=429` header using an API client. The successful response reports `key_id: "key_2"` and `fallback_attempts: 1`. `X-Simulate-Failure: *=429` returns HTTP 503 and does not save the failed exchange.
- **Cache hits:** Send the same first message in two separate new chat sessions with the same system prompt. The second response should show `resolution_source: "LLM_CACHE"`, a null key ID, and zero fallback attempts. Changing the message or system prompt should miss the cache.
- **Token usage:** Each assistant message displays its own input-token and output-token counts beneath the reply, along with source, model and latency. These values are request-specific, not conversation totals.
- **Backend tests:** From `backend/`, activate the Python environment and run `python -m pytest -q`.
- **Frontend checks:** From `frontend/`, run `npm test` and `npm run build`.

## Setup Used: your editor and AI tools

- Editor: Visual Studio Code.
- AI development assistant: OpenAI Codex.
- Runtime verification for the Docker phase depends on Docker Desktop or a Docker Engine/Compose installation.

## Bonus features (if any): what you added beyond the requirements and why

- Nginx serves the frontend as an unprivileged user and provides same-origin API proxying, avoiding browser access to internal Docker service names.
- Backend and frontend health checks help identify startup and readiness problems.
- `make logs`, `make rebuild` and `make clean` provide convenience commands; `make clean` preserves the SQLite volume.
- The frontend includes mocked UI tests for message submission, metadata, errors, system prompts and fresh sessions.
