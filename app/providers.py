from typing import Protocol
from uuid import uuid4

from app.schemas import ChatMessage, ChatResponse


class ChatProvider(Protocol):
    name: str

    def complete(self, messages: list[ChatMessage]) -> ChatResponse: ...


class DemoChatProvider:
    """Kimlik bilgisi istemeyen örnek sağlayıcı; dış servise bağlanmaz."""

    name = "demo"

    def complete(self, messages: list[ChatMessage]) -> ChatResponse:
        last_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            None,
        )
        reply = (
            f"DemoPHO demo yanıtı: {last_user_message}"
            if last_user_message
            else "DemoPHO sohbet demosu hazır. Gerçek bir sağlayıcı yapılandırılmadı."
        )
        return ChatResponse(id=str(uuid4()), provider=self.name, reply=reply)
