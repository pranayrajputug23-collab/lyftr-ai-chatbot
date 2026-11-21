"""Readiness endpoint for the API, SQLite, key pool, and cache."""

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/health")
def health(request: Request):
    database_ok = request.app.state.database.is_reachable()
    keys_configured = len(request.app.state.settings.llm_api_keys)
    cache_enabled = request.app.state.settings.cache_enabled
    if not database_ok or keys_configured == 0:
        raise HTTPException(status_code=503, detail="service not ready")
    return {"status": "ok", "keys_configured": keys_configured, "cache_enabled": cache_enabled}
