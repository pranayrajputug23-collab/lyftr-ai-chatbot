"""FastAPI application factory and startup wiring."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.database import Database
from app.routers import chat, health, sessions
from app.services.llm_service import LLMService
from app.services.session_service import SessionService


def create_app(settings: Settings | None = None, llm_service=None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database.initialize()
        application.state.database = database
        application.state.settings = settings
        application.state.sessions = SessionService(database)
        application.state.llm = llm_service or LLMService(settings)
        yield

    application = FastAPI(
        title="Lyftr AI API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Simulate-Failure"],
    )
    application.include_router(health.router)
    application.include_router(chat.router)
    application.include_router(sessions.router)
    return application


app = create_app()
