from fastapi import APIRouter, HTTPException

from app.dependencies import StoreDep, UserId
from app.schemas import (
    CapabilityDecision,
    CapabilityProposalCreate,
    CapabilityProposalResponse,
    utc_now,
)

router = APIRouter(prefix="/capability-proposals", tags=["Yetenek önerileri"])
COLLECTION = "capability_proposals"


@router.post(
    "", response_model=CapabilityProposalResponse, status_code=201
)
def create_proposal(
    payload: CapabilityProposalCreate, user_id: UserId, store: StoreDep
) -> dict:
    return store.create(
        COLLECTION,
        user_id,
        {
            **payload.model_dump(),
            "status": "pending_approval",
            "decision_note": None,
            "created_at": utc_now(),
            "decided_at": None,
        },
    )


@router.get("", response_model=list[CapabilityProposalResponse])
def list_proposals(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list(COLLECTION, user_id)


@router.post("/{proposal_id}/decision", response_model=CapabilityProposalResponse)
def decide_proposal(
    proposal_id: str,
    payload: CapabilityDecision,
    user_id: UserId,
    store: StoreDep,
) -> dict:
    proposal = store.get(COLLECTION, user_id, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Yetenek önerisi bulunamadı.")
    if proposal["status"] != "pending_approval":
        raise HTTPException(status_code=409, detail="Öneri için zaten karar verilmiş.")
    proposal["status"] = payload.decision
    proposal["decision_note"] = payload.note
    proposal["decided_at"] = utc_now()
    return proposal
