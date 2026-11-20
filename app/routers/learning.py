from fastapi import APIRouter, status

from app.dependencies import StoreDep, UserId
from app.schemas import FeedbackCreate, FeedbackResponse, utc_now

router = APIRouter(prefix="/learning/feedback", tags=["Öğrenme geri bildirimi"])
COLLECTION = "feedback"


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreate, user_id: UserId, store: StoreDep
) -> dict:
    return store.create(
        COLLECTION, user_id, {**payload.model_dump(), "created_at": utc_now()}
    )


@router.get("", response_model=list[FeedbackResponse])
def list_feedback(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list(COLLECTION, user_id)
