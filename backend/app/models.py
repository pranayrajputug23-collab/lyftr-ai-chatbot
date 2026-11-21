"""SQLite record shape used by the persistence layer."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Message:
    id: int
    session_id: str
    role: str
    content: str
    metadata: dict[str, Any] | None
    created_at: str
