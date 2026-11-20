from fastapi import APIRouter, HTTPException, Response, status

from app.dependencies import StoreDep, UserId
from app.schemas import MemoryCreate, MemoryResponse, MemoryUpdate, utc_now

router = APIRouter(prefix="/memories", tags=["Kullanıcı belleği"])
COLLECTION = "memories"


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
def create_memory(payload: MemoryCreate, user_id: UserId, store: StoreDep) -> dict:
    now = utc_now()
    return store.create(
        COLLECTION,
        user_id,
        {**payload.model_dump(), "created_at": now, "updated_at": now},
    )


@router.get("", response_model=list[MemoryResponse])
def list_memories(user_id: UserId, store: StoreDep) -> list[dict]:
    return store.list(COLLECTION, user_id)


@router.get("/{memory_id}", response_model=MemoryResponse)
def get_memory(memory_id: str, user_id: UserId, store: StoreDep) -> dict:
    memory = store.get(COLLECTION, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Bellek bulunamadı.")
    return memory


@router.patch("/{memory_id}", response_model=MemoryResponse)
def update_memory(
    memory_id: str, payload: MemoryUpdate, user_id: UserId, store: StoreDep
) -> dict:
    memory = store.get(COLLECTION, user_id, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Bellek bulunamadı.")
    memory.update(payload.model_dump(exclude_unset=True))
    memory["updated_at"] = utc_now()
    return memory


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str, user_id: UserId, store: StoreDep) -> Response:
    if not store.delete(COLLECTION, user_id, memory_id):
        raise HTTPException(status_code=404, detail="Bellek bulunamadı.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
