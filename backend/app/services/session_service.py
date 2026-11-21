"""Conversation-history operations over the SQLite store."""

from typing import Any

from app.database import Database


class SessionService:
    def __init__(self, database: Database):
        self.database = database

    def history(self, session_id: str) -> list[dict[str, Any]] | None:
        return self.database.get_history(session_id)

    def save_exchange(self, session_id: str, user_message: str, assistant_message: str, metadata: dict[str, Any]) -> None:
        self.database.save_exchange(session_id, user_message, assistant_message, metadata)
