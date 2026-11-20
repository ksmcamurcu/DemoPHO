from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from app.store import MemoryStore


def get_store(request: Request) -> MemoryStore:
    return request.app.state.store


def get_user_id(
    x_user_id: Annotated[
        str,
        Header(
            alias="X-User-ID",
            min_length=1,
            max_length=64,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$",
        ),
    ],
) -> str:
    if not x_user_id.strip():
        raise HTTPException(status_code=422, detail="X-User-ID boş olamaz.")
    return x_user_id


StoreDep = Annotated[MemoryStore, Depends(get_store)]
UserId = Annotated[str, Depends(get_user_id)]
