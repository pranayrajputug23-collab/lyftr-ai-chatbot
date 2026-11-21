# Lyftr AI Architecture

## Overview

Lyftr AI is a React/Vite chat client backed by a Python/FastAPI service. The backend owns conversation retrieval, LLM calls, caching, key selection, and SQLite persistence. The browser creates a fresh session ID on every page load and sends only each new user message. The backend combines that message with the session history from SQLite before calling the model.

The application exposes exactly three API routes:

- `GET /health` reports application, database, key-pool, and cache readiness.
- `POST /chat` processes one new message, performs inference or serves a LiteLLM cache hit, and persists the successful user/assistant exchange.
- `GET /sessions/{session_id}/messages` returns the session's messages in chronological order without the system prompt.

## Backend

FastAPI routes are separated into chat, health, and session routers. Configuration is loaded from environment variables. Pydantic schemas validate the request and response contracts. Services isolate LLM integration, cache-related behavior, and session/database operations. Provider failures are translated into safe API errors; raw provider details, stack traces, and credentials are not returned to clients.

The chat flow validates the incoming session ID and trimmed message, retrieves prior messages, then builds the complete prompt from the configured or supplied system prompt, prior conversation, and new message. Only after a successful model response does it persist the new user and assistant messages. Failed requests therefore do not add a partial exchange to history.

## Frontend

The React/Vite frontend provides a responsive chat interface with distinct user and assistant messages, a loading state, readable errors, Enter-to-send behavior, disabled submission while a request is active, and automatic scrolling to the newest message. It clears the composer after sending. It creates a new client-generated session ID on each page load and submits only the new message; it does not send the full history.

The optional system prompt is sent with chat requests when provided. Each assistant response displays its own resolution source, model, latency, input-token count, and output-token count. These are per-request values, not conversation-wide totals. The API base URL is provided through frontend build/runtime configuration rather than hardcoded to localhost. Required `data-testid` attributes are part of the UI contract.

## SQLite session storage

SQLite is the only database. The backend creates the database and required tables at startup. The `messages` table stores the session ID, role, content, assistant metadata as JSON, and timestamp. A session table or supporting indexes may be added if useful, while preserving the required message schema and API behavior.

Messages are read oldest-first. System prompts are used to construct inference requests but are not returned as conversation history. In Docker, the database path is configured through `DATABASE_URL` and the database directory is mounted from a named volume at `/data`, so messages survive container restarts.

## LiteLLM, caching, and metadata

LiteLLM is the model gateway and response-cache implementation. The cache is enabled with LiteLLM's built-in in-memory or disk-backed cache, not a hand-built response map. Cache identity must be based on the model and complete messages sent to the provider, including the system prompt and conversation context. The session ID is excluded so two separate sessions with identical first-message prompts can reuse a response. Distinct messages or contexts must not collide.

The service will inspect LiteLLM response/cache metadata to distinguish a genuine cache hit from live inference. It will preserve the response's token usage and model for both paths. Live responses include the successful key ID and count of failed keys before success; cache hits have `key_id: null` and `fallback_attempts: 0`. Latency is measured by the server in integer milliseconds. The exact cache-hit and usage metadata exposed by LiteLLM is version-sensitive and will be verified against the selected dependency version.

## API-key failover

The backend reads a comma-separated `LLM_API_KEYS` list and assigns stable IDs in order (`key_1`, `key_2`, and so on). Calls are attempted sequentially. Rate limits, quota exhaustion, and provider 5xx errors advance to the next key; unrelated errors are handled according to their provider classification and do not expose raw provider messages. If all configured keys fail, the endpoint returns HTTP 503 with `{"detail":"all providers unavailable"}`. Keys are never sent to the frontend or included in API responses or logs.

When `ENABLE_FAILURE_SIMULATION=true`, the optional `X-Simulate-Failure` header can inject one of the permitted statuses for selected keys on that request. The simulated failure uses the same retry path as a provider failure. A later key must still make a real model call; if all keys are simulated as unavailable, the request returns 503. Simulation is disabled when the environment flag is false and must never be treated as a successful assistant answer.

## Runtime and deployment

Docker Compose runs the backend and frontend. Each Dockerfile uses multiple build stages. The frontend is available on port 3000 and the backend on port 8000 in local development. Compose supplies the backend URL to the browser-facing frontend configuration and mounts a named volume at `/data` for SQLite. CORS origins, model/provider settings, API keys, database URL, and simulation mode are environment-configured. `.env.example` documents required settings without containing real credentials; `.env` and other secret files are excluded from version control.

Deployment configuration will prepare the frontend for Vercel and the backend for Render or Railway, including public frontend origin, persistent backend storage, and publicly reachable health checks. Documentation will distinguish preparation instructions from deployment that has actually been performed and verified.

## Implementation phases

1. **Planning:** Inspect the workspace, settle the architecture and identify dependencies, provider assumptions, and risks.
2. **Backend:** Implement FastAPI, SQLite, all three endpoints, LiteLLM inference/cache, key failover, failure simulation, and pytest coverage; run tests and fix failures.
3. **Frontend:** Implement the responsive chat interface, session generation, API integration, metadata, loading and error states, and required test IDs.
4. **Docker:** Add multi-stage Dockerfiles, Compose, Makefile, environment examples, and verify startup, shutdown, and persistent storage where the local environment allows.
5. **Final verification:** Check endpoint contracts, multi-turn history, session isolation, cache hits, failover, all-key failures, request validation, and frontend/backend integration.
6. **Deployment preparation:** Document exact Vercel/backend deployment configuration and environment variables without claiming an unverified deployment.

## Technical risks and assumptions

- The assignment does not select a model provider or model. Provider-compatible model configuration and valid backend API keys are necessary for real live responses and deployment verification.
- LiteLLM cache-hit flags and token-usage fields vary by version and provider. The implementation must validate actual response metadata and preserve cached usage rather than infer a hit from repeated request text.
- Cache correctness depends on LiteLLM's key including the complete prompt and model while excluding session ID. This needs explicit testing across new sessions and distinct contexts.
- Provider SDKs may classify quota exhaustion differently. The failover service must normalize the specified status/error classes while keeping secrets and provider detail out of responses and logs.
- SQLite is appropriate for this single-service assignment, but deployed persistence depends on attaching durable storage at the configured database path.
- Browser access to the backend requires correct CORS configuration and a frontend API URL that is available to the browser, not merely resolvable from inside the Compose network.
- Mocked provider tests can verify retry and persistence behavior without API credits, but a real provider smoke test requires valid credentials and may incur provider usage.
