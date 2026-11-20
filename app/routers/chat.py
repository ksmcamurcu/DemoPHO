from fastapi import APIRouter, Request

from app.dependencies import UserId
from app.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["Sohbet"])


@router.post("/completions", response_model=ChatResponse)
def create_completion(
    payload: ChatRequest, _user_id: UserId, request: Request
) -> ChatResponse:
    return request.app.state.chat_provider.complete(payload.messages)
