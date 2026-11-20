from fastapi import APIRouter, status

from app.dependencies import StoreDep, UserId
from app.schemas import CodeExperimentCreate, CodeExperimentResponse, utc_now

router = APIRouter(prefix="/code-experiments", tags=["Kod deneyi kuyruğu"])
COLLECTION = "code_experiments"


@router.post(
    "", response_model=CodeExperimentResponse, status_code=status.HTTP_202_ACCEPTED
)
def queue_experiment(
    payload: CodeExperimentCreate, user_id: UserId, store: StoreDep
) -> dict:
    return store.create(
        COLLECTION,
        user_id,
        {**payload.model_dump(), "status": "queued", "created_at": utc_now()},
    )


@router.get("", response_model=list[CodeExperimentResponse])
def list_experiments(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list(COLLECTION, user_id)
