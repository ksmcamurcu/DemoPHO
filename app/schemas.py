from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(ApiModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(ApiModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)


class ChatResponse(ApiModel):
    id: str
    provider: str
    reply: str


class MemoryCreate(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=10000)


class MemoryUpdate(ApiModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=10000)

    @model_validator(mode="after")
    def require_update_field(self) -> "MemoryUpdate":
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("En az bir geçerli alan gönderilmelidir.")
        return self


class MemoryResponse(MemoryCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class FeedbackCreate(ApiModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(FeedbackCreate):
    id: str
    created_at: datetime


class CapabilityProposalCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=4000)


class CapabilityDecision(ApiModel):
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class CapabilityProposalResponse(CapabilityProposalCreate):
    id: str
    status: Literal["pending_approval", "approved", "rejected"]
    decision_note: str | None = None
    created_at: datetime
    decided_at: datetime | None = None


class ProductResponse(ApiModel):
    id: str
    name: str
    description: str
    price: float = Field(ge=0)


class OrderItem(ApiModel):
    product_id: str
    quantity: int = Field(ge=1, le=100)


class OrderCreate(ApiModel):
    items: list[OrderItem] = Field(min_length=1, max_length=50)


class OrderResponse(ApiModel):
    id: str
    items: list[OrderItem]
    total: float
    status: Literal["pending"]
    created_at: datetime


class AppointmentCreate(ApiModel):
    scheduled_at: datetime
    provider_name: str = Field(min_length=1, max_length=120)
    reason: str = Field(min_length=1, max_length=1000)
    duration_minutes: int = Field(default=30, ge=10, le=240)

    @model_validator(mode="after")
    def require_future_timezone_aware_time(self) -> "AppointmentCreate":
        if self.scheduled_at.tzinfo is None or self.scheduled_at.utcoffset() is None:
            raise ValueError("Randevu zamanı saat dilimi içermelidir.")
        if self.scheduled_at <= datetime.now(timezone.utc):
            raise ValueError("Randevu zamanı gelecekte olmalıdır.")
        return self


class AppointmentResponse(AppointmentCreate):
    id: str
    status: Literal["scheduled"]
    created_at: datetime


class CodeExperimentCreate(ApiModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)


class CodeExperimentResponse(CodeExperimentCreate):
    id: str
    status: Literal["queued"]
    created_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def appointment_end(start: datetime, duration_minutes: int) -> datetime:
    return start + timedelta(minutes=duration_minutes)
