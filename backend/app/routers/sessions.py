"""Session history endpoint."""

from fastapi import APIRouter, HTTPException, Request

from app.schemas import HistoryResponse

router = APIRouter()


@router.get(
    "/sessions/{session_id}/messages",
    response_model=HistoryResponse,
    response_model_exclude_none=True,
)
def session_messages(session_id: str, request: Request):
    history = request.app.state.sessions.history(session_id)
    if history is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"session_id": session_id, "messages": history}
