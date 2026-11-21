"""Chat endpoint: assemble history, infer, and persist successful exchanges."""

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.schemas import ChatRequest, ChatResponse
from app.services.llm_service import ProvidersUnavailable, make_messages, parse_simulated_failures

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request, x_simulate_failure: str | None = Header(default=None)):
    settings = request.app.state.settings
    simulated = parse_simulated_failures(x_simulate_failure) if settings.enable_failure_simulation else {}
    previous = request.app.state.sessions.history(body.session_id) or []
    messages = make_messages(previous, body.message, body.system_prompt)
    try:
        result = await run_in_threadpool(request.app.state.llm.complete, messages, simulated)
    except ProvidersUnavailable:
        raise HTTPException(status_code=503, detail="all providers unavailable") from None
    request.app.state.sessions.save_exchange(body.session_id, body.message, result.reply, result.metadata)
    return {"session_id": body.session_id, "reply": result.reply, "metadata": result.metadata}
