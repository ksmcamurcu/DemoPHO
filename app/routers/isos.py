from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.iso_manager import IsoManager

router = APIRouter(prefix="/isos", tags=["ISO arşivi"])


def get_iso_manager(request: Request) -> IsoManager:
    return request.app.state.iso_manager


IsoManagerDep = Annotated[IsoManager, Depends(get_iso_manager)]


@router.get("")
def list_isos(manager: IsoManagerDep) -> list[dict[str, object]]:
    return manager.list_isos()


@router.post("/{iso_id}/update", status_code=status.HTTP_202_ACCEPTED)
def update_iso(iso_id: str, manager: IsoManagerDep) -> dict[str, object]:
    try:
        return manager.start_update(iso_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{iso_id}/status")
def get_iso_status(iso_id: str, manager: IsoManagerDep) -> dict[str, object]:
    try:
        return manager.get_status(iso_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
