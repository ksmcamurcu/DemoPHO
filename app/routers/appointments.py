from fastapi import APIRouter, HTTPException, status

from app.dependencies import StoreDep, UserId
from app.schemas import (
    AppointmentCreate,
    AppointmentResponse,
    appointment_end,
    utc_now,
)

router = APIRouter(prefix="/appointments", tags=["Randevular"])
COLLECTION = "appointments"


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
def create_appointment(
    payload: AppointmentCreate, user_id: UserId, store: StoreDep
) -> dict:
    requested_start = payload.scheduled_at
    requested_end = appointment_end(requested_start, payload.duration_minutes)
    for existing in store.list(COLLECTION, user_id):
        if existing["provider_name"].casefold() != payload.provider_name.casefold():
            continue
        existing_start = existing["scheduled_at"]
        existing_end = appointment_end(existing_start, existing["duration_minutes"])
        if requested_start < existing_end and existing_start < requested_end:
            raise HTTPException(status_code=409, detail="Bu zaman aralığı dolu.")
    return store.create(
        COLLECTION,
        user_id,
        {**payload.model_dump(), "status": "scheduled", "created_at": utc_now()},
    )


@router.get("", response_model=list[AppointmentResponse])
def list_appointments(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list(COLLECTION, user_id)
