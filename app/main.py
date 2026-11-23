import os

import uvicorn
from fastapi import FastAPI

from app.iso_manager import IsoManager
from app.routers import engine, isos


def create_app(iso_manager: IsoManager | None = None) -> FastAPI:
    application = FastAPI(
        title="Wox VM API",
        description="Wox'ın sınırlı ve yerel sanal makine motoru API'si.",
        version="0.2.4",
    )
    application.state.iso_manager = iso_manager or IsoManager()
    application.include_router(engine.router, prefix="/api/v1")
    application.include_router(isos.router, prefix="/api/v1")

    @application.get("/health", tags=["Sistem"])
    def health() -> dict[str, str]:
        return {"status": "ok", "engine": "Wox Core"}

    return application


app = create_app()


def main() -> None:
    from app.ui import run_desktop

    run_desktop(
        app,
        host="127.0.0.1",
        port=int(os.getenv("WOX_API_PORT", "8000")),
        iso_manager=app.state.iso_manager,
    )


if __name__ == "__main__":
    main()
